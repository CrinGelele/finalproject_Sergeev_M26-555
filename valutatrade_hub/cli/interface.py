"""CLI: парсинг, текущая сессия, вызов usecases и отображение результата."""

#Этап 2

import argparse
import shlex
import sys

from prettytable import PrettyTable

from valutatrade_hub.core import usecases
from valutatrade_hub.core.currencies import CURRENCIES
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    StorageError,
)
from valutatrade_hub.infra.rates import RateService
from valutatrade_hub.logging_config import setup_logging
from valutatrade_hub.parser_service.updater import make_updater


class CommandParser(argparse.ArgumentParser):
    """Ошибки аргументов не завершают интерактивную сессию."""

    def error(self, message):
        """Передать сообщение обычному обработчику CLI."""
        raise ValueError(message)


def build_parser() -> CommandParser:
    """Описать все команды и обязательные аргументы."""
    parser = CommandParser(prog="valutatrade", description="ValutaTrade Hub")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("register", "login"):
        child = commands.add_parser(command)
        child.add_argument("--username", required=True)
        child.add_argument("--password", required=True)
    child = commands.add_parser("show-portfolio")
    child.add_argument("--base")
    for command in ("buy", "sell"):
        child = commands.add_parser(command)
        child.add_argument("--currency", required=True)
        child.add_argument("--amount", type=float, required=True)
    child = commands.add_parser("get-rate")
    child.add_argument("--from", dest="from_code", required=True)
    child.add_argument("--to", dest="to_code", required=True)
    child = commands.add_parser("update-rates")
    child.add_argument("--source", choices=("coingecko", "exchangerate"))
    child = commands.add_parser("show-rates")
    child.add_argument("--currency")
    child.add_argument("--top", type=int)
    child.add_argument("--base", default="USD")
    return parser


class CLI:
    """Интерактивный интерфейс; пользователь хранится только в памяти."""

    def __init__(self, *, rate_service=None, updater_factory=None):
        self.user = None
        self.parser = build_parser()
        self.rate_service = rate_service or RateService()
        self.updater_factory = updater_factory or make_updater

    def _user_id(self) -> int:
        if self.user is None:
            raise ValueError("Сначала выполните login")
        return self.user.user_id

    def execute(self, arguments: str | list[str]) -> int:
        """Выполнить команду; 0 — успех, 1 — обработанная ошибка."""
        try:
            tokens = shlex.split(arguments) if isinstance(arguments, str) else arguments
            args = self.parser.parse_args(tokens)
            self._dispatch(args)
            return 0
        except CurrencyNotFoundError as error:
            print(f"{error}. Поддерживаются: {', '.join(CURRENCIES)}")
        except ApiRequestError as error:
            print(f"{error}. Проверьте сеть и настройки; повторите позже")
        except (InsufficientFundsError, StorageError, ValueError) as error:
            print(error)
        except SystemExit as error:
            return int(error.code)
        return 1

    def _dispatch(self, args):
        if args.command == "register":
            user = usecases.register(args.username, args.password)
            print(
                f"Пользователь '{user.username}' зарегистрирован (id={user.user_id}). "
                f"Войдите: login --username {user.username} --password ****"
            )
        elif args.command == "login":
            self.user = usecases.login(args.username, args.password)
            print(f"Вы вошли как '{self.user.username}'")
        elif args.command == "show-portfolio":
            data = usecases.show_portfolio(
                self._user_id(), args.base, rate_service=self.rate_service
            )
            print(f"Портфель пользователя '{data['username']}' (база: {data['base']}):")
            if not data["rows"]:
                print("Портфель пуст")
                return
            table = PrettyTable(["Валюта", "Баланс", f"Стоимость ({data['base']})"])
            for row in data["rows"]:
                table.add_row(
                    [row["code"], f"{row['balance']:.4f}", f"{row['value']:,.2f}"]
                )
            print(table)
            print(f"ИТОГО: {data['total']:,.2f} {data['base']}")
        elif args.command in ("buy", "sell"):
            result = getattr(usecases, args.command)(
                self._user_id(),
                args.currency,
                args.amount,
                rate_service=self.rate_service,
            )
            operation = "Покупка" if args.command == "buy" else "Продажа"
            label = "стоимость покупки" if args.command == "buy" else "выручка"
            print(
                f"{operation} выполнена: {result['amount']:.4f} {args.currency} "
                f"по курсу {result['rate']:.2f} USD/{args.currency}"
            )
            print("Изменения в портфеле:")
            for code, change in result["changes"].items():
                print(
                    f"- {code}: было {change['before']:.4f} "
                    f"→ стало {change['after']:.4f}"
                )
            print(f"Оценочная {label}: {result['value']:,.2f} USD")
        elif args.command == "get-rate":
            entry = usecases.get_rate(
                args.from_code, args.to_code, rate_service=self.rate_service
            )
            print(
                f"Курс {args.from_code}→{args.to_code}: {entry['rate']:.8g} "
                f"(обновлено: {entry['updated_at']})"
            )
            print(
                f"Обратный курс {args.to_code}→{args.from_code}: "
                f"{1 / entry['rate']:.8g}"
            )
        elif args.command == "update-rates":
            result = self.updater_factory(args.source).run_update()
            print(
                f"Обновлено курсов: {result['count']}. "
                f"Последнее обновление: {result['last_refresh']}"
            )
            if result["errors"]:
                print("Обновление завершено с ошибками. Подробности: logs/parser.log")
        elif args.command == "show-rates":
            data = usecases.show_rates(
                args.currency, args.top, args.base, rate_service=self.rate_service
            )
            print(f"Курсы из кеша (обновление: {data['last_refresh']}):")
            table = PrettyTable(["Пара", "Курс", "Обновлено (UTC)", "Статус"])
            for row in data["rows"]:
                table.add_row(
                    [
                        row["pair"],
                        f"{row['rate']:.8g}",
                        row["updated_at"],
                        "устарел" if row["stale"] else "свежий",
                    ]
                )
            print(table)

    def run(self):
        """Читать команды до exit, EOF или Ctrl+C."""
        print("ValutaTrade Hub. help — команды, exit — выход")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nДо встречи")
                break
            if line == "exit":
                break
            if not line:
                continue
            if line == "help":
                self.parser.print_help()
            elif line.startswith("help "):
                self.execute([line[5:].strip(), "--help"])
            else:
                self.execute(line)


def main() -> int:
    """Точка входа пакета и main.py."""
    setup_logging()
    cli = CLI()
    if len(sys.argv) > 1:
        return cli.execute(sys.argv[1:])
    cli.run()
    return 0
