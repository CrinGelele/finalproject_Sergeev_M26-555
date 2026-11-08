"""Выполнить команды и записать их настоящий вывод в asciinema v2."""

#Этап 5

import io
import json
import shutil
import time
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.support import fixture_updater
from valutatrade_hub.cli.interface import CLI
from valutatrade_hub.core import usecases
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.rates import RateService
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import setup_logging

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo"


def write_player(events: list):
    """Создать автономный HTML-плеер той же записи, без внешних библиотек."""
    content = json.dumps(events, ensure_ascii=False).replace("<", "\\u003c")
    page = """<!doctype html>
<html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ValutaTrade Hub — локальное демо</title>
<style>
body{margin:0;background:#101727;color:#e8edf6;font:16px system-ui,sans-serif}
main{max-width:1160px;margin:32px auto;padding:0 24px}
h1{font-size:30px;margin-bottom:8px}.note{color:#b7c4d9;line-height:1.5}
.bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:24px 0}
button{background:#c2f1e2;color:#101727;border:0;border-radius:8px;padding:10px 16px;
cursor:pointer;font:inherit}input{flex:1;min-width:150px}label{color:#b7c4d9}
pre{background:#080d17;border:1px solid #344052;border-radius:12px;padding:20px;
line-height:1.5;font-size:14px;overflow:auto;min-height:360px;white-space:pre}
a{color:#c2f1e2}code{font-family:monospace}
</style><main><h1>ValutaTrade Hub</h1>
<p class="note">Локальное демо учебного проекта. Все команды выполнены;
курсы получены через явно заданные HTTP-фикстуры. Это не рыночные котировки.
Учебный капитал 10 000 USD подготовлен отдельно и показан в записи.</p>
<div class="bar"><button id="play">▶ Смотреть</button>
<button id="next">Следующий шаг</button><button id="reset">С начала</button>
<input id="seek" type="range" min="0" step="1" value="0" aria-label="Шаг демо">
<label id="counter"></label></div><pre id="screen" aria-live="polite"></pre>
<p class="note">Плеер показывает запись по шагам. Исходные временные метки
сохранены в <a href="session.cast">session.cast</a> (asciinema v2), весь вывод —
в <a href="transcript.txt">transcript.txt</a>.</p></main>
<script id="events" type="application/json">EVENTS</script><script>
const events=JSON.parse(document.getElementById('events').textContent);
let position=0,timer=null;
const screen=document.getElementById('screen'),seek=document.getElementById('seek'),
counter=document.getElementById('counter'),play=document.getElementById('play');
seek.max=events.length;
function show(){screen.textContent=events.slice(0,position).map(e=>e[2]).join('');
seek.value=position;counter.textContent=position+' / '+events.length;
screen.scrollTop=screen.scrollHeight;}
function stop(){clearInterval(timer);timer=null;play.textContent='▶ Смотреть';}
document.getElementById('next').onclick=()=>{stop();position=Math.min(position+1,events.length);show();};
document.getElementById('reset').onclick=()=>{stop();position=0;show();};
seek.oninput=()=>{stop();position=Number(seek.value);show();};
play.onclick=()=>{if(timer){stop();return;}if(position===events.length)position=0;
play.textContent='Ⅱ Пауза';timer=setInterval(()=>{position++;show();
if(position===events.length)stop();},800);};show();
</script></html>"""
    (DEMO_DIR / "player.html").write_text(
        page.replace("EVENTS", content), encoding="utf-8"
    )


def main():
    """Записать полный сценарий, изолировав его от основных data/."""
    runtime = DEMO_DIR / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir()
    config = runtime / "pyproject.toml"
    config.write_text(
        '[tool.valutatrade]\nDATA_DIR = "data"\nLOG_DIR = "logs"\n'
        "RATES_TTL_SECONDS = 300\n",
        encoding="utf-8",
    )
    SettingsLoader().reload(config)
    setup_logging()
    started = time.monotonic()
    timestamp = int(time.time())
    events = []
    results = []

    def emit(output):
        events.append([round(time.monotonic() - started, 6), "o", output])
        print(output, end="")

    rates = RateService(updater=fixture_updater())
    cli = CLI(rate_service=rates, updater_factory=fixture_updater)

    def command(line, expected=0):
        emit(f"> {line}\n")
        capture = io.StringIO()
        with redirect_stdout(capture):
            status = cli.execute(line)
        emit(capture.getvalue())
        results.append({"command": line, "exit_code": status, "expected": expected})
        if status != expected:
            raise RuntimeError(f"Команда {line} вернула {status}, ожидалось {expected}")

    try:
        emit("ValutaTrade Hub — локальный запуск на фикстурах HTTP.\n")
        emit(f"Дата записи: {datetime.now().astimezone().isoformat()}\n")
        command("buy --currency BTC --amount 0.05", 1)
        command("register --username alice --password 1234")
        command("login --username alice --password wrong", 1)
        command("login --username alice --password 1234")
        command("show-portfolio")
        emit(
            "[Подготовка фикстуры: начальный учебный баланс 10000 USD; "
            "отдельная операция, не торговая команда.]\n"
        )
        portfolio = usecases.load_portfolio(cli.user.user_id)
        portfolio.add_currency("USD").deposit(10000)
        usecases.save_portfolio(portfolio)
        command("update-rates")
        command("buy --currency BTC --amount 0.05")
        command("sell --currency BTC --amount 0.01")
        command("show-portfolio")
        command("show-portfolio --base EUR")
        command("get-rate --from USD --to BTC")
        command("get-rate --from BTC --to EUR")
        command("update-rates --source coingecko")
        command("show-rates --top 2")
        command("show-rates --currency RUB")
        command("show-rates --base EUR")
        command("sell --currency BTC --amount 0.05", 1)
        command("buy --currency ABC --amount 1", 1)
        command("buy --currency BTC --amount nan", 1)
        emit("[Фикстура TTL: BTC_USD получает старую дату; обновление недоступно.]\n")
        db = DatabaseManager()
        cache = db.read("rates.json", {})
        cache["pairs"]["BTC_USD"]["updated_at"] = "2020-01-01T00:00:00Z"
        db.write("rates.json", cache)
        with patch.object(
            rates.updater, "run_update", side_effect=ApiRequestError("fixture offline")
        ):
            command("get-rate --from BTC --to USD", 1)
        command("show-rates --currency BTC")
        command("update-rates")
        command("get-rate --from BTC --to USD")
        final = usecases.show_portfolio(cli.user.user_id, rate_service=rates)
        if abs(final["total"] - 10000.0) > 1e-6:
            raise RuntimeError("Итоговая стоимость не совпала с учебным капиталом")
        emit(
            "[Проверка: стоимость портфеля 10000.00 USD, ошибки не изменили баланс.]\n"
        )
        header = {
            "version": 2,
            "width": 160,
            "height": 40,
            "timestamp": timestamp,
            "title": "ValutaTrade Hub — local HTTP fixtures",
            "env": {"TERM": "xterm-256color"},
        }
        with (DEMO_DIR / "session.cast").open("w", encoding="utf-8") as stream:
            for event in [header, *events]:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        (DEMO_DIR / "transcript.txt").write_text(
            "".join(event[2] for event in events), encoding="utf-8"
        )
        (DEMO_DIR / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_player(events)
    finally:
        SettingsLoader().reload(ROOT / "pyproject.toml")
        setup_logging()


if __name__ == "__main__":
    main()
