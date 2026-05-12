"""
Telegram notifier: sends trading signals to a channel or group.

Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID` via environment (see `.env.example`).
"""

import asyncio
import aiohttp
import ssl
from typing import Dict, List, Optional
from datetime import datetime
import json
import io


class TelegramNotifier:
    """Send trading signals and updates to Telegram channel"""
    
    def __init__(self, bot_token: str, channel_id: str, message_thread_id: Optional[int] = None):
        """
        Initialize Telegram notifier
        
        Args:
            bot_token: Telegram bot token (from @BotFather)
            channel_id: Telegram channel/group ID (e.g., "@your_channel" or "-1001234567890")
            message_thread_id: Optional topic/thread ID for groups with topics
        """
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.message_thread_id = message_thread_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.session = None
    
    async def _get_session(self):
        """Get or create aiohttp session with SSL context"""
        if self.session is None or self.session.closed:
            # Create SSL context that doesn't verify certificates
            # This fixes SSL certificate verification errors
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            # Create connector with SSL context
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self.session = aiohttp.ClientSession(connector=connector)
        return self.session
    
    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict] = None,
    ) -> Optional[int]:
        """
        Send a message to the Telegram channel/group
        
        Args:
            text: Message text
            parse_mode: Parse mode (HTML or Markdown)
        
        Returns:
            Optional[int]: Message ID if successful, None otherwise
        """
        try:
            session = await self._get_session()
            url = f"{self.base_url}/sendMessage"
            
            payload = {
                "chat_id": self.channel_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            
            # Add message_thread_id if specified (for groups with topics)
            if self.message_thread_id is not None:
                payload["message_thread_id"] = self.message_thread_id

            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("ok"):
                        message_id = result.get("result", {}).get("message_id")
                        return message_id
                    else:
                        print(f"❌ Telegram error: {result.get('description', 'Unknown error')}")
                        return None
                else:
                    error_text = await response.text()
                    print(f"❌ Telegram error: {error_text}")
                    return None
        except Exception as e:
            print(f"❌ Failed to send Telegram message: {e}")
            return None
    
    async def send_photo(
        self,
        photo: io.BytesIO,
        caption: str = "",
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict] = None,
    ) -> Optional[int]:
        """
        Send a photo to the Telegram channel/group
        
        Args:
            photo: BytesIO buffer containing image data
            caption: Caption text for the photo
            parse_mode: Parse mode (HTML or Markdown)
        
        Returns:
            Optional[int]: Message ID if successful, None otherwise
        """
        try:
            session = await self._get_session()
            url = f"{self.base_url}/sendPhoto"
            
            # Reset buffer position
            photo.seek(0)
            
            # Create form data
            data = aiohttp.FormData()
            data.add_field('chat_id', self.channel_id)
            data.add_field('caption', caption)
            data.add_field('parse_mode', parse_mode)
            data.add_field('photo', photo, filename='chart.png', content_type='image/png')
            
            # Add message_thread_id if specified (for groups with topics)
            if self.message_thread_id is not None:
                data.add_field('message_thread_id', str(self.message_thread_id))

            if reply_markup is not None:
                data.add_field('reply_markup', json.dumps(reply_markup, ensure_ascii=False))
            
            async with session.post(url, data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("ok"):
                        message_id = result.get("result", {}).get("message_id")
                        return message_id
                    else:
                        print(f"❌ Telegram error: {result.get('description', 'Unknown error')}")
                        return None
                else:
                    error_text = await response.text()
                    print(f"❌ Telegram error: {error_text}")
                    return None
        except Exception as e:
            print(f"❌ Failed to send Telegram photo: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def add_reaction(self, message_id: int, reaction: str) -> bool:
        """
        Add a reaction to a message
        
        Args:
            message_id: ID of the message to react to
            reaction: Reaction emoji (e.g., "⬆️", "⬇️")
        
        Returns:
            bool: True if successful
        """
        try:
            session = await self._get_session()
            url = f"{self.base_url}/setMessageReaction"
            
            payload = {
                "chat_id": self.channel_id,
                "message_id": message_id,
                "reaction": [{"type": "emoji", "emoji": reaction}]
            }
            
            # Add message_thread_id if specified (for groups with topics)
            if self.message_thread_id is not None:
                payload["message_thread_id"] = self.message_thread_id
            
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("ok"):
                        return True
                    else:
                        # Don't print error for reactions - they're optional
                        return False
                return False
        except Exception as e:
            # Reactions are optional, don't spam errors
            return False
    
    def format_position_signal(self, position_data: Dict, current_balance: float) -> str:
        """
        Format a new position signal for Telegram - Russian version with premium styling
        
        Args:
            position_data: Position information dict
            current_balance: Current account balance
        
        Returns:
            str: Formatted message in Russian
        """
        asset = position_data.get("asset", "UNKNOWN")
        direction = position_data.get("direction", "UNKNOWN")
        amount = position_data.get("amount", 0.0)
        confidence = position_data.get("confidence", 0.0)
        order_id = position_data.get("order_id", "N/A")
        
        # Get additional analysis data if available
        analysis = position_data.get("analysis", {})
        inner_conf = analysis.get("inner_confidence")
        volatility = analysis.get("volatility", 0.0)
        trend = analysis.get("trend", "N/A")
        macd = analysis.get("macd", {})
        bollinger = analysis.get("bollinger", {})
        confidence_factors = analysis.get("confidence_factors", [])
        
        # Premium styling
        direction_emoji = "🟢" if direction == "CALL" else "🔴"
        direction_text = "⬆️ <b>ВЫШЕ</b>" if direction == "CALL" else "⬇️ <b>НИЖЕ</b>"
        
        # Confidence badge
        if confidence >= 90:
            conf_badge = "🔥"
            conf_level = "Очень высокая"
        elif confidence >= 85:
            conf_badge = "⭐"
            conf_level = "Высокая"
        else:
            conf_badge = "💎"
            conf_level = "Хорошая"
        
        pct_of_balance = (amount / current_balance * 100) if current_balance > 0 else 0
        
        # Build premium message in Russian
        message = f"🎯 <b>НОВЫЙ СИГНАЛ</b> {direction_emoji}\n"
        message += "━━━━━━━━━━━━━━━━━━\n\n"
        
        # Main info section
        message += f"<b>📊 Актив:</b> <code>{asset}</code>\n"
        message += f"{direction_text} {direction_emoji}\n\n"
        
        # Investment details
        message += f"💰 <b>Инвестиция:</b> <i>${amount:.2f}</i>\n"
        message += f"📈 <b>Портфель:</b> <i>{pct_of_balance:.2f}%</i>\n"
        message += f"{conf_badge} <b>Уверенность:</b> <i>{confidence:.1f}%</i> ({conf_level})\n"
        
        if inner_conf is not None:
            message += f"🎲 <b>Внутренняя уверенность:</b> <i>{inner_conf:.1f}%</i>\n"
        
        # Technical indicators (compact)
        if volatility > 0 or trend != "N/A" or macd or bollinger:
            message += "\n📉 <b>Технический анализ:</b>\n"
            if trend != "N/A":
                trend_emoji = "📈" if "up" in trend.lower() or "bullish" in trend.lower() else "📉" if "down" in trend.lower() or "bearish" in trend.lower() else "➡️"
                trend_text = "Восходящий" if "up" in trend.lower() or "bullish" in trend.lower() else "Нисходящий" if "down" in trend.lower() or "bearish" in trend.lower() else "Боковой"
                message += f"   {trend_emoji} <i>Тренд:</i> {trend_text}\n"
            if volatility > 0:
                vol_level = "Высокая" if volatility > 0.05 else "Средняя" if volatility > 0.02 else "Низкая"
                message += f"   📊 <i>Волатильность:</i> {vol_level}\n"
            if macd:
                histogram = macd.get("histogram", 0)
                macd_signal = "🟢 Бычий" if histogram > 0 else "🔴 Медвежий"
                message += f"   {macd_signal} <i>MACD</i>\n"
            if bollinger:
                position_bb = bollinger.get("position", 0.5)
                bb_signal = "🔵 Нижняя полоса" if position_bb < 0.3 else "🟡 Середина" if position_bb < 0.7 else "🟢 Верхняя полоса"
                message += f"   {bb_signal} <i>Bollinger</i>\n"
        
        # Key factors (top 2 only for cleaner look)
        if confidence_factors:
            top_factors = confidence_factors[:2]
            message += "\n✨ <b>Ключевые сигналы:</b>\n"
            for factor in top_factors:
                # Translate and clean up factor text
                clean_factor = factor.replace("Strong ", "Сильный ").replace("High ", "Высокий ").replace("Good ", "Хороший ")
                clean_factor = clean_factor.replace("bullish", "бычий").replace("bearish", "медвежий")
                clean_factor = clean_factor.replace("alignment", "выравнивание").replace("momentum", "импульс")
                message += f"   ✓ <i>{clean_factor}</i>\n"
        
        message += "\n━━━━━━━━━━━━━━━━━━\n"
        message += f"🆔 <code>{order_id}</code>\n"
        message += f"🕐 <i>{datetime.now().strftime('%H:%M:%S')}</i>"
        
        return message
    
    async def send_position_signal(self, position_data: Dict, current_balance: float) -> bool:
        """
        Send a new position signal to Telegram with fire reaction
        
        Args:
            position_data: Position information dict
            current_balance: Current account balance
        
        Returns:
            bool: True if successful
        """
        message = self.format_position_signal(position_data, current_balance)
        message_id = await self.send_message(message)
        
        if message_id:
            # Add fire reaction to all posts
            await asyncio.sleep(0.5)
            await self.add_reaction(message_id, "🔥")
            
            return True
        return False
    
    def format_double_down_signal(self, double_down_data: Dict, current_balance: float) -> str:
        """
        Format a double down signal for Telegram - Russian version with premium styling
        
        Args:
            double_down_data: Double down information dict
            current_balance: Current account balance
        
        Returns:
            str: Formatted message in Russian
        """
        asset = double_down_data.get("asset", "UNKNOWN")
        direction = double_down_data.get("direction", "UNKNOWN")
        amount = double_down_data.get("amount", 0.0)
        original_profit = double_down_data.get("original_profit", 0.0)
        confidence = double_down_data.get("confidence", 0.0)
        position_number = double_down_data.get("position_number", 1)
        
        direction_emoji = "🟢" if direction == "CALL" else "🔴"
        direction_text = "⬆️ <b>ВЫШЕ</b>" if direction == "CALL" else "⬇️ <b>НИЖЕ</b>"
        
        pct_of_balance = (amount / current_balance * 100) if current_balance > 0 else 0
        
        # Premium styling in Russian
        message = f"⚡ <b>УДВОЕНИЕ</b> {direction_emoji}\n"
        message += "━━━━━━━━━━━━━━━━━━\n\n"
        
        message += f"<b>📊 Актив:</b> <code>{asset}</code>\n"
        message += f"{direction_text} {direction_emoji}\n\n"
        
        message += f"💰 <b>Дополнительно:</b> <i>${amount:.2f}</i>\n"
        message += f"📈 <b>Портфель:</b> <i>{pct_of_balance:.2f}%</i>\n"
        message += f"🔢 <b>Позиция №:</b> <i>{position_number}</i>\n"
        message += f"📉 <b>Текущий убыток:</b> <i>${abs(original_profit):.2f}</i>\n"
        message += f"💎 <b>Уверенность:</b> <i>{confidence:.1f}%</i>\n"
        
        message += "\n━━━━━━━━━━━━━━━━━━\n"
        message += f"🕐 <i>{datetime.now().strftime('%H:%M:%S')}</i>"
        
        return message
    
    async def send_double_down_signal(self, double_down_data: Dict, current_balance: float) -> bool:
        """
        Send a double down signal to Telegram with fire reaction
        
        Args:
            double_down_data: Double down information dict
            current_balance: Current account balance
        
        Returns:
            bool: True if successful
        """
        message = self.format_double_down_signal(double_down_data, current_balance)
        message_id = await self.send_message(message)
        
        if message_id:
            # Add fire reaction to all posts
            await asyncio.sleep(0.5)
            await self.add_reaction(message_id, "🔥")
            
            return True
        return False
    
    def format_result_signal(self, result_data: Dict) -> str:
        """
        Format a trade result signal for Telegram - Russian version with premium styling
        
        Args:
            result_data: Trade result information dict
        
        Returns:
            str: Formatted message in Russian
        """
        asset = result_data.get("asset", "UNKNOWN")
        win = result_data.get("win", False)
        profit = result_data.get("profit", 0.0)
        amount = result_data.get("amount", 0.0)
        direction = result_data.get("direction", "UNKNOWN")
        
        # Premium styling based on result
        if win:
            header_emoji = "✅"
            result_emoji = "🟢"
            result_text = "ПОБЕДА"
            profit_emoji = "💰"
        else:
            header_emoji = "❌"
            result_emoji = "🔴"
            result_text = "ПРОИГРЫШ"
            profit_emoji = "📉"
        
        direction_symbol = "⬆️" if direction == "CALL" else "⬇️"
        
        if amount > 0:
            roi = (profit / amount) * 100
        else:
            roi = 0
        
        # Build premium message in Russian
        message = f"{header_emoji} <b>СДЕЛКА ЗАКРЫТА</b> {result_emoji}\n"
        message += "━━━━━━━━━━━━━━━━━━\n\n"
        
        message += f"<b>📊 Актив:</b> <code>{asset}</code> {direction_symbol}\n"
        message += f"{result_emoji} <b>{result_text}</b>\n\n"
        
        message += f"{profit_emoji} <b>Прибыль/Убыток:</b> <i>${profit:+.2f}</i>\n"
        message += f"💵 <b>Инвестировано:</b> <i>${amount:.2f}</i>\n"
        
        if amount > 0:
            roi_emoji = "📈" if roi > 0 else "📉"
            message += f"{roi_emoji} <b>ROI:</b> <i>{roi:+.1f}%</i>\n"
        
        message += "\n━━━━━━━━━━━━━━━━━━\n"
        message += f"🕐 <i>{datetime.now().strftime('%H:%M:%S')}</i>"
        
        return message
    
    async def send_result_signal(self, result_data: Dict) -> bool:
        """
        Send a trade result signal to Telegram with fire reaction
        
        Args:
            result_data: Trade result information dict
        
        Returns:
            bool: True if successful
        """
        message = self.format_result_signal(result_data)
        message_id = await self.send_message(message)
        
        if message_id:
            # Add fire reaction to all posts
            await asyncio.sleep(0.5)
            await self.add_reaction(message_id, "🔥")
            
            return True
        return False
    
    def format_summary_signal(self, summary_data: Dict) -> str:
        """
        Format a cycle/session summary for Telegram - Russian version with premium styling
        
        Args:
            summary_data: Summary information dict
        
        Returns:
            str: Formatted message in Russian
        """
        cycle_num = summary_data.get("cycle_num", 0)
        profit = summary_data.get("profit", 0.0)
        wins = summary_data.get("wins", 0)
        losses = summary_data.get("losses", 0)
        trades = summary_data.get("trades", 0)
        start_balance = summary_data.get("start_balance", 0.0)
        end_balance = summary_data.get("end_balance", 0.0)
        
        win_rate = (wins / trades * 100) if trades > 0 else 0
        
        # Premium styling
        if profit > 0:
            profit_emoji = "💰"
            profit_color = "🟢"
        elif profit < 0:
            profit_emoji = "📉"
            profit_color = "🔴"
        else:
            profit_emoji = "➖"
            profit_color = "🟡"
        
        if win_rate >= 70:
            win_rate_emoji = "🔥"
            win_rate_text = "Отлично"
        elif win_rate >= 60:
            win_rate_emoji = "⭐"
            win_rate_text = "Хорошо"
        else:
            win_rate_emoji = "📊"
            win_rate_text = "Нормально"
        
        if start_balance > 0:
            pct_change = (profit / start_balance) * 100
        else:
            pct_change = 0
        
        # Build premium message in Russian
        message = f"📈 <b>ОТЧЕТ ЦИКЛА {cycle_num}</b>\n"
        message += "━━━━━━━━━━━━━━━━━━\n\n"
        
        # Balance section
        message += f"💵 <b>Баланс</b>\n"
        message += f"   <i>Начало:</i> ${start_balance:.2f}\n"
        message += f"   <i>Конец:</i> ${end_balance:.2f}\n"
        message += f"   {profit_color} <b>Прибыль/Убыток:</b> <i>${profit:+.2f}</i>\n"
        
        if start_balance > 0:
            pct_emoji = "📈" if pct_change > 0 else "📉" if pct_change < 0 else "➖"
            message += f"   {pct_emoji} <b>Изменение:</b> <i>{pct_change:+.2f}%</i>\n"
        
        message += "\n"
        
        # Performance section
        message += f"📊 <b>Производительность</b>\n"
        message += f"   ✅ <i>Побед:</i> {wins}\n"
        message += f"   ❌ <i>Проигрышей:</i> {losses}\n"
        message += f"   📈 <i>Всего сделок:</i> {trades}\n"
        message += f"   {win_rate_emoji} <b>Винрейт:</b> <i>{win_rate:.1f}%</i> ({win_rate_text})\n"
        
        message += "\n━━━━━━━━━━━━━━━━━━\n"
        message += f"🕐 <i>{datetime.now().strftime('%H:%M:%S')}</i>"
        
        return message
    
    async def send_summary_signal(self, summary_data: Dict) -> bool:
        """
        Send a cycle/session summary to Telegram with fire reaction
        
        Args:
            summary_data: Summary information dict
        
        Returns:
            bool: True if successful
        """
        message = self.format_summary_signal(summary_data)
        message_id = await self.send_message(message)
        
        if message_id:
            # Add fire reaction to all posts
            await asyncio.sleep(0.5)
            await self.add_reaction(message_id, "🔥")
            
            return True
        return False

