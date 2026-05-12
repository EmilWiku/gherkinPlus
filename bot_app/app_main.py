"""
Main entry point for the refactored trading bot
"""
import asyncio

from bot import DeepTradingBot
from env_setup import get_pocket_option_ssid, load_dotenv_early, require_env
from stages.testing import DefaultTestingStage

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


async def main():
    """Main entry point"""
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
    
    print("\n🚀 Starting Deep Analysis Trading Bot...\n")
    
    telegram_token = require_env("TELEGRAM_BOT_TOKEN")
    telegram_channel = require_env("TELEGRAM_CHANNEL_ID")
    
    # Initialize bot with default stages (can be customized)
    bot = DeepTradingBot(
        final_ssid,
        is_demo=is_demo,
        telegram_bot_token=telegram_token,
        telegram_channel_id=telegram_channel,
        # You can inject custom stages here:
        # testing_stage=CustomTestingStage(),
        # evaluation_stage=CustomEvaluationStage(),
        # order_placement_stage=CustomOrderPlacementStage(),
        # notification_stage=CustomNotificationStage(),
        # logging_stage=CustomLoggingStage(),
    )
    
    try:
        await bot.connect()
        
        # Asset configuration - Expanded with high payout assets
        otc_assets_by_category = {
            "cryptocurrencies": [
                # High payout (92%)
                "DOTUSD_otc",  # Polkadot OTC
                "LTCUSD_otc",  # Litecoin OTC
                "SOL-USD_otc",  # Solana OTC (uses hyphen format)
                # Medium-high payout
                "ETHUSD_otc",  # Ethereum OTC (90%)
                "DOGE_otc",  # Dogecoin OTC (88%)
                "TON-USD_otc",  # Toncoin OTC (83%)
                "MATIC_otc",  # Polygon OTC (82%)
                "ADA-USD_otc",  # Cardano OTC
                # Fallback to regular versions
                "BTCUSD_otc", "BTCUSD",
                "ETHUSD", "LNKUSD_otc", "LNKUSD",
            ],
            "forex": [
                # High payout (92%) - All major pairs
                "AEDCNY_otc",  # AED/CNY OTC
                "AUDCAD_otc",  # AUD/CAD OTC
                "AUDCHF_otc",  # AUD/CHF OTC
                "AUDUSD_otc",  # AUD/USD OTC
                "CADCHF_otc",  # CAD/CHF OTC
                "CADJPY_otc",  # CAD/JPY OTC
                "EURCHF_otc",  # EUR/CHF OTC
                "EURGBP_otc",  # EUR/GBP OTC
                "EURRUB_otc",  # EUR/RUB OTC
                "EURTRY_otc",  # EUR/TRY OTC
                "GBPUSD_otc",  # GBP/USD OTC
                "MADUSD_otc",  # MAD/USD OTC
                "NZDJPY_otc",  # NZD/JPY OTC
                "NZDUSD_otc",  # NZD/USD OTC
                "SARCNY_otc",  # SAR/CNY OTC
                "TNDUSD_otc",  # TND/USD OTC
                "USDCHF_otc",  # USD/CHF OTC
                "USDCNH_otc",  # USD/CNH OTC
                "USDDZD_otc",  # USD/DZD OTC
                "USDMXN_otc",  # USD/MXN OTC
                "USDPHP_otc",  # USD/PHP OTC
                "USDPKR_otc",  # USD/PKR OTC
                "YERUSD_otc",  # YER/USD OTC
                "ZARUSD_otc",  # ZAR/USD OTC
                # Medium-high payout (90-91%)
                "USDARS_otc",  # USD/ARS OTC (91%)
                "EURNZD_otc",  # EUR/NZD OTC (90%)
                "USDCLP_otc",  # USD/CLP OTC (90%)
                "USDRUB_otc",  # USD/RUB OTC (90%)
                "USDTHB_otc",  # USD/THB OTC (90%)
                "USDVND_otc",  # USD/VND OTC (90%)
                # Medium payout (86-87%)
                "USDMYR_otc",  # USD/MYR OTC (87%)
                "AUDJPY_otc",  # AUD/JPY OTC (86%)
                "EURJPY_otc",  # EUR/JPY OTC (86%)
                # Lower payout (still acceptable)
                "EURUSD_otc",  # EUR/USD OTC (83%)
                "USDJPY_otc",  # USD/JPY OTC (79%)
                "OMRCNY_otc",  # OMR/CNY OTC (78%)
                "AUDNZD_otc",  # AUD/NZD OTC (77%)
                "GBPJPY_otc",  # GBP/JPY OTC (76%)
                "USDINR_otc",  # USD/INR OTC
            ],
            "commodities": [
                "XAUUSD_otc",  # Gold OTC
                "XAGUSD_otc",  # Silver OTC
                "UKBrent_otc",  # Brent Oil OTC
                "USCrude_otc",  # WTI Crude Oil OTC
            ],
            "stocks": [
                # High payout (92%)
                "AMD_otc",  # Advanced Micro Devices OTC (note: no # prefix)
                "#AMZN_otc",  # Amazon OTC
                "#BABA_otc",  # Alibaba OTC
                # Medium-high payout (90-91%)
                "#AAPL_otc",  # Apple OTC (91%)
                # Medium payout (85-87%)
                "#FDX_otc",  # FedEx OTC (87%)
                "#MCD_otc",  # McDonald's OTC (86%)
                "GME_otc",  # GameStop Corp OTC (85%) (note: no # prefix)
                # Lower payout (still acceptable)
                "#NFLX_otc",  # Netflix OTC (81%)
                "#INTC_otc",  # Intel OTC (75%)
                "PLTR_otc",  # Palantir Technologies OTC (75%) (note: no # prefix)
                "#TSLA_otc",  # Tesla OTC (72%)
                "#XOM_otc",  # ExxonMobil OTC (72%)
                "#CITI_otc",  # Citigroup Inc OTC
                # Additional stocks
                "#MSFT_otc", "#BA_otc", "#VISA_otc",
                "#JNJ_otc", "#PFE_otc", "#AXP_otc", "#CSCO_otc",
                "#FB_otc", "#TWITTER_otc",
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
        
        # Run session
        await bot.run_session(otc_assets, otc_assets_by_category)
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await bot.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

