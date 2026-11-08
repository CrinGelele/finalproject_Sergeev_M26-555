"""Единый контракт курсов: прямой, обратный и кросс-курс через USD."""

#Этап 4

from datetime import UTC, datetime

from valutatrade_hub.core.currencies import CryptoCurrency, get_currency
from valutatrade_hub.core.exceptions import ApiRequestError, StorageError
from valutatrade_hub.core.utils import parse_timestamp, utc_now, validate_number
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import make_updater


class RateService:
    """Читать rates.json; при отсутствии/истечении TTL один раз обновить."""

    def __init__(self, storage=None, updater=None):
        self.storage = storage or RatesStorage()
        self.updater = updater

    def _fresh(self, timestamp: str) -> bool:
        age = (datetime.now(UTC) - parse_timestamp(timestamp)).total_seconds()
        return 0 <= age <= SettingsLoader().get("RATES_TTL_SECONDS")

    def _direct(self, pairs: dict, from_code: str, to_code: str):
        if from_code == to_code:
            return {"rate": 1.0, "updated_at": utc_now(), "source": "identity"}
        pair = f"{from_code}_{to_code}"
        inverse = False
        entry = pairs.get(pair)
        if entry is None:
            entry = pairs.get(f"{to_code}_{from_code}")
            inverse = True
        if entry is None:
            return None
        try:
            rate = validate_number(entry["rate"], "rate")
            timestamp = entry["updated_at"]
            parse_timestamp(timestamp)
            return {
                "rate": validate_number(1 / rate if inverse else rate, "rate"),
                "updated_at": timestamp,
                "source": entry.get("source", "cache"),
            }
        except (KeyError, TypeError, ValueError) as error:
            raise StorageError(f"Некорректная запись курса {pair}") from error

    def _resolve(self, pairs: dict, from_code: str, to_code: str):
        direct = self._direct(pairs, from_code, to_code)
        if direct:
            return direct
        left = self._direct(pairs, from_code, "USD")
        right = self._direct(pairs, to_code, "USD")
        if left is None or right is None:
            return None
        return {
            "rate": validate_number(left["rate"] / right["rate"], "rate"),
            "updated_at": min(
                left["updated_at"], right["updated_at"], key=parse_timestamp
            ),
            "source": f"{left['source']} / {right['source']}",
        }

    def get_rate(self, from_code: str, to_code: str) -> dict:
        """Вернуть rate + updated_at; устаревший курс не использовать."""
        get_currency(from_code)
        get_currency(to_code)
        if from_code == to_code:
            return self._direct({}, from_code, to_code)
        entry = self._resolve(self.storage.load_rates()["pairs"], from_code, to_code)
        if entry and self._fresh(entry["updated_at"]):
            return entry
        reason = "устарел" if entry else "отсутствует"
        try:
            (self.updater or make_updater()).run_update()
        except ApiRequestError as error:
            raise ApiRequestError(
                f"Курс {from_code}→{to_code} {reason}. "
                f"Выполните update-rates или повторите позже. {error}"
            ) from error
        entry = self._resolve(self.storage.load_rates()["pairs"], from_code, to_code)
        if entry and self._fresh(entry["updated_at"]):
            return entry
        raise ApiRequestError(
            f"Курс {from_code}→{to_code} {reason}. "
            "Обновление не дало свежего курса для этой пары"
        )

    def show_rates(
        self, currency: str | None = None, top: int | None = None, base: str = "USD"
    ) -> dict:
        """Список локальных курсов с флагом устаревания, без сетевых запросов."""
        get_currency(base)
        if top is not None and (
            isinstance(top, bool) or not isinstance(top, int) or top < 1
        ):
            raise ValueError("'top' должен быть положительным целым числом")
        if currency:
            get_currency(currency)
        snapshot = self.storage.load_rates()
        pairs = snapshot["pairs"]
        if not pairs:
            raise ValueError(
                "Локальный кеш курсов пуст. "
                "Выполните 'update-rates', чтобы загрузить данные."
            )
        codes = {part for pair in pairs for part in pair.split("_")}
        codes.discard(base)
        if currency:
            codes &= {currency}
        if top is not None:
            codes = {
                code for code in codes if isinstance(get_currency(code), CryptoCurrency)
            }
        rows = []
        for code in sorted(codes):
            entry = self._resolve(pairs, code, base)
            if entry:
                rows.append(
                    {
                        "pair": f"{code}_{base}",
                        **entry,
                        "stale": not self._fresh(entry["updated_at"]),
                    }
                )
        if currency and not rows:
            raise ValueError(f"Курс для '{currency}' не найден в кеше")
        if top is not None:
            rows = sorted(rows, key=lambda row: row["rate"], reverse=True)[:top]
        return {"rows": rows, "last_refresh": snapshot["last_refresh"]}
