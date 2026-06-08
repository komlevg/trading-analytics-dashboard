import pandas as pd
import matplotlib.pyplot as plt

# --- загрузка данных ---
df = pd.read_csv("trades_clean.csv")

# --- базовая подготовка ---
df["Entry Time"] = pd.to_datetime(df["Entry Time"])
df["Exit Time"] = pd.to_datetime(df["Exit Time"])

df = df.sort_values("Entry Time")

# если нет Net PnL — считаем
if "Net PnL" not in df.columns:
    df["Net PnL"] = df["PnL ($)"] + df["Fee"]

# --- 1. БАЗОВАЯ СТАТИСТИКА ---
print("\n=== BASIC STATS ===")

total_trades = len(df)
winrate = (df["PnL ($)"] > 0).mean()

avg_pnl = df["PnL ($)"].mean()
avg_win = df[df["PnL ($)"] > 0]["PnL ($)"].mean()
avg_loss = df[df["PnL ($)"] < 0]["PnL ($)"].mean()

profit_factor = (
    df[df["PnL ($)"] > 0]["PnL ($)"].sum() /
    abs(df[df["PnL ($)"] < 0]["PnL ($)"].sum())
)

print("Total trades:", total_trades)
print("Winrate:", round(winrate, 3))
print("Avg PnL:", round(avg_pnl, 2))
print("Avg Win:", round(avg_win, 2))
print("Avg Loss:", round(avg_loss, 2))
print("Profit Factor:", round(profit_factor, 2))

# --- 2. EXPECTANCY ---
print("\n=== EXPECTANCY ===")

avg_loss_abs = abs(avg_loss)
expectancy = winrate * avg_win - (1 - winrate) * avg_loss_abs

print("Expectancy:", round(expectancy, 2))

# --- 3. LONG / SHORT ---
print("\n=== SIDE ANALYSIS ===")
print(df.groupby("Side")["PnL ($)"].agg(["count","mean","sum"]))

# --- 4. АКТИВЫ ---
print("\n=== ASSET ANALYSIS ===")
asset_stats = df.groupby("Asset")["PnL ($)"].agg(["count","mean","sum"])
print(asset_stats.sort_values("sum", ascending=False))

# --- 5. ПЛЕЧО ---
print("\n=== LEVERAGE ANALYSIS ===")
print(df.groupby("Leverage")["PnL ($)"].agg(["count","mean","sum"]))

# --- 6. ТИП ВЫХОДА ---
print("\n=== RESULT TYPE ANALYSIS ===")
print(df.groupby("Result Type")["PnL ($)"].agg(["count","mean","sum"]))

# --- 7. ДЛИТЕЛЬНОСТЬ ---
print("\n=== DURATION ANALYSIS ===")

df["Duration (min)"] = (
    df["Exit Time"] - df["Entry Time"]
).dt.total_seconds() / 60

df["Duration Bucket"] = pd.cut(
    df["Duration (min)"],
    bins=[0, 60, 240, 1440, 10000],
    labels=["<1h", "1-4h", "4-24h", "1d+"]
)

print(df.groupby("Duration Bucket")["PnL ($)"].mean())

# --- 8. ЛУЧШИЕ / ХУДШИЕ ---
print("\n=== TOP 5 BEST TRADES ===")
print(df.sort_values("PnL ($)", ascending=False).head(5))

print("\n=== TOP 5 WORST TRADES ===")
print(df.sort_values("PnL ($)").head(5))

# --- 9. EQUITY CURVE ---
df["Equity"] = df["PnL ($)"].cumsum()

plt.figure()
plt.plot(df["Entry Time"], df["Equity"])
plt.title("Equity Curve")
plt.xlabel("Time")
plt.ylabel("PnL ($)")
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

# --- 10. ДЕТЕКТОР ПРОБЛЕМ ---
print("\n=== WARNINGS ===")

if winrate < 0.4:
    print("⚠️ Низкий winrate")

if expectancy < 0:
    print("❌ Отрицательное ожидание")

if profit_factor < 1:
    print("❌ Стратегия убыточна")

# --- 11. ИТОГ ---
print("\n=== SUMMARY ===")

if expectancy > 0 and profit_factor > 1:
    print("✅ У тебя есть edge")
else:
    print("❌ Edge не обнаружен (пока)")


print("\n=== MONTHLY ANALYSIS ===")

df["Month"] = df["Entry Time"].dt.to_period("M")

monthly_stats = df.groupby("Month").agg(
    Trades=("PnL ($)", "count"),
    Total_PnL=("PnL ($)", "sum"),
    Avg_PnL=("PnL ($)", "mean"),
    Winrate=("PnL ($)", lambda x: (x > 0).mean())
)

print(monthly_stats)

monthly_stats["Total_PnL"].plot(kind="bar", title="Monthly PnL")
monthly_stats["Profit Factor"] = df.groupby("Month")["PnL ($)"].apply(
    lambda x: x[x > 0].sum() / abs(x[x < 0].sum()) if (x[x < 0].sum() != 0) else 0
)
plt.xticks(rotation=45)
plt.show()