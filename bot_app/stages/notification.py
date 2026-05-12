"""
Notification Stage - Interface and implementations for notifications (Telegram, etc.)
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict


class NotificationStage(ABC):
    """Abstract interface for notification stage"""
    
    @abstractmethod
    async def send_position_signal(self, position_data: Dict, current_balance: float):
        """Send notification when a position is opened"""
        pass
    
    @abstractmethod
    async def send_result_signal(self, result_data: Dict):
        """Send notification when a position result is available"""
        pass
    
    @abstractmethod
    async def send_summary_signal(self, summary_data: Dict):
        """Send summary notification (e.g., cycle summary)"""
        pass
    
    @abstractmethod
    async def send_double_down_signal(self, dd_data: Dict, current_balance: float):
        """Send notification when double down occurs"""
        pass
    
    @abstractmethod
    async def close(self):
        """Close/cleanup notification resources"""
        pass


class DefaultNotificationStage(NotificationStage):
    """Default implementation using Telegram"""
    
    def __init__(self, telegram_notifier=None):
        """
        Initialize with optional Telegram notifier.
        
        Args:
            telegram_notifier: TelegramNotifier instance or None
        """
        self.telegram = telegram_notifier
    
    async def send_position_signal(self, position_data: Dict, current_balance: float):
        """Send position signal via Telegram"""
        if self.telegram:
            try:
                await self.telegram.send_position_signal(position_data, current_balance)
            except Exception as e:
                print(f"⚠️ Telegram error: {e}")
    
    async def send_result_signal(self, result_data: Dict):
        """Send result signal via Telegram"""
        if self.telegram:
            try:
                await self.telegram.send_result_signal(result_data)
            except Exception as e:
                print(f"⚠️ Telegram error: {e}")
    
    async def send_summary_signal(self, summary_data: Dict):
        """Send summary signal via Telegram"""
        if self.telegram:
            try:
                await self.telegram.send_summary_signal(summary_data)
            except Exception as e:
                print(f"⚠️ Telegram error: {e}")
    
    async def send_double_down_signal(self, dd_data: Dict, current_balance: float):
        """Send double down signal via Telegram"""
        if self.telegram:
            try:
                await self.telegram.send_double_down_signal(dd_data, current_balance)
            except Exception as e:
                print(f"⚠️ Telegram error: {e}")
    
    async def close(self):
        """Close Telegram connection"""
        if self.telegram:
            try:
                await self.telegram.close()
            except Exception:
                pass


class NullNotificationStage(NotificationStage):
    """Null implementation that does nothing (for testing)"""
    
    async def send_position_signal(self, position_data: Dict, current_balance: float):
        pass
    
    async def send_result_signal(self, result_data: Dict):
        pass
    
    async def send_summary_signal(self, summary_data: Dict):
        pass
    
    async def send_double_down_signal(self, dd_data: Dict, current_balance: float):
        pass
    
    async def close(self):
        pass

