"""
M2 Notification Stage - Sends formatted Telegram messages with M2 visualizations
"""
from typing import Dict, Optional, List
from datetime import datetime
from urllib.parse import quote

from visualization_lib import ChartComposer
from advanced_visualization import AdvancedVisualizer

# Russian translations
RUSSIAN_TEXTS = {
    "M2 SIGNAL": "M2 СИГНАЛ",
    "Asset": "Актив",
    "Direction": "Направление",
    "CALL": "ВВЕРХ",
    "PUT": "ВНИЗ",
    "M2 Score": "M2 Оценка",
    "Pattern": "Паттерн",
    "Current Price": "Текущая цена",
    "Score Breakdown": "Разбивка оценки",
    "Pattern": "Паттерн",
    "Confirmation": "Подтверждение",
    "Momentum": "Импульс",
    "Consistency": "Последовательность",
    "pts": "балл",
    "Time Placed": "Время размещения",
    "Prognosis Close": "Прогноз закрытия",
    "Selected by M2 Criteria": "Выбрано по критериям M2",
    "Exceptional": "Исключительный",
    "Excellent": "Отличный",
    "Strong": "Сильный",
    "Moderate": "Умеренный",
    "M2 Analysis Summary": "Сводка анализа M2",
    "Selected": "Выбрано",
    "best signals": "лучших сигналов",
}

# Beautiful names mapping for assets
BEAUTIFUL_ASSET_NAMES = {
    # Forex OTC
    "EURUSD_otc": "EUR/USD",
    "GBPUSD_otc": "GBP/USD",
    "USDJPY_otc": "USD/JPY",
    "USDCHF_otc": "USD/CHF",
    "USDCAD_otc": "USD/CAD",
    "AUDUSD_otc": "AUD/USD",
    "AUDNZD_otc": "AUD/NZD",
    "AUDCAD_otc": "AUD/CAD",
    "AUDCHF_otc": "AUD/CHF",
    "AUDJPY_otc": "AUD/JPY",
    "CADCHF_otc": "CAD/CHF",
    "CADJPY_otc": "CAD/JPY",
    "CHFJPY_otc": "CHF/JPY",
    "EURCHF_otc": "EUR/CHF",
    "EURGBP_otc": "EUR/GBP",
    "EURJPY_otc": "EUR/JPY",
    "EURNZD_otc": "EUR/NZD",
    "GBPAUD_otc": "GBP/AUD",
    "GBPJPY_otc": "GBP/JPY",
    "NZDJPY_otc": "NZD/JPY",
    "NZDUSD_otc": "NZD/USD",
    "EURRUB_otc": "EUR/RUB",
    "USDRUB_otc": "USD/RUB",
    "EURHUF_otc": "EUR/HUF",
    "CHFNOK_otc": "CHF/NOK",
    # Commodities OTC
    "XAUUSD_otc": "Золото",
    "XAGUSD_otc": "Серебро",
    "UKBrent_otc": "Нефть Brent",
    "USCrude_otc": "Нефть WTI",
    "XNGUSD_otc": "Природный газ",
    "XPTUSD_otc": "Платина",
    "XPDUSD_otc": "Палладий",
    # Indices OTC
    "SP500_otc": "S&P 500",
    "NASUSD_otc": "NASDAQ",
    "DJI30_otc": "Dow Jones",
    "JPN225_otc": "Nikkei 225",
    "D30EUR_otc": "DAX 30",
    "E50EUR_otc": "Euro Stoxx 50",
    "F40EUR_otc": "CAC 40",
    "E35EUR_otc": "IBEX 35",
    "100GBP_otc": "FTSE 100",
    "AUS200_otc": "ASX 200",
    # Stocks OTC
    "#AAPL_otc": "Apple",
    "#MSFT_otc": "Microsoft",
    "#TSLA_otc": "Tesla",
    "#FB_otc": "Meta (Facebook)",
    "#AMZN_otc": "Amazon",
    "#NFLX_otc": "Netflix",
    "#INTC_otc": "Intel",
    "#BA_otc": "Boeing",
    "#JNJ_otc": "Johnson & Johnson",
    "#PFE_otc": "Pfizer",
    "#XOM_otc": "Exxon Mobil",
    "#AXP_otc": "American Express",
    "#MCD_otc": "McDonald's",
    "#CSCO_otc": "Cisco",
    "#VISA_otc": "Visa",
    "#CITI_otc": "Citigroup",
    "#FDX_otc": "FedEx",
    "#TWITTER_otc": "Twitter",
    "#BABA_otc": "Alibaba",
    "Microsoft_otc": "Microsoft",
    "Facebook_OTC": "Meta (Facebook)",
    "Tesla_otc": "Tesla",
    "Boeing_OTC": "Boeing",
    "American_Express_otc": "American Express",
    # Cryptocurrencies (non-OTC)
    "BTCUSD": "Bitcoin",
    "ETHUSD": "Ethereum",
    "DOTUSD": "Polkadot",
}


def get_beautiful_asset_name(technical_name: str) -> str:
    """
    Get beautiful display name for an asset.
    
    Args:
        technical_name: Technical asset name (e.g., "USCrude_otc")
    
    Returns:
        Beautiful name (e.g., "Нефть WTI") or original if not found
    """
    return BEAUTIFUL_ASSET_NAMES.get(technical_name, technical_name)


class M2NotificationStage:
    """
    Notification stage for M2-based signals.
    Sends vibrant Telegram messages with M2 analysis charts.
    """
    
    def __init__(self, telegram_notifier=None, use_advanced_viz: bool = True):
        """
        Initialize with Telegram notifier.
        
        Args:
            telegram_notifier: TelegramNotifier instance
            use_advanced_viz: If True, use advanced visualization (Plotly/Seaborn),
                            otherwise use original ChartComposer
        """
        self.telegram = telegram_notifier
        self.use_advanced_viz = use_advanced_viz
        if use_advanced_viz:
            self.advanced_visualizer_light = AdvancedVisualizer(style='light')
            self.advanced_visualizer_dark = AdvancedVisualizer(style='dark')
        else:
            self.chart_composer = ChartComposer()
    
    def _format_m2_signal_message(self, analysis: Dict) -> str:
        """
        Format a vibrant M2 signal message with emojis.
        
        Args:
            analysis: M2 analysis result
        
        Returns:
            Formatted message string
        """
        asset = analysis.get("asset", "UNKNOWN")
        direction = analysis.get("signal_direction", "")
        m2_score = analysis.get("m2_score", 0)
        time_placed = analysis.get("time_placed", datetime.now())
        prognosis_close = analysis.get("prognosis_close_time", datetime.now())
        current_price = analysis.get("current_price", 0)
        live_quote = analysis.get("live_quote")
        chart_tf = int(analysis.get("chart_timeframe_sec", 60))
        if chart_tf < 60:
            tf_label = f"S{chart_tf}"
        elif chart_tf % 3600 == 0:
            tf_label = f"H{chart_tf // 3600}"
        else:
            tf_label = f"M{chart_tf // 60}"
        
        pattern_analysis = analysis.get("pattern_analysis", {})
        pattern_1m = pattern_analysis.get("pattern_1m", {})
        pattern_name = pattern_1m.get("pattern", "Regular Pattern")
        
        # Score breakdown
        pattern_score = analysis.get("pattern_score", 0)
        confirmation_score = analysis.get("confirmation_score", 0)
        momentum_score = analysis.get("momentum_score", 0)
        consistency_score = analysis.get("consistency_score", 0)
        
        # Direction-aware visual style for caption (matches chart palette).
        is_call = direction == "CALL"
        direction_emoji = "⬜️🔼" if is_call else "⬛️🔽"
        signal_emoji = "🤍📈" if is_call else "🖤📉"
        mood_line = "⚪️ **Режим сигнала:** White Momentum" if is_call else "⚫️ **Режим сигнала:** Black Pressure"
        
        if m2_score >= 85:
            score_emoji = "🔥"
            score_text = "Exceptional"
        elif m2_score >= 75:
            score_emoji = "⭐"
            score_text = "Excellent"
        elif m2_score >= 65:
            score_emoji = "✨"
            score_text = "Strong"
        else:
            score_emoji = "💡"
            score_text = "Moderate"
        
        # Format times
        placed_str = time_placed.strftime("%H:%M:%S")
        close_str = prognosis_close.strftime("%H:%M:%S")
        
        # Get beautiful time range if available
        beautiful_range = analysis.get("beautiful_time_range", f"{placed_str} до {close_str}")
        direction_ru = RUSSIAN_TEXTS.get(direction, direction)
        score_text_ru = RUSSIAN_TEXTS.get(score_text, score_text)
        
        # Get beautiful asset name
        beautiful_asset_name = get_beautiful_asset_name(asset)
        
        # Build message in Russian
        message_parts = [
            f"{signal_emoji} **{RUSSIAN_TEXTS['M2 SIGNAL']}** {signal_emoji}",
            "",
            f"💰 **{RUSSIAN_TEXTS['Asset']}:** `{beautiful_asset_name}`",
            f"{direction_emoji} **{RUSSIAN_TEXTS['Direction']}:** {direction_ru}",
            mood_line,
            f"{score_emoji} **{RUSSIAN_TEXTS['M2 Score']}:** {m2_score:.1f}% ({score_text_ru})",
            f"📊 **{RUSSIAN_TEXTS['Pattern']}:** {pattern_name}",
            f"💵 **Закрытие последней свечи {tf_label} (на графике):** `${current_price:.5f}`",
            f"📈 **График:** последние 50 свечей {tf_label} (как в Pocket Option)",
            "",
            f"⏰ **{RUSSIAN_TEXTS['Time Placed']}:** {beautiful_range}",
            "💡 **Рекомендация по риску:** ставка до 10% от баланса",
        ]
        if live_quote is not None:
            message_parts.insert(8, f"📡 **Live-котировка (справочно):** `${live_quote:.5f}`")

        return "\n".join(message_parts)

    def _build_trade_link(self, asset: str) -> str:
        """
        Build a direct PocketOption link for the signal asset.
        Note: pre-filling stake amount through URL is generally not supported.
        """
        return "https://clck.ru/3NJnGL"
    
    async def send_signal(self, analysis: Dict):
        """
        Send an M2 trading signal with visualization.
        
        Args:
            analysis: M2 analysis result
        """
        if not self.telegram:
            print(f"⚠️ No Telegram notifier configured, skipping signal for {analysis.get('asset')}")
            return
        
        try:
            # Format message
            message = self._format_m2_signal_message(analysis)
            
            # Create visualization using advanced library or original
            asset_name = analysis.get("asset", "Asset")
            if self.use_advanced_viz:
                # Direction-based palette:
                # CALL (up) -> white theme, PUT (down) -> black theme.
                direction = analysis.get("signal_direction", "")
                visualizer = self.advanced_visualizer_light if direction == "CALL" else self.advanced_visualizer_dark
                chart_buffer = visualizer.create_comprehensive_chart(analysis, asset_name)
            else:
                chart_buffer = self.chart_composer.create_m2_visualization(analysis, asset_name)
            
            # Add inline button with direct link to the suggested asset.
            trade_url = self._build_trade_link(asset_name)
            reply_markup = {
                "inline_keyboard": [
                    [{"text": "✨📊 Открыть сделку в PocketOption", "url": trade_url}]
                ]
            }

            # Send message with image
            result = await self.telegram.send_photo(
                photo=chart_buffer,
                caption=message,
                parse_mode='Markdown',
                reply_markup=reply_markup,
            )
            print(f"✅ Sent M2 signal for {asset_name} with {'advanced' if self.use_advanced_viz else 'standard'} visualization")
        
        except Exception as e:
            print(f"❌ Failed to send M2 signal notification: {e}")
            import traceback
            traceback.print_exc()
    
    async def send_summary(self, signals: List[Dict]):
        """Send summary of selected signals"""
        if not self.telegram or not signals:
            return
        
        try:
            summary_parts = [
                f"📊 **{RUSSIAN_TEXTS['M2 Analysis Summary']}**",
                "",
                f"🎯 {RUSSIAN_TEXTS['Selected']} {len(signals)} {RUSSIAN_TEXTS['best signals']}:",
                ""
            ]
            
            for i, signal in enumerate(signals, 1):
                asset = signal.get("asset", "UNKNOWN")
                beautiful_asset_name = get_beautiful_asset_name(asset)
                direction = signal.get("signal_direction", "UNKNOWN")
                direction_ru = RUSSIAN_TEXTS.get(direction, direction)
                m2_score = signal.get("m2_score", 0)
                summary_parts.append(f"{i}. {beautiful_asset_name} {direction_ru} (M2: {m2_score:.1f}%)")
            
            message = "\n".join(summary_parts)
            await self.telegram.send_message(
                text=message,
                parse_mode='Markdown'
            )
        except Exception as e:
            print(f"⚠️ Failed to send summary: {e}")
    
    async def close(self):
        """Close resources"""
        if self.telegram:
            try:
                await self.telegram.close()
            except Exception:
                pass

