"""
Legacy refactored tryout variant kept for comparison with `tryout.py`.
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


# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

class TradingConfig:
    """Centralized trading configuration"""
    # Entry thresholds
    MIN_CONFIDENCE = 88.0  # Minimum confidence to enter trade
    MIN_CONFIDENCE_FACTORS = 3  # Minimum number of confidence factors
    MIN_ADX = 20.0  # Minimum ADX for trend strength
    MIN_HISTORICAL_WIN_RATE = 0.40  # Minimum historical win rate
    MIN_OTC_INNER_CONFIDENCE = 80.0  # Minimum inner confidence for OTC
    
    # Position sizing
    MIN_POSITION_PCT = 0.003  # 0.3% of balance (at 88% confidence)
    MAX_POSITION_PCT = 0.01  # 1% of balance (at 100% confidence)
    MAX_TOTAL_EXPOSURE_PCT = 0.05  # 5% of balance total exposure
    MAX_POSITIONS_PER_CYCLE = 3  # Maximum positions per cycle
    
    # Double down rules
    MAX_POSITIONS_PER_ASSET = 3  # Maximum positions per asset
    MAX_EXPOSURE_PER_ASSET_PCT = 0.05  # 5% per asset
    MAX_TOTAL_EXPOSURE_AFTER_DD_PCT = 0.08  # 8% after double down
    DOUBLE_DOWN_MULTIPLIER = 1.5  # Conservative 1.5x (not 2x)
    MIN_TIME_REMAINING_DD = 60  # 1 minute minimum for double down
    HIGH_VOLATILITY_THRESHOLD = 0.05  # Volatility threshold for reduction
    
    # Circuit breakers
    MAX_LOSS_STREAK = 3  # Stop after 3 consecutive losses
    MIN_WIN_RATE = 0.55  # Minimum win rate to continue
    MIN_TRADES_FOR_WIN_RATE_CHECK = 5  # Minimum trades before checking win rate
    
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
    
    def get_recent_performance(self, limit: int = 10) -> Dict:
        """Get recent trading performance for risk management"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT win, profit
            FROM trades
            WHERE win IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.5, "loss_streak": 0}
        
        wins = sum(1 for row in rows if row[0] == 1)
        losses = sum(1 for row in rows if row[0] == 0)
        total_trades = len(rows)
        win_rate = wins / total_trades if total_trades > 0 else 0.5
        
        # Calculate loss streak
        loss_streak = 0
        for row in rows:
            if row[0] == 0:  # Loss
                loss_streak += 1
            else:
                break
        
        return {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "loss_streak": loss_streak
        }


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
        
        # 1. Multi-timeframe trend alignment (25 points)
        if trend_1m == trend_5m and trend_1m != "neutral":
            confidence_score += 25
            signal_direction = "CALL" if trend_1m == "bullish" else "PUT"
            confidence_factors.append(f"Strong {trend_1m} alignment (1m & 5m)")
        
        # 2. RSI extreme conditions (20-25 points) - STRICT thresholds
        if rsi_1m < 20 and rsi_5m < 25:  # Extremely oversold
            confidence_score += 25
            if signal_direction != "PUT":
                signal_direction = "CALL"
            confidence_factors.append(f"RSI extremely oversold (1m: {rsi_1m:.1f}, 5m: {rsi_5m:.1f})")
        elif rsi_1m < 25 and rsi_5m < 30:  # Very oversold
            confidence_score += 20
            if signal_direction != "PUT":
                signal_direction = "CALL"
            confidence_factors.append(f"RSI very oversold (1m: {rsi_1m:.1f}, 5m: {rsi_5m:.1f})")
        elif rsi_1m > 80 and rsi_5m > 75:  # Extremely overbought
            confidence_score += 25
            if signal_direction != "CALL":
                signal_direction = "PUT"
            confidence_factors.append(f"RSI extremely overbought (1m: {rsi_1m:.1f}, 5m: {rsi_5m:.1f})")
        elif rsi_1m > 75 and rsi_5m > 70:  # Very overbought
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
        
        # 11. Historical performance (-15 to +8 points)
        if asset_stats and asset_stats.get("total_trades", 0) >= 5:
            win_rate = asset_stats.get("win_rate", 0.5)
            total_profit = asset_stats.get("total_profit", 0.0)
            if win_rate > 0.70 and total_profit > 0:
                confidence_score += 8
                confidence_factors.append(f"Excellent asset history ({win_rate:.1%} win rate, +${total_profit:.2f})")
            elif win_rate > 0.60:
                confidence_score += 5
                confidence_factors.append(f"Good asset history ({win_rate:.1%} win rate)")
            elif win_rate < 0.30:
                confidence_score -= 15
                confidence_factors.append(f"Poor asset history ({win_rate:.1%} win rate)")
            elif win_rate < 0.40:
                confidence_score -= 8
                confidence_factors.append(f"Weak asset history ({win_rate:.1%} win rate)")
        
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
                               recent_performance: Optional[Dict] = None) -> float:
        """
        Calculate position size with strict risk management.
        
        Formula:
        - Base: 0.3% (88% confidence) to 1% (100% confidence)
        - Volatility adjustment: Reduce by up to 50% in high volatility
        - Performance adjustment: Reduce by up to 30% if win rate < 50%
        - Maximum: 1% of balance
        
        Args:
            confidence_score: Confidence score (88-100)
            current_balance: Current account balance
            volatility: Price volatility (0-1 range)
            inner_confidence: Inner confidence for OTC assets
            recent_performance: Recent trading performance dict
        
        Returns:
            Position size in dollars
        """
        if confidence_score < TradingConfig.MIN_CONFIDENCE:
            return 0.0
        
        # Base percentage: scale from MIN to MAX based on confidence
        confidence_range = 100 - TradingConfig.MIN_CONFIDENCE
        confidence_ratio = (confidence_score - TradingConfig.MIN_CONFIDENCE) / confidence_range
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
        
        # Performance-based reduction
        if recent_performance:
            win_rate = recent_performance.get("win_rate", 0.5)
            if win_rate < 0.5:
                performance_factor = 0.7 + (win_rate * 0.6)  # 0.7 to 1.0
                base_percentage *= performance_factor
        
        # Calculate final amount
        amount = current_balance * base_percentage
        
        # Enforce limits
        amount = max(1.0, min(amount, current_balance * TradingConfig.MAX_POSITION_PCT))
        
        return round(amount, 2)
    
    @staticmethod
    def check_circuit_breakers(recent_performance: Dict) -> Tuple[bool, str]:
        """
        Check if circuit breakers should stop trading.
        
        Returns:
            (should_stop, reason)
        """
        loss_streak = recent_performance.get("loss_streak", 0)
        win_rate = recent_performance.get("win_rate", 0.5)
        total_trades = recent_performance.get("total_trades", 0)
        
        # Circuit breaker 1: Loss streak
        if loss_streak >= TradingConfig.MAX_LOSS_STREAK:
            return True, f"{loss_streak} consecutive losses"
        
        # Circuit breaker 2: Win rate
        if (total_trades >= TradingConfig.MIN_TRADES_FOR_WIN_RATE_CHECK and 
            win_rate < TradingConfig.MIN_WIN_RATE):
            return True, f"Win rate {win_rate:.1%} below threshold {TradingConfig.MIN_WIN_RATE:.1%}"
        
        return False, ""
    
    @staticmethod
    def validate_entry_opportunity(opportunity: Dict, asset_stats: Dict,
                                  categories_used: set, assets_by_category: Optional[Dict] = None) -> Tuple[bool, str]:
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
        
        # Check 3: Trend alignment
        if trend_1m == "neutral" or trend_5m == "neutral":
            return False, "Neutral trend detected"
        
        # Check 4: ADX threshold
        if adx < TradingConfig.MIN_ADX:
            return False, f"ADX {adx:.1f} below {TradingConfig.MIN_ADX}"
        
        # Check 5: Historical performance
        if asset_stats.get("total_trades", 0) >= 5:
            win_rate = asset_stats.get("win_rate", 0.5)
            if win_rate < TradingConfig.MIN_HISTORICAL_WIN_RATE:
                return False, f"Historical win rate {win_rate:.1%} below {TradingConfig.MIN_HISTORICAL_WIN_RATE:.1%}"
        
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
        """Load historical trades from Excel for validation"""
        try:
            df = pd.read_excel('export_history.xlsx')
            print(f"📊 Loaded {len(df)} historical trades from Excel")
            
            # Map columns
            order_id_col = None
            profit_col = None
            
            for col in df.columns:
                col_lower = col.lower()
                if ('order' in col_lower or 'id' in col_lower or 'deal' in col_lower) and not order_id_col:
                    order_id_col = col
                if 'profit' in col_lower and not profit_col:
                    profit_col = col
            
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
        except Exception as e:
            print(f"⚠️ Error loading historical trades: {e}")
    
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
        
        # Initial filtering
        candidates = []
        for result in results:
            if isinstance(result, Exception) or "error" in result:
                continue
            
            asset = result.get("asset", "")
            confidence = result.get("confidence_score", 0)
            direction = result.get("signal_direction")
            inner_confidence = result.get("inner_confidence")
            
            # OTC inner confidence check
            if "_otc" in asset.lower():
                if inner_confidence is not None and inner_confidence < TradingConfig.MIN_OTC_INNER_CONFIDENCE:
                    continue
                elif inner_confidence is None:
                    inner_confidence = await self.get_asset_inner_confidence(asset)
                    if inner_confidence is not None and inner_confidence < TradingConfig.MIN_OTC_INNER_CONFIDENCE:
                        continue
            
            # Store payout if available
            payout = self.asset_payout_percentages.get(asset)
            if payout:
                result["payout_percentage"] = payout
            
            if direction and confidence >= TradingConfig.MIN_CONFIDENCE:
                candidates.append(result)
        
        if not candidates:
            print(f"⚠️ No assets meet confidence threshold ({TradingConfig.MIN_CONFIDENCE}%+)")
            return []
        
        # Sort by confidence
        candidates.sort(key=lambda x: x.get("confidence_score", 0), reverse=True)
        
        # Apply strict filters
        validated = []
        categories_used = set()
        
        for opp in candidates:
            asset = opp.get("asset", "")
            asset_stats = self.db.get_asset_stats(asset)
            
            # Validate entry criteria
            is_valid, reason = RiskManager.validate_entry_opportunity(
                opp, asset_stats, categories_used, assets_by_category
            )
            
            if not is_valid:
                continue
            
            validated.append(opp)
            if assets_by_category:
                category = RiskManager._get_asset_category(asset, assets_by_category)
                categories_used.add(category)
            
            # Limit positions per cycle
            if len(validated) >= TradingConfig.MAX_POSITIONS_PER_CYCLE:
                break
        
        return validated
    
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
            return {"invested": 0, "positions": []}
        
        # Get current balance
        try:
            balance = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            current_balance = balance.balance
        except:
            current_balance = self.initial_balance if self.initial_balance else 1000.0
        
        # Check circuit breakers
        recent_stats = self.db.get_recent_performance(limit=10)
        if recent_stats:
            should_stop, reason = RiskManager.check_circuit_breakers(recent_stats)
            if should_stop:
                print(f"🛑 CIRCUIT BREAKER: {reason} - pausing trading")
                return {"invested": 0, "positions": []}
        
        # Check total exposure
        total_exposure = sum(
            pos.get("amount", 0)
            for positions in self.active_positions.values()
            for pos in positions
        )
        
        # Place trades
        positions_created = []
        total_invested = 0.0
        
        print(f"\n✅ Found {len(opportunities)} validated opportunities:")
        for opp in opportunities:
            print(f"   {opp['asset']}: {opp['signal_direction']} - {opp['confidence_score']:.1f}% confidence")
            print(f"      Factors: {', '.join(opp['confidence_factors'][:2])}")
        
        for opp in opportunities:
            # Check exposure limit
            if (total_invested + total_exposure) / current_balance > TradingConfig.MAX_TOTAL_EXPOSURE_PCT:
                print(f"⚠️ Reached maximum exposure limit ({TradingConfig.MAX_TOTAL_EXPOSURE_PCT*100:.1f}%)")
                break
            
            try:
                direction = OrderDirection.CALL if opp["signal_direction"] == "CALL" else OrderDirection.PUT
                
                # Calculate position size
                amount = RiskManager.calculate_position_size(
                    opp["confidence_score"],
                    current_balance,
                    volatility=opp.get("volatility", 0.0),
                    inner_confidence=opp.get("inner_confidence"),
                    recent_performance=recent_stats
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
                    direction=opp["signal_direction"],
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
                    "direction": opp["signal_direction"],
                    "amount": amount,
                    "confidence": opp["confidence_score"],
                    "order_id": order.order_id,
                    "analysis": opp
                }
                positions_created.append(position_data)
                total_invested += amount
                
                # Log
                pct = (amount / current_balance * 100) if current_balance > 0 else 0
                print(f"💰 {opp['asset']}: ${amount:.2f} {opp['signal_direction']} ({pct:.2f}% of balance)")
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
        Conservative double down on losing positions.
        
        RULES:
        - Only on losing positions (profit < 0)
        - Maximum 3 positions per asset
        - Maximum 5% exposure per asset
        - Maximum 8% total exposure after double down
        - Amount: 1.5x last position (conservative)
        - Requires: At least 1 minute remaining
        - Volatility check: Reduce by 30% if high volatility
        """
        print(f"\n{'='*70}")
        print(f"📈 DOUBLE-DOWN ANALYSIS")
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
            
            # All checks passed - place double down
            try:
                order = await self.client.place_order(
                    asset=asset,
                    amount=double_amount,
                    direction=original_direction,
                    duration=300
                )
                
                payout = self.asset_payout_percentages.get(asset)
                self.db.save_trade(
                    asset=asset,
                    direction=pos_info["analysis"]["signal_direction"],
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
                    "amount": double_amount,
                    "original_profit": current_profit
                })
                total_additional += double_amount
                
                print(f"📉 {asset}: DOUBLED DOWN ${double_amount:.2f} (Position #{len(positions)})")
                
                # Telegram notification
                if self.telegram:
                    try:
                        await self.telegram.send_double_down_signal({
                            "asset": asset,
                            "direction": pos_info["analysis"]["signal_direction"],
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
                    # Use OrderStatus as source of truth
                    is_win = result.status == OrderStatus.WIN
                    is_lose = result.status == OrderStatus.LOSE
                    
                    profit = result.profit if result.profit is not None else 0.0
                    
                    # Handle unclear status
                    if not is_win and not is_lose:
                        if profit > 0:
                            is_win = True
                        elif profit < 0:
                            is_lose = True
                    
                    final_win = is_win
                    
                    # Ensure profit sign matches status
                    if is_win and profit <= 0:
                        profit = pos_info['amount'] * 0.8  # Default payout
                    elif is_lose and profit >= 0:
                        profit = -pos_info['amount']  # Full loss
                    
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
                    else:
                        losses += 1
                    
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
        print(f"🎯 Strategy: Conservative (88%+ confidence, 0.3%-1% position size)")
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
        """Run 8-hour session with multiple 5-minute cycles"""
        total_cycles = (TradingConfig.SESSION_DURATION_HOURS * 60) // TradingConfig.CYCLE_DURATION_MINUTES
        session_start = datetime.now()
        session_end = session_start + timedelta(hours=TradingConfig.SESSION_DURATION_HOURS)
        
        print(f"\n{'='*70}")
        print(f"🚀 STARTING {TradingConfig.SESSION_DURATION_HOURS}-HOUR TRADING SESSION")
        print(f"{'='*70}")
        print(f"⏰ Start: {session_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"⏰ End: {session_end.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🔄 Total Cycles: {total_cycles} ({TradingConfig.CYCLE_DURATION_MINUTES} minutes each)")
        print(f"💰 Initial Balance: ${self.initial_balance:.2f}")
        print(f"{'='*70}\n")
        
        total_profit = 0.0
        total_wins = 0
        total_losses = 0
        total_trades = 0
        cycle_results = []
        
        for cycle in range(1, total_cycles + 1):
            if datetime.now() >= session_end:
                print(f"\n⏰ Session time completed. Stopping.")
                break
            
            cycle_result = await self.run_cycle(assets, assets_by_category, cycle_num=cycle)
            cycle_results.append(cycle_result)
            
            total_profit += cycle_result.get("profit", 0)
            total_wins += cycle_result.get("wins", 0)
            total_losses += cycle_result.get("losses", 0)
            total_trades += cycle_result.get("trades", 0)
            
            if cycle < total_cycles:
                await asyncio.sleep(30)  # 30 seconds between cycles
        
        # Final summary
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
        
        # Asset configuration
        otc_assets_by_category = {
            "cryptocurrencies": [
                "BTCUSD_otc", "BTCUSD",
                "ETHUSD_otc", "ETHUSD",
                "LNKUSD_otc", "LNKUSD",
                "DOTUSD_otc", "DOTUSD",
            ],
            "forex": [
                "AUDCHF_otc", "AUDNZD_otc", "AUDUSD_otc", "AUDCAD_otc",
                "CADCHF_otc", "CHFJPY_otc", "EURCHF_otc", "EURNZD_otc",
                "EURUSD_otc", "EURGBP_otc", "EURJPY_otc", "GBPAUD_otc",
                "GBPUSD_otc", "GBPJPY_otc", "USDJPY_otc", "USDCHF_otc",
                "USDCAD_otc", "NZDUSD_otc", "NZDJPY_otc",
            ],
            "commodities": [
                "XAUUSD_otc", "XAGUSD_otc", "UKBrent_otc", "USCrude_otc",
            ],
            "stocks": [
                "#AAPL_otc", "#MSFT_otc", "#BA_otc", "#VISA_otc",
                "#JNJ_otc", "#PFE_otc", "#AXP_otc", "#CSCO_otc",
                "#FB_otc", "#MCD_otc", "#TSLA_otc", "#BABA_otc",
                "#AMZN_otc", "#NFLX_otc", "#INTC_otc", "#XOM_otc",
                "#CITI_otc", "#TWITTER_otc",
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

