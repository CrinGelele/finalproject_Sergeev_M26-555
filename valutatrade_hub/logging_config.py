"""JSON-логи: ISO-время UTC, уровень, сообщение и ротация по размеру."""

#Этап 3

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from valutatrade_hub.infra.settings import SettingsLoader


class JsonFormatter(logging.Formatter):
    """Форматировать стандартные и доменные записи одинаково."""

    def format(self, record: logging.LogRecord) -> str:
        """Вернуть одну JSON-строку."""
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        entry.update(getattr(record, "action_data", {}))
        return json.dumps(entry, ensure_ascii=False, default=str, allow_nan=False)


def setup_logging():
    """Настроить actions.log и parser.log без дублирования обработчиков."""
    settings = SettingsLoader()
    directory = settings.get("LOG_DIR")
    directory.mkdir(parents=True, exist_ok=True)
    for name, filename in (
        ("valutatrade.actions", "actions.log"),
        ("valutatrade.parser", "parser.log"),
    ):
        logger = logging.getLogger(name)
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
        logger.setLevel(settings.get("LOG_LEVEL"))
        logger.propagate = False
        handler = RotatingFileHandler(
            directory / filename,
            maxBytes=settings.get("LOG_MAX_BYTES"),
            backupCount=settings.get("LOG_BACKUP_COUNT"),
            encoding="utf-8",
        )
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
