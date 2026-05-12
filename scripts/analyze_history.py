import pandas as pd
import numpy as np
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_excel = _REPO / "data" / "examples" / "export_history.xlsx"

# Load data
df = pd.read_excel(_excel)

# Clean and prepare
df['Win'] = df['Прибыль'] > 0
df['Loss'] = df['Прибыль'] < 0

print("=" * 70)
print("HISTORICAL TRADING DATA ANALYSIS")
print("=" * 70)

print(f"\n=== OVERALL STATISTICS ===")
print(f"Total trades: {len(df)}")
print(f"Wins: {df['Win'].sum()} ({df['Win'].mean()*100:.1f}%)")
print(f"Losses: {df['Loss'].sum()} ({df['Loss'].mean()*100:.1f}%)")
print(f"Breakeven: {(df['Прибыль'] == 0).sum()}")
print(f"\nTotal profit: ${df['Прибыль'].sum():.2f}")
print(f"Average profit per trade: ${df['Прибыль'].mean():.2f}")
print(f"Median profit per trade: ${df['Прибыль'].median():.2f}")
print(f"Best trade: ${df['Прибыль'].max():.2f}")
print(f"Worst trade: ${df['Прибыль'].min():.2f}")

print(f"\n=== BY ASSET ===")
asset_stats = df.groupby('Актив').agg({
    'Прибыль': ['count', 'sum', 'mean'],
    'Win': 'mean',
    'Размер сделки': 'mean'
}).round(2)
asset_stats.columns = ['Trades', 'Total_Profit', 'Avg_Profit', 'Win_Rate', 'Avg_Size']
asset_stats = asset_stats.sort_values('Total_Profit')
print(asset_stats.to_string())

print(f"\n=== BY DIRECTION ===")
dir_stats = df.groupby('Направление').agg({
    'Прибыль': ['count', 'sum', 'mean'],
    'Win': 'mean'
}).round(2)
dir_stats.columns = ['Trades', 'Total_Profit', 'Avg_Profit', 'Win_Rate']
print(dir_stats.to_string())

print(f"\n=== WORST PERFORMING ASSETS ===")
worst_assets = asset_stats.nsmallest(10, 'Total_Profit')
print(worst_assets.to_string())

print(f"\n=== BEST PERFORMING ASSETS ===")
best_assets = asset_stats.nlargest(10, 'Total_Profit')
print(best_assets.to_string())

print(f"\n=== SIZE ANALYSIS ===")
print(f"Average trade size: ${df['Размер сделки'].mean():.2f}")
print(f"Median trade size: ${df['Размер сделки'].median():.2f}")
print(f"Max trade size: ${df['Размер сделки'].max():.2f}")
print(f"Min trade size: ${df['Размер сделки'].min():.2f}")

# Analyze by trade size
df['Size_Category'] = pd.cut(df['Размер сделки'], 
                              bins=[0, 10, 25, 50, 100, float('inf')],
                              labels=['<10', '10-25', '25-50', '50-100', '>100'])
size_stats = df.groupby('Size_Category').agg({
    'Прибыль': ['count', 'sum', 'mean'],
    'Win': 'mean'
}).round(2)
size_stats.columns = ['Trades', 'Total_Profit', 'Avg_Profit', 'Win_Rate']
print(f"\n=== BY TRADE SIZE ===")
print(size_stats.to_string())

