"""Необязательный ручной запуск Parser Service по интервалу."""

#Этап 4

import logging
import time

from valutatrade_hub.core.exceptions import ApiRequestError, StorageError
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import setup_logging
from valutatrade_hub.parser_service.updater import make_updater


def main():
    """Обновлять до Ctrl+C; никаких системных заданий не создаёт."""
    setup_logging()
    interval = SettingsLoader().get("PARSER_INTERVAL_SECONDS")
    try:
        while True:
            try:
                make_updater().run_update()
            except (ApiRequestError, StorageError) as error:
                logging.getLogger("valutatrade.parser").error("%s", error)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Parser Service остановлен")


if __name__ == "__main__":
    main()
