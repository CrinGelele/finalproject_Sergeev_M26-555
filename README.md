# Python, итоговый проект — ValutaTrade Hub

Сергеев Максим Александрович, группа М26-555.

Консольное приложение для покупки и продажи виртуальных валют.
Пользователи, кошельки и курсы хранятся в JSON; Parser Service обновляет курсы
через CoinGecko и ExchangeRate-API.

## Установка и запуск

Нужны Python 3.12 и [uv](https://docs.astral.sh/uv/).

```bash
make install
make run
```

Без make: `uv sync --locked`, затем `uv run valutatrade`.
Вводите команды в одной сессии. `help` выводит справку, `exit` — выход.

```text
register --username alice --password 1234
login --username alice --password 1234
show-portfolio
update-rates
buy --currency BTC --amount 0.05
sell --currency BTC --amount 0.01
show-portfolio --base USD
get-rate --from USD --to BTC
show-rates --top 2
show-rates --currency RUB
show-rates --base EUR
```

Регистрация создаёт пустой портфель. Для пробных сделок при закрытом
приложении задайте USD-баланс зарегистрированного пользователя
в `data/portfolios.json`, например:

```json
[
  {"user_id": 1, "wallets": {"USD": {"currency_code": "USD", "balance": 10000}}}
]
```

Сохраните записи остальных пользователей, если они есть. При покупке
списывается `amount × rate` USD, при продаже USD зачисляются обратно.
Неверная сумма, неизвестная валюта или недостаток средств отменяют сделку.

## Курсы и Parser Service

CoinGecko работает без ключа. Ключ ExchangeRate-API задайте в окружении
терминала перед запуском; в исходниках и файлах данных его хранить не нужно:

```bash
export EXCHANGERATE_API_KEY='ваш_ключ'
uv run valutatrade update-rates
uv run valutatrade update-rates --source coingecko
uv run valutatrade update-rates --source exchangerate
```

`rates.json` содержит последний срез курсов, `exchange_rates.json` — историю.
TTL по умолчанию — 300 секунд; возраст проверяется для каждой валютной пары.
При устаревшем курсе приложение пробует обновить данные. Если свежего курса
получить не удалось, сделка не выполняется. `show-rates` показывает содержимое
кэша и отмечает устаревшие записи. Поддержаны прямые, обратные и кросс-курсы
через USD.

Пути к данным, TTL и логирование настраиваются в `[tool.valutatrade]`
файла `pyproject.toml`. API-адреса, список валют и таймаут находятся
в `parser_service/config.py`. Периодическое обновление:
`uv run python -m valutatrade_hub.parser_service.scheduler`.
Логи операций и парсера сохраняются в `logs/` с ротацией.

## Структура и проверка

- `valutatrade_hub/core` — пользователи, кошельки, валюты и операции.
- `valutatrade_hub/infra` — конфигурация, JSON-хранилище и кэш курсов.
- `valutatrade_hub/parser_service` — API-клиенты и обновление курсов.
- `valutatrade_hub/cli` — команды и интерактивная сессия.
- `tests` — проверки моделей, сделок, CLI, API, TTL и сохранения данных.

```bash
make lint
make test
make build
make demo
```

## Демонстрация

![Полный сценарий ValutaTrade Hub](demo/session.gif)

[Запись сценария](demo/session.cast) воспроизводится командой
`asciinema play demo/session.cast`. Демо использует фиксированные ответы API
из `tests/fixtures` и отдельный учебный баланс 10 000 USD.
Показаны регистрация, вход, сделки, оценка портфеля, получение и обновление
курсов, а также ошибки ввода и недостаток средств.
