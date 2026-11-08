"""Пользователь, отдельный кошелёк и портфель."""

#Этап 2

import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.utils import parse_timestamp, validate_number
from valutatrade_hub.infra.rates import RateService


class User:
    """Пользователь с солью и односторонним SHA-256-хешем пароля."""

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ):
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
            raise ValueError("user_id должен быть положительным целым числом")
        if not isinstance(registration_date, datetime):
            raise ValueError("Дата регистрации должна быть datetime")
        self._user_id = user_id
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @classmethod
    def create(cls, user_id: int, username: str, password: str):
        """Создать пользователя с новой солью и текущей датой."""
        user = cls(user_id, username, "", secrets.token_hex(16), datetime.now(UTC))
        user.change_password(password)
        return user

    @property
    def user_id(self) -> int:
        """Идентификатор пользователя, доступный только для чтения."""
        return self._user_id

    @property
    def username(self) -> str:
        """Имя пользователя."""
        return self._username

    @username.setter
    def username(self, value: str):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя пользователя не может быть пустым")
        self._username = value.strip()

    @property
    def hashed_password(self) -> str:
        """Хеш для сериализации; открытый пароль не хранится."""
        return self._hashed_password

    @property
    def salt(self) -> str:
        """Уникальная соль пользователя."""
        return self._salt

    @property
    def registration_date(self) -> datetime:
        """Дата регистрации."""
        return self._registration_date

    def get_user_info(self) -> dict:
        """Вернуть информацию без пароля, хеша и соли."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "registration_date": self.registration_date.isoformat(),
        }

    def change_password(self, new_password: str):
        """Проверить длину и заменить хеш пароля."""
        if not isinstance(new_password, str) or len(new_password) < 4:
            raise ValueError("Пароль должен быть не короче 4 символов")
        self._hashed_password = hashlib.sha256(
            (new_password + self.salt).encode("utf-8")
        ).hexdigest()

    def verify_password(self, password: str) -> bool:
        """Сравнить хеш введённого пароля с сохранённым."""
        if not isinstance(password, str):
            return False
        hashed = hashlib.sha256((password + self.salt).encode("utf-8")).hexdigest()
        return hmac.compare_digest(hashed, self.hashed_password)

    def to_dict(self) -> dict:
        """Подготовить запись users.json."""
        return {
            **self.get_user_info(),
            "hashed_password": self.hashed_password,
            "salt": self.salt,
        }

    @classmethod
    def from_dict(cls, record: dict):
        """Восстановить пользователя из JSON-записи."""
        return cls(
            record["user_id"],
            record["username"],
            record["hashed_password"],
            record["salt"],
            parse_timestamp(record["registration_date"]),
        )


class Wallet:
    """Неотрицательный баланс одной поддерживаемой валюты."""

    def __init__(self, currency_code: str, balance: float = 0.0):
        self.currency_code = get_currency(currency_code).code
        self.balance = balance

    @property
    def balance(self) -> float:
        """Текущий баланс."""
        return self._balance

    @balance.setter
    def balance(self, value: float):
        self._balance = validate_number(value, "balance", allow_zero=True)

    def deposit(self, amount: float):
        """Пополнить кошелёк положительной суммой."""
        self.balance = self.balance + validate_number(amount, "amount")

    def withdraw(self, amount: float):
        """Снять средства, если их достаточно."""
        amount = validate_number(amount, "amount")
        if amount > self.balance:
            raise InsufficientFundsError(self.balance, amount, self.currency_code)
        self.balance = self.balance - amount

    def get_balance_info(self) -> str:
        """Вернуть баланс вместе с кодом валюты."""
        return f"{self.currency_code}: {self.balance:.4f}"


class Portfolio:
    """Кошельки одного пользователя; валюты в словаре уникальны."""

    def __init__(
        self, user_id: int, user: User, wallets: dict | None = None, rate_provider=None
    ):
        if user_id != user.user_id:
            raise ValueError("Портфель и пользователь должны иметь одинаковый user_id")
        self._user_id = user_id
        self._user = user
        self._wallets = dict(wallets or {})
        for code, wallet in self._wallets.items():
            if not isinstance(wallet, Wallet) or code != wallet.currency_code:
                raise ValueError("Ключ кошелька должен совпадать с кодом валюты")
        self._rate_provider = rate_provider

    @property
    def user(self) -> User:
        """Владелец, доступный только для чтения."""
        return self._user

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Копия словаря; сами кошельки остаются объектами портфеля."""
        return self._wallets.copy()

    def add_currency(self, currency_code: str) -> Wallet:
        """Создать кошелёк, только если его ещё нет."""
        get_currency(currency_code)
        if currency_code not in self._wallets:
            self._wallets[currency_code] = Wallet(currency_code)
        return self._wallets[currency_code]

    def get_wallet(self, currency_code: str) -> Wallet:
        """Получить существующий кошелёк."""
        get_currency(currency_code)
        if currency_code not in self._wallets:
            raise ValueError(
                f"У вас нет кошелька '{currency_code}'. Добавьте валюту: "
                "она создаётся автоматически при первой покупке."
            )
        return self._wallets[currency_code]

    def get_total_value(self, base_currency: str = "USD") -> float:
        """Оценить все ненулевые остатки по актуальным курсам."""
        get_currency(base_currency)
        if self._rate_provider is None:
            self._rate_provider = RateService()
        return sum(
            wallet.balance * self._rate_provider.get_rate(code, base_currency)["rate"]
            for code, wallet in self._wallets.items()
            if wallet.balance
        )

    def to_dict(self) -> dict:
        """Подготовить запись portfolios.json."""
        return {
            "user_id": self._user_id,
            "wallets": {
                code: {"currency_code": code, "balance": wallet.balance}
                for code, wallet in self._wallets.items()
            },
        }
