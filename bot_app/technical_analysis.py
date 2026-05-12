"""
Technical Analysis Engine
"""
import math
from typing import List, Dict
from pocketoptionapi_async.models import Candle

class TechnicalAnalyzer:
    """Technical analysis indicators and calculations"""
    
    @staticmethod
    def calculate_sma(prices: List[float], period: int) -> float:
        """Simple Moving Average"""
        if len(prices) < period:
            return sum(prices) / len(prices) if prices else 0
        return sum(prices[-period:]) / period
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> float:
        """Exponential Moving Average"""
        if not prices:
            return 0
        if len(prices) < period:
            return sum(prices) / len(prices)
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema
    
    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> float:
        """Relative Strength Index"""
        if len(prices) < period + 1:
            return 50.0
        
        gains, losses = [], []
        for i in range(len(prices) - period, len(prices)):
            change = prices[i] - prices[i - 1]
            gains.append(change if change > 0 else 0)
            losses.append(abs(change) if change < 0 else 0)
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def calculate_adx(candles: List[Candle], period: int = 14) -> float:
        """Average Directional Index (trend strength)"""
        if len(candles) < period * 2:
            return 25.0
        
        plus_dm, minus_dm, tr_values = [], [], []
        
        for i in range(1, len(candles)):
            high_diff = candles[i].high - candles[i-1].high
            low_diff = candles[i-1].low - candles[i].low
            
            plus_dm.append(high_diff if high_diff > low_diff and high_diff > 0 else 0)
            minus_dm.append(low_diff if low_diff > high_diff and low_diff > 0 else 0)
            
            tr = max(
                candles[i].high - candles[i].low,
                abs(candles[i].high - candles[i-1].close),
                abs(candles[i].low - candles[i-1].close)
            )
            tr_values.append(tr)
        
        if len(plus_dm) < period:
            return 25.0
        
        atr = sum(tr_values[-period:]) / period
        if atr == 0:
            return 25.0
        
        plus_di = (sum(plus_dm[-period:]) / period / atr) * 100
        minus_di = (sum(minus_dm[-period:]) / period / atr) * 100
        
        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
        return dx
    
    @staticmethod
    def calculate_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
        """MACD (Moving Average Convergence Divergence)"""
        if len(prices) < slow + signal:
            return {"macd": 0, "signal": 0, "histogram": 0}
        
        ema_fast = TechnicalAnalyzer.calculate_ema(prices, fast)
        ema_slow = TechnicalAnalyzer.calculate_ema(prices, slow)
        macd_line = ema_fast - ema_slow
        
        # Calculate signal line
        macd_values = []
        for i in range(slow, len(prices)):
            ema_f = TechnicalAnalyzer.calculate_ema(prices[:i+1], fast)
            ema_s = TechnicalAnalyzer.calculate_ema(prices[:i+1], slow)
            macd_values.append(ema_f - ema_s)
        
        signal_line = TechnicalAnalyzer.calculate_ema(macd_values, signal) if len(macd_values) >= signal else 0
        histogram = macd_line - signal_line
        
        return {"macd": macd_line, "signal": signal_line, "histogram": histogram}
    
    @staticmethod
    def calculate_bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0) -> Dict:
        """Bollinger Bands"""
        if len(prices) < period:
            sma = sum(prices) / len(prices) if prices else 0
            return {"upper": sma, "middle": sma, "lower": sma, "width": 0, "position": 0.5}
        
        sma = sum(prices[-period:]) / period
        variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
        std = math.sqrt(variance)
        
        upper = sma + (std_dev * std)
        lower = sma - (std_dev * std)
        width = (upper - lower) / sma * 100 if sma > 0 else 0
        current = prices[-1]
        position = (current - lower) / (upper - lower) if (upper - lower) > 0 else 0.5
        
        return {
            "upper": upper,
            "middle": sma,
            "lower": lower,
            "width": width,
            "position": position
        }
    
    @staticmethod
    def calculate_volume_profile(candles: List[Candle]) -> Dict:
        """Analyze volume distribution"""
        if not candles:
            return {"trend": "neutral", "strength": 0, "ratio": 1.0}
        
        volumes = [c.volume or 0 for c in candles]
        avg_volume = sum(volumes) / len(volumes) if volumes else 0
        recent_volume = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else volumes[-1] if volumes else 0
        
        volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1.0
        
        if len(candles) >= 5:
            price_trend = "up" if candles[-1].close > candles[-5].close else "down"
        else:
            price_trend = "up" if candles[-1].close > candles[0].close else "down"
        
        volume_trend = "increasing" if volume_ratio > 1.2 else "decreasing" if volume_ratio < 0.8 else "stable"
        
        strength = 0
        if volume_trend == "increasing" and price_trend == "up":
            strength = 1.0
        elif volume_trend == "increasing" and price_trend == "down":
            strength = -1.0
        
        return {"trend": volume_trend, "strength": strength, "ratio": volume_ratio}
    
    @staticmethod
    def calculate_support_resistance(candles: List[Candle]) -> Dict:
        """Identify support and resistance levels"""
        if len(candles) < 20:
            return {"support": 0, "resistance": 0, "distance_to_support": 0, "distance_to_resistance": 0}
        
        highs = [c.high for c in candles[-20:]]
        lows = [c.low for c in candles[-20:]]
        
        resistance = max(highs)
        support = min(lows)
        current = candles[-1].close
        
        distance_to_resistance = ((resistance - current) / current * 100) if current > 0 else 0
        distance_to_support = ((current - support) / current * 100) if current > 0 else 0
        
        return {
            "support": support,
            "resistance": resistance,
            "distance_to_support": distance_to_support,
            "distance_to_resistance": distance_to_resistance
        }

