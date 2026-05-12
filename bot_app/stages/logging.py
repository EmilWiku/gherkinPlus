"""
Logging Stage - Interface and implementations for debug logging
"""
from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
from datetime import datetime


class LoggingStage(ABC):
    """Abstract interface for logging stage"""
    
    @abstractmethod
    def log_info(self, message: str, data: Optional[Dict] = None):
        """Log informational message"""
        pass
    
    @abstractmethod
    def log_warning(self, message: str, data: Optional[Dict] = None):
        """Log warning message"""
        pass
    
    @abstractmethod
    def log_error(self, message: str, error: Optional[Exception] = None, data: Optional[Dict] = None):
        """Log error message"""
        pass
    
    @abstractmethod
    def log_debug(self, message: str, data: Optional[Dict] = None):
        """Log debug message"""
        pass
    
    @abstractmethod
    def log_cycle_start(self, cycle_num: int, balance: float):
        """Log cycle start"""
        pass
    
    @abstractmethod
    def log_cycle_end(self, cycle_num: int, profit: float, wins: int, losses: int):
        """Log cycle end"""
        pass
    
    @abstractmethod
    def log_position_opened(self, position_data: Dict):
        """Log when position is opened"""
        pass
    
    @abstractmethod
    def log_position_closed(self, result_data: Dict):
        """Log when position is closed"""
        pass


class DefaultLoggingStage(LoggingStage):
    """Default implementation using print statements"""
    
    def __init__(self, log_level: str = "INFO"):
        """
        Initialize logger.
        
        Args:
            log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR)
        """
        self.log_level = log_level
        self._levels = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}
    
    def _should_log(self, level: str) -> bool:
        """Check if message at given level should be logged"""
        return self._levels.get(level, 1) >= self._levels.get(self.log_level, 1)
    
    def _format_message(self, level: str, message: str) -> str:
        """Format log message"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"[{timestamp}] [{level}] {message}"
    
    def log_info(self, message: str, data: Optional[Dict] = None):
        """Log informational message"""
        if self._should_log("INFO"):
            formatted = self._format_message("INFO", message)
            print(formatted)
            if data:
                print(f"   Data: {data}")
    
    def log_warning(self, message: str, data: Optional[Dict] = None):
        """Log warning message"""
        if self._should_log("WARNING"):
            formatted = self._format_message("WARNING", message)
            print(formatted)
            if data:
                print(f"   Data: {data}")
    
    def log_error(self, message: str, error: Optional[Exception] = None, data: Optional[Dict] = None):
        """Log error message"""
        if self._should_log("ERROR"):
            formatted = self._format_message("ERROR", message)
            print(formatted)
            if error:
                print(f"   Error: {error}")
            if data:
                print(f"   Data: {data}")
    
    def log_debug(self, message: str, data: Optional[Dict] = None):
        """Log debug message"""
        if self._should_log("DEBUG"):
            formatted = self._format_message("DEBUG", message)
            print(formatted)
            if data:
                print(f"   Data: {data}")
    
    def log_cycle_start(self, cycle_num: int, balance: float):
        """Log cycle start"""
        print(f"\n{'='*70}")
        print(f"🚀 CYCLE {cycle_num} - 5-MINUTE SESSION")
        print(f"{'='*70}")
        print(f"💰 Start Balance: ${balance:.2f}")
        print(f"{'='*70}\n")
    
    def log_cycle_end(self, cycle_num: int, profit: float, wins: int, losses: int):
        """Log cycle end"""
        total_trades = wins + losses
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        print(f"\n{'='*70}")
        print(f"📊 CYCLE {cycle_num} SUMMARY")
        print(f"{'='*70}")
        print(f"💰 Profit: ${profit:+.2f}")
        print(f"📈 Wins: {wins} | Losses: {losses}")
        print(f"📊 Win Rate: {win_rate:.1f}%")
        print(f"{'='*70}\n")
    
    def log_position_opened(self, position_data: Dict):
        """Log when position is opened"""
        asset = position_data.get("asset", "UNKNOWN")
        direction = position_data.get("direction", "UNKNOWN")
        amount = position_data.get("amount", 0)
        confidence = position_data.get("confidence", 0)
        print(f"💰 Position opened: {asset} {direction} ${amount:.2f} (confidence: {confidence:.1f}%)")
    
    def log_position_closed(self, result_data: Dict):
        """Log when position is closed"""
        asset = result_data.get("asset", "UNKNOWN")
        win = result_data.get("win", False)
        profit = result_data.get("profit", 0)
        emoji = "🎉" if win else "❌"
        result_text = "WIN" if win else "LOSS"
        print(f"{emoji} {asset}: {result_text} ${profit:+.2f}")


class FileLoggingStage(LoggingStage):
    """File-based logging implementation"""
    
    def __init__(self, log_file: str = "trading.log", log_level: str = "INFO"):
        """
        Initialize file logger.
        
        Args:
            log_file: Path to log file
            log_level: Minimum log level
        """
        self.log_file = log_file
        self.log_level = log_level
        self._levels = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}
    
    def _should_log(self, level: str) -> bool:
        """Check if message at given level should be logged"""
        return self._levels.get(level, 1) >= self._levels.get(self.log_level, 1)
    
    def _write_log(self, level: str, message: str, extra: Optional[str] = None):
        """Write log to file"""
        if not self._should_log(level):
            return
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"
        if extra:
            log_line += f" | {extra}"
        log_line += "\n"
        
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception as e:
            print(f"Failed to write to log file: {e}")
    
    def log_info(self, message: str, data: Optional[Dict] = None):
        self._write_log("INFO", message, str(data) if data else None)
        if self._should_log("INFO"):
            print(f"[INFO] {message}")
    
    def log_warning(self, message: str, data: Optional[Dict] = None):
        self._write_log("WARNING", message, str(data) if data else None)
        if self._should_log("WARNING"):
            print(f"[WARNING] {message}")
    
    def log_error(self, message: str, error: Optional[Exception] = None, data: Optional[Dict] = None):
        error_str = str(error) if error else None
        self._write_log("ERROR", message, error_str or str(data) if data else None)
        if self._should_log("ERROR"):
            print(f"[ERROR] {message}")
            if error:
                print(f"   Error: {error}")
    
    def log_debug(self, message: str, data: Optional[Dict] = None):
        self._write_log("DEBUG", message, str(data) if data else None)
    
    def log_cycle_start(self, cycle_num: int, balance: float):
        self._write_log("INFO", f"Cycle {cycle_num} started", f"Balance: ${balance:.2f}")
    
    def log_cycle_end(self, cycle_num: int, profit: float, wins: int, losses: int):
        total_trades = wins + losses
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        self._write_log("INFO", f"Cycle {cycle_num} ended", 
                       f"Profit: ${profit:.2f}, Wins: {wins}, Losses: {losses}, Win Rate: {win_rate:.1f}%")
    
    def log_position_opened(self, position_data: Dict):
        asset = position_data.get("asset", "UNKNOWN")
        direction = position_data.get("direction", "UNKNOWN")
        amount = position_data.get("amount", 0)
        self._write_log("INFO", f"Position opened: {asset} {direction}", f"Amount: ${amount:.2f}")
    
    def log_position_closed(self, result_data: Dict):
        asset = result_data.get("asset", "UNKNOWN")
        win = result_data.get("win", False)
        profit = result_data.get("profit", 0)
        self._write_log("INFO", f"Position closed: {asset}", f"Result: {'WIN' if win else 'LOSS'}, Profit: ${profit:.2f}")

