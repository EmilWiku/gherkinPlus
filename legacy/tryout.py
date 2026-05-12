"""
Legacy monolithic PocketOption trading bot (reference / experiments).
Prefer `main.py` + `bot.py` under `bot_app/` for the modular pipeline.
"""

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "bot_app"))
sys.path.insert(0, str(_REPO / "PocketOptionAPI"))

from pocketoptionapi_async import AsyncPocketOptionClient, OrderDirection
from pocketoptionapi_async.models import Candle, Balance, OrderStatus
from pocketoptionapi_async.utils import analyze_candles, calculate_volatility, determine_trend
from telegram_notifier import TelegramNotifier
import asyncio
import sqlite3
import math
import pandas as pd
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta

from env_setup import get_pocket_option_ssid, load_dotenv_early, require_env

# CONFIGURATION CONSTANTS
# ============================================================================

class TradingConfig:
    """Centralized trading thresholds and risk parameters."""
    # Entry thresholds
    MIN_CONFIDENCE = 90.0  # Minimum confidence to enter trade (90% - balanced with historical modifiers)
    MIN_CONFIDENCE_FACTORS = 6  # Minimum number of confidence factors (increased from 4 to 6)
    MIN_ADX = 30.0  # Minimum ADX for trend strength (increased from 25 to 30)
    MIN_HISTORICAL_WIN_RATE = 0.30  # Hard block only if <30% (very poor), otherwise use as modifier
    HISTORICAL_BLOCK_THRESHOLD = 0.30  # Only block assets with <30% win rate
    HISTORICAL_LARGE_LOSS_THRESHOLD = -200.0  # Only block if lost >$200
    MIN_OTC_INNER_CONFIDENCE = 85.0  # Minimum inner confidence for OTC (increased from 80%)
    
    # Position sizing - INCREASED for higher risk/reward
    MIN_POSITION_PCT = 0.08  # 8% of balance (at 90% confidence)
    MAX_POSITION_PCT = 0.10  # 10% of balance (at 100% confidence)
    MAX_TOTAL_EXPOSURE_PCT = 0.12  # 12% of balance total exposure (allows 1-2 positions)
    MAX_POSITIONS_PER_CYCLE = 2  # Maximum positions per cycle
    
    # Double down rules - DISABLED (too risky)
    ENABLE_DOUBLE_DOWN = False  # DISABLED to prevent compounding losses
    MAX_POSITIONS_PER_ASSET = 1  # Only 1 position per asset (no doubling)
    MAX_EXPOSURE_PER_ASSET_PCT = 0.10  # 10% per asset max (matches MAX_POSITION_PCT)
    MAX_TOTAL_EXPOSURE_AFTER_DD_PCT = 0.12  # 12% after double down (if enabled)
    DOUBLE_DOWN_MULTIPLIER = 1.0  # No doubling (1.0x = same size)
    MIN_TIME_REMAINING_DD = 60  # 1 minute minimum for double down
    HIGH_VOLATILITY_THRESHOLD = 0.05  # Volatility threshold for reduction
    
    # Circuit breakers - ENABLED to prevent large losses
    ENABLE_CIRCUIT_BREAKER = True
    MAX_CONSECUTIVE_LOSSES = 3  # Stop trading after 3 consecutive losses
    MAX_LOSSES_PER_HOUR = 5  # Stop trading if 5 losses in 1 hour
    MAX_DRAWDOWN_PCT = 0.10  # Stop trading if 10% drawdown from session start
    CIRCUIT_BREAKER_COOLDOWN_MINUTES = 30  # Wait 30 minutes before resuming
    
    # Trading duration
    CYCLE_DURATION_MINUTES = 5
    SESSION_DURATION_HOURS = 8
    CHECK_INTERVAL_SECONDS = 60  # Check positions every minute


# ============================================================================
# DATABASE LAYER
# ============================================================================

class TradeDatabase:
    """SQLite database for tracking trades and performance"""
    
    def __init__(self, db_path: str = "trading_metrics.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create trades table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                asset TEXT NOT NULL,
                direction TEXT NOT NULL,
                amount REAL NOT NULL,
                duration INTEGER NOT NULL,
                order_id TEXT UNIQUE,
                signal_strength REAL,
                confidence_score REAL,
                status TEXT,
                profit REAL,
                win INTEGER DEFAULT 0,
                payout_percentage REAL,
                expected_profit REAL
            )
        ''')
        
        # Migrate: add missing columns
        try:
            cursor.execute("PRAGMA table_info(trades)")
            columns = [column[1] for column in cursor.fetchall()]
            for col in ['confidence_score', 'payout_percentage', 'expected_profit']:
                if col not in columns:
                    cursor.execute(f'ALTER TABLE trades ADD COLUMN {col} REAL')
            conn.commit()
        except Exception:
            pass
        
        conn.commit()
        conn.close()
    
    def save_trade(self, asset: str, direction: str, amount: float, duration: int,
                   order_id: str, signal_strength: float, confidence_score: float,
                   payout_percentage: Optional[float] = None):
        """Save a trade to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        expected_profit = amount * (payout_percentage / 100) if payout_percentage else None
        
        try:
            cursor.execute('''
                INSERT INTO trades (asset, direction, amount, duration, order_id,
                                  signal_strength, confidence_score, payout_percentage, expected_profit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (asset, direction, amount, duration, order_id, signal_strength, 
                  confidence_score, payout_percentage, expected_profit))
            conn.commit()
        except sqlite3.OperationalError:
            # Fallback if columns don't exist
            cursor.execute('''
                INSERT INTO trades (asset, direction, amount, duration, order_id, signal_strength, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (asset, direction, amount, duration, order_id, signal_strength, confidence_score))
            conn.commit()
        finally:
            conn.close()
    
    def update_trade_result(self, order_id: str, status: str, profit: float, win: bool):
        """Update trade result - uses OrderStatus as source of truth"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE trades SET status = ?, profit = ?, win = ?
            WHERE order_id = ?
        ''', (status, profit, 1 if win else 0, order_id))
        conn.commit()
        conn.close()
        
        return win
    
    def get_asset_stats(self, asset: str) -> Dict:
        """Get performance statistics for an asset"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN win = 0 THEN 1 ELSE 0 END) as losses,
                AVG(profit) as avg_profit,
                SUM(profit) as total_profit
            FROM trades
            WHERE asset = ? AND win IS NOT NULL
        ''', (asset,))
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0] > 0:
            return {
                "total_trades": row[0],
                "wins": row[1] or 0,
                "losses": row[2] or 0,
                "win_rate": (row[1] or 0) / row[0] if row[0] > 0 else 0.0,
                "avg_profit": row[3] or 0.0,
                "total_profit": row[4] or 0.0
            }
        return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.5, "avg_profit": 0.0, "total_profit": 0.0}
    


# ============================================================================
# TECHNICAL ANALYSIS ENGINE
# ============================================================================

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


# ============================================================================
# CONFIDENCE SCORING SYSTEM
# ============================================================================

class ConfidenceScorer:
    """
    Calculates confidence score (0-100) based on multiple technical indicators.
    
    SCORING BREAKDOWN:
    - Multi-timeframe trend alignment: 25 points
    - RSI extreme conditions: 20-25 points
    - Moving average alignment: 15 points
    - EMA crossover: 10 points
    - Trend strength (ADX): 10 points (or -5 if weak)
    - Momentum confirmation: 8-12 points
    - Volume confirmation: 5 points
    - Support/Resistance: 5 points
    - MACD confirmation: 5-8 points
    - Bollinger Bands: 3-7 points
    - Historical performance: -15 to +8 points
    """
    
    @staticmethod
    def calculate_confidence(candles_1m: List[Candle], candles_5m: List[Candle], 
                            asset_stats: Dict) -> Dict:
        """
        Calculate confidence score and determine signal direction.
        
        Returns:
            Dict with signal_direction, confidence_score, confidence_factors, and all indicators
        """
        if not candles_1m or len(candles_1m) < 30:
            return {"error": "Insufficient data"}
        
        closes_1m = [c.close for c in candles_1m]
        closes_5m = [c.close for c in candles_5m] if candles_5m and len(candles_5m) >= 10 else closes_1m
        
        # Calculate all indicators
        sma_9_1m = TechnicalAnalyzer.calculate_sma(closes_1m, 9)
        sma_21_1m = TechnicalAnalyzer.calculate_sma(closes_1m, 21)
        sma_50_1m = TechnicalAnalyzer.calculate_sma(closes_1m, 50) if len(closes_1m) >= 50 else sma_21_1m
        
        sma_9_5m = TechnicalAnalyzer.calculate_sma(closes_5m, 9) if len(closes_5m) >= 9 else sma_9_1m
        sma_21_5m = TechnicalAnalyzer.calculate_sma(closes_5m, 21) if len(closes_5m) >= 21 else sma_21_1m
        
        ema_12_1m = TechnicalAnalyzer.calculate_ema(closes_1m, 12)
        ema_26_1m = TechnicalAnalyzer.calculate_ema(closes_1m, 26)
        ema_12_5m = TechnicalAnalyzer.calculate_ema(closes_5m, 12) if len(closes_5m) >= 12 else ema_12_1m
        ema_26_5m = TechnicalAnalyzer.calculate_ema(closes_5m, 26) if len(closes_5m) >= 26 else ema_26_1m
        
        rsi_1m = TechnicalAnalyzer.calculate_rsi(closes_1m, 14)
        rsi_5m = TechnicalAnalyzer.calculate_rsi(closes_5m, 14) if len(closes_5m) >= 15 else rsi_1m
        
        adx = TechnicalAnalyzer.calculate_adx(candles_1m, 14)
        volume_profile = TechnicalAnalyzer.calculate_volume_profile(candles_1m)
        support_resistance = TechnicalAnalyzer.calculate_support_resistance(candles_1m)
        macd = TechnicalAnalyzer.calculate_macd(closes_1m)
        bollinger = TechnicalAnalyzer.calculate_bollinger_bands(closes_1m)
        
        current_price = closes_1m[-1]
        
        # Determine trends
        trend_1m = "bullish" if sma_9_1m > sma_21_1m else "bearish" if sma_9_1m < sma_21_1m else "neutral"
        trend_5m = "bullish" if sma_9_5m > sma_21_5m else "bearish" if sma_9_5m < sma_21_5m else "neutral"
        
        trend_strength_1m = abs(sma_9_1m - sma_21_1m) / current_price * 100 if current_price > 0 else 0
        trend_strength_5m = abs(sma_9_5m - sma_21_5m) / current_price * 100 if current_price > 0 else 0
        
        # Calculate momentum
        momentum_1m = closes_1m[-1] - closes_1m[-10] if len(closes_1m) >= 10 else 0
        momentum_5m = closes_5m[-1] - closes_5m[-5] if len(closes_5m) >= 5 else momentum_1m
        
        # Initialize scoring
        confidence_score = 0.0
        signal_direction = None
        confidence_factors = []
        
        # 1. Multi-timeframe trend alignment (25 points) - Require strong trend strength
        if trend_1m == trend_5m and trend_1m != "neutral":
            # Only give full points if trend is strong (not just aligned)
            trend_strength = min(trend_strength_1m, trend_strength_5m)
            if trend_strength > 0.15:  # Require at least 0.15% trend strength
                confidence_score += 25
                signal_direction = "CALL" if trend_1m == "bullish" else "PUT"
                confidence_factors.append(f"Strong {trend_1m} alignment (1m & 5m, strength: {trend_strength:.2f}%)")
            elif trend_strength > 0.05:
                confidence_score += 15  # Reduced points for weaker trends
                if signal_direction is None:
                    signal_direction = "CALL" if trend_1m == "bullish" else "PUT"
                confidence_factors.append(f"Moderate {trend_1m} alignment (1m & 5m, strength: {trend_strength:.2f}%)")
        
        # 2. RSI extreme conditions (20-25 points) - MUCH STRICTER thresholds
        if rsi_1m < 15 and rsi_5m < 20:  # Extremely oversold (stricter)
            confidence_score += 25
            if signal_direction != "PUT":
                signal_direction = "CALL"
            confidence_factors.append(f"RSI extremely oversold (1m: {rsi_1m:.1f}, 5m: {rsi_5m:.1f})")
        elif rsi_1m < 20 and rsi_5m < 25:  # Very oversold (stricter)
            confidence_score += 20
            if signal_direction != "PUT":
                signal_direction = "CALL"
            confidence_factors.append(f"RSI very oversold (1m: {rsi_1m:.1f}, 5m: {rsi_5m:.1f})")
        elif rsi_1m > 85 and rsi_5m > 80:  # Extremely overbought (stricter)
            confidence_score += 25
            if signal_direction != "CALL":
                signal_direction = "PUT"
            confidence_factors.append(f"RSI extremely overbought (1m: {rsi_1m:.1f}, 5m: {rsi_5m:.1f})")
        elif rsi_1m > 80 and rsi_5m > 75:  # Very overbought (stricter)
            confidence_score += 20
            if signal_direction != "CALL":
                signal_direction = "PUT"
            confidence_factors.append(f"RSI very overbought (1m: {rsi_1m:.1f}, 5m: {rsi_5m:.1f})")
        
        # 3. Moving average alignment (15 points)
        if sma_9_1m > sma_21_1m > sma_50_1m and current_price > sma_9_1m:
            confidence_score += 15
            if signal_direction is None:
                signal_direction = "CALL"
            confidence_factors.append("Perfect SMA alignment (bullish)")
        elif sma_9_1m < sma_21_1m < sma_50_1m and current_price < sma_9_1m:
            confidence_score += 15
            if signal_direction is None:
                signal_direction = "PUT"
            confidence_factors.append("Perfect SMA alignment (bearish)")
        
        # 4. EMA crossover (10 points)
        if ema_12_1m > ema_26_1m and ema_12_5m > ema_26_5m:
            confidence_score += 10
            if signal_direction != "PUT":
                signal_direction = "CALL"
            confidence_factors.append("EMA bullish crossover (both timeframes)")
        elif ema_12_1m < ema_26_1m and ema_12_5m < ema_26_5m:
            confidence_score += 10
            if signal_direction != "CALL":
                signal_direction = "PUT"
            confidence_factors.append("EMA bearish crossover (both timeframes)")
        
        # 5. Trend strength ADX (10 points or -5)
        if adx > 25:
            confidence_score += 10
            confidence_factors.append(f"Strong trend (ADX: {adx:.1f})")
        elif adx < 20:
            confidence_score -= 5
            confidence_factors.append(f"Weak trend (ADX: {adx:.1f})")
        
        # 6. Momentum confirmation (8-12 points)
        momentum_strength_1m = abs(momentum_1m) / current_price * 100 if current_price > 0 else 0
        momentum_strength_5m = abs(momentum_5m) / current_price * 100 if current_price > 0 else 0
        
        if momentum_1m > 0 and momentum_5m > 0 and signal_direction == "CALL":
            if momentum_strength_1m > 0.1 and momentum_strength_5m > 0.05:
                confidence_score += 12
                confidence_factors.append("Strong positive momentum (both timeframes)")
            else:
                confidence_score += 8
                confidence_factors.append("Positive momentum (both timeframes)")
        elif momentum_1m < 0 and momentum_5m < 0 and signal_direction == "PUT":
            if momentum_strength_1m > 0.1 and momentum_strength_5m > 0.05:
                confidence_score += 12
                confidence_factors.append("Strong negative momentum (both timeframes)")
            else:
                confidence_score += 8
                confidence_factors.append("Negative momentum (both timeframes)")
        
        # 7. Volume confirmation (5 points)
        if volume_profile["strength"] > 0 and signal_direction == "CALL":
            confidence_score += 5
            confidence_factors.append("Volume supports bullish move")
        elif volume_profile["strength"] < 0 and signal_direction == "PUT":
            confidence_score += 5
            confidence_factors.append("Volume supports bearish move")
        
        # 8. Support/Resistance (5 points)
        if signal_direction == "CALL" and support_resistance["distance_to_support"] < 1.0:
            confidence_score += 5
            confidence_factors.append("Near support level (bullish)")
        elif signal_direction == "PUT" and support_resistance["distance_to_resistance"] < 1.0:
            confidence_score += 5
            confidence_factors.append("Near resistance level (bearish)")
        
        # 9. MACD confirmation (5-8 points)
        if macd["histogram"] > 0 and signal_direction == "CALL":
            confidence_score += 8
            confidence_factors.append(f"MACD bullish (histogram: {macd['histogram']:.4f})")
        elif macd["histogram"] < 0 and signal_direction == "PUT":
            confidence_score += 8
            confidence_factors.append(f"MACD bearish (histogram: {macd['histogram']:.4f})")
        elif macd["macd"] > macd["signal"] and signal_direction == "CALL":
            confidence_score += 5
            confidence_factors.append("MACD line above signal (bullish)")
        elif macd["macd"] < macd["signal"] and signal_direction == "PUT":
            confidence_score += 5
            confidence_factors.append("MACD line below signal (bearish)")
        
        # 10. Bollinger Bands (3-7 points)
        if bollinger["position"] < 0.2 and signal_direction == "CALL":
            confidence_score += 7
            confidence_factors.append(f"Price near lower Bollinger Band (position: {bollinger['position']:.2f})")
        elif bollinger["position"] > 0.8 and signal_direction == "PUT":
            confidence_score += 7
            confidence_factors.append(f"Price near upper Bollinger Band (position: {bollinger['position']:.2f})")
        elif bollinger["width"] > 2.0:
            confidence_score += 3
            confidence_factors.append(f"High volatility (BB width: {bollinger['width']:.2f}%)")
        
        # 11. Historical performance (-10 to +10 points) - MODIFIER, not blocker
        # Prioritize current candle analysis, but adjust confidence based on history
        historical_modifier = 0
        
        if asset_stats and asset_stats.get("total_trades", 0) >= 5:
            win_rate = asset_stats.get("win_rate", 0.5)
            total_profit = asset_stats.get("total_profit", 0.0)
            
            # Positive modifiers for good history
            if win_rate > 0.70 and total_profit > 0:
                historical_modifier += 10
                confidence_factors.append(f"Excellent asset history ({win_rate:.1%} win rate, +${total_profit:.2f})")
            elif win_rate > 0.60 and total_profit > 0:
                historical_modifier += 6
                confidence_factors.append(f"Good asset history ({win_rate:.1%} win rate, +${total_profit:.2f})")
            elif win_rate > 0.50:
                historical_modifier += 3
                confidence_factors.append(f"Decent asset history ({win_rate:.1%} win rate)")
            # Negative modifiers for poor history (but don't block unless <30%)
            elif win_rate < 0.35:
                historical_modifier -= 10
                confidence_factors.append(f"Poor asset history ({win_rate:.1%} win rate) - reducing confidence")
            elif win_rate < 0.45:
                historical_modifier -= 5
                confidence_factors.append(f"Weak asset history ({win_rate:.1%} win rate) - reducing confidence")
            elif total_profit < -100:
                historical_modifier -= 8
                confidence_factors.append(f"Asset has losses (${total_profit:.2f}) - reducing confidence")
        
        confidence_score += historical_modifier
        
        # Ensure confidence is between 0-100
        confidence_score = max(0, min(100, confidence_score))
        
        # Calculate volatility for position sizing
        volatility = calculate_volatility(closes_1m) if closes_1m else 0.0
        
        return {
            "signal_direction": signal_direction,
            "confidence_score": confidence_score,
            "confidence_factors": confidence_factors,
            "rsi_1m": rsi_1m,
            "rsi_5m": rsi_5m,
            "adx": adx,
            "trend_1m": trend_1m,
            "trend_5m": trend_5m,
            "trend_strength_1m": trend_strength_1m,
            "trend_strength_5m": trend_strength_5m,
            "momentum_1m": momentum_1m,
            "momentum_5m": momentum_5m,
            "volume_profile": volume_profile,
            "support_resistance": support_resistance,
            "macd": macd,
            "bollinger": bollinger,
            "volatility": volatility,
            "current_price": current_price
        }


# ============================================================================
# RISK MANAGEMENT
# ============================================================================

class RiskManager:
    """Risk management and position sizing"""
    
    @staticmethod
    def calculate_position_size(confidence_score: float, current_balance: float,
                               volatility: float = 0.0, inner_confidence: Optional[float] = None,
                               asset_stats: Optional[Dict] = None) -> float:
        """
        Calculate position size with risk management.
        
        Formula:
        - Base: 8% (90% confidence) to 10% (100% confidence)
        - Volatility adjustment: Reduce by up to 50% in high volatility
        - Historical performance modifier: Reduce size for poor performers
        - Maximum: 10% of balance
        
        Args:
            confidence_score: Confidence score (92-100)
            current_balance: Current account balance
            volatility: Price volatility (0-1 range)
            inner_confidence: Inner confidence for OTC assets
            asset_stats: Historical performance stats (optional)
        
        Returns:
            Position size in dollars
        """
        if confidence_score < TradingConfig.MIN_CONFIDENCE:
            return 0.0
        
        # Base percentage: scale from MIN to MAX based on confidence
        # Scales from 85% to 100% confidence
        confidence_range = 100 - TradingConfig.MIN_CONFIDENCE
        confidence_ratio = (confidence_score - TradingConfig.MIN_CONFIDENCE) / confidence_range
        confidence_ratio = max(0, min(1, confidence_ratio))  # Clamp to 0-1
        base_percentage = TradingConfig.MIN_POSITION_PCT + (
            confidence_ratio * (TradingConfig.MAX_POSITION_PCT - TradingConfig.MIN_POSITION_PCT)
        )
        
        # Inner confidence boost (only if very high)
        if inner_confidence is not None and inner_confidence >= 90:
            inner_boost = ((inner_confidence - 90) / 10) * 0.002  # 0 to 0.2%
            base_percentage += inner_boost
        
        # Volatility reduction (aggressive)
        if volatility > 0:
            volatility_factor = max(0.5, 1.0 - (volatility * 15))  # Up to 50% reduction
            base_percentage *= volatility_factor
        
        # Historical performance modifier (reduce size for poor performers, but don't block)
        if asset_stats and asset_stats.get("total_trades", 0) >= 3:
            win_rate = asset_stats.get("win_rate", 0.5)
            total_profit = asset_stats.get("total_profit", 0.0)
            
            # Reduce position size for poor historical performance
            if win_rate < 0.40:
                historical_factor = 0.5  # Reduce by 50% if win rate < 40%
                base_percentage *= historical_factor
            elif win_rate < 0.50:
                historical_factor = 0.7  # Reduce by 30% if win rate < 50%
                base_percentage *= historical_factor
            elif win_rate > 0.65 and total_profit > 0:
                historical_factor = 1.1  # Increase by 10% for excellent history
                base_percentage *= min(historical_factor, 1.0)  # Cap at 1.0 to respect max limits
        
        # Calculate final amount
        amount = current_balance * base_percentage
        
        # Enforce limits (max 10% of balance per trade)
        amount = max(1.0, min(amount, current_balance * TradingConfig.MAX_POSITION_PCT))
        
        return round(amount, 2)
    
    
    @staticmethod
    def validate_entry_opportunity(opportunity: Dict, asset_stats: Dict,
                                  categories_used: set, assets_by_category: Optional[Dict] = None,
                                  asset_performance: Optional[Dict] = None) -> Tuple[bool, str]:
        """
        Validate if an opportunity meets all entry criteria.
        
        Returns:
            (is_valid, reason)
        """
        asset = opportunity.get("asset", "")
        confidence = opportunity.get("confidence_score", 0)
        factors = opportunity.get("confidence_factors", [])
        trend_1m = opportunity.get("trend_1m", "neutral")
        trend_5m = opportunity.get("trend_5m", "neutral")
        adx = opportunity.get("adx", 0)
        
        # Check 1: Confidence threshold
        if confidence < TradingConfig.MIN_CONFIDENCE:
            return False, f"Confidence {confidence:.1f}% below {TradingConfig.MIN_CONFIDENCE}%"
        
        # Check 2: Minimum factors
        if len(factors) < TradingConfig.MIN_CONFIDENCE_FACTORS:
            return False, f"Only {len(factors)} factors (need {TradingConfig.MIN_CONFIDENCE_FACTORS})"
        
        # Check 3: Trend alignment (STRICT - both must be aligned)
        if trend_1m == "neutral" or trend_5m == "neutral":
            return False, "Neutral trend detected - both timeframes must be bullish or bearish"
        if trend_1m != trend_5m:
            return False, f"Trend mismatch: 1m={trend_1m}, 5m={trend_5m} - must align"
        
        # Check 4: ADX threshold (STRICT - must have strong trend)
        if adx < TradingConfig.MIN_ADX:
            return False, f"ADX {adx:.1f} below {TradingConfig.MIN_ADX} - weak trend"
        
        # Check 5: Historical performance - SOFT FILTER (only block very poor performers)
        # We prioritize current candle analysis, but use history as a modifier
        # Only hard-block assets with extremely poor performance
        
        # Check database stats - only block if very poor (<30% win rate)
        if asset_stats.get("total_trades", 0) >= 5:
            win_rate = asset_stats.get("win_rate", 0.5)
            total_profit = asset_stats.get("total_profit", 0.0)
            # Only block if win rate is extremely low OR large losses
            if win_rate < TradingConfig.HISTORICAL_BLOCK_THRESHOLD:
                return False, f"Historical win rate {win_rate:.1%} extremely low (<{TradingConfig.HISTORICAL_BLOCK_THRESHOLD:.0%})"
            if total_profit < TradingConfig.HISTORICAL_LARGE_LOSS_THRESHOLD:
                return False, f"Historical losses too large: ${total_profit:.2f}"
        
        # Check Excel historical data - only block if very poor
        asset = opportunity.get('asset', '')
        if asset_performance and asset in asset_performance:
            perf = asset_performance[asset]
            if perf.get("total_trades", 0) >= 3:
                excel_win_rate = perf.get("win_rate", 0.5)
                excel_profit = perf.get("total_profit", 0.0)
                # Only block if extremely poor performance
                if excel_win_rate < TradingConfig.HISTORICAL_BLOCK_THRESHOLD:
                    return False, f"Excel data: win rate {excel_win_rate:.1%} extremely low (<{TradingConfig.HISTORICAL_BLOCK_THRESHOLD:.0%})"
                if excel_profit < TradingConfig.HISTORICAL_LARGE_LOSS_THRESHOLD:
                    return False, f"Excel data: large losses ${excel_profit:.2f} - too risky"
        
        # Historical data will be used as confidence/position size modifier (not a blocker)
        
        # Check 6: Category correlation
        if assets_by_category:
            category = RiskManager._get_asset_category(asset, assets_by_category)
            if category in categories_used:
                return False, f"Already trading in {category} category"
        
        return True, "Valid"
    
    @staticmethod
    def _get_asset_category(asset: str, assets_by_category: Dict) -> str:
        """Get category for an asset"""
        for category, assets in assets_by_category.items():
            if asset in assets:
                return category
        return "unknown"


# ============================================================================
# MAIN TRADING BOT
# ============================================================================

class DeepTradingBot:
    """
    Main trading bot implementing the strategy.
    
    WORKFLOW:
    1. Connect to PocketOption
    2. Analyze all assets with multi-timeframe analysis
    3. Filter opportunities through strict criteria
    4. Calculate position sizes with risk management
    5. Place trades on high-confidence setups
    6. Monitor positions and double down conservatively
    7. Check results and validate against balance
    """
    
    def __init__(self, ssid: str, is_demo: bool = True, 
                 telegram_bot_token: Optional[str] = None, 
                 telegram_channel_id: Optional[str] = None):
        self.ssid = ssid
        self.is_demo = is_demo
        self.client = None
        self.initial_balance = None
        self.db = TradeDatabase()
        self.active_positions = {}  # {asset: [position_info, ...]}
        self.asset_inner_confidence = {}  # Cache: {asset: confidence}
        self.asset_payout_percentages = {}  # Cache: {asset: payout%}
        self.historical_trades = {}  # Loaded from Excel
        self.asset_performance = {}  # Asset performance from historical data
        
        # Circuit breaker state
        self.consecutive_losses = 0
        self.losses_this_hour = []
        self.session_start_balance = None
        self.circuit_breaker_active = False
        self.circuit_breaker_until = None
        
        # Initialize Telegram
        self.telegram = None
        if telegram_bot_token and telegram_channel_id:
            try:
                self.telegram = TelegramNotifier(telegram_bot_token, telegram_channel_id)
                print("✅ Telegram notifier initialized")
            except Exception as e:
                print(f"⚠️ Failed to initialize Telegram: {e}")
        
        # Load historical trades
        self._load_historical_trades()
    
    def _load_historical_trades(self):
        """Load historical trades from Excel for validation and asset filtering"""
        try:
            df = pd.read_excel('export_history.xlsx')
            print(f"📊 Loaded {len(df)} historical trades from Excel")
            
            # Map columns (handling Russian column names)
            order_id_col = None
            profit_col = None
            asset_col = None
            direction_col = None
            
            for col in df.columns:
                col_lower = col.lower()
                if ('сделка' in col_lower or 'order' in col_lower or 'id' in col_lower or 'deal' in col_lower) and not order_id_col:
                    order_id_col = col
                if 'прибыль' in col_lower or ('profit' in col_lower and not profit_col):
                    profit_col = col
                if 'актив' in col_lower or 'asset' in col_lower:
                    asset_col = col
                if 'направление' in col_lower or 'direction' in col_lower:
                    direction_col = col
            
            # Calculate asset performance statistics
            if asset_col and profit_col:
                asset_performance = {}
                for asset in df[asset_col].unique():
                    asset_df = df[df[asset_col] == asset]
                    if len(asset_df) >= 3:  # Need at least 3 trades to evaluate
                        wins = (asset_df[profit_col] > 0).sum()
                        total = len(asset_df)
                        win_rate = wins / total if total > 0 else 0.0
                        total_profit = asset_df[profit_col].sum()
                        avg_profit = asset_df[profit_col].mean()
                        
                        asset_performance[asset] = {
                            "total_trades": total,
                            "wins": wins,
                            "losses": total - wins,
                            "win_rate": win_rate,
                            "total_profit": total_profit,
                            "avg_profit": avg_profit
                        }
                
                self.asset_performance = asset_performance
                print(f"✅ Analyzed {len(asset_performance)} assets from historical data")
                
                # Show worst performers
                worst = sorted(asset_performance.items(), key=lambda x: x[1]['total_profit'])[:5]
                if worst:
                    print(f"⚠️ Worst performing assets (will be filtered):")
                    for asset, stats in worst:
                        print(f"   {asset}: {stats['win_rate']:.1%} win rate, ${stats['total_profit']:.2f} total")
            
            # Map individual trades for validation
            if order_id_col and profit_col:
                for idx, row in df.iterrows():
                    order_id = str(row[order_id_col]) if order_id_col else None
                    profit = float(row[profit_col]) if pd.notna(row[profit_col]) else 0.0
                    if order_id:
                        self.historical_trades[order_id] = {
                            "profit": profit,
                            "win": profit > 0
                        }
            
            print(f"✅ Mapped {len(self.historical_trades)} trades for validation")
        except FileNotFoundError:
            print("⚠️ export_history.xlsx not found - validation limited")
            self.asset_performance = {}
        except Exception as e:
            print(f"⚠️ Error loading historical trades: {e}")
            self.asset_performance = {}
    
    async def connect(self):
        """Connect to PocketOption and set up event listeners"""
        self.client = AsyncPocketOptionClient(self.ssid, is_demo=self.is_demo, enable_logging=False)
        await self.client.connect()
        
        # Set up event listeners
        self.client.add_event_callback("payout_update", self._on_payout_update)
        self.client.add_event_callback("json_data", self._on_json_data)
        self.client.add_event_callback("stream_update", self._on_stream_update)
        
        print("⏳ Waiting for balance data...")
        await asyncio.sleep(3)
        
        balance = await self._get_balance_with_retry(max_retries=5, delay=2)
        self.initial_balance = balance.balance
        self.session_start_balance = balance.balance  # Track for drawdown calculation
        print(f"✅ Connected! Initial balance: ${balance.balance:.2f} {balance.currency}")
    
    async def _on_payout_update(self, data: Dict):
        """Handle payout update events"""
        try:
            asset_symbol = data.get("symbol", "")
            payout = data.get("payout")
            if asset_symbol and payout is not None:
                self.asset_payout_percentages[asset_symbol] = float(payout)
            
            confidence = data.get("confidence") or data.get("inner_confidence")
            if asset_symbol and confidence is not None:
                self.asset_inner_confidence[asset_symbol] = float(confidence)
        except Exception:
            pass
    
    async def _on_json_data(self, data: Dict):
        """Handle JSON data events"""
        try:
            if isinstance(data, dict):
                asset_symbol = data.get("asset") or data.get("symbol", "")
                confidence = data.get("confidence") or data.get("inner_confidence") or data.get("otc_confidence")
                if asset_symbol and confidence is not None:
                    self.asset_inner_confidence[asset_symbol] = float(confidence)
        except Exception:
            pass
    
    async def _on_stream_update(self, data: Dict):
        """Handle stream update events"""
        try:
            if isinstance(data, dict):
                asset_symbol = data.get("asset") or data.get("symbol", "")
                confidence = data.get("confidence") or data.get("inner_confidence")
                if asset_symbol and confidence is not None:
                    self.asset_inner_confidence[asset_symbol] = float(confidence)
        except Exception:
            pass
    
    async def disconnect(self):
        """Disconnect from PocketOption"""
        if self.client:
            await self.client.disconnect()
    
    async def _get_balance_with_retry(self, max_retries: int = 5, delay: float = 2.0) -> Balance:
        """Get balance with retry logic"""
        for attempt in range(max_retries):
            try:
                if not self.client.is_connected:
                    raise ConnectionError("Connection lost")
                balance = await self.client.get_balance()
                if balance:
                    return balance
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                    await self.client._request_balance_update()
                else:
                    raise
        raise Exception("Balance data not available")
    
    async def get_asset_inner_confidence(self, asset: str) -> Optional[float]:
        """Get inner confidence for OTC assets"""
        try:
            if asset in self.asset_inner_confidence:
                return self.asset_inner_confidence[asset]
            
            if "_otc" in asset.lower():
                message1 = f'42["getAssetInfo",{{"asset":"{asset}"}}]'
                message2 = f'42["getOTCConfidence",{{"asset":"{asset}"}}]'
                await self.client.send_message(message1)
                await self.client.send_message(message2)
                await asyncio.sleep(0.8)
                
                if asset in self.asset_inner_confidence:
                    return self.asset_inner_confidence[asset]
            
            return None
        except Exception:
            return None
    
    async def analyze_asset(self, asset: str) -> Dict:
        """Analyze a single asset with multi-timeframe analysis"""
        try:
            # Get inner confidence for OTC assets
            inner_confidence = None
            if "_otc" in asset.lower():
                inner_confidence = await self.get_asset_inner_confidence(asset)
            
            # Get candle data
            candles_1m = await self.client.get_candles(asset=asset, timeframe=60, count=100)
            candles_5m = await self.client.get_candles(asset=asset, timeframe=300, count=50)
            
            if not candles_1m or len(candles_1m) < 30:
                return {"error": "Insufficient data", "asset": asset}
            
            # Get historical stats
            asset_stats = self.db.get_asset_stats(asset)
            
            # Calculate confidence
            analysis = ConfidenceScorer.calculate_confidence(candles_1m, candles_5m, asset_stats)
            analysis["asset"] = asset
            analysis["inner_confidence"] = inner_confidence
            
            return analysis
        except Exception as e:
            return {"error": str(e), "asset": asset}
    
    async def find_trading_opportunities(self, assets: List[str], 
                                        assets_by_category: Optional[Dict] = None) -> List[Dict]:
        """
        Find and filter trading opportunities.
        
        PROCESS:
        1. Analyze all assets in parallel
        2. Filter by confidence threshold
        3. Apply strict quality filters
        4. Limit by position count and category correlation
        
        Returns:
            List of validated opportunities
        """
        print(f"📊 Analyzing {len(assets)} assets...")
        
        # Analyze all assets in parallel
        tasks = [self.analyze_asset(asset) for asset in assets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Initial filtering with detailed logging
        candidates = []
        rejected_count = 0
        rejection_reasons = {}
        
        for result in results:
            if isinstance(result, Exception) or "error" in result:
                rejected_count += 1
                continue
            
            asset = result.get("asset", "")
            confidence = result.get("confidence_score", 0)
            direction = result.get("signal_direction")
            inner_confidence = result.get("inner_confidence")
            
            # OTC inner confidence check (relaxed - only reject if explicitly low)
            if "_otc" in asset.lower():
                if inner_confidence is not None and inner_confidence < TradingConfig.MIN_OTC_INNER_CONFIDENCE:
                    rejected_count += 1
                    reason = f"Inner confidence {inner_confidence:.1f}% < {TradingConfig.MIN_OTC_INNER_CONFIDENCE}%"
                    rejection_reasons[asset] = reason
                    continue
                elif inner_confidence is None:
                    # Try to get it, but don't reject if unavailable
                    inner_confidence = await self.get_asset_inner_confidence(asset)
                    if inner_confidence is not None and inner_confidence < TradingConfig.MIN_OTC_INNER_CONFIDENCE:
                        rejected_count += 1
                        reason = f"Inner confidence {inner_confidence:.1f}% < {TradingConfig.MIN_OTC_INNER_CONFIDENCE}%"
                        rejection_reasons[asset] = reason
                        continue
            
            # Store payout if available
            payout = self.asset_payout_percentages.get(asset)
            if payout:
                result["payout_percentage"] = payout
            
            # Check basic requirements
            if not direction:
                rejected_count += 1
                rejection_reasons[asset] = "No signal direction"
                continue
            
            if confidence < TradingConfig.MIN_CONFIDENCE:
                rejected_count += 1
                rejection_reasons[asset] = f"Confidence {confidence:.1f}% < {TradingConfig.MIN_CONFIDENCE}%"
                continue
            
            candidates.append(result)
        
        # Log rejection summary
        if rejected_count > 0:
            print(f"📊 Analysis complete: {len(candidates)} candidates, {rejected_count} rejected")
            if len(candidates) == 0 and rejected_count > 0:
                print(f"⚠️ Top rejection reasons:")
                # Show top 5 most common reasons
                reason_counts = {}
                for reason in rejection_reasons.values():
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                    print(f"   - {reason}: {count} assets")
        
        if not candidates:
            print(f"⚠️ No assets meet confidence threshold ({TradingConfig.MIN_CONFIDENCE}%+)")
            return []
        
        # Sort by confidence
        candidates.sort(key=lambda x: x.get("confidence_score", 0), reverse=True)
        
        # Apply filters with detailed logging
        validated = []
        categories_used = set()
        filter_rejections = {}
        
        print(f"\n🔍 Validating {len(candidates)} candidates...")
        
        for opp in candidates:
            asset = opp.get("asset", "")
            asset_stats = self.db.get_asset_stats(asset)
            
            # Validate entry criteria
            is_valid, reason = RiskManager.validate_entry_opportunity(
                opp, asset_stats, categories_used, assets_by_category, self.asset_performance
            )
            
            if not is_valid:
                filter_rejections[asset] = reason
                continue
            
            validated.append(opp)
            if assets_by_category:
                category = RiskManager._get_asset_category(asset, assets_by_category)
                categories_used.add(category)
            
            # Log successful validation
            confidence = opp.get("confidence_score", 0)
            direction = opp.get("signal_direction", "")
            factors_count = len(opp.get("confidence_factors", []))
            print(f"   ✅ {asset}: {direction} - {confidence:.1f}% confidence ({factors_count} factors)")
            
            # Limit positions per cycle
            if len(validated) >= TradingConfig.MAX_POSITIONS_PER_CYCLE:
                print(f"   ⏸️  Reached max positions per cycle ({TradingConfig.MAX_POSITIONS_PER_CYCLE})")
                break
        
        # Log filter rejections
        if filter_rejections and len(validated) == 0:
            print(f"\n⚠️ All candidates filtered out. Top rejection reasons:")
            reason_counts = {}
            for reason in filter_rejections.values():
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"   - {reason}: {count} assets")
        
        return validated
    
    def check_circuit_breaker(self) -> Tuple[bool, str]:
        """Check if circuit breaker should stop trading"""
        if not TradingConfig.ENABLE_CIRCUIT_BREAKER:
            return True, "Circuit breaker disabled"
        
        # Check if circuit breaker is in cooldown
        if self.circuit_breaker_active and self.circuit_breaker_until:
            if datetime.now() < self.circuit_breaker_until:
                remaining = (self.circuit_breaker_until - datetime.now()).total_seconds() / 60
                return False, f"Circuit breaker active - {remaining:.1f} minutes remaining"
            else:
                # Cooldown expired, reset
                self.circuit_breaker_active = False
                self.circuit_breaker_until = None
                self.consecutive_losses = 0
                print("✅ Circuit breaker cooldown expired - resuming trading")
        
        # Check consecutive losses
        if self.consecutive_losses >= TradingConfig.MAX_CONSECUTIVE_LOSSES:
            self.circuit_breaker_active = True
            self.circuit_breaker_until = datetime.now() + timedelta(minutes=TradingConfig.CIRCUIT_BREAKER_COOLDOWN_MINUTES)
            return False, f"Circuit breaker: {self.consecutive_losses} consecutive losses (max: {TradingConfig.MAX_CONSECUTIVE_LOSSES})"
        
        # Check losses per hour
        now = datetime.now()
        self.losses_this_hour = [loss_time for loss_time in self.losses_this_hour 
                                 if (now - loss_time).total_seconds() < 3600]
        if len(self.losses_this_hour) >= TradingConfig.MAX_LOSSES_PER_HOUR:
            self.circuit_breaker_active = True
            self.circuit_breaker_until = datetime.now() + timedelta(minutes=TradingConfig.CIRCUIT_BREAKER_COOLDOWN_MINUTES)
            return False, f"Circuit breaker: {len(self.losses_this_hour)} losses in last hour (max: {TradingConfig.MAX_LOSSES_PER_HOUR})"
        
        # Drawdown check will be done in async context when we have balance
        
        return True, "OK"
    
    async def place_trades(self, opportunities: List[Dict], 
                          assets_by_category: Optional[Dict] = None) -> Dict:
        """
        Place trades on validated opportunities.
        
        PROCESS:
        1. Check circuit breakers
        2. Check exposure limits
        3. Calculate position sizes
        4. Place orders
        5. Track positions
        
        Returns:
            Dict with invested amount and positions created
        """
        if not opportunities:
            print(f"⚠️ Нет возможностей для торговли - все активы отфильтрованы")
            return {"invested": 0, "positions": []}
        
        # Check circuit breaker
        can_trade, reason = self.check_circuit_breaker()
        if not can_trade:
            print(f"🛑 {reason}")
            return {"invested": 0, "positions": []}
        
        print(f"\n💰 Подготовка к размещению {len(opportunities)} сделок...")
        
        # Get current balance
        try:
            balance = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            current_balance = balance.balance
            print(f"   💵 Текущий баланс: ${current_balance:.2f}")
            
            # Check drawdown
            if self.session_start_balance and TradingConfig.ENABLE_CIRCUIT_BREAKER:
                drawdown = (self.session_start_balance - current_balance) / self.session_start_balance
                if drawdown >= TradingConfig.MAX_DRAWDOWN_PCT:
                    self.circuit_breaker_active = True
                    self.circuit_breaker_until = datetime.now() + timedelta(minutes=TradingConfig.CIRCUIT_BREAKER_COOLDOWN_MINUTES)
                    print(f"🛑 Circuit breaker: {drawdown:.1%} drawdown (max: {TradingConfig.MAX_DRAWDOWN_PCT:.1%})")
                    return {"invested": 0, "positions": []}
        except:
            current_balance = self.initial_balance if self.initial_balance else 1000.0
            print(f"   ⚠️ Не удалось получить баланс, используем: ${current_balance:.2f}")
        
        # Check total exposure
        total_exposure = sum(
            pos.get("amount", 0)
            for positions in self.active_positions.values()
            for pos in positions
        )
        
        # Place trades
        positions_created = []
        total_invested = 0.0
        
        print(f"\n✅ Найдено {len(opportunities)} проверенных возможностей:")
        for opp in opportunities:
            print(f"   {opp['asset']}: {opp['signal_direction']} - {opp['confidence_score']:.1f}% уверенность")
            print(f"      Факторы: {', '.join(opp['confidence_factors'][:2])}")
        
        for opp in opportunities:
            # Check exposure limit
            if (total_invested + total_exposure) / current_balance > TradingConfig.MAX_TOTAL_EXPOSURE_PCT:
                print(f"⚠️ Reached maximum exposure limit ({TradingConfig.MAX_TOTAL_EXPOSURE_PCT*100:.1f}%)")
                break
            
            try:
                # Use analysis direction directly (reverted from inverted logic)
                signal_direction = opp["signal_direction"]
                direction = OrderDirection.CALL if signal_direction == "CALL" else OrderDirection.PUT
                
                # Calculate position size (with historical data modifier)
                asset_stats = self.db.get_asset_stats(opp["asset"])
                amount = RiskManager.calculate_position_size(
                    opp["confidence_score"],
                    current_balance,
                    volatility=opp.get("volatility", 0.0),
                    inner_confidence=opp.get("inner_confidence"),
                    asset_stats=asset_stats
                )
                
                if amount <= 0:
                    continue
                
                # Place order
                order = await self.client.place_order(
                    asset=opp["asset"],
                    amount=amount,
                    direction=direction,
                    duration=300  # 5 minutes
                )
                
                # Save to database
                payout = opp.get("payout_percentage") or self.asset_payout_percentages.get(opp["asset"])
                self.db.save_trade(
                    asset=opp["asset"],
                    direction=signal_direction,
                    amount=amount,
                    duration=300,
                    order_id=order.order_id,
                    signal_strength=opp["confidence_score"],
                    confidence_score=opp["confidence_score"],
                    payout_percentage=payout
                )
                
                # Track position
                if opp["asset"] not in self.active_positions:
                    self.active_positions[opp["asset"]] = []
                
                self.active_positions[opp["asset"]].append({
                    "order": order,
                    "analysis": opp,
                    "direction": direction,
                    "amount": amount,
                    "timestamp": datetime.now()
                })
                
                position_data = {
                    "asset": opp["asset"],
                    "direction": signal_direction,
                    "amount": amount,
                    "confidence": opp["confidence_score"],
                    "order_id": order.order_id,
                    "analysis": opp
                }
                positions_created.append(position_data)
                total_invested += amount
                
                # Log
                pct = (amount / current_balance * 100) if current_balance > 0 else 0
                print(f"💰 {opp['asset']}: ${amount:.2f} {signal_direction} ({pct:.2f}% of balance)")
                print(f"   📊 Confidence: {opp['confidence_score']:.1f}% | Top factors: {', '.join(opp['confidence_factors'][:2])}")
                
                # Telegram notification
                if self.telegram:
                    try:
                        await self.telegram.send_position_signal(position_data, current_balance)
                    except Exception as e:
                        print(f"⚠️ Telegram error: {e}")
                
            except Exception as e:
                print(f"❌ {opp['asset']}: Failed to invest - {e}")
        
        print(f"\n💵 Total invested: ${total_invested:.2f}")
        return {"invested": total_invested, "positions": positions_created}
    
    async def double_down_analysis(self) -> Dict:
        """
        Double down analysis - DISABLED by default to prevent compounding losses.
        
        This feature is disabled in TradingConfig.ENABLE_DOUBLE_DOWN = False
        to prevent the strategy from compounding losses which led to the 4k loss.
        """
        if not TradingConfig.ENABLE_DOUBLE_DOWN:
            return {"doubled_down": 0, "additional": 0}
        
        print(f"\n{'='*70}")
        print(f"📈 DOUBLE-DOWN ANALYSIS (DISABLED)")
        print(f"{'='*70}\n")
        
        doubled_down = []
        total_additional = 0.0
        
        # Get current balance
        try:
            balance = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            current_balance = balance.balance
        except:
            current_balance = self.initial_balance if self.initial_balance else 1000.0
        
        for asset, positions in self.active_positions.items():
            if not positions:
                continue
            
            # Find losing positions
            losing_positions = []
            for idx, position in enumerate(positions):
                try:
                    result = await self.client.check_order_result(position["order"].order_id)
                    if not result:
                        continue
                    
                    profit = result.profit if result.profit is not None else 0.0
                    time_remaining = (result.expires_at - datetime.now()).total_seconds()
                    
                    if profit < 0 and time_remaining > TradingConfig.MIN_TIME_REMAINING_DD:
                        losing_positions.append({
                            "index": idx,
                            "position": position,
                            "profit": profit,
                            "time_remaining": time_remaining,
                            "result": result
                        })
                except Exception:
                    continue
            
            if not losing_positions:
                continue
            
            # Target most recent losing position
            losing_positions.sort(key=lambda x: (x["index"], x["profit"]))
            target = losing_positions[-1]
            
            pos_info = target["position"]
            current_profit = target["profit"]
            time_remaining = target["time_remaining"]
            
            print(f"🔍 {asset}: Found losing position (${current_profit:.2f})")
            
            # Validation checks
            original_direction = pos_info["direction"]
            
            # Check 1: Max positions per asset
            if len(positions) >= TradingConfig.MAX_POSITIONS_PER_ASSET:
                print(f"⏭️ {asset}: Max positions ({TradingConfig.MAX_POSITIONS_PER_ASSET}) reached")
                continue
            
            # Check 2: Max exposure per asset
            total_exposure_asset = sum(p["amount"] for p in positions)
            max_exposure_asset = current_balance * TradingConfig.MAX_EXPOSURE_PER_ASSET_PCT
            if total_exposure_asset >= max_exposure_asset:
                print(f"⏭️ {asset}: Max exposure per asset reached")
                continue
            
            # Check 3: Calculate double down amount (1.5x conservative)
            last_amount = positions[-1]["amount"]
            double_amount = last_amount * TradingConfig.DOUBLE_DOWN_MULTIPLIER
            
            # Check 4: Re-analyze for volatility
            analysis = await self.analyze_asset(asset)
            if "error" in analysis:
                continue
            
            volatility = analysis.get("volatility", 0.0)
            if volatility > TradingConfig.HIGH_VOLATILITY_THRESHOLD:
                double_amount *= 0.7  # Reduce by 30%
                print(f"   ⚠️ High volatility ({volatility:.4f}), reducing by 30%")
            
            # Check 5: Total exposure limit
            new_total_exposure = total_exposure_asset + double_amount
            max_total = current_balance * TradingConfig.MAX_TOTAL_EXPOSURE_AFTER_DD_PCT
            if new_total_exposure > max_total:
                double_amount = max(1.0, max_total - total_exposure_asset)
                print(f"   ⚠️ Adjusted to ${double_amount:.2f} to stay within limit")
            
            # Check 6: Minimum amount
            if double_amount < 1.0:
                continue
            
            # All checks passed - place double down in same direction
            try:
                order = await self.client.place_order(
                    asset=asset,
                    amount=double_amount,
                    direction=original_direction,  # Same direction as original
                    duration=300
                )
                
                payout = self.asset_payout_percentages.get(asset)
                original_direction_str = pos_info["analysis"]["signal_direction"]
                
                self.db.save_trade(
                    asset=asset,
                    direction=original_direction_str,
                    amount=double_amount,
                    duration=300,
                    order_id=order.order_id,
                    signal_strength=analysis.get("confidence_score", 0),
                    confidence_score=analysis.get("confidence_score", 0),
                    payout_percentage=payout
                )
                
                positions.append({
                    "order": order,
                    "analysis": analysis,
                    "direction": original_direction,
                    "amount": double_amount,
                    "timestamp": datetime.now()
                })
                
                doubled_down.append({
                    "asset": asset,
                    "direction": original_direction_str,
                    "amount": double_amount,
                    "original_profit": current_profit,
                    "position_number": len(positions)
                })
                total_additional += double_amount
                
                print(f"📉 {asset}: DOUBLED DOWN ${double_amount:.2f} (Position #{len(positions)})")
                
                # Telegram notification
                if self.telegram:
                    try:
                        await self.telegram.send_double_down_signal({
                            "asset": asset,
                            "direction": original_direction_str,
                            "amount": double_amount,
                            "original_profit": current_profit,
                            "position_number": len(positions)
                        }, current_balance)
                    except Exception:
                        pass
                
            except Exception as e:
                print(f"❌ {asset}: Failed to double down - {e}")
        
        if doubled_down:
            print(f"\n💵 Additional invested: ${total_additional:.2f}")
        else:
            print("⚠️ No positions qualified for doubling down")
        
        return {"doubled_down": len(doubled_down), "additional": total_additional}
    
    async def check_all_positions(self) -> Dict:
        """
        Check results of all active positions.
        
        Uses OrderStatus as source of truth for win/loss determination.
        """
        print(f"\n{'='*70}")
        print(f"📊 FINAL RESULTS")
        print(f"{'='*70}\n")
        
        # Get balance before for validation
        balance_before = None
        try:
            balance_before = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            balance_before_value = balance_before.balance
        except:
            balance_before_value = None
        
        total_profit = 0.0
        wins = 0
        losses = 0
        
        for asset, positions in self.active_positions.items():
            for pos_info in positions:
                order = pos_info["order"]
                
                # Check result with retries
                result = None
                for attempt in range(10):
                    result = await self.client.check_order_result(order.order_id)
                    if result and result.status in [OrderStatus.WIN, OrderStatus.LOSE, OrderStatus.CLOSED]:
                        break
                    await asyncio.sleep(2)
                
                if result:
                    # Get profit - this is the REAL source of truth
                    profit = result.profit if result.profit is not None else 0.0
                    
                    # Determine win/loss based on ACTUAL profit value
                    # Profit > 0 = WIN, Profit < 0 = LOSS, Profit = 0 = check status
                    if profit > 0:
                        final_win = True
                    elif profit < 0:
                        final_win = False
                    else:
                        # If profit is exactly 0, use OrderStatus as fallback
                        final_win = result.status == OrderStatus.WIN
                    
                    # Log for debugging
                    status_str = result.status.value if result.status else "UNKNOWN"
                    print(f"   🔍 Debug: Status={status_str}, Profit=${profit:.2f}, Determined={'WIN' if final_win else 'LOSS'}")
                    
                    # Update database
                    self.db.update_trade_result(
                        order.order_id,
                        result.status.value,
                        profit,
                        final_win
                    )
                    
                    # Count
                    if final_win:
                        wins += 1
                        self.consecutive_losses = 0  # Reset consecutive losses on win
                    else:
                        losses += 1
                        self.consecutive_losses += 1  # Track consecutive losses
                        self.losses_this_hour.append(datetime.now())  # Track for hourly limit
                    
                    total_profit += profit
                    
                    # Display
                    emoji = "🎉" if final_win else "❌"
                    result_text = "WIN" if final_win else "LOSS"
                    print(f"{emoji} {asset}: {result_text} ${profit:+.2f} (${pos_info['amount']:.2f} invested)")
                    
                    if pos_info['amount'] > 0:
                        roi = (profit / pos_info['amount'] * 100)
                        print(f"   💰 ROI: {roi:+.1f}%")
                    
                    # Telegram notification
                    if self.telegram:
                        try:
                            await self.telegram.send_result_signal({
                                "asset": asset,
                                "win": final_win,
                                "profit": profit,
                                "amount": pos_info['amount'],
                                "direction": pos_info['direction'].value if hasattr(pos_info['direction'], 'value') else str(pos_info['direction'])
                            })
                        except Exception:
                            pass
        
        # Validate against balance
        if balance_before_value is not None:
            try:
                await asyncio.sleep(2)
                balance_after = await self._get_balance_with_retry(max_retries=3, delay=1.0)
                balance_change = balance_after.balance - balance_before_value
                
                if abs(total_profit - balance_change) > 0.01:
                    print(f"\n⚠️ VALIDATION: Calculated ${total_profit:.2f} vs Balance ${balance_change:.2f}")
                else:
                    print(f"\n✅ Balance validated: Profit matches balance change")
            except Exception:
                pass
        
        return {
            "total_profit": total_profit,
            "wins": wins,
            "losses": losses,
            "total_trades": wins + losses
        }
    
    async def run_cycle(self, assets: List[str], assets_by_category: Optional[Dict] = None, 
                       cycle_num: int = 1) -> Dict:
        """
        Run a single 5-minute trading cycle.
        
        PHASES:
        1. Find and validate opportunities (first 40 seconds)
        2. Place trades
        3. Monitor and double down (until 1m40s remaining)
        4. Wait for completion (1m40s)
        5. Check results
        """
        cycle_start_balance = None
        try:
            balance = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            cycle_start_balance = balance.balance
        except:
            cycle_start_balance = self.initial_balance
        
        print(f"\n{'='*70}")
        print(f"🚀 CYCLE {cycle_num} - 5-MINUTE SESSION")
        print(f"{'='*70}")
        print(f"💰 Start Balance: ${cycle_start_balance:.2f}")
        print(f"🎯 Strategy: Strict (85%+ confidence, 1%-4% position size, 4+ factors required)")
        print(f"{'='*70}\n")
        
        # Phase 1: Find opportunities and place trades
        opportunities = await self.find_trading_opportunities(assets, assets_by_category)
        trade_result = await self.place_trades(opportunities, assets_by_category)
        
        if trade_result["invested"] == 0:
            print("⚠️ No trades placed this cycle")
            return {"profit": 0, "wins": 0, "losses": 0, "trades": 0}
        
        # Phase 2: Monitor and double down
        session_duration = timedelta(minutes=TradingConfig.CYCLE_DURATION_MINUTES)
        session_start = datetime.now()
        check_interval = TradingConfig.CHECK_INTERVAL_SECONDS
        
        elapsed = (datetime.now() - session_start).total_seconds()
        stop_time = session_duration.total_seconds() - 100  # Stop 1m40s before end
        
        while elapsed < stop_time:
            await asyncio.sleep(check_interval)
            elapsed = (datetime.now() - session_start).total_seconds()
            remaining = (session_duration.total_seconds() - elapsed) / 60
            print(f"\n⏰ {remaining:.1f} minutes remaining...")
            await self.double_down_analysis()
        
        # Phase 3: Wait for completion
        print(f"\n⏳ Waiting for positions to complete...")
        await asyncio.sleep(100)
        
        # Phase 4: Check results
        results = await self.check_all_positions()
        self.active_positions.clear()
        
        # Final summary
        try:
            balance = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            cycle_end_balance = balance.balance
            cycle_profit = cycle_end_balance - cycle_start_balance
        except:
            cycle_profit = results["total_profit"]
            cycle_end_balance = cycle_start_balance + cycle_profit
        
        print(f"\n{'='*70}")
        print(f"📊 CYCLE {cycle_num} SUMMARY")
        print(f"{'='*70}")
        print(f"💰 Start: ${cycle_start_balance:.2f} | End: ${cycle_end_balance:.2f}")
        print(f"💰 Profit: ${cycle_profit:+.2f}")
        print(f"📈 Wins: {results['wins']} | Losses: {results['losses']}")
        print(f"📊 Win Rate: {(results['wins'] / results['total_trades'] * 100) if results['total_trades'] > 0 else 0:.1f}%")
        print(f"{'='*70}\n")
        
        # Telegram summary
        if self.telegram:
            try:
                await self.telegram.send_summary_signal({
                    "cycle_num": cycle_num,
                    "profit": cycle_profit,
                    "wins": results["wins"],
                    "losses": results["losses"],
                    "trades": results["total_trades"],
                    "start_balance": cycle_start_balance,
                    "end_balance": cycle_end_balance
                })
            except Exception:
                pass
        
        return {
            "profit": cycle_profit,
            "wins": results["wins"],
            "losses": results["losses"],
            "trades": results["total_trades"]
        }
    
    async def run_session(self, assets: List[str], assets_by_category: Optional[Dict] = None):
        """Run indefinitely with multiple 5-minute cycles until interrupted"""
        session_start = datetime.now()
        
        print(f"\n{'='*70}")
        print(f"🚀 STARTING INDEFINITE TRADING SESSION")
        print(f"{'='*70}")
        print(f"⏰ Start: {session_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"⏰ Duration: Running indefinitely until stopped")
        print(f"🔄 Cycle Duration: {TradingConfig.CYCLE_DURATION_MINUTES} minutes each")
        print(f"💰 Initial Balance: ${self.initial_balance:.2f}")
        print(f"{'='*70}\n")
        
        total_profit = 0.0
        total_wins = 0
        total_losses = 0
        total_trades = 0
        cycle_results = []
        cycle = 0
        
        try:
            while True:
                cycle += 1
                cycle_result = await self.run_cycle(assets, assets_by_category, cycle_num=cycle)
                cycle_results.append(cycle_result)
                
                total_profit += cycle_result.get("profit", 0)
                total_wins += cycle_result.get("wins", 0)
                total_losses += cycle_result.get("losses", 0)
                total_trades += cycle_result.get("trades", 0)
                
                # 30 seconds between cycles
                await asyncio.sleep(30)
        except KeyboardInterrupt:
            print(f"\n⏰ Session interrupted by user. Stopping.")
        
        # Final summary
        session_end = datetime.now()
        session_duration = session_end - session_start
        hours = int(session_duration.total_seconds() // 3600)
        minutes = int((session_duration.total_seconds() % 3600) // 60)
        
        try:
            balance = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            final_balance = balance.balance
            session_profit = final_balance - self.initial_balance
        except:
            session_profit = total_profit
            final_balance = self.initial_balance + total_profit
        
        print(f"\n{'='*70}")
        print(f"🎉 SESSION COMPLETE")
        print(f"{'='*70}")
        print(f"⏰ Duration: {hours}h {minutes}m")
        print(f"💰 Initial: ${self.initial_balance:.2f} | Final: ${final_balance:.2f}")
        print(f"💰 Total Profit: ${session_profit:+.2f}")
        print(f"📊 Total Trades: {total_trades}")
        print(f"📈 Wins: {total_wins} | Losses: {total_losses}")
        print(f"📊 Win Rate: {(total_wins / total_trades * 100) if total_trades > 0 else 0:.1f}%")
        print(f"🔄 Cycles: {len(cycle_results)}")
        print(f"{'='*70}\n")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

async def test_connection(ssid: str, is_demo: bool = False) -> bool:
    """Test connection to PocketOption"""
    print("=" * 60)
    print("🔍 Testing Connection...")
    print("=" * 60)
    
    client = None
    try:
        client = AsyncPocketOptionClient(ssid, is_demo=is_demo, enable_logging=False)
        await client.connect()
        
        if not client.is_connected:
            print("❌ Connection failed")
            return False
        
        print("✅ Connection established!")
        await asyncio.sleep(2)
        
        candles_df = await client.get_candles_dataframe(asset='EURUSD_otc', timeframe=60)
        
        if candles_df is not None and not candles_df.empty:
            print(f"✅ Data retrieval successful! ({len(candles_df)} candles)")
            print("=" * 60)
            print("✅ Connection test PASSED!")
            print("=" * 60)
            return True
        else:
            print("⚠️ No candle data received")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass
    
    return False


def parse_session_string(session_string: str) -> Dict:
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
    load_dotenv_early()
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
    print(f"   Format: {'Full auth message' if SSID.startswith('42["auth",') else 'Simple session ID'}")
    print(f"   Demo: {is_demo}\n")
    
    connection_ok = await test_connection(final_ssid, is_demo=is_demo)
    
    if not connection_ok:
        print("\n❌ Connection test failed! Aborting.")
        return
    
    print("\n🚀 Starting Deep Analysis Trading Bot...\n")
    
    telegram_token = require_env("TELEGRAM_BOT_TOKEN")
    telegram_channel = require_env("TELEGRAM_CHANNEL_ID")

    bot = DeepTradingBot(
        final_ssid,
        is_demo=is_demo,
        telegram_bot_token=telegram_token,
        telegram_channel_id=telegram_channel,
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
        if bot.telegram:
            await bot.telegram.close()
        await bot.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

