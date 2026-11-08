"""Снимок курсов и история измерений с атомарной записью каждого файла."""

#Этап 4

import re

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.core.utils import parse_timestamp, validate_code, validate_number
from valutatrade_hub.infra.database import atomic_write_json, read_json
from valutatrade_hub.parser_service.config import ParserConfig


class RatesStorage:
    """Хранилище Parser Service; старые/равные срезы не заменяют новые."""

    def __init__(self, config: ParserConfig | None = None):
        self.config = config or ParserConfig()

    def load_rates(self) -> dict:
        """Прочитать снимок, включая плоский формат из второго урока."""
        data = read_json(self.config.RATES_FILE_PATH, {"pairs": {}})
        if not isinstance(data, dict):
            raise StorageError("rates.json должен содержать объект")
        pairs = data.get("pairs")
        if pairs is None:
            pairs = {
                key: value
                for key, value in data.items()
                if re.fullmatch(r"[A-Z]{2,5}_[A-Z]{2,5}", key)
            }
        if not isinstance(pairs, dict):
            raise StorageError("rates.json: pairs должен содержать объект")
        return {
            "pairs": pairs,
            "last_refresh": data.get("last_refresh"),
            "source": data.get("source", "ParserService"),
        }

    def save(self, snapshot: dict, records: list):
        """Проверить и объединить историю/кеш, затем заменить JSON-файлы."""
        current = self.load_rates()
        history = read_json(self.config.HISTORY_FILE_PATH, [])
        if not isinstance(history, list) or not all(
            isinstance(item, dict) and "id" in item for item in history
        ):
            raise StorageError("exchange_rates.json должен содержать список измерений")
        pairs = current["pairs"].copy()
        try:
            for pair, entry in snapshot["pairs"].items():
                from_code, to_code = pair.split("_")
                validate_code(from_code)
                validate_code(to_code)
                validate_number(entry["rate"], "rate")
                updated = parse_timestamp(entry["updated_at"])
                previous = pairs.get(pair)
                if not previous or updated > parse_timestamp(previous["updated_at"]):
                    pairs[pair] = entry.copy()
            refresh = snapshot["last_refresh"]
            if current["last_refresh"] and parse_timestamp(
                current["last_refresh"]
            ) > parse_timestamp(refresh):
                refresh = current["last_refresh"]
        except (KeyError, TypeError, ValueError) as error:
            raise StorageError("Некорректный снимок курсов") from error
        indexed = {item["id"]: item for item in history}
        for record in records:
            try:
                validate_code(record["from_currency"])
                validate_code(record["to_currency"])
                validate_number(record["rate"], "rate")
                parse_timestamp(record["timestamp"])
                if not record["timestamp"].endswith("Z"):
                    raise ValueError("История требует UTC")
                expected_id = (
                    f"{record['from_currency']}_{record['to_currency']}_"
                    f"{record['timestamp']}"
                )
                if record["id"] != expected_id:
                    raise ValueError("Некорректный идентификатор измерения")
            except (KeyError, TypeError, ValueError) as error:
                raise StorageError("Некорректное измерение курсов") from error
            indexed.setdefault(record["id"], record)

        atomic_write_json(self.config.HISTORY_FILE_PATH, list(indexed.values()))
        atomic_write_json(
            self.config.RATES_FILE_PATH,
            {"pairs": pairs, "source": "ParserService", "last_refresh": refresh},
        )
