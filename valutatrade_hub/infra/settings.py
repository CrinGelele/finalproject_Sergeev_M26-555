"""Единая конфигурация из [tool.valutatrade] в pyproject.toml."""

#Этап 3

import tomllib
from pathlib import Path


class SettingsLoader:
    """Singleton: __new__ выбран как простой и читаемый вариант."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_settings"):
            self.reload()

    def reload(self, config_path: str | Path | None = None):
        """Перезагрузить конфигурацию; относительные пути идут от её папки."""
        path = Path(config_path) if config_path else Path.cwd() / "pyproject.toml"
        defaults = {
            "DATA_DIR": "data",
            "LOG_DIR": "logs",
            "RATES_TTL_SECONDS": 300,
            "DEFAULT_BASE_CURRENCY": "USD",
            "LOG_FORMAT": "json",
            "LOG_LEVEL": "INFO",
            "LOG_MAX_BYTES": 1_048_576,
            "LOG_BACKUP_COUNT": 3,
            "PARSER_INTERVAL_SECONDS": 300,
        }
        if path.exists():
            with path.open("rb") as stream:
                defaults.update(
                    tomllib.load(stream).get("tool", {}).get("valutatrade", {})
                )
        for name in ("DATA_DIR", "LOG_DIR"):
            defaults[name] = (path.resolve().parent / defaults[name]).resolve()
        for name in ("RATES_TTL_SECONDS", "PARSER_INTERVAL_SECONDS", "LOG_MAX_BYTES"):
            if isinstance(defaults[name], bool) or defaults[name] <= 0:
                raise ValueError(f"{name} должен быть положительным числом")
        self._settings = defaults

    def get(self, key: str, default=None):
        """Вернуть значение настройки или default."""
        return self._settings.get(key, default)
