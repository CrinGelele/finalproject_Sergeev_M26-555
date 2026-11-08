"""Бизнес-операции. Сумма сделки — количество выбранной валюты."""

#Этап 2

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import InsufficientFundsError, StorageError
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.utils import validate_number
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.rates import RateService
from valutatrade_hub.infra.settings import SettingsLoader


def _user_from_record(record: dict) -> User:
    try:
        return User.from_dict(record)
    except (KeyError, TypeError, ValueError) as error:
        raise StorageError("Некорректная запись пользователя в users.json") from error


def get_user(user_id: int) -> User:
    """Получить пользователя по ID."""
    for record in DatabaseManager().read_records("users.json"):
        user = _user_from_record(record)
        if user.user_id == user_id:
            return user
    raise ValueError(f"Пользователь с id={user_id} не найден")


def register(username: str, password: str) -> User:
    """Зарегистрировать уникальное имя и пустой портфель."""
    db = DatabaseManager()
    users = db.read_records("users.json")
    if not isinstance(username, str) or not username.strip():
        raise ValueError("Имя пользователя не может быть пустым")
    username = username.strip()
    loaded = [_user_from_record(record) for record in users]
    if any(user.username == username for user in loaded):
        raise ValueError(f"Имя пользователя '{username}' уже занято")
    user_id = max((user.user_id for user in loaded), default=0) + 1
    user = User.create(user_id, username, password)
    portfolios = db.read_records("portfolios.json")
    if any(record.get("user_id") == user_id for record in portfolios):
        raise StorageError("В portfolios.json уже есть портфель для нового user_id")
    db.write("portfolios.json", [*portfolios, Portfolio(user_id, user).to_dict()])
    try:
        db.write("users.json", [*users, user.to_dict()])
    except StorageError:
        db.write("portfolios.json", portfolios)
        raise
    return user


def login(username: str, password: str) -> User:
    """Проверить имя и пароль; CLI хранит сессию в памяти."""
    for record in DatabaseManager().read_records("users.json"):
        user = _user_from_record(record)
        if user.username == username:
            if not user.verify_password(password):
                raise ValueError("Неверный пароль")
            return user
    raise ValueError(f"Пользователь '{username}' не найден")


def load_portfolio(user_id: int, rate_service=None) -> Portfolio:
    """Загрузить независимые объекты кошельков пользователя."""
    user = get_user(user_id)
    records = DatabaseManager().read_records("portfolios.json")
    record = next((item for item in records if item.get("user_id") == user_id), None)
    if record is None:
        raise StorageError("Портфель пользователя не найден в portfolios.json")
    try:
        wallets = {
            code: Wallet(code, entry["balance"])
            for code, entry in record["wallets"].items()
        }
        return Portfolio(user_id, user, wallets, rate_service)
    except (KeyError, TypeError, ValueError) as error:
        raise StorageError("Некорректная запись портфеля в portfolios.json") from error


def save_portfolio(portfolio: Portfolio):
    """Заменить только портфель владельца, сохранив остальных пользователей."""
    db = DatabaseManager()
    records = db.read_records("portfolios.json")
    updated = portfolio.to_dict()
    index = next(
        (
            i
            for i, item in enumerate(records)
            if item.get("user_id") == updated["user_id"]
        ),
        None,
    )
    if index is None:
        raise StorageError("Портфель пользователя не найден")
    records[index] = updated
    db.write("portfolios.json", records)


def show_portfolio(user_id: int, base: str | None = None, *, rate_service=None) -> dict:
    """Подготовить строки и итоговую стоимость для CLI."""
    base = base or SettingsLoader().get("DEFAULT_BASE_CURRENCY")
    get_currency(base)
    rates = rate_service or RateService()
    portfolio = load_portfolio(user_id, rates)
    rows = []
    for code, wallet in sorted(portfolio.wallets.items()):
        value = (
            wallet.balance * rates.get_rate(code, base)["rate"] if wallet.balance else 0
        )
        rows.append({"code": code, "balance": wallet.balance, "value": value})
    return {
        "username": portfolio.user.username,
        "base": base,
        "rows": rows,
        "total": sum(row["value"] for row in rows),
    }


def _trade_input(currency_code: str, amount: float) -> float:
    get_currency(currency_code)
    amount = validate_number(amount, "amount")
    if currency_code == "USD":
        raise ValueError("USD — расчётная валюта. Выберите другую валюту для сделки")
    return amount


@log_action("BUY", verbose=True)
def buy(user_id: int, currency_code: str, amount: float, *, rate_service=None) -> dict:
    """Списать стоимость в USD и пополнить покупаемую валюту."""
    amount = _trade_input(currency_code, amount)
    portfolio = load_portfolio(user_id)
    rate = (rate_service or RateService()).get_rate(currency_code, "USD")["rate"]
    cost = validate_number(amount * rate, "cost")
    usd = portfolio.wallets.get("USD")
    available = usd.balance if usd else 0.0
    if cost > available:
        raise InsufficientFundsError(available, cost, "USD")
    wallet = portfolio.wallets.get(currency_code)
    before = wallet.balance if wallet else 0.0
    validate_number(before + amount, "balance", allow_zero=True)

    wallet = portfolio.add_currency(currency_code)
    usd.withdraw(cost)
    wallet.deposit(amount)
    save_portfolio(portfolio)
    return {
        "currency_code": currency_code,
        "amount": amount,
        "rate": rate,
        "value": cost,
        "changes": {
            currency_code: {"before": before, "after": wallet.balance},
            "USD": {"before": available, "after": usd.balance},
        },
    }


@log_action("SELL", verbose=True)
def sell(user_id: int, currency_code: str, amount: float, *, rate_service=None) -> dict:
    """Снять продаваемую валюту и начислить выручку в USD."""
    amount = _trade_input(currency_code, amount)
    portfolio = load_portfolio(user_id)
    wallet = portfolio.get_wallet(currency_code)
    if amount > wallet.balance:
        raise InsufficientFundsError(wallet.balance, amount, currency_code)
    rate = (rate_service or RateService()).get_rate(currency_code, "USD")["rate"]
    revenue = validate_number(amount * rate, "revenue")
    usd_before = portfolio.wallets.get("USD")
    usd_before = usd_before.balance if usd_before else 0.0
    validate_number(usd_before + revenue, "balance", allow_zero=True)
    before = wallet.balance
    usd = portfolio.add_currency("USD")
    wallet.withdraw(amount)
    usd.deposit(revenue)
    save_portfolio(portfolio)
    return {
        "currency_code": currency_code,
        "amount": amount,
        "rate": rate,
        "value": revenue,
        "changes": {
            currency_code: {"before": before, "after": wallet.balance},
            "USD": {"before": usd_before, "after": usd.balance},
        },
    }


def get_rate(from_code: str, to_code: str, *, rate_service=None) -> dict:
    """Получить актуальный курс через единый сервис."""
    return (rate_service or RateService()).get_rate(from_code, to_code)


def show_rates(currency=None, top=None, base="USD", *, rate_service=None) -> dict:
    """Прочитать локальный кеш с фильтрами."""
    return (rate_service or RateService()).show_rates(currency, top, base)
