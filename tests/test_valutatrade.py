"""Проверки моделей, операций, API-контрактов, кеша, CLI и сохранения."""

#Этап 5

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import requests

from tests.support import (
    FixtureResponse,
    FixtureTransport,
    fixture_updater,
)
from valutatrade_hub.cli.interface import CLI
from valutatrade_hub.core import usecases
from valutatrade_hub.core.currencies import (
    CryptoCurrency,
    Currency,
    FiatCurrency,
    get_currency,
)
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    StorageError,
)
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.utils import utc_now
from valutatrade_hub.infra.database import DatabaseManager, atomic_write_json
from valutatrade_hub.infra.rates import RateService
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import setup_logging
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater, make_updater

ROOT = Path(__file__).resolve().parents[1]


class ProjectCase(unittest.TestCase):
    """Каждый тест получает собственные данные внутри папки работы."""

    def setUp(self):
        directory = ROOT / "tests" / "runtime"
        directory.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=directory)
        self.root = Path(self.temporary.name)
        self.config_path = self.root / "pyproject.toml"
        self.config_path.write_text(
            '[tool.valutatrade]\nDATA_DIR = "data"\nLOG_DIR = "logs"\n'
            "RATES_TTL_SECONDS = 300\n",
            encoding="utf-8",
        )
        SettingsLoader().reload(self.config_path)
        setup_logging()
        self.db = DatabaseManager()
        self.rates = RateService(updater=fixture_updater())

    def tearDown(self):
        SettingsLoader().reload(ROOT / "pyproject.toml")
        setup_logging()
        self.temporary.cleanup()

    def funded_user(self):
        """Зарегистрировать учебный аккаунт и явно подготовить 10000 USD."""
        user = usecases.register("alice", "1234")
        portfolio = usecases.load_portfolio(user.user_id)
        portfolio.add_currency("USD").deposit(10000.0)
        usecases.save_portfolio(portfolio)
        fixture_updater().run_update()
        return user


class ModelTests(ProjectCase):
    """Инварианты и публичный контракт моделей."""

    def test_user_hash_salt_info_and_serialization(self):
        first = User.create(1, "alice", "1234")
        second = User.create(2, "bob", "1234")
        self.assertNotEqual(first.salt, second.salt)
        self.assertNotEqual(first.hashed_password, second.hashed_password)
        self.assertNotIn("1234", first.to_dict().values())
        self.assertEqual(len(first.hashed_password), 64)
        self.assertEqual(
            set(first.get_user_info()), {"user_id", "username", "registration_date"}
        )
        restored = User.from_dict(first.to_dict())
        self.assertTrue(restored.verify_password("1234"))
        restored.change_password("different")
        self.assertFalse(restored.verify_password("1234"))
        self.assertTrue(restored.verify_password("different"))

    def test_invalid_user_fields_do_not_change_password(self):
        user = User.create(1, "alice", "1234")
        for name in ("", " ", None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                user.username = name
        with self.assertRaises(ValueError):
            user.change_password("12")
        self.assertTrue(user.verify_password("1234"))
        self.assertEqual(user.username, "alice")

    def test_wallet_invalid_values_and_no_partial_mutation(self):
        wallet = Wallet("USD", 10)
        for value in (-1, 0, True, "2", None, float("nan"), float("inf")):
            with self.subTest(value=value):
                for operation in (wallet.deposit, wallet.withdraw):
                    with self.assertRaises(ValueError):
                        operation(value)
                    self.assertEqual(wallet.balance, 10)
        for value in (-1, False, "2", float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                wallet.balance = value
        self.assertEqual(wallet.balance, 10)
        wallet.withdraw(10)
        self.assertEqual(wallet.balance, 0)
        self.assertIn("USD", wallet.get_balance_info())

    def test_withdraw_error_preserves_balance(self):
        wallet = Wallet("BTC", 0.04)
        with self.assertRaises(InsufficientFundsError) as context:
            wallet.withdraw(0.05)
        self.assertIn("доступно 0.0400 BTC", str(context.exception))
        self.assertEqual(wallet.balance, 0.04)

    def test_portfolio_unique_dictionary_copy_and_total(self):
        user = self.funded_user()
        portfolio = usecases.load_portfolio(user.user_id, self.rates)
        first = portfolio.add_currency("BTC")
        first.deposit(0.05)
        self.assertIs(first, portfolio.add_currency("BTC"))
        copy = portfolio.wallets
        copy.clear()
        self.assertEqual(len(portfolio.wallets), 2)
        self.assertIs(portfolio.user, portfolio.user)
        with self.assertRaises(AttributeError):
            portfolio.user = User.create(2, "bob", "1234")
        self.assertAlmostEqual(portfolio.get_total_value(), 10000 + 0.05 * 59337.21)
        self.assertAlmostEqual(
            portfolio.get_total_value("EUR"), (10000 + 0.05 * 59337.21) * 0.927
        )

    def test_portfolio_owns_dictionary_but_shares_wallet_objects(self):
        user = User.create(1, "alice", "1234")
        wallets = {"USD": Wallet("USD", 1)}
        portfolio = Portfolio(1, user, wallets)
        wallets.clear()
        self.assertEqual(portfolio.get_wallet("USD").balance, 1)
        portfolio.wallets["USD"].deposit(2)
        self.assertEqual(portfolio.get_wallet("USD").balance, 3)

    def test_currencies_abstract_validation_and_display(self):
        with self.assertRaises(TypeError):
            Currency("Dollar", "USD")
        self.assertIsInstance(get_currency("USD"), FiatCurrency)
        self.assertIsInstance(get_currency("BTC"), CryptoCurrency)
        self.assertEqual(
            get_currency("USD").get_display_info(),
            "[FIAT] USD — US Dollar (Issuing: United States)",
        )
        self.assertIn(
            "MCAP: 1.12e+12",
            CryptoCurrency("Bitcoin", "BTC", "SHA-256", 1.12e12).get_display_info(),
        )
        with self.assertRaises(CurrencyNotFoundError):
            get_currency("ABC")
        for code in ("usd", "U SD", "U", "TOOLONG", ""):
            with self.assertRaises(ValueError):
                get_currency(code)


class TradeTests(ProjectCase):
    """Баланс, сохранение, логирование и отказные сценарии."""

    def test_register_login_and_empty_portfolio(self):
        user = usecases.register("alice", "1234")
        self.assertTrue(usecases.login("alice", "1234").verify_password("1234"))
        self.assertEqual(usecases.load_portfolio(user.user_id).wallets, {})
        self.assertEqual(usecases.show_portfolio(user.user_id)["total"], 0)
        with self.assertRaisesRegex(ValueError, "уже занято"):
            usecases.register("alice", "1234")
        with self.assertRaisesRegex(ValueError, "Неверный пароль"):
            usecases.login("alice", "wrong")
        with self.assertRaisesRegex(ValueError, "не найден"):
            usecases.login("bob", "1234")

    def test_buy_and_sell_conserve_usd_valuation(self):
        user = self.funded_user()
        usecases.buy(user.user_id, "BTC", 0.05, rate_service=self.rates)
        portfolio = usecases.load_portfolio(user.user_id, self.rates)
        self.assertAlmostEqual(portfolio.get_wallet("USD").balance, 7033.1395)
        self.assertAlmostEqual(portfolio.get_wallet("BTC").balance, 0.05)
        self.assertAlmostEqual(portfolio.get_total_value(), 10000)
        result = usecases.sell(user.user_id, "BTC", 0.01, rate_service=self.rates)
        self.assertAlmostEqual(result["value"], 593.3721)
        portfolio = usecases.load_portfolio(user.user_id, self.rates)
        self.assertAlmostEqual(portfolio.get_wallet("USD").balance, 7626.5116)
        self.assertAlmostEqual(portfolio.get_wallet("BTC").balance, 0.04)
        self.assertAlmostEqual(portfolio.get_total_value(), 10000)
        data = usecases.show_portfolio(user.user_id, "EUR", rate_service=self.rates)
        self.assertAlmostEqual(data["total"], 9270)

    def test_repeated_buy_and_sell_entire_balance(self):
        user = self.funded_user()
        for _ in range(2):
            usecases.buy(user.user_id, "EUR", 50, rate_service=self.rates)
        self.assertEqual(
            usecases.load_portfolio(user.user_id).get_wallet("EUR").balance, 100
        )
        usecases.sell(user.user_id, "EUR", 100, rate_service=self.rates)
        self.assertEqual(
            usecases.load_portfolio(user.user_id).get_wallet("EUR").balance, 0
        )
        self.assertAlmostEqual(
            usecases.load_portfolio(user.user_id).get_wallet("USD").balance, 10000
        )

    def test_failed_buy_does_not_create_wallet(self):
        user = usecases.register("alice", "1234")
        fixture_updater().run_update()
        before = self.db.path("portfolios.json").read_bytes()
        with self.assertRaises(InsufficientFundsError):
            usecases.buy(user.user_id, "BTC", 0.05, rate_service=self.rates)
        self.assertEqual(before, self.db.path("portfolios.json").read_bytes())

    def test_failed_sell_preserves_all_balances(self):
        user = self.funded_user()
        with self.assertRaisesRegex(ValueError, "нет кошелька"):
            usecases.sell(user.user_id, "BTC", 1, rate_service=self.rates)
        usecases.buy(user.user_id, "BTC", 0.05, rate_service=self.rates)
        before = self.db.path("portfolios.json").read_bytes()
        with self.assertRaises(InsufficientFundsError):
            usecases.sell(user.user_id, "BTC", 0.06, rate_service=self.rates)
        self.assertEqual(before, self.db.path("portfolios.json").read_bytes())

    def test_invalid_inputs_and_base_usd_leave_data_unchanged(self):
        user = self.funded_user()
        before = self.db.path("portfolios.json").read_bytes()
        for code, amount in (
            ("BTC", -1),
            ("BTC", float("nan")),
            ("btc", 1),
            ("ABC", 1),
            ("USD", 1),
        ):
            with self.assertRaises((ValueError, CurrencyNotFoundError)):
                usecases.buy(user.user_id, code, amount, rate_service=self.rates)
            self.assertEqual(before, self.db.path("portfolios.json").read_bytes())

    def test_sale_creates_usd_wallet_if_missing(self):
        user = self.funded_user()
        portfolio = Portfolio(user.user_id, user, {"BTC": Wallet("BTC", 0.05)})
        usecases.save_portfolio(portfolio)
        usecases.sell(user.user_id, "BTC", 0.01, rate_service=self.rates)
        self.assertAlmostEqual(
            usecases.load_portfolio(user.user_id).get_wallet("USD").balance, 593.3721
        )

    def test_other_users_preserved(self):
        alice = self.funded_user()
        bob = usecases.register("bob", "password")
        usecases.buy(alice.user_id, "BTC", 0.05, rate_service=self.rates)
        self.assertEqual(usecases.load_portfolio(bob.user_id).wallets, {})
        self.assertEqual(len(self.db.read_records("users.json")), 2)

    def test_trade_logs_success_and_propagated_error(self):
        user = self.funded_user()
        usecases.buy(user.user_id, "BTC", 0.05, rate_service=self.rates)
        with self.assertRaises(InsufficientFundsError):
            usecases.sell(user.user_id, "BTC", 1, rate_service=self.rates)
        records = [
            json.loads(line)
            for line in (self.root / "logs/actions.log").read_text().splitlines()
        ]
        self.assertEqual(records[0]["result"], "OK")
        self.assertEqual(records[0]["rate"], 59337.21)
        self.assertIn("wallets", records[0])
        self.assertEqual(records[1]["result"], "ERROR")
        self.assertEqual(records[1]["error_type"], "InsufficientFundsError")
        self.assertNotIn("password", records[0])

    def test_save_failure_preserves_file_and_next_loaded_balance(self):
        user = self.funded_user()
        before = self.db.path("portfolios.json").read_bytes()
        with (
            patch(
                "valutatrade_hub.infra.database.os.replace",
                side_effect=OSError("disk error"),
            ),
            self.assertRaises(StorageError),
        ):
            usecases.buy(user.user_id, "BTC", 0.05, rate_service=self.rates)
        self.assertEqual(before, self.db.path("portfolios.json").read_bytes())
        self.assertNotIn("BTC", usecases.load_portfolio(user.user_id).wallets)
        self.assertEqual(list(self.db.path("portfolios.json").parent.glob("*.tmp")), [])

    def test_nonfinite_amounts_leave_balances_and_valid_error_logs(self):
        user = self.funded_user()
        before = self.db.path("portfolios.json").read_bytes()
        for amount in (float("nan"), float("inf"), float("-inf")):
            for operation in (usecases.buy, usecases.sell):
                with self.subTest(amount=amount, operation=operation.__name__):
                    with self.assertRaises(ValueError):
                        operation(user.user_id, "BTC", amount, rate_service=self.rates)
                    self.assertEqual(
                        before, self.db.path("portfolios.json").read_bytes()
                    )
        records = [
            json.loads(line, parse_constant=lambda value: self.fail(value))
            for line in (self.root / "logs/actions.log").read_text().splitlines()
        ]
        self.assertEqual(len(records), 6)
        self.assertTrue(all(record["result"] == "ERROR" for record in records))
        self.assertEqual(
            {record["amount"] for record in records}, {"nan", "inf", "-inf"}
        )

    def test_register_rolls_back_portfolio_on_users_save_failure(self):
        original = self.db.write

        def fail_users(filename, data):
            if filename == "users.json":
                raise StorageError("disk error")
            original(filename, data)

        with (
            patch.object(self.db, "write", side_effect=fail_users),
            self.assertRaises(StorageError),
        ):
            usecases.register("alice", "1234")
        self.assertEqual(self.db.read_records("portfolios.json"), [])
        self.assertEqual(self.db.read_records("users.json"), [])


class ApiTests(ProjectCase):
    """Успешные форматы и контролируемые ошибки внешних API."""

    def test_coingecko_ids_and_timeout(self):
        transport = FixtureTransport()
        client = CoinGeckoClient(ParserConfig(EXCHANGERATE_API_KEY=None), transport)
        rates = client.fetch_rates()
        self.assertEqual(
            rates, {"BTC_USD": 59337.21, "ETH_USD": 3720, "SOL_USD": 145.12}
        )
        self.assertEqual(transport.calls[0][1]["timeout"], 10)
        self.assertEqual(
            transport.calls[0][1]["params"]["ids"], "bitcoin,ethereum,solana"
        )
        self.assertIsNotNone(client.updated_at)

    def test_exchange_inverse_conversion_and_legacy_rates_field(self):
        client = ExchangeRateApiClient(
            ParserConfig(EXCHANGERATE_API_KEY="fixture-only"), FixtureTransport()
        )
        self.assertAlmostEqual(client.fetch_rates()["EUR_USD"], 1 / 0.927)
        response = FixtureResponse(
            {
                "result": "success",
                "base_code": "USD",
                "rates": {"EUR": 0.927, "GBP": 0.809, "RUB": 98.45},
            }
        )
        client = ExchangeRateApiClient(
            ParserConfig(EXCHANGERATE_API_KEY="fixture-only"),
            FixtureTransport(response=response),
        )
        self.assertAlmostEqual(client.fetch_rates()["RUB_USD"], 1 / 98.45)

    def test_missing_key_fails_before_network_and_repr_hides_key(self):
        transport = FixtureTransport()
        with self.assertRaisesRegex(ApiRequestError, "EXCHANGERATE_API_KEY"):
            ExchangeRateApiClient(
                ParserConfig(EXCHANGERATE_API_KEY=None), transport
            ).fetch_rates()
        self.assertEqual(transport.calls, [])
        self.assertNotIn(
            "fixture-only", repr(ParserConfig(EXCHANGERATE_API_KEY="fixture-only"))
        )

    def test_http_errors_and_timeout_are_safe(self):
        for status in (401, 403, 429, 500):
            transport = FixtureTransport(response=FixtureResponse({}, status))
            with (
                self.subTest(status=status),
                self.assertRaisesRegex(ApiRequestError, f"HTTP {status}"),
            ):
                CoinGeckoClient(transport=transport).fetch_rates()
        config = ParserConfig(EXCHANGERATE_API_KEY="fixture-only")
        transport = FixtureTransport(
            error=requests.exceptions.Timeout("URL/fixture-only/latest/USD")
        )
        with self.assertRaises(ApiRequestError) as context:
            ExchangeRateApiClient(config, transport).fetch_rates()
        self.assertNotIn("fixture-only", str(context.exception))

    def test_bad_json_partial_fields_and_nonfinite_rates(self):
        responses = [
            ValueError("bad JSON"),
            [],
            {},
            {"bitcoin": {"usd": float("nan")}},
            {"bitcoin": {"usd": "1"}},
        ]
        for data in responses:
            with self.subTest(data=data), self.assertRaises(ApiRequestError):
                CoinGeckoClient(
                    transport=FixtureTransport(response=FixtureResponse(data))
                ).fetch_rates()
        for value in (0, -1, float("inf"), "0.9", None):
            response = FixtureResponse(
                {
                    "result": "success",
                    "base_code": "USD",
                    "rates": {"EUR": value, "GBP": 1, "RUB": 1},
                }
            )
            with self.assertRaises(ApiRequestError):
                ExchangeRateApiClient(
                    ParserConfig(EXCHANGERATE_API_KEY="fixture-only"),
                    FixtureTransport(response=response),
                ).fetch_rates()

    def test_api_error_payload_and_wrong_base(self):
        for payload in (
            {"result": "error", "error-type": "invalid-key"},
            {"result": "success", "base_code": "EUR", "rates": {}},
        ):
            with self.assertRaises(ApiRequestError):
                ExchangeRateApiClient(
                    ParserConfig(EXCHANGERATE_API_KEY="fixture-only"),
                    FixtureTransport(response=FixtureResponse(payload)),
                ).fetch_rates()


class RateTests(ProjectCase):
    """TTL, кросс-курсы, устойчивость и история."""

    def test_updater_merges_sources_history_and_duplicates(self):
        updater = fixture_updater()
        result = updater.run_update()
        self.assertEqual(result["count"], 6)
        self.assertEqual(result["errors"], [])
        data = self.db.read("rates.json", {})
        history = self.db.read("exchange_rates.json", [])
        self.assertEqual(len(data["pairs"]), 6)
        self.assertEqual(len(history), 6)
        self.assertEqual(history[0]["meta"]["raw_id"], "bitcoin")
        for entry in history:
            self.assertEqual(
                entry["id"],
                f"{entry['from_currency']}_{entry['to_currency']}_{entry['timestamp']}",
            )
        updater.storage.save(data, history)
        self.assertEqual(len(self.db.read("exchange_rates.json", [])), 6)

    def test_partial_failure_preserves_unaffected_pairs(self):
        fixture_updater().run_update()
        previous = self.db.read("rates.json", {})["pairs"]["EUR_USD"]
        config = ParserConfig(EXCHANGERATE_API_KEY=None)
        updater = RatesUpdater(
            [
                ExchangeRateApiClient(config),
                CoinGeckoClient(config, FixtureTransport()),
            ],
            RatesStorage(config),
        )
        result = updater.run_update()
        self.assertEqual(result["count"], 3)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(self.db.read("rates.json", {})["pairs"]["EUR_USD"], previous)

    def test_all_sources_fail_does_not_touch_cache(self):
        fixture_updater().run_update()
        before = self.db.path("rates.json").read_bytes()
        updater = RatesUpdater(
            [ExchangeRateApiClient(ParserConfig(EXCHANGERATE_API_KEY=None))],
            RatesStorage(),
        )
        with self.assertRaises(ApiRequestError):
            updater.run_update()
        self.assertEqual(before, self.db.path("rates.json").read_bytes())

    def test_older_snapshot_cannot_replace_newer(self):
        fixture_updater().run_update()
        original = self.db.read("rates.json", {})
        past = "2020-01-01T00:00:00Z"
        RatesStorage().save(
            {
                "pairs": {
                    "BTC_USD": {"rate": 1.0, "updated_at": past, "source": "fixture"}
                },
                "last_refresh": past,
            },
            [],
        )
        self.assertEqual(self.db.read("rates.json", {}), original)

    def test_direct_inverse_cross_and_identity_no_update_when_fresh(self):
        fixture_updater().run_update()
        with patch.object(
            self.rates.updater,
            "run_update",
            side_effect=AssertionError("no network expected"),
        ):
            self.assertEqual(self.rates.get_rate("BTC", "USD")["rate"], 59337.21)
            self.assertAlmostEqual(
                self.rates.get_rate("USD", "BTC")["rate"], 1 / 59337.21
            )
            self.assertAlmostEqual(
                self.rates.get_rate("BTC", "EUR")["rate"], 59337.21 * 0.927
            )
            self.assertAlmostEqual(
                self.rates.get_rate("EUR", "GBP")["rate"], 0.809 / 0.927
            )
            self.assertEqual(self.rates.get_rate("USD", "USD")["rate"], 1)

    def test_stale_pair_refreshes_once(self):
        fixture_updater().run_update()
        data = self.db.read("rates.json", {})
        data["pairs"]["BTC_USD"]["updated_at"] = "2020-01-01T00:00:00Z"
        self.db.write("rates.json", data)
        with patch.object(
            self.rates.updater, "run_update", wraps=self.rates.updater.run_update
        ) as update:
            self.assertEqual(self.rates.get_rate("BTC", "USD")["rate"], 59337.21)
            update.assert_called_once()

    def test_stale_failed_refresh_blocks_trade(self):
        user = self.funded_user()
        data = self.db.read("rates.json", {})
        data["pairs"]["BTC_USD"]["updated_at"] = "2020-01-01T00:00:00Z"
        self.db.write("rates.json", data)
        before = self.db.path("portfolios.json").read_bytes()
        with (
            patch.object(
                self.rates.updater,
                "run_update",
                side_effect=ApiRequestError("fixture offline"),
            ),
            self.assertRaisesRegex(ApiRequestError, "устарел"),
        ):
            usecases.buy(user.user_id, "BTC", 0.05, rate_service=self.rates)
        self.assertEqual(before, self.db.path("portfolios.json").read_bytes())

    def test_missing_rate_with_failed_refresh_is_unavailable(self):
        with (
            patch.object(
                self.rates.updater, "run_update", side_effect=ApiRequestError("offline")
            ),
            self.assertRaisesRegex(ApiRequestError, "отсутствует"),
        ):
            self.rates.get_rate("USD", "BTC")

    def test_partial_refresh_cannot_make_old_other_source_fresh(self):
        fixture_updater().run_update()
        data = self.db.read("rates.json", {})
        data["pairs"]["EUR_USD"]["updated_at"] = "2020-01-01T00:00:00Z"
        self.db.write("rates.json", data)
        rates = RateService(updater=fixture_updater("coingecko"))
        with self.assertRaisesRegex(ApiRequestError, "не дало свежего курса"):
            rates.get_rate("EUR", "USD")

    def test_per_pair_ttl_and_cross_uses_oldest_time(self):
        fixture_updater().run_update()
        data = self.db.read("rates.json", {})
        past = (datetime.now(UTC) - timedelta(seconds=200)).isoformat()
        data["pairs"]["EUR_USD"]["updated_at"] = past
        self.db.write("rates.json", data)
        self.assertEqual(self.rates.get_rate("BTC", "EUR")["updated_at"], past)
        self.assertTrue(self.rates._fresh(past))
        self.assertFalse(self.rates._fresh("2020-01-01T00:00:00Z"))

    def test_show_rates_filters_cross_base_top_and_stale(self):
        fixture_updater().run_update()
        self.assertEqual(
            [row["pair"] for row in self.rates.show_rates(top=2)["rows"]],
            ["BTC_USD", "ETH_USD"],
        )
        self.assertEqual(
            self.rates.show_rates(currency="RUB")["rows"][0]["pair"], "RUB_USD"
        )
        self.assertAlmostEqual(
            self.rates.show_rates(currency="BTC", base="EUR")["rows"][0]["rate"],
            59337.21 * 0.927,
        )
        data = self.db.read("rates.json", {})
        data["pairs"]["BTC_USD"]["updated_at"] = "2020-01-01T00:00:00Z"
        self.db.write("rates.json", data)
        self.assertTrue(self.rates.show_rates(currency="BTC")["rows"][0]["stale"])
        with self.assertRaises(ValueError):
            self.rates.show_rates(top=0)

    def test_flat_cache_compatibility(self):
        self.db.write(
            "rates.json",
            {
                "BTC_USD": {"rate": 10, "updated_at": utc_now()},
                "source": "fixture",
                "last_refresh": utc_now(),
            },
        )
        self.assertEqual(self.rates.get_rate("BTC", "USD")["rate"], 10)
        self.assertEqual(len(self.rates.show_rates()["rows"]), 1)

    def test_corrupt_json_is_not_overwritten(self):
        path = self.db.path("rates.json")
        path.parent.mkdir(exist_ok=True)
        path.write_text("{broken}")
        with self.assertRaises(StorageError):
            fixture_updater().run_update()
        self.assertEqual(path.read_text(), "{broken}")

    def test_atomic_write_rejects_nan_and_cleans_temp(self):
        path = self.root / "file.json"
        atomic_write_json(path, {"rate": 1})
        with self.assertRaises(StorageError):
            atomic_write_json(path, {"rate": float("nan")})
        self.assertEqual(json.loads(path.read_text()), {"rate": 1})
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_history_rejects_non_utc_timestamp_before_writing(self):
        timestamp = "2026-10-08T12:00:00+03:00"
        record = {
            "id": f"BTC_USD_{timestamp}",
            "from_currency": "BTC",
            "to_currency": "USD",
            "rate": 10,
            "timestamp": timestamp,
            "source": "fixture",
        }
        with self.assertRaises(StorageError):
            RatesStorage().save({"pairs": {}, "last_refresh": utc_now()}, [record])
        self.assertFalse(self.db.path("exchange_rates.json").exists())

    def test_source_selection_and_singletons(self):
        self.assertIs(SettingsLoader(), SettingsLoader())
        self.assertIs(DatabaseManager(), DatabaseManager())
        self.assertEqual(len(make_updater().clients), 2)
        self.assertIsInstance(make_updater("coingecko").clients[0], CoinGeckoClient)
        self.assertIsInstance(
            make_updater("exchangerate").clients[0], ExchangeRateApiClient
        )
        with self.assertRaises(ValueError):
            make_updater("other")


class CliTests(ProjectCase):
    """Один полный интерактивный сценарий и восстановление после ошибок."""

    def test_cli_full_cycle_and_error_messages(self):
        cli = CLI(rate_service=self.rates, updater_factory=fixture_updater)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli.execute("buy --currency BTC --amount 0.05"), 1)
            self.assertEqual(
                cli.execute("register --username alice --password 1234"), 0
            )
            self.assertEqual(cli.execute("login --username alice --password wrong"), 1)
            self.assertEqual(cli.execute("login --username alice --password 1234"), 0)
            self.assertEqual(cli.execute("show-portfolio"), 0)
            portfolio = usecases.load_portfolio(cli.user.user_id)
            portfolio.add_currency("USD").deposit(10000)
            usecases.save_portfolio(portfolio)
            self.assertEqual(cli.execute("update-rates"), 0)
            self.assertEqual(cli.execute("buy --currency BTC --amount 0.05"), 0)
            self.assertEqual(cli.execute("sell --currency BTC --amount 0.01"), 0)
            self.assertEqual(cli.execute("show-portfolio"), 0)
            self.assertEqual(cli.execute("get-rate --from USD --to BTC"), 0)
            self.assertEqual(cli.execute("show-rates --top 2"), 0)
            self.assertEqual(cli.execute("show-rates --currency RUB"), 0)
            self.assertEqual(cli.execute("show-rates --base EUR"), 0)
            self.assertEqual(cli.execute("buy --currency ABC --amount 1"), 1)
            self.assertEqual(cli.execute("sell --currency BTC --amount 1"), 1)
        text = output.getvalue()
        for expected in (
            "Сначала выполните login",
            "Неверный пароль",
            "Портфель пуст",
            "Покупка выполнена",
            "Продажа выполнена",
            "10,000.00 USD",
            "Курс USD→BTC",
            "Недостаточно средств",
            "Неизвестная валюта 'ABC'",
        ):
            self.assertIn(expected, text)

    def test_cli_quoted_name_argument_errors_and_help(self):
        cli = CLI()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(
                cli.execute('register --username "alice smith" --password 1234'), 0
            )
            self.assertEqual(
                cli.execute('login --username "alice smith" --password 1234'), 0
            )
            self.assertEqual(cli.execute("buy --currency BTC"), 1)
            self.assertEqual(cli.execute("buy --currency BTC --amount nope"), 1)
            self.assertEqual(cli.execute("update-rates --source unknown"), 1)
            self.assertEqual(cli.execute("buy --help"), 0)
            self.assertEqual(cli.execute('buy --currency "BTC'), 1)
            self.assertEqual(cli.execute("show-portfolio"), 0)


if __name__ == "__main__":
    unittest.main()
