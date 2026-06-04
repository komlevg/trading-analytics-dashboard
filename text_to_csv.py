import re
import logging
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ─────────────────────────────────────────────
# RAW TEXT — вставьте свои данные сюда
# ─────────────────────────────────────────────
raw_text = """"""

# ─────────────────────────────────────────────
# ПАТТЕРНЫ — значения на следующей строке после метки
# ─────────────────────────────────────────────
PATTERNS_EN = {
    "asset":       r'^([A-Z]+USDT)',
    "side":        r'^(Long|Short)$',
    "leverage":    r'^(\d+)X',
    "result_type": r'^(Stop Loss|Take Profit|Close All|Liquidated)',
    "entry_time":  r'Opening Time\s*\n([\d\-: ]+)',
    "exit_time":   r'Liquidate Date\s*\n([\d\-: ]+)',
    "entry_price": r'Average price\s*\n([\d.]+)',
    "exit_price":  r'Exit Price\s*\n([\d.]+)',
    "pnl":         r'Realized PnL\s*\n([+\-]?\d+\.?\d*)USDT',
    "pnl_pct":     r'Realized PnL%\s*\n([+\-]?\d+\.?\d*)%',
    "size":        r'Liquidation Qty\s*\n([\d.]+)',
    "fee":         r'Fee\s*\n([+\-]?\d+\.?\d+)',
}

PATTERNS_RU = {
    "asset":       r'^([A-Z]+USDT)',
    "leverage":    r'^(\d+)X',
    "entry_time":  r'Время открытия\s*\n([\d\-: ]+)',
    "exit_time":   r'Дата ликвидации\s*\n([\d\-: ]+)',
    "entry_price": r'Средняя цена\s*\n([\d.]+)',
    "exit_price":  r'Цена выхода\s*\n([\d.]+)',
    "pnl":         r'PnL\s*\n([+\-]?\d+\.?\d*)USDT',
    "pnl_pct":     r'PnL %\s*\n([+\-]?\d+\.?\d*)%',
    "size":        r'Объём ликвидации\s*\n([\d.]+)',
    "fee":         r'Комиссия\s*\n([+\-]?\d+\.?\d+)',
}


# ─────────────────────────────────────────────
# УТИЛИТА ИЗВЛЕЧЕНИЯ
# ─────────────────────────────────────────────
def extract(pattern, text, cast=str, default=None):
    match = re.search(pattern, text, re.MULTILINE)
    if match:
        try:
            return cast(match.group(1).strip())
        except (ValueError, TypeError):
            return default
    return default


# ─────────────────────────────────────────────
# ПАРСИНГ ОДНОЙ СДЕЛКИ
# ─────────────────────────────────────────────
def parse_trade(trade: str) -> dict | None:
    trade = trade.strip()
    if len(trade) < 30:
        return None

    is_ru = "Бессрочный контракт" in trade
    p = PATTERNS_RU if is_ru else PATTERNS_EN

    asset      = extract(p["asset"], trade)
    entry_time = extract(p["entry_time"], trade)
    exit_time  = extract(p["exit_time"], trade)

    # обязательные поля
    if not all([asset, entry_time, exit_time]):
        logging.warning(f"Пропущена сделка (нет обязательных полей): {trade[:80]!r}")
        return None

    if is_ru:
        side_raw    = extract(r'(Лонг|Шорт)', trade)
        side        = {"Лонг": "Long", "Шорт": "Short"}.get(side_raw)
        result_map  = {"Стоп-лосс": "Stop Loss", "Ручное закрытие": "Manual", "Тейк-профит": "Take Profit"}
        result_type = next((v for k, v in result_map.items() if k in trade), "Other")
    else:
        side        = extract(p["side"], trade)
        result_type = extract(p["result_type"], trade)

    return {
        "Asset":       asset,
        "Side":        side,
        "Leverage":    extract(p["leverage"], trade, int),
        "Result Type": result_type,
        "Entry Time":  entry_time,
        "Exit Time":   exit_time,
        "Entry Price": extract(p["entry_price"], trade, float),
        "Exit Price":  extract(p["exit_price"], trade, float),
        "Size":        extract(p["size"], trade, float),
        "PnL ($)":     extract(p["pnl"], trade, float),
        "PnL (%)":     extract(p["pnl_pct"], trade, float),
        "Fee":         extract(p["fee"], trade, float),
    }


# ─────────────────────────────────────────────
# РАЗБИВКА НА БЛОКИ СДЕЛОК
# ─────────────────────────────────────────────
trades_raw = re.findall(r'[A-Z]+USDT[\s\S]*?(?=\n[A-Z]+USDT|\Z)', raw_text)
logging.info(f"Найдено блоков: {len(trades_raw)}")

data = [r for trade in trades_raw if (r := parse_trade(trade)) is not None]
logging.info(f"Успешно распарсено: {len(data)} из {len(trades_raw)}")

if not data:
    logging.error("Данные не распарсились. Проверьте формат входного текста.")
    # Печатаем первый блок для отладки
    if trades_raw:
        print("\n--- Первый блок (для отладки) ---")
        print(repr(trades_raw[0]))
    exit(1)


# ─────────────────────────────────────────────
# СБОРКА DATAFRAME
# ─────────────────────────────────────────────
df = pd.DataFrame(data)

df["Entry Time"] = pd.to_datetime(df["Entry Time"], errors="coerce")
df["Exit Time"]  = pd.to_datetime(df["Exit Time"],  errors="coerce")

# предупреждение о строках с невалидным временем
bad_time = df[df["Entry Time"].isna() | df["Exit Time"].isna()]
if not bad_time.empty:
    logging.warning(f"{len(bad_time)} строк с невалидным форматом времени:\n{bad_time[['Asset', 'Entry Time', 'Exit Time']]}")

df["Net PnL"]        = df["PnL ($)"].fillna(0) + df["Fee"].fillna(0)
df["Duration (min)"] = (df["Exit Time"] - df["Entry Time"]).dt.total_seconds() / 60

# сортировка по времени открытия
df = df.sort_values("Entry Time").reset_index(drop=True)

print(df.to_string())

# utf-8-sig — корректно открывается в Excel
df.to_csv("trades_clean.csv", index=False, encoding="utf-8-sig")
logging.info("Сохранено в trades_clean.csv")