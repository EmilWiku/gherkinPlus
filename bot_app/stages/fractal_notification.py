"""
Fractal Notification Stage - Sends formatted Telegram messages with fractal visualizations
"""
from abc import ABC, abstractmethod
from typing import Dict, Optional
from datetime import datetime
import io

from fractal_visualization import FractalVisualizer


class FractalNotificationStage:
    """
    Notification stage for fractal-based signals.
    Sends simplified, vibrant Telegram messages with fractal charts.
    """
    
    def __init__(self, telegram_notifier=None):
        """
        Initialize with Telegram notifier.
        
        Args:
            telegram_notifier: TelegramNotifier instance
        """
        self.telegram = telegram_notifier
        self.visualizer = FractalVisualizer()
    
    def _format_signal_message(self, opportunity: Dict) -> str:
        """
        Format a vibrant signal message with emojis.
        
        Args:
            opportunity: Analysis result with signal data
        
        Returns:
            Formatted message string
        """
        asset = opportunity.get("asset", "UNKNOWN")
        direction = opportunity.get("signal_direction", "")
        confidence = opportunity.get("confidence_score", 0)
        time_placed = opportunity.get("time_placed", datetime.now())
        prognosis_close = opportunity.get("prognosis_close_time", datetime.now())
        current_price = opportunity.get("current_price", 0)
        
        # Emojis based on direction
        direction_emoji = "🔼" if direction == "CALL" else "🔽"
        signal_emoji = "📈" if direction == "CALL" else "📉"
        confidence_emoji = "🔥" if confidence >= 90 else "✨" if confidence >= 80 else "💡"
        
        # Format times
        placed_str = time_placed.strftime("%H:%M:%S")
        close_str = prognosis_close.strftime("%H:%M:%S")
        
        # Build message
        message_parts = [
            f"{signal_emoji} **TRADING SIGNAL** {signal_emoji}",
            "",
            f"💰 **Asset:** `{asset}`",
            f"{direction_emoji} **Direction:** {direction}",
            f"{confidence_emoji} **Certainty:** {confidence:.1f}%",
            f"💵 **Current Price:** ${current_price:.5f}",
            "",
            f"⏰ **Time Placed:** {placed_str}",
            f"⏳ **Prognosis Close:** {close_str}",
            "",
            f"📊 **Fractal Analysis Complete**"
        ]
        
        return "\n".join(message_parts)
    
    async def send_signal(self, opportunity: Dict):
        """
        Send a trading signal with visualization.
        
        Args:
            opportunity: Analysis result with signal data
        """
        if not self.telegram:
            print(f"⚠️ No Telegram notifier configured, skipping signal for {opportunity.get('asset')}")
            return
        
        try:
            # Format message
            message = self._format_signal_message(opportunity)
            
            # Create visualization
            candles = opportunity.get("candles", [])
            fractals = opportunity.get("fractals", {})
            signal_direction = opportunity.get("signal_direction")
            asset_name = opportunity.get("asset", "Asset")
            
            if candles:
                chart_buffer = self.visualizer.create_fractal_chart(
                    candles, fractals, signal_direction, asset_name
                )
                
                # Send message with image
                result = await self.telegram.send_photo(
                    photo=chart_buffer,
                    caption=message,
                    parse_mode='Markdown'
                )
                print(f"✅ Sent signal for {asset_name} with visualization")
            else:
                # Send text only if no candles
                await self.telegram.send_message(
                    text=message,
                    parse_mode='Markdown'
                )
                print(f"✅ Sent signal for {asset_name} (text only)")
        
        except Exception as e:
            print(f"❌ Failed to send signal notification: {e}")
            import traceback
            traceback.print_exc()
    
    async def send_summary(self, summary_data: Dict):
        """Send summary (optional, for compatibility)"""
        pass
    
    async def close(self):
        """Close resources"""
        if self.telegram:
            try:
                await self.telegram.close()
            except Exception:
                pass

