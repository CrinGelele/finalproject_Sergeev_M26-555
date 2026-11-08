"""Иерархия и реестр поддерживаемых валют."""

#Этап 3

from abc import ABC, abstractmethod

from valutatrade_hub.core.exceptions import CurrencyNotFoundError
from valutatrade_hub.core.utils import validate_code, validate_number


class Currency(ABC):
    """Валюта с единым способом представления."""

    def __init__(self, name: str, code: str):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Название валюты не может быть пустым")
        self.name = name.strip()
        self.code = validate_code(code)

    @abstractmethod
    def get_display_info(self) -> str:
        """Вернуть информацию для интерфейса."""


class FiatCurrency(Currency):
    """Фиатная валюта и страна/зона эмиссии."""

    def __init__(self, name: str, code: str, issuing_country: str):
        super().__init__(name, code)
        self.issuing_country = issuing_country

    def get_display_info(self) -> str:
        """Показать тип, код, название и эмитента."""
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    """Криптовалюта с алгоритмом и известной капитализацией."""

    def __init__(self, name: str, code: str, algorithm: str, market_cap: float):
        super().__init__(name, code)
        self.algorithm = algorithm
        self.market_cap = validate_number(market_cap, "market_cap", allow_zero=True)

    def get_display_info(self) -> str:
        """Показать тип, код, алгоритм и капитализацию."""
        cap = f"{self.market_cap:.3g}" if self.market_cap else "unknown"
        return (
            f"[CRYPTO] {self.code} — {self.name} (Algo: {self.algorithm}, MCAP: {cap})"
        )


CURRENCIES = {
    "USD": FiatCurrency("US Dollar", "USD", "United States"),
    "EUR": FiatCurrency("Euro", "EUR", "Eurozone"),
    "GBP": FiatCurrency("Pound Sterling", "GBP", "United Kingdom"),
    "RUB": FiatCurrency("Russian Ruble", "RUB", "Russia"),
    "BTC": CryptoCurrency("Bitcoin", "BTC", "SHA-256", 0),
    "ETH": CryptoCurrency("Ethereum", "ETH", "Proof of Stake", 0),
    "SOL": CryptoCurrency("Solana", "SOL", "Proof of History / Stake", 0),
}


def get_currency(code: str) -> Currency:
    """Найти валюту по коду или явно сообщить об ошибке."""
    validate_code(code)
    if code not in CURRENCIES:
        raise CurrencyNotFoundError(code)
    return CURRENCIES[code]
