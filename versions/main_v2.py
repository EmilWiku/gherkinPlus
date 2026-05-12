"""
Main entry point for Version 2 - Fractal Analysis Bot
Uses deep fractal analysis of candles, no historical data, sends signals only (no orders)
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "bot_app"))
sys.path.insert(0, str(_ROOT / "PocketOptionAPI"))

import asyncio
from env_setup import get_pocket_option_ssid, load_dotenv_early, require_env
from pocketoptionapi_async import AsyncPocketOptionClient
from stages.testing import DefaultTestingStage
from stages.fractal_evaluation import FractalEvaluationStage
from stages.fractal_notification import FractalNotificationStage
from telegram_notifier import TelegramNotifier

load_dotenv_early()


def parse_session_string(session_string: str) -> dict:
    """Parse session string to extract SSID and parameters"""
    import json
    import re
    
    result = {
        "session_id": None,
        "is_demo": False,
        "uid": 0,
        "platform": 1
    }
    
    try:
        if session_string.startswith('42["auth",'):
            json_start = session_string.find("{")
            json_end = session_string.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_part = session_string[json_start:json_end]
                data = json.loads(json_part)
                
                session_value = data.get("session", "")
                result["is_demo"] = bool(data.get("isDemo", 0))
                result["uid"] = data.get("uid", 0)
                result["platform"] = data.get("platform", 1)
                
                if session_value.startswith("a:") and "session_id" in session_value:
                    session_id_match = re.search(r'session_id";s:\d+:"([^"]+)"', session_value)
                    if session_id_match:
                        result["session_id"] = session_id_match.group(1)
                    else:
                        result["session_id"] = session_value
                else:
                    result["session_id"] = session_value
        else:
            result["session_id"] = session_string
        
        return result
        
    except Exception:
        result["session_id"] = session_string
        return result


async def run_fractal_analysis_cycle(client, evaluation_stage, notification_stage, assets):
    """Run a single analysis cycle using fractal analysis
    
    Returns:
        int: Number of signals found (0 if none)
    """
    print(f"\n{'='*70}")
    print(f"🔍 FRACTAL ANALYSIS CYCLE")
    print(f"{'='*70}\n")
    
    # Find opportunities using fractal analysis
    opportunities = await evaluation_stage.find_opportunities(assets, client)
    
    if not opportunities:
        print("⚠️ No high-confidence fractal signals found this cycle")
        return 0
    
    print(f"\n✅ Found {len(opportunities)} high-confidence signals:")
    for opp in opportunities:
        asset = opp.get("asset", "UNKNOWN")
        direction = opp.get("signal_direction", "UNKNOWN")
        confidence = opp.get("confidence_score", 0)
        print(f"   • {asset}: {direction} ({confidence:.1f}% confidence)")
    
    # Send notifications for each opportunity
    for opportunity in opportunities:
        await notification_stage.send_signal(opportunity)
        # Small delay between messages to avoid rate limiting
        await asyncio.sleep(1)
    
    return len(opportunities)


async def main():
    """Main entry point for Version 2"""
    SSID = get_pocket_option_ssid()
    parsed = parse_session_string(SSID)
    use_full_format = SSID.startswith('42["auth",') and parsed["session_id"] and not parsed["session_id"].startswith("a:")
    
    if use_full_format:
        final_ssid = SSID
        is_demo = parsed["is_demo"]
    else:
        final_ssid = parsed["session_id"] or SSID
        is_demo = parsed["is_demo"] if parsed["session_id"] else False
    
    print(f"📋 Parsed SSID:")
    print(f"   Format: {'Full auth message' if SSID.startswith('42[\"auth\",') else 'Simple session ID'}")
    print(f"   Demo: {is_demo}\n")
    
    # Test connection
    testing_stage = DefaultTestingStage()
    connection_ok = await testing_stage.test_connection(final_ssid, is_demo=is_demo)
    
    if not connection_ok:
        print("\n❌ Connection test failed! Aborting.")
        return
    
    print("\n🚀 Starting Fractal Analysis Bot (Version 2)...\n")
    print("📊 Mode: Signal Generation Only (No Orders)")
    print("🔍 Analysis: Deep Fractal Pattern Recognition")
    print("📈 Strategy: Pure Candle Structure Analysis\n")
    
    telegram_token = require_env("TELEGRAM_BOT_TOKEN")
    telegram_channel = require_env("TELEGRAM_CHANNEL_ID")

    # Initialize stages
    telegram_notifier = TelegramNotifier(telegram_token, telegram_channel)
    evaluation_stage = FractalEvaluationStage(min_confidence=75.0)
    notification_stage = FractalNotificationStage(telegram_notifier)
    
    # Connect to PocketOption
    client = AsyncPocketOptionClient(final_ssid, is_demo=is_demo, enable_logging=False)
    
    try:
        await client.connect()
        print("✅ Connected to PocketOption\n")
        
        # Asset configuration
        otc_assets_by_category = {
            "cryptocurrencies": [
                "DOTUSD_otc", "LTCUSD_otc", "SOL-USD_otc",
                "ETHUSD_otc", "DOGE_otc", "TON-USD_otc",
                "MATIC_otc", "ADA-USD_otc",
                "BTCUSD_otc", "BTCUSD", "ETHUSD",
            ],
            "forex": [
                "AEDCNY_otc", "AUDCAD_otc", "AUDCHF_otc", "AUDUSD_otc",
                "CADCHF_otc", "CADJPY_otc", "EURCHF_otc", "EURGBP_otc",
                "EURRUB_otc", "EURTRY_otc", "GBPUSD_otc", "MADUSD_otc",
                "NZDJPY_otc", "NZDUSD_otc", "USDCHF_otc", "USDCNH_otc",
                "USDMXN_otc", "EURUSD_otc", "USDJPY_otc",
            ],
            "commodities": [
                "XAUUSD_otc", "XAGUSD_otc",
                "UKBrent_otc", "USCrude_otc",
            ],
            "stocks": [
                "AMD_otc", "#AMZN_otc", "#BABA_otc",
                "#AAPL_otc", "#FDX_otc", "#MCD_otc",
                "GME_otc", "#NFLX_otc", "#TSLA_otc",
            ]
        }
        
        # Flatten assets
        otc_assets = []
        for category, assets in otc_assets_by_category.items():
            otc_assets.extend(assets)
        
        print(f"📊 Asset Categories:")
        for category, assets in otc_assets_by_category.items():
            print(f"   {category.capitalize()}: {len(assets)} assets")
        print(f"   Total: {len(otc_assets)} assets\n")
        
        # Send startup message
        try:
            await telegram_notifier.send_message(
                text="🚀 **Fractal Analysis Bot Started**\n\n"
                     "📊 Mode: Signal Generation\n"
                     "🔍 Analysis: Deep Fractal Patterns\n"
                     f"📈 Monitoring {len(otc_assets)} assets\n\n"
                     "⚡ Ready to analyze and signal!",
                parse_mode='Markdown'
            )
        except Exception as e:
            print(f"⚠️ Failed to send startup message: {e}")
        
        # Main loop - run analysis cycles
        cycle = 0
        try:
            while True:
                cycle += 1
                print(f"\n{'='*70}")
                print(f"🔄 CYCLE {cycle}")
                print(f"{'='*70}")
                
                signals_found = await run_fractal_analysis_cycle(client, evaluation_stage, notification_stage, otc_assets)
                
                # Only wait if signals were found, otherwise proceed immediately to next cycle
                if signals_found > 0:
                    print(f"\n⏳ Waiting 5 minutes until next cycle...")
                    await asyncio.sleep(300)  # 5 minutes
                else:
                    print(f"\n⚡ No signals found - proceeding to next cycle immediately...")
                    await asyncio.sleep(5)  # Small delay to prevent too rapid cycling
                
        except KeyboardInterrupt:
            print("\n\n⚠️ Interrupted by user")
            try:
                await telegram_notifier.send_message(
                    text="🛑 **Fractal Analysis Bot Stopped**\n\nSession ended by user.",
                    parse_mode='Markdown'
                )
            except Exception:
                pass
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await notification_stage.close()
        if client:
            await client.disconnect()
        print("\n✅ Disconnected")


if __name__ == "__main__":
    asyncio.run(main())

