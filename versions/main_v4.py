"""
Main entry point for Version 4 - M2 Criteria Bot.
Uses BinaryOptionsToolsV2 (GitHub API) as the PocketOption data source.
"""
import sys
import os
import logging
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "bot_app"))
sys.path.insert(0, str(_ROOT / "PocketOptionAPI"))
if hasattr(sys.stdout, "reconfigure"):
    # Prevent UnicodeEncodeError on Windows cp1251 terminals.
    sys.stdout.reconfigure(encoding="utf-8")
# Compatibility patch for BinaryOptionsToolsV2 on Python 3.13.
if not hasattr(logging.Logger, "warn"):
    logging.Logger.warn = logging.Logger.warning

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from BinaryOptionsToolsV2 import PocketOptionAsync
from stages.m2_evaluation import M2EvaluationStage
from stages.m2_notification import M2NotificationStage
from telegram_notifier import TelegramNotifier
from env_setup import get_pocket_option_ssid, load_dotenv_early, require_env

load_dotenv_early()


def parse_session_string(session_string: str) -> Dict[str, Any]:
    """Parse session string to extract SSID and auth parameters."""
    import json
    import re

    result: Dict[str, Any] = {
        "session_id": None,
        "is_demo": False,
        "uid": 0,
        "platform": 1,
    }

    try:
        if session_string.startswith('42["auth",'):
            json_start = session_string.find("{")
            json_end = session_string.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                data = json.loads(session_string[json_start:json_end])
                session_value = data.get("session", "")
                result["is_demo"] = bool(data.get("isDemo", 0))
                result["uid"] = data.get("uid", 0)
                result["platform"] = data.get("platform", 1)

                if session_value.startswith("a:") and "session_id" in session_value:
                    session_id_match = re.search(r'session_id";s:\d+:"([^"]+)"', session_value)
                    result["session_id"] = session_id_match.group(1) if session_id_match else session_value
                else:
                    result["session_id"] = session_value
        else:
            result["session_id"] = session_string
    except Exception:
        result["session_id"] = session_string

    return result


def is_working_hours(current_time: datetime) -> bool:
    """Check if current time is within working hours (08:00 to 23:00)."""
    return 8 <= current_time.hour < 23


def get_next_working_hour_start(current_time: datetime) -> datetime:
    """Get next 08:00 from current time."""
    today_8am = current_time.replace(hour=8, minute=0, second=0, microsecond=0)
    if current_time < today_8am:
        return today_8am
    return today_8am + timedelta(days=1)


@dataclass
class CandleCompat:
    """Compatibility candle model for existing M2 pipeline."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float]
    asset: str
    timeframe: int


class BinaryOptionsToolsClientAdapter:
    """Adapter exposing get_candles(asset, timeframe, count) for M2 pipeline."""

    def __init__(self, ssid: str):
        self._client = PocketOptionAsync(ssid=ssid)
        self._connected = False

    async def connect(self) -> None:
        await self._client.connect()
        self._connected = True

    async def wait_for_assets(self, timeout: float = 60.0) -> None:
        await self._client.wait_for_assets(timeout=timeout)

    async def disconnect(self) -> None:
        await self._client.disconnect()
        self._connected = False

    async def get_live_price(self, asset: str, timeout: float = 6.0) -> Optional[float]:
        """Last traded quote from real-time stream (matches terminal price better than stale candle close)."""
        async def _read() -> Optional[float]:
            sub = await self._client.subscribe_symbol(asset)
            async for update in sub:
                if isinstance(update, dict) and update.get("close") is not None:
                    return float(update["close"])
            return None

        try:
            return await asyncio.wait_for(_read(), timeout=timeout)
        except Exception:
            return None

    async def get_pocket_m2_last_candles(self, asset: str, count: int = 50) -> List[CandleCompat]:
        """
        Same M2 candle series as Pocket Option terminal (chart type M2, period=120s).
        Fetches native OHLC from the API — not aggregated from M1.
        """
        async def _call():
            offset_sec = max(120 * count, 6000)
            return await self._client.get_candles(asset=asset, period=120, offset=offset_sec)

        try:
            raw = await _call()
        except Exception as exc:
            exc_text = str(exc).lower()
            if "channel" in exc_text or "closed" in exc_text:
                await self._reconnect()
                raw = await _call()
            else:
                raise

        if not isinstance(raw, list) or not raw:
            raise RuntimeError(f"No M2 candles for {asset}")
        norm = self._normalize_candles(raw, asset=asset, timeframe=120)
        norm.sort(key=lambda c: c.timestamp)
        return norm[-count:] if len(norm) > count else norm

    async def _reconnect(self) -> None:
        try:
            if self._connected:
                await self._client.disconnect()
        except Exception:
            pass
        await self._client.connect()
        self._connected = True

    @staticmethod
    def _parse_timestamp(raw_ts: Any) -> datetime:
        if isinstance(raw_ts, datetime):
            return raw_ts
        if isinstance(raw_ts, (int, float)):
            # Try seconds first; fallback to milliseconds.
            if raw_ts > 1e12:
                return datetime.fromtimestamp(raw_ts / 1000.0)
            return datetime.fromtimestamp(raw_ts)
        if isinstance(raw_ts, str):
            try:
                return datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                pass
        return datetime.now()

    @staticmethod
    def _pick_first(data: Dict[str, Any], keys: List[str], default: Any = 0.0) -> Any:
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
        return default

    @classmethod
    def _normalize_candles(cls, raw_candles: List[Dict[str, Any]], asset: str, timeframe: int) -> List[CandleCompat]:
        candles: List[CandleCompat] = []
        for row in raw_candles:
            ts = cls._pick_first(row, ["timestamp", "time", "ts", "t"], None)
            op = float(cls._pick_first(row, ["open", "o"]))
            hi = float(cls._pick_first(row, ["high", "h"], op))
            lo = float(cls._pick_first(row, ["low", "l"], op))
            cl = float(cls._pick_first(row, ["close", "c"], op))
            vol_raw = cls._pick_first(row, ["volume", "v"], None)
            vol = float(vol_raw) if vol_raw is not None else None

            candles.append(
                CandleCompat(
                    timestamp=cls._parse_timestamp(ts),
                    open=op,
                    high=hi,
                    low=lo,
                    close=cl,
                    volume=vol,
                    asset=asset,
                    timeframe=timeframe,
                )
            )
        candles.sort(key=lambda c: c.timestamp)
        return candles

    @staticmethod
    def _dataset_freshness_score(candles: List[CandleCompat]) -> float:
        """
        Lower is better. Measures how close the last candle timestamp is to now.
        """
        if not candles:
            return float("inf")
        now = datetime.now()
        return abs((now - candles[-1].timestamp).total_seconds())

    async def get_candles(self, asset: str, timeframe: int, count: int) -> List[CandleCompat]:
        async def _call_with_reconnect(call_coro):
            try:
                return await call_coro()
            except Exception as exc:
                exc_text = str(exc).lower()
                if "channel" in exc_text or "closed" in exc_text:
                    await self._reconnect()
                    return await call_coro()
                raise

        datasets: List[List[CandleCompat]] = []

        # Strategy 1: old behavior (offset as count-like window)
        try:
            raw_1 = await _call_with_reconnect(
                lambda: self._client.get_candles(asset=asset, period=timeframe, offset=max(count, 100))
            )
            if isinstance(raw_1, list):
                datasets.append(self._normalize_candles(raw_1, asset=asset, timeframe=timeframe))
        except Exception:
            pass

        # Strategy 2: period-style offset in seconds
        try:
            raw_2 = await _call_with_reconnect(
                lambda: self._client.get_candles(asset=asset, period=timeframe, offset=max(timeframe * count, 3600))
            )
            if isinstance(raw_2, list):
                datasets.append(self._normalize_candles(raw_2, asset=asset, timeframe=timeframe))
        except Exception:
            pass

        # Strategy 3: advanced endpoint bounded by current time
        try:
            raw_3 = await _call_with_reconnect(
                lambda: self._client.get_candles_advanced(
                    asset=asset,
                    period=timeframe,
                    offset=max(timeframe * count, 3600),
                    time=int(time.time()),
                )
            )
            if isinstance(raw_3, list):
                datasets.append(self._normalize_candles(raw_3, asset=asset, timeframe=timeframe))
        except Exception:
            pass

        # Strategy 4: simple candles endpoint
        try:
            raw_4 = await _call_with_reconnect(lambda: self._client.candles(asset=asset, period=timeframe))
            if isinstance(raw_4, list):
                datasets.append(self._normalize_candles(raw_4, asset=asset, timeframe=timeframe))
        except Exception:
            pass

        # Strategy 5: wide history window (API sometimes returns 1 bar for small offset)
        try:
            wide = max(timeframe * count, 86400)
            raw_5 = await _call_with_reconnect(
                lambda: self._client.get_candles(asset=asset, period=timeframe, offset=wide)
            )
            if isinstance(raw_5, list) and raw_5:
                datasets.append(self._normalize_candles(raw_5, asset=asset, timeframe=timeframe))
        except Exception:
            pass

        if not datasets:
            raise RuntimeError(f"No candle data returned for {asset} ({timeframe}s)")

        # Prefer sets with enough bars; among those pick freshest. Avoid 1-bar "fresh" noise.
        min_bars = min(10, count)
        usable = [ds for ds in datasets if len(ds) >= min_bars]
        if usable:
            best = min(usable, key=lambda ds: (self._dataset_freshness_score(ds), -len(ds)))
        else:
            best = max(datasets, key=len)

        if len(best) < 5:
            raise RuntimeError(f"Too few candles for {asset} ({timeframe}s): {len(best)}")

        return best[-count:] if len(best) > count else best

    async def get_active_assets(self) -> List[str]:
        """Fetch active assets from API and normalize to symbol list."""
        raw = await self._client.active_assets()
        assets: List[str] = []
        if isinstance(raw, list):
            for row in raw:
                if isinstance(row, str):
                    assets.append(row)
                elif isinstance(row, dict):
                    symbol = row.get("symbol") or row.get("asset") or row.get("name")
                    if symbol:
                        assets.append(str(symbol))
        return assets


class SafeM2EvaluationStage(M2EvaluationStage):
    """
    BinaryOptionsToolsV2 transport can close channels on high parallel load.
    This stage executes asset analysis sequentially for stability.
    """

    async def find_best_opportunities(self, assets: List[str], client, target_beautiful_time=None) -> List[Dict]:
        print(f"🔍 Analyzing {len(assets)} assets using M2 criteria (safe sequential mode)...")
        analyses: List[Dict] = []
        error_count = 0

        for asset in assets:
            result = await self.analyze_asset(asset, client, target_beautiful_time=target_beautiful_time)
            if isinstance(result, Exception):
                print(f"⚠️ {asset}: {result}")
                error_count += 1
                continue
            if "error" in result and result["error"]:
                print(f"⚠️ {asset}: {result['error']}")
                error_count += 1
                continue
            analyses.append(result)

        print(f"📈 Summary: {len(analyses)} successful analyses, {error_count} errors")
        return self.m2_analyzer.select_best_signals(
            analyses, top_n=self.top_signals, min_score=self.min_m2_score
        )


async def run_m2_analysis_cycle(client, evaluation_stage, notification_stage, assets) -> int:
    """Run one M2 analysis cycle and publish selected signals."""
    from beautiful_time import get_next_beautiful_time, get_beautiful_time_range

    print(f"\n{'='*70}")
    print("🔍 M2 CRITERIA ANALYSIS CYCLE (v4 / BinaryOptionsToolsV2)")
    print(f"{'='*70}\n")

    current_time = datetime.now()
    beautiful_start = get_next_beautiful_time(current_time)
    beautiful_start, beautiful_end = get_beautiful_time_range(beautiful_start)
    print(f"⏰ Target beautiful time: {beautiful_start.strftime('%H:%M:%S')} до {beautiful_end.strftime('%H:%M:%S')}")

    best_signals = await evaluation_stage.find_best_opportunities(
        assets, client, target_beautiful_time=beautiful_start
    )

    if not best_signals:
        print("⚠️ No signals meet M2 criteria this cycle")
        return 0

    print(f"\n✅ Selected {len(best_signals)} best signals:")
    for signal in best_signals:
        asset = signal.get("asset", "UNKNOWN")
        direction = signal.get("signal_direction", "UNKNOWN")
        m2_score = signal.get("m2_score", 0)
        pattern = signal.get("pattern_analysis", {}).get("pattern_1m", {}).get("pattern", "Unknown")
        beautiful_range = signal.get("beautiful_time_range", "N/A")
        print(f"   • {asset}: {direction} (M2: {m2_score:.1f}%, Pattern: {pattern}, Time: {beautiful_range})")

    for signal in best_signals:
        await notification_stage.send_signal(signal)
        await asyncio.sleep(1)

    await notification_stage.send_summary(best_signals)
    return len(best_signals)


def get_assets() -> List[str]:
    """Assets list for M2 analysis."""
    otc_assets_by_category = {
        "cryptocurrencies": ["BTCUSD", "ETHUSD", "DOTUSD"],
        "forex": [
            "EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "USDCHF_otc", "USDCAD_otc",
            "AUDUSD_otc", "AUDNZD_otc", "AUDCAD_otc", "AUDCHF_otc", "AUDJPY_otc",
            "CADCHF_otc", "CADJPY_otc", "CHFJPY_otc", "EURCHF_otc", "EURGBP_otc",
            "EURJPY_otc", "EURNZD_otc", "GBPAUD_otc", "GBPJPY_otc",
            "NZDJPY_otc", "NZDUSD_otc", "EURRUB_otc", "USDRUB_otc", "EURHUF_otc",
            "CHFNOK_otc",
        ],
        "stocks": [
            "#AAPL_otc", "#MSFT_otc", "#TSLA_otc", "#FB_otc", "#AMZN_otc",
            "#NFLX_otc", "#INTC_otc", "#BA_otc", "#JNJ_otc", "#PFE_otc",
            "#XOM_otc", "#AXP_otc", "#MCD_otc", "#CSCO_otc", "#VISA_otc",
            "#CITI_otc", "#FDX_otc", "#TWITTER_otc", "#BABA_otc",
            "Microsoft_otc", "Facebook_OTC", "Tesla_otc", "Boeing_OTC",
            "American_Express_otc",
        ],
    }
    assets: List[str] = []
    for category, category_assets in otc_assets_by_category.items():
        assets.extend(category_assets)
        print(f"   {category.capitalize()}: {len(category_assets)} assets")
    print(f"   Total: {len(assets)} assets\n")
    asset_limit = int(os.getenv("BOT_ASSET_LIMIT", "0"))
    if asset_limit > 0:
        assets = assets[:asset_limit]
        print(f"⚙️ BOT_ASSET_LIMIT applied: {len(assets)} assets\n")
    return assets


async def main() -> None:
    """Main entry point for Version 4."""
    TELEGRAM_BOT_TOKEN = require_env("TELEGRAM_BOT_TOKEN")
    TELEGRAM_GROUP_ID = require_env("TELEGRAM_CHANNEL_ID")
    raw_topic = os.environ.get("TELEGRAM_TOPIC_ID", "").strip()
    TELEGRAM_TOPIC_ID = int(raw_topic) if raw_topic.isdigit() else None

    ssid_raw = get_pocket_option_ssid()
    parsed = parse_session_string(ssid_raw)
    # Keep full Socket.IO auth envelope when present (BinaryOptionsToolsV2 warning path
    # for plain session_id is broken in this environment).
    final_ssid = ssid_raw if ssid_raw.startswith('42["auth",') else (parsed["session_id"] or ssid_raw)

    # Note: BinaryOptionsToolsV2 auth is SSID-based. Email/password are not used directly here.
    po_email = os.getenv("POCKET_OPTION_EMAIL", "")
    po_password = os.getenv("POCKET_OPTION_PASSWORD", "")
    if po_email and po_password:
        print("ℹ️ POCKET_OPTION_EMAIL/POCKET_OPTION_PASSWORD provided (not used by SSID-based API client).")

    print("📋 Telegram target:")
    print(f"   Group ID: {TELEGRAM_GROUP_ID}")
    print(f"   Topic ID: {TELEGRAM_TOPIC_ID}\n")

    telegram_notifier = TelegramNotifier(
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_GROUP_ID,
        message_thread_id=TELEGRAM_TOPIC_ID,
    )
    evaluation_stage = SafeM2EvaluationStage(min_m2_score=30.0, top_signals=5)
    notification_stage = M2NotificationStage(telegram_notifier)
    client = BinaryOptionsToolsClientAdapter(final_ssid)

    test_mode = os.getenv("BOT_TEST_MODE", "0") == "1"
    max_cycles = int(os.getenv("BOT_MAX_CYCLES", "1" if test_mode else "0"))
    cycle = 0

    try:
        await client.connect()
        print("✅ Connected to PocketOption via BinaryOptionsToolsV2\n")
        assets = get_assets()
        try:
            # BinaryOptionsToolsV2 may need extra time after connect before assets are available.
            await client.wait_for_assets(timeout=60.0)
            active_assets = await client.get_active_assets()
            if not active_assets:
                # One short retry to avoid transient "uninitialized" window.
                await asyncio.sleep(2)
                active_assets = await client.get_active_assets()
            if active_assets:
                active_set = set(active_assets)
                filtered_assets = [a for a in assets if a in active_set]
                if filtered_assets:
                    print(f"✅ Filtered assets by API availability: {len(filtered_assets)} / {len(assets)}")
                    assets = filtered_assets
        except Exception as exc:
            print(f"⚠️ Could not fetch active assets list: {exc}")
        from beautiful_time import get_next_beautiful_time

        while True:
            current_time = datetime.now()
            if not is_working_hours(current_time):
                next_8am = get_next_working_hour_start(current_time)
                wait_seconds = (next_8am - current_time).total_seconds()
                print(f"⏸️ Outside working hours. Sleeping for {wait_seconds:.0f}s")
                await asyncio.sleep(wait_seconds)
                continue

            cycle += 1
            print(f"\n{'='*70}\n🔄 CYCLE {cycle}\n{'='*70}")
            signals_found = await run_m2_analysis_cycle(client, evaluation_stage, notification_stage, assets)

            if max_cycles > 0 and cycle >= max_cycles:
                print(f"✅ Max cycles reached ({max_cycles}). Stopping.")
                break

            if signals_found > 0:
                await asyncio.sleep(90)
            else:
                now = datetime.now()
                next_beautiful = get_next_beautiful_time(now)
                wait_seconds = (next_beautiful - now).total_seconds()
                await asyncio.sleep(max(2, wait_seconds - 15 if wait_seconds > 15 else 2))

    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
    except Exception as exc:
        print(f"\n❌ Error: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            await notification_stage.close()
        except Exception:
            pass
        try:
            await client.disconnect()
        except Exception:
            pass
        print("\n✅ Disconnected")


if __name__ == "__main__":
    asyncio.run(main())
