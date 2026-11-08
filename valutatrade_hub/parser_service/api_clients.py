"""Два API-клиента с единым контрактом: пара → положительный курс."""

#Этап 4

import time
from abc import ABC, abstractmethod

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import utc_now, validate_number
from valutatrade_hub.parser_service.config import ParserConfig


class BaseApiClient(ABC):
    """Общий интерфейс и проверка HTTP-ответов."""

    source = "Unknown"

    def __init__(self, config: ParserConfig | None = None, transport=None):
        self.config = config or ParserConfig()
        self.transport = transport or requests
        self.metadata = {}
        self.updated_at = None

    def _get(self, url: str, **kwargs) -> dict:
        self.metadata = {}
        self.updated_at = None
        started = time.monotonic()
        try:
            response = self.transport.get(
                url, timeout=self.config.REQUEST_TIMEOUT, **kwargs
            )
        except requests.exceptions.RequestException as error:
            raise ApiRequestError(
                f"{self.source}: сеть недоступна или превышен таймаут"
            ) from error
        if response.status_code != 200:
            reasons = {
                401: "неверный ключ доступа",
                403: "доступ запрещён",
                429: "превышен лимит запросов",
            }
            reason = reasons.get(response.status_code, "сервис недоступен")
            raise ApiRequestError(
                f"{self.source}: HTTP {response.status_code}, {reason}"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise ApiRequestError(f"{self.source}: ответ не является JSON") from error
        if not isinstance(payload, dict):
            raise ApiRequestError(f"{self.source}: ожидался JSON-объект")
        self.updated_at = utc_now()
        self.metadata = {
            "request_ms": round((time.monotonic() - started) * 1000, 3),
            "status_code": response.status_code,
        }
        return payload

    @abstractmethod
    def fetch_rates(self) -> dict:
        """Вернуть {FROM_TO: rate}; сбой обернуть в ApiRequestError."""


class CoinGeckoClient(BaseApiClient):
    """Получить криптовалюты по ID CoinGecko."""

    source = "CoinGecko"

    def fetch_rates(self) -> dict:
        """Преобразовать цены выбранных монет в пары к базовой валюте."""
        config = self.config
        try:
            ids = [config.CRYPTO_ID_MAP[code] for code in config.CRYPTO_CURRENCIES]
            data = self._get(
                config.COINGECKO_URL,
                params={
                    "ids": ",".join(ids),
                    "vs_currencies": config.BASE_CURRENCY.lower(),
                },
            )
            return {
                f"{code}_{config.BASE_CURRENCY}": validate_number(
                    data[config.CRYPTO_ID_MAP[code]][config.BASE_CURRENCY.lower()],
                    "rate",
                )
                for code in config.CRYPTO_CURRENCIES
            }
        except (KeyError, TypeError, ValueError) as error:
            raise ApiRequestError(
                "CoinGecko: некорректный или неполный ответ"
            ) from error


class ExchangeRateApiClient(BaseApiClient):
    """Получить фиатные курсы и привести их к валюте → базе."""

    source = "ExchangeRate-API"

    def fetch_rates(self) -> dict:
        """Инвертировать BASE→currency; поддержать официальный conversion_rates."""
        config = self.config
        if not config.EXCHANGERATE_API_KEY:
            raise ApiRequestError(
                "ExchangeRate-API: задайте EXCHANGERATE_API_KEY в окружении"
            )
        url = (
            f"{config.EXCHANGERATE_API_URL}/{config.EXCHANGERATE_API_KEY}"
            f"/latest/{config.BASE_CURRENCY}"
        )
        data = self._get(url)
        if data.get("result") != "success":
            reasons = {
                "invalid-key": "неверный ключ",
                "inactive-account": "учётная запись не активирована",
                "quota-reached": "превышена квота",
            }
            error_code = data.get("error-type")
            reason = (
                reasons.get(error_code, "API вернул ошибку")
                if isinstance(error_code, str)
                else "API вернул ошибку"
            )
            raise ApiRequestError(f"ExchangeRate-API: {reason}")
        if data.get("base_code") != config.BASE_CURRENCY:
            raise ApiRequestError("ExchangeRate-API: неожиданная базовая валюта")
        try:
            rates = data.get("conversion_rates", data.get("rates"))
            return {
                f"{code}_{config.BASE_CURRENCY}": validate_number(
                    1 / validate_number(rates[code], "rate"), "rate"
                )
                for code in config.FIAT_CURRENCIES
            }
        except (KeyError, TypeError, ValueError) as error:
            raise ApiRequestError(
                "ExchangeRate-API: некорректные или неполные курсы"
            ) from error
