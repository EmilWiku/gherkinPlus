"""
Generate multiple chart styles from the same latest PocketOption candles.

Usage:
    python examples/generate_chart_techniques.py --asset GBPJPY_otc
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "bot_app"))
sys.path.insert(0, str(_REPO_ROOT / "PocketOptionAPI"))
sys.path.insert(0, str(_REPO_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from BinaryOptionsToolsV2 import PocketOptionAsync

from env_setup import get_pocket_option_ssid, load_dotenv_early


def normalize_candles(raw: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for c in raw:
        ts = c.get("timestamp") or c.get("time")
        if ts is None:
            continue
        if ts > 1e12:
            ts = ts / 1000.0
        rows.append(
            {
                "timestamp": datetime.fromtimestamp(ts),
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": float(c["volume"]) if c.get("volume") is not None else None,
            }
        )
    df = pd.DataFrame(rows).sort_values("timestamp")
    return df.tail(50).reset_index(drop=True)


def save_plotly_candles(df: pd.DataFrame, asset: str, output: Path, dark: bool) -> None:
    theme = "plotly_dark" if dark else "plotly_white"
    paper = "#0F172A" if dark else "#FFFFFF"
    plot = "#111827" if dark else "#F8FAFC"
    text = "#E5E7EB" if dark else "#0F172A"

    df = df.copy()
    df["ma20"] = df["close"].rolling(20).mean()
    last_close = float(df["close"].iloc[-1])

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df["timestamp"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price",
            increasing_line_color="#10B981",
            decreasing_line_color="#EF4444",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["ma20"],
            mode="lines",
            line=dict(color="#3B82F6", width=2),
            name="MA20",
        )
    )
    fig.add_hline(
        y=last_close,
        line_dash="dash",
        line_color="#F59E0B",
        annotation_text=f"Last close: {last_close:.5f}",
    )
    fig.update_layout(
        template=theme,
        paper_bgcolor=paper,
        plot_bgcolor=plot,
        font=dict(color=text, size=13),
        title=f"{asset} | Technique {'A' if not dark else 'B'}",
        xaxis_rangeslider_visible=False,
        width=1500,
        height=850,
        margin=dict(l=50, r=30, t=70, b=40),
    )
    img = pio.to_image(fig, format="png", width=1500, height=850, scale=2)
    output.write_bytes(img)


def save_matplotlib_clean(df: pd.DataFrame, asset: str, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(15, 8))
    x = range(len(df))
    for i, row in df.iterrows():
        color = "#10B981" if row["close"] >= row["open"] else "#EF4444"
        ax.plot([i, i], [row["low"], row["high"]], color=color, linewidth=1.2)
        bottom = min(row["open"], row["close"])
        height = abs(row["close"] - row["open"])
        ax.add_patch(plt.Rectangle((i - 0.32, bottom), 0.64, height if height > 0 else 1e-6, color=color, alpha=0.85))

    ma20 = df["close"].rolling(20).mean()
    ax.plot(x, ma20, color="#2563EB", linewidth=2, label="MA20")
    last_close = float(df["close"].iloc[-1])
    ax.axhline(last_close, color="#F59E0B", linestyle="--", linewidth=1.8, label=f"Last close {last_close:.5f}")
    ax.set_title(f"{asset} | Technique C (Matplotlib clean)")
    ax.grid(alpha=0.2)
    ax.legend()
    plt.tight_layout()
    fig.savefig(output, dpi=170)
    plt.close(fig)


def save_infographic(df: pd.DataFrame, asset: str, output: Path) -> None:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 9), gridspec_kw={"height_ratios": [3, 1]})
    x = range(len(df))
    ax1.plot(x, df["close"], color="#111827", linewidth=2.5, label="Close")
    ax1.fill_between(x, df["low"], df["high"], color="#93C5FD", alpha=0.35, label="Range")
    ax1.set_title(f"{asset} | Technique D (Range + Close)")
    ax1.grid(alpha=0.2)
    ax1.legend()

    energy = ((df["high"] - df["low"]) * 0.7 + (df["close"] - df["open"]).abs() * 0.3) * 10000
    colors = ["#10B981" if c >= o else "#EF4444" for o, c in zip(df["open"], df["close"])]
    ax2.bar(x, energy, color=colors, alpha=0.8)
    ax2.set_title("Market activity proxy")
    ax2.grid(alpha=0.2)
    plt.tight_layout()
    fig.savefig(output, dpi=170)
    plt.close(fig)


async def fetch_latest_m2(asset: str, ssid: str) -> pd.DataFrame:
    client = PocketOptionAsync(ssid=ssid)
    await client.connect()
    try:
        await client.wait_for_assets(timeout=30)
        raw = await client.get_candles(asset=asset, period=120, offset=120 * 60)
        df = normalize_candles(raw)
        if len(df) < 20:
            raise RuntimeError(f"Too few candles returned: {len(df)}")
        return df
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def main() -> None:
    load_dotenv_early()
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", default="GBPJPY_otc")
    parser.add_argument(
        "--ssid",
        default="",
        help="Override SSID; default from POCKET_OPTION_SSID / POCKET_OPTION_SSID_FILE",
    )
    args = parser.parse_args()
    ssid = args.ssid.strip() or get_pocket_option_ssid()

    df = await fetch_latest_m2(args.asset, ssid)

    out_root = _REPO_ROOT / "artifacts" / "examples"
    out_root.mkdir(parents=True, exist_ok=True)
    out_dir = out_root / f"charts_{args.asset}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    save_plotly_candles(df, args.asset, out_dir / "technique_A_plotly_light.png", dark=False)
    save_plotly_candles(df, args.asset, out_dir / "technique_B_plotly_dark.png", dark=True)
    save_matplotlib_clean(df, args.asset, out_dir / "technique_C_matplotlib_clean.png")
    save_infographic(df, args.asset, out_dir / "technique_D_infographic.png")

    print(f"Generated charts in: {out_dir}")


if __name__ == "__main__":
    asyncio.run(main())
