"""Настройки API. Ключ читается только для запросов и не выводится."""

#Этап 4

import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader


@dataclass
class ParserConfig:
    """Конфигурация клиентов, валют, таймаута и файлов."""

    EXCHANGERATE_API_KEY: str | None = field(
        default_factory=lambda: os.getenv("EXCHANGERATE_API_KEY"), repr=False
    )
    COINGECKO_URL: str = "https://api.coingecko.com/api/v3/simple/price"
    EXCHANGERATE_API_URL: str = "https://v6.exchangerate-api.com/v6"
    BASE_CURRENCY: str = "USD"
    FIAT_CURRENCIES: tuple = ("EUR", "GBP", "RUB")
    CRYPTO_CURRENCIES: tuple = ("BTC", "ETH", "SOL")
    CRYPTO_ID_MAP: dict = field(
        default_factory=lambda: {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
        }
    )
    RATES_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().get("DATA_DIR") / "rates.json"
    )
    HISTORY_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().get("DATA_DIR") / "exchange_rates.json"
    )
    REQUEST_TIMEOUT: int = 10
