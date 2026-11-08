"""Явные фикстуры HTTP; никаких запросов к реальным API."""

#Этап 5

import json
from pathlib import Path

from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater

FIXTURES = Path(__file__).parent / "fixtures"


class FixtureResponse:
    """Минимальный ответ с методами, используемыми API-клиентами."""

    def __init__(self, data, status_code=200):
        self.data = data
        self.status_code = status_code

    def json(self):
        """Вернуть фикстуру либо воспроизвести ошибку JSON."""
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class FixtureTransport:
    """Ответы из файлов; сохраняет параметры запросов для проверки контракта."""

    def __init__(self, *, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        """Воспроизвести локальный HTTP-ответ без сети."""
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        if self.response:
            return self.response
        filename = "coingecko.json" if "coingecko" in url else "exchangerate.json"
        return FixtureResponse(json.loads((FIXTURES / filename).read_text()))


def fixture_updater(source=None) -> RatesUpdater:
    """Реальные клиенты с фикстурным транспортом и явным учебным ключом."""
    config = ParserConfig(EXCHANGERATE_API_KEY="fixture-only")
    transport = FixtureTransport()
    clients = {
        "coingecko": CoinGeckoClient(config, transport),
        "exchangerate": ExchangeRateApiClient(config, transport),
    }
    selected = [clients[source]] if source else list(clients.values())
    return RatesUpdater(selected, RatesStorage(config))
