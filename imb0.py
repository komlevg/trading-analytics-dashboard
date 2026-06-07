"""
FVG Telegram Bot  (aiogram 3.x)
================================
Бот для мониторинга Fair Value Gap на крипто активах.

Установка:
    pip install aiogram ccxt pandas numpy

Настройка:
    1. @BotFather → /newbot → BOT_TOKEN
    2. Задайте токен:
         export TG_TOKEN="123456:ABC..."
       или пропишите прямо в BOT_TOKEN ниже.

Команды бота:
    /start                  — приветствие и список команд
    /monitor BTC/USDT 1h    — запустить мониторинг пары
    /stop                   — остановить мониторинг
    /status                 — текущие открытые FVG
    /symbol ETH/USDT        — сменить пару (мониторинг перезапустится)
    /timeframe 4h           — сменить таймфрейм
    /interval 120           — сменить интервал проверки (секунды)
    /settings               — показать текущие настройки
"""

import asyncio
import hashlib
import logging
import os
import sys
from datetime import datetime, timezone

try:
    import ccxt
    import pandas as pd
    import numpy as np
    from aiogram import Bot, Dispatcher, F
    from aiogram.filters import Command, CommandStart
    from aiogram.types import Message, BotCommand
    from aiogram.enums import ParseMode
    from aiogram.client.default import DefaultBotProperties
except ImportError as e:
    print(f"[ОШИБКА] Не установлены зависимости: {e}")
    print("Установите: pip install aiogram ccxt pandas numpy")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Конфиг (можно менять здесь или через env)
# ─────────────────────────────────────────────
BOT_TOKEN       =  os.getenv("TG_TOKEN", "ВСТАВЬТЕ_ТОКЕН_СЮДА")
DEFAULT_SYMBOL  = "BTC/USDT"
DEFAULT_TF      = "1h"
DEFAULT_EXCHANGE= "binance"
DEFAULT_INTERVAL= 60       # секунд между проверками
DEFAULT_LIMIT   = 300      # свечей для загрузки
FVG_DAYS        = 7        # горизонт поиска FVG
FVG_MIN_PCT     = 0.05     # мин. размер FVG в % от цены


# ─────────────────────────────────────────────
# Состояние бота (одно на весь процесс)
# ─────────────────────────────────────────────
class MonitorState:
    def __init__(self):
        self.symbol:    str   = DEFAULT_SYMBOL
        self.timeframe: str   = DEFAULT_TF
        self.interval:  int   = DEFAULT_INTERVAL
        self.exchange:  str   = DEFAULT_EXCHANGE
        self.running:   bool  = False
        self.known_ids: set   = set()
        self.task: asyncio.Task | None = None
        self.chat_id:   int | None = None

state = MonitorState()


# ─────────────────────────────────────────────
# FVG-логика
# ─────────────────────────────────────────────
def fvg_uid(row: dict) -> str:
    key = f"{row['time']}_{row['type']}_{row['gap_bot']:.6f}_{row['gap_top']:.6f}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def fetch_ohlcv(exchange_id: str, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("timestamp").sort_index()


def detect_fvg(df: pd.DataFrame,
               min_pct: float = FVG_MIN_PCT,
               days: int = FVG_DAYS) -> pd.DataFrame:
    fvgs   = []
    prices = df.reset_index()

    for i in range(2, len(prices)):
        c0, c1, c2 = prices.iloc[i-2], prices.iloc[i-1], prices.iloc[i]
        mid = (c1["close"] + c1["open"]) / 2

        if c2["low"] > c0["high"]:
            gap = c2["low"] - c0["high"]
            if gap / mid * 100 >= min_pct:
                fvgs.append({"time": c2["timestamp"], "type": "Bullish FVG",
                              "gap_top": c2["low"],  "gap_bot": c0["high"],
                              "gap_size": gap, "gap_pct": round(gap / mid * 100, 3),
                              "filled": False})
        elif c2["high"] < c0["low"]:
            gap = c0["low"] - c2["high"]
            if gap / mid * 100 >= min_pct:
                fvgs.append({"time": c2["timestamp"], "type": "Bearish FVG",
                              "gap_top": c0["low"],  "gap_bot": c2["high"],
                              "gap_size": gap, "gap_pct": round(gap / mid * 100, 3),
                              "filled": False})

    if not fvgs:
        return pd.DataFrame()

    result = pd.DataFrame(fvgs)
    cutoff = pd.Timestamp.now(tz=timezone.utc) - pd.Timedelta(days=days)
    result = result[result["time"] >= cutoff].reset_index(drop=True)
    if result.empty:
        return result

    for idx, fvg in result.iterrows():
        future = df[df.index > fvg["time"]]
        if fvg["type"] == "Bullish FVG":
            if (future["low"] <= fvg["gap_bot"]).any():
                result.at[idx, "filled"] = True
        else:
            if (future["high"] >= fvg["gap_top"]).any():
                result.at[idx, "filled"] = True

    result["id"] = result.apply(fvg_uid, axis=1)
    return result


# ─────────────────────────────────────────────
# Форматирование сообщений
# ─────────────────────────────────────────────
def fmt_fvg_alert(row: pd.Series, current_price: float) -> str:
    is_bull = "Bullish" in row["type"]
    emoji   = "🟢" if is_bull else "🔴"
    arrow   = "▲ БЫЧИЙ" if is_bull else "▼ МЕДВЕЖИЙ"
    edge    = row["gap_top"] if is_bull else row["gap_bot"]
    dist    = abs(current_price - edge)
    dist_pct= dist / current_price * 100

    return (
        f"{emoji} <b>Новый FVG — {state.symbol} [{state.timeframe}]</b>\n\n"
        f"Тип:           <b>{arrow} FVG</b>\n"
        f"Зона:          <code>{row['gap_bot']:.4f} – {row['gap_top']:.4f}</code>\n"
        f"Размер:        <code>{row['gap_size']:.4f}  ({row['gap_pct']}%)</code>\n"
        f"Текущая цена:  <code>{current_price:.4f}</code>\n"
        f"Расстояние:    <code>{dist:.4f}  ({dist_pct:.2f}%)</code>\n"
        f"Время FVG:     {row['time'].strftime('%Y-%m-%d %H:%M UTC')}"
    )


def fmt_status(fvgs: pd.DataFrame, current_price: float) -> str:
    if fvgs.empty:
        return f"📭 Открытых FVG нет за последние {FVG_DAYS} дней."

    open_fvgs = fvgs[~fvgs["filled"]]
    if open_fvgs.empty:
        return "📭 Все найденные FVG уже закрыты."

    lines = [
        f"📊 <b>Открытые FVG — {state.symbol} [{state.timeframe}]</b>\n"
        f"Цена: <code>{current_price:.4f}</code>  │  Найдено: {len(open_fvgs)}\n"
    ]
    for _, row in open_fvgs.tail(10).iterrows():
        emoji = "🟢▲" if "Bullish" in row["type"] else "🔴▼"
        lines.append(
            f"{emoji} <code>{row['gap_bot']:.4f} – {row['gap_top']:.4f}</code>"
            f"  ({row['gap_pct']}%)\n"
            f"    ⏱ {row['time'].strftime('%m-%d %H:%M UTC')}"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Фоновый мониторинг
# ─────────────────────────────────────────────
async def monitor_loop(bot: Bot):
    log.info("Мониторинг запущен: %s [%s]", state.symbol, state.timeframe)

    first_run = True
    while state.running:
        try:
            df  = await asyncio.to_thread(
                fetch_ohlcv, state.exchange, state.symbol, state.timeframe, DEFAULT_LIMIT
            )
            fvgs = await asyncio.to_thread(detect_fvg, df)
            current_price = float(df["close"].iloc[-1])

            if fvgs.empty:
                if first_run:
                    await bot.send_message(state.chat_id,
                        f"▶️ Мониторинг запущен.\n"
                        f"Пара: <b>{state.symbol}</b>  [{state.timeframe}]\n"
                        f"FVG за последние {FVG_DAYS} дней не найдено. Жду…",
                        parse_mode=ParseMode.HTML)
                    first_run = False
                await asyncio.sleep(state.interval)
                continue

            current_ids = set(fvgs["id"].tolist())

            if first_run:
                state.known_ids = current_ids
                open_cnt = (~fvgs["filled"]).sum()
                await bot.send_message(state.chat_id,
                    f"▶️ Мониторинг запущен.\n"
                    f"Пара: <b>{state.symbol}</b>  [{state.timeframe}]\n"
                    f"Загружено FVG: {len(fvgs)}  (открытых: {open_cnt})\n"
                    f"Интервал проверки: {state.interval} сек.\n\n"
                    f"Буду уведомлять о <b>новых</b> FVG.",
                    parse_mode=ParseMode.HTML)
                first_run = False

            else:
                new_ids = current_ids - state.known_ids
                if new_ids:
                    new_rows = fvgs[fvgs["id"].isin(new_ids)]
                    for _, row in new_rows.iterrows():
                        msg = fmt_fvg_alert(row, current_price)
                        await bot.send_message(state.chat_id, msg, parse_mode=ParseMode.HTML)
                        log.info("Новый FVG отправлен: %s %s", row["type"], row["id"])
                    state.known_ids = current_ids

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("Ошибка в мониторинге: %s", e)
            if state.chat_id:
                await bot.send_message(state.chat_id,
                    f"⚠️ Ошибка мониторинга:\n<code>{e}</code>", parse_mode=ParseMode.HTML)

        await asyncio.sleep(state.interval)

    log.info("Мониторинг остановлен.")


def start_monitor(bot: Bot):
    if state.task and not state.task.done():
        state.task.cancel()
    state.running   = True
    state.known_ids = set()
    state.task = asyncio.create_task(monitor_loop(bot))


def stop_monitor():
    state.running = False
    if state.task and not state.task.done():
        state.task.cancel()
        state.task = None


# ─────────────────────────────────────────────
# Хэндлеры команд
# ─────────────────────────────────────────────
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(msg: Message):
    state.chat_id = msg.chat.id
    await msg.answer(
        "👋 <b>FVG Monitor Bot</b>\n\n"
        "Команды:\n"
        "/monitor <code>BTC/USDT 1h</code> — запустить мониторинг\n"
        "/stop — остановить мониторинг\n"
        "/status — открытые FVG прямо сейчас\n"
        "/symbol <code>ETH/USDT</code> — сменить пару\n"
        "/timeframe <code>4h</code> — сменить таймфрейм\n"
        "/interval <code>120</code> — интервал проверки (сек)\n"
        "/settings — текущие настройки",
        parse_mode=ParseMode.HTML,
    )


@dp.message(Command("monitor"))
async def cmd_monitor(msg: Message, bot: Bot):
    state.chat_id = msg.chat.id
    parts = (msg.text or "").split()[1:]

    if len(parts) >= 1:
        state.symbol = parts[0].upper()
    if len(parts) >= 2:
        state.timeframe = parts[1].lower()

    if state.running:
        await msg.answer("🔄 Перезапускаю мониторинг…")

    start_monitor(bot)


@dp.message(Command("stop"))
async def cmd_stop(msg: Message):
    if not state.running:
        await msg.answer("⏹ Мониторинг и так не запущен.")
        return
    stop_monitor()
    await msg.answer(f"⏹ Мониторинг <b>{state.symbol}</b> остановлен.", parse_mode=ParseMode.HTML)


@dp.message(Command("status"))
async def cmd_status(msg: Message):
    await msg.answer("⏳ Загружаю данные…")
    try:
        df  = await asyncio.to_thread(
            fetch_ohlcv, state.exchange, state.symbol, state.timeframe, DEFAULT_LIMIT
        )
        fvgs = await asyncio.to_thread(detect_fvg, df)
        price = float(df["close"].iloc[-1])
        await msg.answer(fmt_status(fvgs, price), parse_mode=ParseMode.HTML)
    except Exception as e:
        await msg.answer(f"❌ Ошибка: <code>{e}</code>", parse_mode=ParseMode.HTML)


@dp.message(Command("symbol"))
async def cmd_symbol(msg: Message, bot: Bot):
    parts = (msg.text or "").split()
    if len(parts) < 2:
        await msg.answer("Использование: /symbol <code>ETH/USDT</code>", parse_mode=ParseMode.HTML)
        return
    state.symbol = parts[1].upper()
    await msg.answer(f"✅ Пара изменена на <b>{state.symbol}</b>", parse_mode=ParseMode.HTML)
    if state.running:
        state.chat_id = msg.chat.id
        start_monitor(bot)
        await msg.answer("🔄 Мониторинг перезапущен с новой парой.")


@dp.message(Command("timeframe"))
async def cmd_timeframe(msg: Message, bot: Bot):
    valid = {"1m","3m","5m","15m","30m","1h","2h","4h","6h","12h","1d","1w"}
    parts = (msg.text or "").split()
    if len(parts) < 2 or parts[1].lower() not in valid:
        await msg.answer(
            f"Использование: /timeframe <code>4h</code>\n"
            f"Доступные: <code>{' '.join(sorted(valid))}</code>",
            parse_mode=ParseMode.HTML)
        return
    state.timeframe = parts[1].lower()
    await msg.answer(f"✅ Таймфрейм изменён на <b>{state.timeframe}</b>", parse_mode=ParseMode.HTML)
    if state.running:
        state.chat_id = msg.chat.id
        start_monitor(bot)
        await msg.answer("🔄 Мониторинг перезапущен с новым таймфреймом.")


@dp.message(Command("interval"))
async def cmd_interval(msg: Message):
    parts = (msg.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await msg.answer("Использование: /interval <code>120</code>  (секунды)", parse_mode=ParseMode.HTML)
        return
    secs = int(parts[1])
    if secs < 10:
        await msg.answer("⚠️ Минимальный интервал — 10 секунд.")
        return
    state.interval = secs
    await msg.answer(f"✅ Интервал изменён на <b>{secs} сек.</b>", parse_mode=ParseMode.HTML)


@dp.message(Command("settings"))
async def cmd_settings(msg: Message):
    status = "🟢 запущен" if state.running else "🔴 остановлен"
    await msg.answer(
        f"⚙️ <b>Текущие настройки</b>\n\n"
        f"Статус:     {status}\n"
        f"Пара:       <code>{state.symbol}</code>\n"
        f"Таймфрейм:  <code>{state.timeframe}</code>\n"
        f"Биржа:      <code>{state.exchange}</code>\n"
        f"Интервал:   <code>{state.interval} сек.</code>\n"
        f"FVG за:     <code>последние {FVG_DAYS} дней</code>\n"
        f"Мин. размер FVG: <code>{FVG_MIN_PCT}%</code>",
        parse_mode=ParseMode.HTML,
    )


# ─────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────
async def set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start",     description="Приветствие и список команд"),
        BotCommand(command="monitor",   description="Запустить мониторинг [пара] [таймфрейм]"),
        BotCommand(command="stop",      description="Остановить мониторинг"),
        BotCommand(command="status",    description="Текущие открытые FVG"),
        BotCommand(command="symbol",    description="Сменить торговую пару"),
        BotCommand(command="timeframe", description="Сменить таймфрейм"),
        BotCommand(command="interval",  description="Интервал проверки в секундах"),
        BotCommand(command="settings",  description="Текущие настройки"),
    ])


async def main():
    if BOT_TOKEN == "ВСТАВЬТЕ_ТОКЕН_СЮДА":
        print("[ОШИБКА] Задайте BOT_TOKEN: export TG_TOKEN='...' или впишите в код.")
        sys.exit(1)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await set_commands(bot)
    log.info("Бот запущен. Ожидаю команды…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())