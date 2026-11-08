"""Ошибки, которые CLI может показать пользователю."""

#Этап 3


class InsufficientFundsError(Exception):
    """На кошельке недостаточно денег для операции."""

    def __init__(self, available: float, required: float, code: str):
        self.available = available
        self.required = required
        self.code = code
        super().__init__(
            f"Недостаточно средств: доступно {available:.4f} {code}, "
            f"требуется {required:.4f} {code}"
        )


class CurrencyNotFoundError(Exception):
    """Код отсутствует в реестре поддерживаемых валют."""

    def __init__(self, code: str):
        super().__init__(f"Неизвестная валюта '{code}'")


class ApiRequestError(Exception):
    """Не удалось получить или использовать актуальный курс."""

    def __init__(self, reason: str):
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")


class StorageError(Exception):
    """JSON-файл повреждён или недоступен."""
