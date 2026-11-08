"""Логирование результата покупки/продажи без изменения поведения."""

#Этап 3

import inspect
import logging
import math
from functools import wraps


def log_action(action: str, *, verbose: bool = False):
    """Записать успех/ошибку; исключение обязательно пробросить дальше."""

    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs).arguments
            amount = bound.get("amount")
            if isinstance(amount, float) and not math.isfinite(amount):
                amount = str(amount)
            fields = {
                "action": action,
                "user_id": bound.get("user_id"),
                "currency_code": bound.get("currency_code"),
                "amount": amount,
                "rate": None,
                "base": "USD",
            }
            logger = logging.getLogger("valutatrade.actions")
            try:
                result = function(*args, **kwargs)
            except Exception as error:
                fields.update(
                    result="ERROR",
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
                logger.info(action, extra={"action_data": fields})
                raise
            fields.update(result="OK", rate=result["rate"])
            if verbose:
                fields["wallets"] = result["changes"]
            logger.info(action, extra={"action_data": fields})
            return result

        return wrapped

    return decorate
