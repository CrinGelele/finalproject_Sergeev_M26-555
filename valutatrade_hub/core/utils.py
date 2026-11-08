"""Общие проверки и работа с метками UTC."""

#Этап 2

import math
import re
from datetime import UTC, datetime


def validate_number(value: float, name: str, *, allow_zero: bool = False) -> float:
    """Проверить конечное число; bool и строки не считаются суммами."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{name}' должен быть положительным числом")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"'{name}' должен быть конечным числом") from error
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        raise ValueError(f"'{name}' должен быть положительным числом")
    return number


def validate_code(code: str) -> str:
    """Код: от 2 до 5 латинских букв в верхнем регистре."""
    if not isinstance(code, str) or not re.fullmatch(r"[A-Z]{2,5}", code):
        raise ValueError("Код валюты: 2–5 латинских букв в верхнем регистре")
    return code


def utc_now() -> str:
    """Текущее время UTC в ISO-формате с микросекундами."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    """Прочитать ISO-дату; старые примеры без зоны считать UTC."""
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return date.replace(tzinfo=UTC) if date.tzinfo is None else date.astimezone(UTC)
