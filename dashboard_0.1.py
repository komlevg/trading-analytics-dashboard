import pandas as pd
import numpy as np
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns

# ===================== НАСТРОЙКИ =====================
CSV_FILE = 'trades_clean.csv'  # ← поменяй на имя твоего файла

# ===================== ЗАГРУЗКА ДАННЫХ =====================
df = pd.read_csv(CSV_FILE)

# Преобразуем время в datetime
df['Entry Time'] = pd.to_datetime(df['Entry Time'])
df['Exit Time'] = pd.to_datetime(df['Exit Time'])

# Добавляем полезные колонки
df['Date'] = df['Entry Time'].dt.date
df['Hour'] = df['Entry Time'].dt.hour
df['Weekday'] = df['Entry Time'].dt.strftime('%A')
df['Win'] = df['Net PnL'] > 0
df['Duration_hours'] = df['Duration (min)'] / 60

print(f"Загружено сделок: {len(df)}")
print(f"Период: с {df['Entry Time'].min()} по {df['Exit Time'].max()}\n")

# ===================== ОСНОВНАЯ СТАТИСТИКА =====================
total_trades = len(df)
wins = df['Win'].sum()
winrate = wins / total_trades * 100

total_pnl = df['Net PnL'].sum()
avg_pnl = df['Net PnL'].mean()
max_pnl = df['Net PnL'].max()
min_pnl = df['Net PnL'].min()

profit_factor = df[df['Net PnL'] > 0]['Net PnL'].sum() / abs(df[df['Net PnL'] < 0]['Net PnL'].sum()) if df[df['Net PnL'] < 0]['Net PnL'].sum() != 0 else float('inf')

expectancy = df['Net PnL'].mean()

print("=== ОБЩАЯ СТАТИСТИКА ===")
print(f"Всего сделок:          {total_trades}")
print(f"Прибыльных сделок:     {wins} ({winrate:.1f}%)")
print(f"Убыточных сделок:      {total_trades - wins} ({100 - winrate:.1f}%)")
print(f"Общий Net PnL:         ${total_pnl:.2f}")
print(f"Средний PnL на сделку: ${avg_pnl:.2f}")
print(f"Expectancy:            ${expectancy:.2f}")
print(f"Profit Factor:         {profit_factor:.2f}")
print(f"Максимальная прибыль:  ${max_pnl:.2f}")
print(f"Максимальный убыток:   ${min_pnl:.2f}")

# ===================== АНАЛИЗ ПО ТИПУ ЗАКРЫТИЯ =====================
print("\n=== ПО ТИПУ ЗАКРЫТИЯ ===")
result_stats = df.groupby('Result Type').agg(
    Количество=('Net PnL', 'count'),
    Winrate=('Win', 'mean'),
    Total_PnL=('Net PnL', 'sum'),
    Avg_PnL=('Net PnL', 'mean'),
    Avg_Duration_min=('Duration (min)', 'mean')
).round(2)

result_stats['Winrate'] = result_stats['Winrate'] * 100
print(result_stats)

# ===================== АНАЛИЗ ПО АКТИВАМ =====================
print("\n=== ТОП АКТИВОВ ===")
asset_stats = df.groupby('Asset').agg(
    Сделок=('Net PnL', 'count'),
    Winrate=('Win', 'mean'),
    Total_PnL=('Net PnL', 'sum'),
    Avg_PnL=('Net PnL', 'mean')
).round(2)
asset_stats['Winrate'] *= 100
print(asset_stats.sort_values('Total_PnL', ascending=False))

# ===================== ПО ДНЯМ НЕДЕЛИ =====================
print("\n=== ПО ДНЯМ НЕДЕЛИ ===")
weekday_stats = df.groupby('Weekday').agg(
    Сделок=('Net PnL', 'count'),
    Winrate=('Win', 'mean'),
    Total_PnL=('Net PnL', 'sum')
).round(2)
weekday_stats['Winrate'] *= 100
print(weekday_stats.sort_values('Total_PnL', ascending=False))

# ===================== ВИЗУАЛИЗАЦИЯ =====================
plt.style.use('dark_background')

fig, axs = plt.subplots(2, 2, figsize=(14, 10))

# 1. Распределение PnL
sns.histplot(df['Net PnL'], bins=30, kde=True, ax=axs[0,0], color='cyan')
axs[0,0].set_title('Распределение Net PnL')
axs[0,0].axvline(0, color='red', linestyle='--')

# 2. Кумулятивная прибыль
df_sorted = df.sort_values('Exit Time')
df_sorted['Cumulative_PnL'] = df_sorted['Net PnL'].cumsum()
axs[0,1].plot(df_sorted['Exit Time'], df_sorted['Cumulative_PnL'], color='lime', linewidth=2)
axs[0,1].set_title('Кумулятивная кривая PnL')
axs[0,1].axhline(0, color='red', linestyle='--')
axs[0,1].tick_params(axis='x', rotation=45)

# 3. Winrate по активам
asset_winrate = df.groupby('Asset')['Win'].mean() * 100
asset_winrate.sort_values().plot(kind='barh', ax=axs[1,0], color='skyblue')
axs[1,0].set_title('Winrate по активам (%)')
axs[1,0].set_xlabel('Winrate %')

# 4. PnL по типу результата
df.groupby('Result Type')['Net PnL'].sum().plot(kind='bar', ax=axs[1,1], color=['red', 'green', 'orange'])
axs[1,1].set_title('Общий PnL по типу закрытия')
axs[1,1].set_ylabel('Net PnL $')

plt.tight_layout()
plt.show()

# ===================== ДОПОЛНИТЕЛЬНЫЕ МЕТРИКИ =====================
print(f"\nСредняя длительность сделки: {df['Duration (min)'].mean():.1f} минут ({df['Duration_hours'].mean():.1f} часов)")
print(f"Максимальная длительность:  {df['Duration (min)'].max():.1f} минут")

# ===================== СОХРАНЕНИЕ РЕЗУЛЬТАТОВ =====================
df.to_csv('analyzed_trades.csv', index=False)
print("\nАнализ завершён! Расширенный файл сохранён как 'analyzed_trades.csv'")