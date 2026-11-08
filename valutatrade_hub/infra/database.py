"""Чтение JSON и атомарная замена отдельных файлов."""

#Этап 3

import json
import os
import tempfile
from pathlib import Path

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.infra.settings import SettingsLoader


def read_json(path: Path, default):
    """Отсутствие файла допустимо; повреждённый JSON нельзя затирать."""
    if not path.exists():
        return default
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError) as error:
        raise StorageError(f"Не удалось прочитать {path.name}") from error


def atomic_write_json(path: Path, data):
    """Записать tmp в той же папке и заменить файл через os.replace."""
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError) as error:
        raise StorageError(f"Не удалось сохранить {path.name}") from error
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


class DatabaseManager:
    """Singleton через __new__: один экземпляр без метакласса; JSON не кешируется."""

    _instance = None

    def __new__(cls):

        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def path(self, filename: str) -> Path:
        """Получить путь к файлу в data/."""
        return SettingsLoader().get("DATA_DIR") / filename

    def read(self, filename: str, default):
        """Прочитать данные без изменения диска."""
        return read_json(self.path(filename), default)

    def write(self, filename: str, data):
        """Атомарно заменить один JSON-файл."""
        atomic_write_json(self.path(filename), data)

    def read_records(self, filename: str) -> list:
        """Прочитать список записей и проверить форму контейнера."""
        records = self.read(filename, [])
        if not isinstance(records, list) or not all(
            isinstance(record, dict) for record in records
        ):
            raise StorageError(f"{filename} должен содержать список объектов")
        return records
