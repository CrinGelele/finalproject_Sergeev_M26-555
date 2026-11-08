"""Оркестрация клиентов; сбой одного источника не останавливает другой."""

#Этап 4

import logging

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import utc_now, validate_number
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage


class RatesUpdater:
    """Получить успешные ответы и передать единый снимок хранилищу."""

    def __init__(self, clients: list, storage: RatesStorage):
        self.clients = clients
        self.storage = storage

    def run_update(self) -> dict:
        """Вернуть число измерений, время обновления и список ошибок."""
        logger = logging.getLogger("valutatrade.parser")
        logger.info("Starting rates update...")
        pairs, records, errors = {}, [], []
        for client in self.clients:
            try:
                logger.info("Fetching from %s...", client.source)
                rates = client.fetch_rates()
                if not rates:
                    raise ApiRequestError(f"{client.source}: пустой ответ")
                timestamp = client.updated_at or utc_now()
                client_records, client_pairs = [], {}
                for pair, rate in rates.items():
                    rate = validate_number(rate, "rate")
                    from_code, to_code = pair.split("_")
                    client_pairs[pair] = {
                        "rate": rate,
                        "updated_at": timestamp,
                        "source": client.source,
                    }
                    meta = dict(client.metadata)
                    if client.source == "CoinGecko":
                        meta["raw_id"] = client.config.CRYPTO_ID_MAP[from_code]
                    client_records.append(
                        {
                            "id": f"{pair}_{timestamp}",
                            "from_currency": from_code,
                            "to_currency": to_code,
                            "rate": rate,
                            "timestamp": timestamp,
                            "source": client.source,
                            "meta": meta,
                        }
                    )
                pairs.update(client_pairs)
                records.extend(client_records)
                logger.info("%s OK (%s rates)", client.source, len(rates))
            except ApiRequestError as error:
                errors.append(str(error))
                logger.error("Failed to fetch from %s: %s", client.source, error)
        if not pairs:
            raise ApiRequestError("Обновить курсы не удалось. " + "; ".join(errors))
        refresh = utc_now()
        logger.info("Writing %s rates to rates.json...", len(pairs))
        self.storage.save(
            {"pairs": pairs, "source": "ParserService", "last_refresh": refresh},
            records,
        )
        logger.info("Update completed (%s rates, %s errors)", len(pairs), len(errors))
        return {"count": len(pairs), "last_refresh": refresh, "errors": errors}


def make_updater(source: str | None = None) -> RatesUpdater:
    """Создать обновлятор всех либо одного выбранного источника."""
    config = ParserConfig()
    clients = {
        "coingecko": CoinGeckoClient(config),
        "exchangerate": ExchangeRateApiClient(config),
    }
    if source and source not in clients:
        raise ValueError("Источник: coingecko или exchangerate")
    selected = [clients[source]] if source else list(clients.values())
    return RatesUpdater(selected, RatesStorage(config))
