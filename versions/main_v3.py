"""
Main entry point for Version 3 - M2 Criteria Bot
Selects best signals based on M2 (Multi-Method Multi-Timeframe) criteria
"""
import sys
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "bot_app"))
sys.path.insert(0, str(_ROOT / "PocketOptionAPI"))

import asyncio
from datetime import datetime, timedelta
from pocketoptionapi_async import AsyncPocketOptionClient
from stages.testing import DefaultTestingStage
from stages.m2_evaluation import M2EvaluationStage
from stages.m2_notification import M2NotificationStage
from telegram_notifier import TelegramNotifier
from env_setup import get_pocket_option_ssid, load_dotenv_early, require_env

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


def is_working_hours(current_time: datetime) -> bool:
    """
    Check if current time is within working hours (8:00 to 23:00).
    
    Args:
        current_time: Current datetime
    
    Returns:
        True if within working hours, False otherwise
    """
    hour = current_time.hour
    return 8 <= hour < 23


def get_next_working_hour_start(current_time: datetime) -> datetime:
    """
    Get the next 8:00 AM from current time.
    If current time is before 8:00 today, return 8:00 today.
    Otherwise, return 8:00 tomorrow.
    
    Args:
        current_time: Current datetime
    
    Returns:
        Next 8:00 AM datetime
    """
    # Create datetime for 8:00 today
    today_8am = current_time.replace(hour=8, minute=0, second=0, microsecond=0)
    
    # If current time is before 8:00 today, return today's 8:00
    if current_time < today_8am:
        return today_8am
    
    # Otherwise, return 8:00 tomorrow
    return today_8am + timedelta(days=1)


async def run_m2_analysis_cycle(client, evaluation_stage, notification_stage, assets):
    """Run a single analysis cycle using M2 criteria
    
    Returns:
        int: Number of signals found (0 if none)
    """
    from beautiful_time import get_next_beautiful_time, get_beautiful_time_range
    from datetime import datetime
    
    print(f"\n{'='*70}")
    print(f"🔍 M2 CRITERIA ANALYSIS CYCLE")
    print(f"{'='*70}\n")
    
    # Calculate beautiful time BEFORE analysis to ensure signals are valid
    current_time = datetime.now()
    beautiful_start = get_next_beautiful_time(current_time)
    beautiful_start, beautiful_end = get_beautiful_time_range(beautiful_start)
    
    print(f"⏰ Target beautiful time: {beautiful_start.strftime('%H:%M:%S')} до {beautiful_end.strftime('%H:%M:%S')}")
    
    # Find best opportunities using M2 criteria with pre-calculated beautiful time
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
    
    # Send notifications immediately - time is already calculated correctly
    for signal in best_signals:
        await notification_stage.send_signal(signal)
        # Small delay between messages to avoid rate limiting
        await asyncio.sleep(1)
    
    # Send summary
    await notification_stage.send_summary(best_signals)
    
    return len(best_signals)


async def main():
    """Main entry point for Version 3"""
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
    
    # Optional SOCKS/HTTP proxy (see POCKET_OPTION_PROXY_URL in .env.example)
    PROXY_URL = os.environ.get("POCKET_OPTION_PROXY_URL", "").strip() or None

    if PROXY_URL:
        print(f"🌐 Proxy enabled: {PROXY_URL.split('@')[-1] if '@' in PROXY_URL else PROXY_URL}")
    else:
        print("🌐 Proxy: disabled (direct connection)")
    
    # Test connection
    testing_stage = DefaultTestingStage()
    connection_ok = await testing_stage.test_connection(final_ssid, is_demo=is_demo, proxy_url=PROXY_URL)
    
    if not connection_ok:
        print("\n❌ Connection test failed! Aborting.")
        return
    
    TELEGRAM_BOT_TOKEN = require_env("TELEGRAM_BOT_TOKEN")
    TELEGRAM_GROUP_ID = require_env("TELEGRAM_CHANNEL_ID")
    raw_topic = os.environ.get("TELEGRAM_TOPIC_ID", "").strip()
    TELEGRAM_TOPIC_ID = int(raw_topic) if raw_topic.isdigit() else None

    # Initialize stages
    telegram_notifier = TelegramNotifier(
        TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID, message_thread_id=TELEGRAM_TOPIC_ID
    )
    evaluation_stage = M2EvaluationStage(min_m2_score=30.0, top_signals=5)
    notification_stage = M2NotificationStage(telegram_notifier)
    
    # Connect to PocketOption (using proxy if configured above)
    client = AsyncPocketOptionClient(final_ssid, is_demo=is_demo, enable_logging=False, proxy_url=PROXY_URL)
    
    try:
        await client.connect()
        print("✅ Connected to PocketOption\n")
        
        # Asset configuration - All OTC assets from constants
        otc_assets_by_category = {
            "cryptocurrencies": [
                # Non-OTC crypto (no OTC versions in constants)
                "BTCUSD", "ETHUSD", "DOTUSD",
            ],
            "forex": [
                # All OTC Forex pairs from constants
                "EURUSD_otc", "GBPUSD_otc", "USDJPY_otc", "USDCHF_otc", "USDCAD_otc",
                "AUDUSD_otc", "AUDNZD_otc", "AUDCAD_otc", "AUDCHF_otc", "AUDJPY_otc",
                "CADCHF_otc", "CADJPY_otc", "CHFJPY_otc", "EURCHF_otc", "EURGBP_otc",
                "EURJPY_otc", "EURNZD_otc", "GBPAUD_otc", "GBPJPY_otc",
                "NZDJPY_otc", "NZDUSD_otc",
                # Additional forex
                "EURRUB_otc", "USDRUB_otc", "EURHUF_otc", "CHFNOK_otc",
            ],
            "stocks": [
                # All OTC US Stocks from constants
                "#AAPL_otc", "#MSFT_otc", "#TSLA_otc", "#FB_otc", "#AMZN_otc",
                "#NFLX_otc", "#INTC_otc", "#BA_otc", "#JNJ_otc", "#PFE_otc",
                "#XOM_otc", "#AXP_otc", "#MCD_otc", "#CSCO_otc", "#VISA_otc",
                "#CITI_otc", "#FDX_otc", "#TWITTER_otc", "#BABA_otc",
                # Additional OTC stocks
                "Microsoft_otc", "Facebook_OTC", "Tesla_otc", "Boeing_OTC", 
                "American_Express_otc",
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
        
        # Main loop - run analysis cycles
        cycle = 0
        from beautiful_time import get_next_beautiful_time
        
        try:
            while True:
                current_time = datetime.now()
                
                # Check if we're in working hours (8:00 to 23:00)
                if not is_working_hours(current_time):
                    next_8am = get_next_working_hour_start(current_time)
                    wait_seconds = (next_8am - current_time).total_seconds()
                    wait_hours = wait_seconds / 3600
                    
                    print(f"\n{'='*70}")
                    print(f"⏸️  БОТ НА ПАУЗЕ (вне рабочих часов)")
                    print(f"{'='*70}")
                    print(f"⏰ Текущее время: {current_time.strftime('%H:%M:%S')}")
                    print(f"⏰ Рабочие часы: 08:00 - 23:00")
                    print(f"⏰ Следующий запуск: {next_8am.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"⏳ Ожидание {wait_hours:.1f} часов ({wait_seconds:.0f} секунд)...")
                    print(f"{'='*70}\n")
                    
                    # Wait until next 8:00 AM
                    await asyncio.sleep(wait_seconds)
                    print(f"✅ Рабочие часы начались! Продолжаем работу...\n")
                    continue
                
                cycle += 1
                print(f"\n{'='*70}")
                print(f"🔄 CYCLE {cycle}")
                print(f"{'='*70}")
                
                signals_found = await run_m2_analysis_cycle(client, evaluation_stage, notification_stage, otc_assets)
                
                # Check if we've passed working hours after the cycle
                current_time = datetime.now()
                if not is_working_hours(current_time):
                    next_8am = get_next_working_hour_start(current_time)
                    wait_seconds = (next_8am - current_time).total_seconds()
                    wait_hours = wait_seconds / 3600
                    
                    print(f"\n{'='*70}")
                    print(f"⏸️  РАБОЧИЕ ЧАСЫ ЗАВЕРШЕНЫ")
                    print(f"{'='*70}")
                    print(f"⏰ Текущее время: {current_time.strftime('%H:%M:%S')}")
                    print(f"⏰ Рабочие часы: 08:00 - 23:00")
                    print(f"⏰ Следующий запуск: {next_8am.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"⏳ Ожидание {wait_hours:.1f} часов ({wait_seconds:.0f} секунд)...")
                    print(f"{'='*70}\n")
                    
                    # Wait until next 8:00 AM
                    await asyncio.sleep(wait_seconds)
                    print(f"✅ Рабочие часы начались! Продолжаем работу...\n")
                    continue
                
                if signals_found > 0:
                    # If signals were found and posted, wait 1.5 minutes before next cycle
                    print(f"\n⏳ Ожидание 1.5 минуты перед следующим циклом...")
                    await asyncio.sleep(90)  # 1.5 minutes
                else:
                    # If no signals found, wait until close to next beautiful time
                    current_time = datetime.now()
                    next_beautiful = get_next_beautiful_time(current_time)
                    wait_seconds = (next_beautiful - current_time).total_seconds()
                    
                    # Check if next beautiful time is within working hours
                    if next_beautiful.hour >= 23:
                        # Next beautiful time is after 23:00, wait until next 8:00
                        next_8am = get_next_working_hour_start(current_time)
                        wait_seconds = (next_8am - current_time).total_seconds()
                        wait_hours = wait_seconds / 3600
                        
                        print(f"\n⏸️  Следующее красивое время вне рабочих часов")
                        print(f"⏰ Следующий запуск: {next_8am.strftime('%Y-%m-%d %H:%M:%S')}")
                        print(f"⏳ Ожидание {wait_hours:.1f} часов...")
                        await asyncio.sleep(wait_seconds)
                        print(f"✅ Рабочие часы начались! Продолжаем работу...\n")
                        continue
                    
                    # If next beautiful time is more than 15 seconds away, wait until 15 seconds before it
                    if wait_seconds > 15:
                        wait_until = wait_seconds - 15
                        print(f"\n⏳ Следующее красивое время: {next_beautiful.strftime('%H:%M:%S')}")
                        print(f"   Ожидание {wait_until:.0f} секунд до начала анализа...")
                        await asyncio.sleep(wait_until)
                    else:
                        # Already close to beautiful time, small delay and continue
                        print(f"\n⏳ Близко к красивому времени, продолжаем...")
                        await asyncio.sleep(2)
                
        except KeyboardInterrupt:
            print("\n\n⚠️ Interrupted by user")
            try:
                await telegram_notifier.send_message(
                    text="🛑 **M2 Criteria Bot Stopped**\n\nSession ended by user.",
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

