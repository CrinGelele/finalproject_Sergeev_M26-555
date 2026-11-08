# Python, итоговый проект — ValutaTrade Hub

Сергеев Максим Александрович, группа М26-555.

Учебный валютный кошелёк: регистрация, покупка и продажа виртуальных валют,
оценка портфеля. Данные хранятся в JSON. Parser Service получает курсы
криптовалют из CoinGecko, фиатных валют — из ExchangeRate-API.

## Структура каталогов

```text
finalproject_Sergeev_M26-555/
├── data/                     # пользователи, портфели, кэш и история курсов
├── valutatrade_hub/
│   ├── core/                 # модели, валюты, исключения и операции
│   ├── infra/                # настройки, JSON-хранилище и работа с курсами
│   ├── parser_service/       # API-клиенты, обновление, хранение и планировщик
│   ├── cli/                  # команды и интерактивная сессия
│   ├── logging_config.py
│   └── decorators.py
├── demo/                     # GIF, запись и сценарий демонстрации
├── main.py
├── Makefile
├── pyproject.toml
└── uv.lock
```

## Установка и запуск

Нужны Python 3.12, [uv](https://docs.astral.sh/uv/) и make.

```bash
git clone https://github.com/CrinGelele/finalproject_Sergeev_M26-555.git
cd finalproject_Sergeev_M26-555
make install
make run
```

Без make: `uv sync --locked`, затем `uv run valutatrade`.
Команды ниже вводятся в одной сессии; `help` — справка, `exit` — выход.

```text
register --username alice --password 1234
login --username alice --password 1234
show-portfolio
```

Новый портфель пуст. Чтобы повторить пример сделок, завершите приложение
командой `exit`. В списке `data/portfolios.json` найдите объект своего
пользователя и задайте учебный USD-баланс, сохранив записи остальных пользователей.
Пример объекта для `user_id=1`:

```json
{"user_id": 1, "wallets": {"USD": {"currency_code": "USD", "balance": 10000}}}
```

Настройте ключ по инструкции ниже, снова выполните `make run` и войдите:

```text
login --username alice --password 1234
update-rates
buy --currency BTC --amount 0.05
sell --currency BTC --amount 0.01
show-portfolio --base USD
get-rate --from USD --to BTC
show-rates --top 2
show-rates --currency RUB
show-rates --base EUR
```

## Parser Service и API-ключ

CoinGecko работает без ключа. Ключ [ExchangeRate-API](https://www.exchangerate-api.com/)
хранится в переменной окружения `EXCHANGERATE_API_KEY`.
Перед запуском приложения задайте её в текущем терминале:

```bash
export EXCHANGERATE_API_KEY='ваш_ключ'
uv run valutatrade update-rates
```

Обновление одного источника: `uv run valutatrade update-rates --source coingecko`
или `uv run valutatrade update-rates --source exchangerate`.
Для периодического обновления запустите в отдельном терминале из папки проекта:

```bash
export EXCHANGERATE_API_KEY='ваш_ключ'
uv run python -m valutatrade_hub.parser_service.scheduler
```

Интервал — 300 секунд, параметр `PARSER_INTERVAL_SECONDS` в `[tool.valutatrade]`
файла `pyproject.toml`. Планировщик останавливается по Ctrl+C.
Ключ не добавляйте в исходники или Git. Если храните его в локальном `.env`,
загрузите переменные перед запуском: `set -a`, `source .env`, `set +a`.

## Кэш и TTL

`data/rates.json` — последний срез курсов; `data/exchange_rates.json` — история.
TTL каждой пары — 300 секунд (`RATES_TTL_SECONDS` в `[tool.valutatrade]`).
`get-rate`, оценка портфеля и сделки используют свежий кэш; отсутствующий или
устаревший курс запускает обновление. Если свежий курс недоступен, операция
отклоняется с сообщением. `show-rates` читает кэш и отмечает устаревшие записи.
Логи операций и парсера сохраняются в `logs/` с ротацией.

## Демонстрация

![Демонстрация](demo/session.gif)

[Запись](demo/session.cast). Для воспроизводимости демо использует фиксированные
ответы API из `demo/fixtures` и отдельный учебный баланс 10 000 USD.
