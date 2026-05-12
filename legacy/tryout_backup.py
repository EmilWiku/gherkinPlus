import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "bot_app"))
sys.path.insert(0, str(_REPO / "PocketOptionAPI"))

from pocketoptionapi_async import AsyncPocketOptionClient, OrderDirection
from pocketoptionapi_async.models import Candle, Balance, OrderStatus
from pocketoptionapi_async.utils import analyze_candles, calculate_volatility, determine_trend, calculate_support_resistance as utils_support_resistance
from telegram_notifier import TelegramNotifier
import asyncio
import json
import re
import sqlite3
import statistics
import math
import pandas as pd
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from collections import deque

from env_setup import get_pocket_option_ssid, load_dotenv_early, require_env


class TradeDatabase:
    """SQLite database for tracking trades and performance"""
    
    def __init__(self, db_path: str = "trading_metrics.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
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
                win INTEGER DEFAULT 0
            )
        ''')
        
        # Migrate existing database: add confidence_score column if it doesn't exist
        try:
            cursor.execute("PRAGMA table_info(trades)")
            columns = [column[1] for column in cursor.fetchall()]
            if 'confidence_score' not in columns:
                cursor.execute('ALTER TABLE trades ADD COLUMN confidence_score REAL')
                conn.commit()
        except Exception:
            # If table doesn't exist yet, it will be created with the column above
            pass
        
        # Create asset_performance table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS asset_performance (
                asset TEXT PRIMARY KEY,
                total_trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0.0,
                total_profit REAL DEFAULT 0.0,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_trade(self, asset: str, direction: str, amount: float, duration: int,
                   order_id: str, signal_strength: float, confidence_score: float,
                   payout_percentage: Optional[float] = None):
        """Save a trade to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Ensure all columns exist
        try:
            cursor.execute("PRAGMA table_info(trades)")
            columns = [column[1] for column in cursor.fetchall()]
            if 'confidence_score' not in columns:
                cursor.execute('ALTER TABLE trades ADD COLUMN confidence_score REAL')
            if 'payout_percentage' not in columns:
                cursor.execute('ALTER TABLE trades ADD COLUMN payout_percentage REAL')
            if 'expected_profit' not in columns:
                cursor.execute('ALTER TABLE trades ADD COLUMN expected_profit REAL')
            conn.commit()
        except Exception:
            pass
        
        # Calculate expected profit if payout is known
        expected_profit = None
        if payout_percentage is not None:
            expected_profit = amount * (payout_percentage / 100)
        
        # Insert trade
        try:
            cursor.execute('''
                INSERT INTO trades (asset, direction, amount, duration, order_id,
                                  signal_strength, confidence_score, payout_percentage, expected_profit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (asset, direction, amount, duration, order_id, signal_strength, 
                  confidence_score, payout_percentage, expected_profit))
            conn.commit()
        except sqlite3.OperationalError as e:
            # Fallback: try with fewer columns if some don't exist
            try:
                cursor.execute('''
                    INSERT INTO trades (asset, direction, amount, duration, order_id,
                                      signal_strength, confidence_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (asset, direction, amount, duration, order_id, signal_strength, confidence_score))
                conn.commit()
            except Exception:
                raise
        
        conn.close()
    
    def update_trade_result(self, order_id: str, status: str, profit: float, win: bool, 
                           actual_payout: Optional[float] = None):
        """Update trade result - uses win parameter as source of truth (from OrderStatus)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get the original trade data for validation
        cursor.execute('SELECT amount, payout_percentage, expected_profit FROM trades WHERE order_id = ?', (order_id,))
        trade_data = cursor.fetchone()
        
        # Use win parameter as source of truth (comes from OrderStatus.WIN check)
        # This is more reliable than inferring from profit
        
        # Validate expected vs actual profit for wins
        if trade_data:
            amount, payout_pct, expected_profit = trade_data
            if win and payout_pct:
                # Expected profit should be: amount * (payout_percentage / 100)
                calculated_expected = amount * (payout_pct / 100)
                # Allow some variance (rounding, fees, etc.)
                if abs(profit - calculated_expected) > (amount * 0.05):  # Allow 5% variance
                    print(f"⚠️ Profit validation for {order_id}: Expected ~${calculated_expected:.2f} (based on {payout_pct}% payout), got ${profit:.2f}")
        
        # Update with win status (from OrderStatus)
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


class DeepAnalyzer:
    """Deep multi-timeframe analysis for 15-minute predictions"""
    
    @staticmethod
    def calculate_sma(prices: List[float], period: int) -> float:
        if len(prices) < period:
            return sum(prices) / len(prices) if prices else 0
        return sum(prices[-period:]) / period
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> float:
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
        """Calculate Average Directional Index (trend strength)"""
        if len(candles) < period * 2:
            return 25.0  # Neutral
        
        plus_dm = []
        minus_dm = []
        tr_values = []
        
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
        return dx  # Simplified ADX
    
    @staticmethod
    def calculate_volume_profile(candles: List[Candle]) -> Dict:
        """Analyze volume distribution"""
        if not candles:
            return {"trend": "neutral", "strength": 0}
        
        volumes = [c.volume or 0 for c in candles]
        avg_volume = sum(volumes) / len(volumes) if volumes else 0
        recent_volume = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else volumes[-1] if volumes else 0
        
        volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1.0
        
        # Check if volume is increasing with price
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
    
    @staticmethod
    def calculate_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
        """Calculate MACD (Moving Average Convergence Divergence)"""
        if len(prices) < slow + signal:
            return {"macd": 0, "signal": 0, "histogram": 0}
        
        ema_fast = DeepAnalyzer.calculate_ema(prices, fast)
        ema_slow = DeepAnalyzer.calculate_ema(prices, slow)
        macd_line = ema_fast - ema_slow
        
        # Calculate signal line (EMA of MACD)
        macd_values = []
        for i in range(slow, len(prices)):
            ema_f = DeepAnalyzer.calculate_ema(prices[:i+1], fast)
            ema_s = DeepAnalyzer.calculate_ema(prices[:i+1], slow)
            macd_values.append(ema_f - ema_s)
        
        signal_line = DeepAnalyzer.calculate_ema(macd_values, signal) if len(macd_values) >= signal else 0
        histogram = macd_line - signal_line
        
        return {"macd": macd_line, "signal": signal_line, "histogram": histogram}
    
    @staticmethod
    def calculate_bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0) -> Dict:
        """Calculate Bollinger Bands"""
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
            "position": position  # 0 = lower band, 1 = upper band, 0.5 = middle
        }
    
    @staticmethod
    def analyze_multi_timeframe(candles_1m: List[Candle], candles_5m: List[Candle], 
                                asset_stats: Dict) -> Dict:
        """Deep multi-timeframe analysis for 15-minute prediction"""
        if not candles_1m or len(candles_1m) < 30:
            return {"error": "Insufficient data"}
        
        closes_1m = [c.close for c in candles_1m]
        closes_5m = [c.close for c in candles_5m] if candles_5m and len(candles_5m) >= 10 else closes_1m
        
        # Multi-timeframe indicators
        sma_9_1m = DeepAnalyzer.calculate_sma(closes_1m, 9)
        sma_21_1m = DeepAnalyzer.calculate_sma(closes_1m, 21)
        sma_50_1m = DeepAnalyzer.calculate_sma(closes_1m, 50) if len(closes_1m) >= 50 else sma_21_1m
        
        sma_9_5m = DeepAnalyzer.calculate_sma(closes_5m, 9) if len(closes_5m) >= 9 else sma_9_1m
        sma_21_5m = DeepAnalyzer.calculate_sma(closes_5m, 21) if len(closes_5m) >= 21 else sma_21_1m
        
        ema_12_1m = DeepAnalyzer.calculate_ema(closes_1m, 12)
        ema_26_1m = DeepAnalyzer.calculate_ema(closes_1m, 26)
        ema_12_5m = DeepAnalyzer.calculate_ema(closes_5m, 12) if len(closes_5m) >= 12 else ema_12_1m
        ema_26_5m = DeepAnalyzer.calculate_ema(closes_5m, 26) if len(closes_5m) >= 26 else ema_26_1m
        
        rsi_1m = DeepAnalyzer.calculate_rsi(closes_1m, 14)
        rsi_5m = DeepAnalyzer.calculate_rsi(closes_5m, 14) if len(closes_5m) >= 15 else rsi_1m
        
        adx = DeepAnalyzer.calculate_adx(candles_1m, 14)
        volume_profile = DeepAnalyzer.calculate_volume_profile(candles_1m)
        support_resistance = DeepAnalyzer.calculate_support_resistance(candles_1m)
        macd = DeepAnalyzer.calculate_macd(closes_1m)
        bollinger = DeepAnalyzer.calculate_bollinger_bands(closes_1m)
        
        current_price = closes_1m[-1]
        
        # Calculate trend alignment across timeframes
        trend_1m = "bullish" if sma_9_1m > sma_21_1m else "bearish" if sma_9_1m < sma_21_1m else "neutral"
        trend_5m = "bullish" if sma_9_5m > sma_21_5m else "bearish" if sma_9_5m < sma_21_5m else "neutral"
        
        # Store trends for filtering
        trend_strength_1m = abs(sma_9_1m - sma_21_1m) / current_price * 100 if current_price > 0 else 0
        trend_strength_5m = abs(sma_9_5m - sma_21_5m) / current_price * 100 if current_price > 0 else 0
        
        # Calculate momentum
        momentum_1m = closes_1m[-1] - closes_1m[-10] if len(closes_1m) >= 10 else 0
        momentum_5m = closes_5m[-1] - closes_5m[-5] if len(closes_5m) >= 5 else momentum_1m
        
        # Confidence scoring system (0-100)
        confidence_score = 0.0
        signal_direction = None
        confidence_factors = []
        
        # 1. Multi-timeframe trend alignment (weight: 25 points)
        if trend_1m == trend_5m and trend_1m != "neutral":
            if trend_1m == "bullish":
                confidence_score += 25
                signal_direction = "CALL"
                confidence_factors.append("Strong bullish alignment (1m & 5m)")
            else:
                confidence_score += 25
                signal_direction = "PUT"
                confidence_factors.append("Strong bearish alignment (1m & 5m)")
        
        # 2. RSI confirmation across timeframes (weight: 25 points - increased)
        # More refined RSI thresholds based on successful patterns
        if rsi_1m < 25 and rsi_5m < 30:  # Very oversold
            confidence_score += 25
            if signal_direction != "PUT":
                signal_direction = "CALL"
            confidence_factors.append(f"RSI very oversold (1m: {rsi_1m:.1f}, 5m: {rsi_5m:.1f})")
        elif rsi_1m < 30 and rsi_5m < 35:  # Oversold
            confidence_score += 20
            if signal_direction != "PUT":
                signal_direction = "CALL"
            confidence_factors.append(f"RSI oversold (1m: {rsi_1m:.1f}, 5m: {rsi_5m:.1f})")
        elif rsi_1m > 75 and rsi_5m > 70:  # Very overbought
            confidence_score += 25
            if signal_direction != "CALL":
                signal_direction = "PUT"
            confidence_factors.append(f"RSI very overbought (1m: {rsi_1m:.1f}, 5m: {rsi_5m:.1f})")
        elif rsi_1m > 70 and rsi_5m > 65:  # Overbought
            confidence_score += 20
            if signal_direction != "CALL":
                signal_direction = "PUT"
            confidence_factors.append(f"RSI overbought (1m: {rsi_1m:.1f}, 5m: {rsi_5m:.1f})")
        
        # 3. Moving average alignment (weight: 15 points)
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
        
        # 4. EMA crossover confirmation (weight: 10 points)
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
        
        # 5. Trend strength (ADX) (weight: 10 points)
        if adx > 25:  # Strong trend
            confidence_score += 10
            confidence_factors.append(f"Strong trend (ADX: {adx:.1f})")
        elif adx < 20:  # Weak trend
            confidence_score -= 5
            confidence_factors.append(f"Weak trend (ADX: {adx:.1f})")
        
        # 6. Momentum confirmation (weight: 12 points - increased)
        momentum_strength_1m = abs(momentum_1m) / current_price * 100 if current_price > 0 else 0
        momentum_strength_5m = abs(momentum_5m) / current_price * 100 if current_price > 0 else 0
        
        if momentum_1m > 0 and momentum_5m > 0 and signal_direction == "CALL":
            if momentum_strength_1m > 0.1 and momentum_strength_5m > 0.05:  # Strong momentum
                confidence_score += 12
                confidence_factors.append("Strong positive momentum (both timeframes)")
            else:
                confidence_score += 8
                confidence_factors.append("Positive momentum (both timeframes)")
        elif momentum_1m < 0 and momentum_5m < 0 and signal_direction == "PUT":
            if momentum_strength_1m > 0.1 and momentum_strength_5m > 0.05:  # Strong momentum
                confidence_score += 12
                confidence_factors.append("Strong negative momentum (both timeframes)")
            else:
                confidence_score += 8
                confidence_factors.append("Negative momentum (both timeframes)")
        
        # 7. Volume confirmation (weight: 5 points)
        if volume_profile["strength"] > 0 and signal_direction == "CALL":
            confidence_score += 5
            confidence_factors.append("Volume supports bullish move")
        elif volume_profile["strength"] < 0 and signal_direction == "PUT":
            confidence_score += 5
            confidence_factors.append("Volume supports bearish move")
        
        # 8. Support/Resistance levels (weight: 5 points)
        if signal_direction == "CALL" and support_resistance["distance_to_support"] < 1.0:
            confidence_score += 5
            confidence_factors.append("Near support level (bullish)")
        elif signal_direction == "PUT" and support_resistance["distance_to_resistance"] < 1.0:
            confidence_score += 5
            confidence_factors.append("Near resistance level (bearish)")
        
        # 10. MACD confirmation (weight: 8 points)
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
        
        # 11. Bollinger Bands confirmation (weight: 7 points)
        if bollinger["position"] < 0.2 and signal_direction == "CALL":  # Near lower band
            confidence_score += 7
            confidence_factors.append(f"Price near lower Bollinger Band (position: {bollinger['position']:.2f})")
        elif bollinger["position"] > 0.8 and signal_direction == "PUT":  # Near upper band
            confidence_score += 7
            confidence_factors.append(f"Price near upper Bollinger Band (position: {bollinger['position']:.2f})")
        elif bollinger["width"] > 2.0:  # High volatility
            confidence_score += 3
            confidence_factors.append(f"High volatility (BB width: {bollinger['width']:.2f}%)")
        
        # 9. Historical performance adjustment (weight: 8 points - increased)
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
        
        return {
            "signal_direction": signal_direction,
            "confidence_score": confidence_score,
            "confidence_factors": confidence_factors,
            "rsi_1m": rsi_1m,
            "rsi_5m": rsi_5m,
            "adx": adx,
            "trend_1m": trend_1m,
            "trend_5m": trend_5m,
            "momentum_1m": momentum_1m,
            "momentum_5m": momentum_5m,
            "volume_profile": volume_profile,
            "support_resistance": support_resistance,
            "macd": macd,
            "bollinger": bollinger,
            "current_price": current_price
        }


class DeepTradingBot:
    """Deep analysis bot for 15-minute profitable predictions"""
    
    def __init__(self, ssid: str, is_demo: bool = True, telegram_bot_token: Optional[str] = None, telegram_channel_id: Optional[str] = None):
        self.ssid = ssid
        self.is_demo = is_demo
        self.client = None
        self.initial_balance = None
        self.db = TradeDatabase()
        self.active_positions = {}  # {asset: [order_info, ...]}
        self.min_confidence = 88.0  # Only trade with 88%+ confidence (increased for better quality)
        self.max_positions_per_cycle = 3  # Limit positions per cycle to avoid overtrading
        self.max_total_exposure = 0.05  # Max 5% of balance in total positions
        self.loss_streak_limit = 3  # Stop trading after 3 consecutive losses
        self.win_rate_threshold = 0.55  # Minimum win rate to continue trading
        self.session_start = None
        self.cycle_results = []  # Track results across cycles
        self.best_assets = {}  # Track best performing assets
        self.asset_inner_confidence = {}  # Cache for inner confidence: {asset: confidence_value}
        self.asset_payout_percentages = {}  # Cache payout percentages: {asset: payout_percentage}
        self.recent_candles = {}  # Cache recent candles for real-time analysis: {asset: [candles]}
        self.min_payout_percentage = 80.0  # Minimum payout percentage to invest (80%+)
        self.historical_trades = {}  # Loaded from Excel for validation: {order_id: trade_data}
        
        # Load historical trades from Excel for validation
        self._load_historical_trades()
        
        # Initialize Telegram notifier if credentials provided
        self.telegram = None
        if telegram_bot_token and telegram_channel_id:
            try:
                self.telegram = TelegramNotifier(telegram_bot_token, telegram_channel_id)
                print("✅ Telegram notifier initialized")
            except Exception as e:
                print(f"⚠️ Failed to initialize Telegram notifier: {e}")
        
    async def connect(self):
        """Connect to PocketOption"""
        self.client = AsyncPocketOptionClient(self.ssid, is_demo=self.is_demo, enable_logging=False)
        await self.client.connect()
        
        # Set up event listeners for asset confidence data
        # Try multiple event types that might contain confidence information
        self.client.add_event_callback("payout_update", self._on_payout_update)
        self.client.add_event_callback("json_data", self._on_json_data)
        self.client.add_event_callback("stream_update", self._on_stream_update)
        
        print("⏳ Waiting for balance data...")
        await asyncio.sleep(3)
        
        balance = await self._get_balance_with_retry(max_retries=5, delay=2)
        self.initial_balance = balance.balance
        print(f"✅ Connected! Initial balance: ${balance.balance:.2f} {balance.currency}")
    
    async def _on_payout_update(self, data: Dict):
        """Handle payout update events - contains payout percentage and confidence data"""
        try:
            asset_symbol = data.get("symbol", "")
            
            # Store payout percentage (this is the key metric for filtering)
            payout = data.get("payout")
            if asset_symbol and payout is not None:
                try:
                    payout_value = float(payout)
                    self.asset_payout_percentages[asset_symbol] = payout_value
                    print(f"📊 Payout update: {asset_symbol} = {payout_value}%")
                except (ValueError, TypeError):
                    pass
            
            # Check if this message contains confidence information
            confidence = data.get("confidence") or data.get("inner_confidence")
            if asset_symbol and confidence is not None:
                self.asset_inner_confidence[asset_symbol] = float(confidence)
        except Exception as e:
            print(f"⚠️ Error in payout update handler: {e}")
    
    async def _on_json_data(self, data: Dict):
        """Handle JSON data events - might contain asset confidence"""
        try:
            if isinstance(data, dict):
                asset_symbol = data.get("asset") or data.get("symbol", "")
                confidence = data.get("confidence") or data.get("inner_confidence") or data.get("otc_confidence")
                if asset_symbol and confidence is not None:
                    self.asset_inner_confidence[asset_symbol] = float(confidence)
        except Exception:
            pass
    
    async def _on_stream_update(self, data: Dict):
        """Handle stream update events - might contain asset confidence"""
        try:
            if isinstance(data, dict):
                asset_symbol = data.get("asset") or data.get("symbol", "")
                confidence = data.get("confidence") or data.get("inner_confidence")
                if asset_symbol and confidence is not None:
                    self.asset_inner_confidence[asset_symbol] = float(confidence)
        except Exception:
            pass
    
    def _load_historical_trades(self):
        """Load historical trades from Excel file for validation"""
        try:
            df = pd.read_excel('export_history.xlsx')
            print(f"📊 Loaded {len(df)} historical trades from Excel for validation")
            
            # Map column names (handle different possible names)
            order_id_col = None
            profit_col = None
            asset_col = None
            status_col = None
            
            for col in df.columns:
                col_lower = col.lower()
                if 'order' in col_lower or 'id' in col_lower or 'deal' in col_lower:
                    order_id_col = col
                if 'profit' in col_lower:
                    profit_col = col
                if 'asset' in col_lower or 'symbol' in col_lower or 'instrument' in col_lower:
                    asset_col = col
                if 'status' in col_lower or 'result' in col_lower or 'outcome' in col_lower:
                    status_col = col
            
            # Store trades by order_id for validation
            if order_id_col and profit_col:
                for idx, row in df.iterrows():
                    order_id = str(row[order_id_col]) if order_id_col else None
                    profit = float(row[profit_col]) if pd.notna(row[profit_col]) else 0.0
                    asset = str(row[asset_col]) if asset_col and pd.notna(row[asset_col]) else None
                    status = str(row[status_col]) if status_col and pd.notna(row[status_col]) else None
                    
                    if order_id:
                        self.historical_trades[order_id] = {
                            "profit": profit,
                            "asset": asset,
                            "status": status,
                            "win": profit > 0  # Use profit as truth
                        }
            
            print(f"✅ Mapped {len(self.historical_trades)} trades for validation")
        except FileNotFoundError:
            print("⚠️ export_history.xlsx not found - validation will be limited")
        except Exception as e:
            print(f"⚠️ Error loading historical trades: {e}")
    
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
            # Check cache first
            if asset in self.asset_inner_confidence:
                return self.asset_inner_confidence[asset]
            
            # For OTC assets, try to request confidence data
            if "_otc" in asset.lower():
                # Try different request formats that might return confidence
                # Format 1: Request asset info
                message1 = f'42["getAssetInfo",{{"asset":"{asset}"}}]'
                await self.client.send_message(message1)
                
                # Format 2: Request OTC confidence
                message2 = f'42["getOTCConfidence",{{"asset":"{asset}"}}]'
                await self.client.send_message(message2)
                
                # Wait a bit for response
                await asyncio.sleep(0.8)
                
                # Check cache again after request
                if asset in self.asset_inner_confidence:
                    return self.asset_inner_confidence[asset]
            
            return None
        except Exception as e:
            return None
    
    async def deep_analyze_asset(self, asset: str) -> Dict:
        """Deep multi-timeframe analysis"""
        try:
            # Get inner confidence for OTC assets first
            inner_confidence = None
            if "_otc" in asset.lower():
                inner_confidence = await self.get_asset_inner_confidence(asset)
            
            # Get multiple timeframes
            candles_1m = await self.client.get_candles(asset=asset, timeframe=60, count=100)
            candles_5m = await self.client.get_candles(asset=asset, timeframe=300, count=50)
            
            if not candles_1m or len(candles_1m) < 30:
                return {"error": "Insufficient data", "asset": asset}
            
            asset_stats = self.db.get_asset_stats(asset)
            analysis = DeepAnalyzer.analyze_multi_timeframe(candles_1m, candles_5m, asset_stats)
            analysis["asset"] = asset
            analysis["inner_confidence"] = inner_confidence  # Store inner confidence
            
            return analysis
        except Exception as e:
            return {"error": str(e), "asset": asset}
    
    def calculate_investment_amount(self, confidence_score: float, current_balance: float, 
                                   volatility: float = 0.0, inner_confidence: Optional[float] = None,
                                   recent_performance: Optional[Dict] = None) -> float:
        """Calculate investment amount with strict risk management (0.3% to 1% of balance)"""
        if confidence_score < 88:
            return 0
        
        # CONSERVATIVE: Scale from 0.3% (88% confidence) to 1% (100% confidence)
        # Much smaller positions to preserve capital
        confidence_ratio = (confidence_score - 88) / 12  # 0 to 1
        base_percentage = 0.003 + (confidence_ratio * 0.007)  # 0.3% to 1%
        
        # Adjust for inner confidence if available (for OTC assets) - but be conservative
        if inner_confidence is not None:
            # Only boost if inner confidence is very high (90%+)
            if inner_confidence >= 90:
                inner_boost = ((inner_confidence - 90) / 10) * 0.002  # 0 to 0.2%
                base_percentage += inner_boost
        
        # Aggressive volatility reduction: reduce position size significantly in high volatility
        if volatility > 0:
            # More aggressive reduction: up to 50% reduction in high volatility
            volatility_factor = max(0.5, 1.0 - (volatility * 15))
            base_percentage *= volatility_factor
        
        # Reduce position size if recent performance is poor
        if recent_performance:
            win_rate = recent_performance.get("win_rate", 0.5)
            if win_rate < 0.5:
                # Reduce by up to 30% if win rate is below 50%
                performance_factor = 0.7 + (win_rate * 0.6)  # 0.7 to 1.0
                base_percentage *= performance_factor
        
        # Calculate final amount
        amount = current_balance * base_percentage
        
        # Ensure minimum of $1 and maximum of 1% of balance (reduced from 2%)
        amount = max(1.0, min(amount, current_balance * 0.01))
        
        return round(amount, 2)
    
    def get_asset_category(self, asset: str, assets_by_category: Dict) -> str:
        """Get category for an asset"""
        for category, assets in assets_by_category.items():
            if asset in assets:
                return category
        return "unknown"
    
    async def initial_analysis_and_investment(self, assets: List[str], assets_by_category: Dict = None) -> Dict:
        """Initial deep analysis and investment phase"""
        print(f"\n{'='*70}")
        print(f"🔬 DEEP ANALYSIS PHASE - Initial Investment")
        print(f"{'='*70}\n")
        
        print(f"📊 Analyzing {len(assets)} assets with multi-timeframe analysis...")
        
        # Analyze all assets
        tasks = [self.deep_analyze_asset(asset) for asset in assets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter only high-confidence opportunities
        high_confidence = []
        for result in results:
            if isinstance(result, Exception) or "error" in result:
                continue
            
            confidence = result.get("confidence_score", 0)
            direction = result.get("signal_direction")
            inner_confidence = result.get("inner_confidence")
            asset = result.get("asset", "")
            
            # For OTC assets, require inner confidence > 80% if available
            # If inner confidence is not available (None), allow the asset through
            if "_otc" in asset.lower():
                if inner_confidence is not None and inner_confidence < 80:
                    continue  # Skip OTC assets with inner confidence < 80%
                elif inner_confidence is None:
                    # Try to get it one more time
                    inner_confidence = await self.get_asset_inner_confidence(asset)
                    if inner_confidence is not None and inner_confidence < 80:
                        continue
            
            # Store payout percentage if available (for logging, but don't filter by it)
            payout_percentage = self.asset_payout_percentages.get(asset)
            if payout_percentage is not None:
                result["payout_percentage"] = payout_percentage
            
            if direction and confidence >= self.min_confidence:
                high_confidence.append(result)
        
        if not high_confidence:
            print(f"⚠️ No assets meet the high confidence threshold ({self.min_confidence}%+)")
            return {"invested": 0, "positions": []}
        
        # Sort by confidence (highest first)
        high_confidence.sort(key=lambda x: x.get("confidence_score", 0), reverse=True)
        
        # STRICT FILTERING: Additional quality checks
        filtered_confidence = []
        asset_categories_used = set()  # Track categories to avoid correlation
        
        for opp in high_confidence:
            asset = opp.get("asset", "")
            confidence = opp.get("confidence_score", 0)
            
            # Check 1: Require multiple strong signals (at least 3 confidence factors)
            factors = opp.get("confidence_factors", [])
            if len(factors) < 3:
                continue  # Skip if not enough confirmation
            
            # Check 2: Avoid correlated assets (same category)
            category = self.get_asset_category(asset, assets_by_category) if assets_by_category else "unknown"
            if category in asset_categories_used:
                continue  # Skip if we already have a position in this category
            
            # Check 3: Require strong trend alignment
            trend_1m = opp.get("trend_1m", "neutral")
            trend_5m = opp.get("trend_5m", "neutral")
            if trend_1m == "neutral" or trend_5m == "neutral":
                continue  # Skip neutral trends
            
            # Check 4: Require ADX > 20 (some trend strength)
            adx = opp.get("adx", 0)
            if adx < 20:
                continue  # Skip weak trends
            
            # Check 5: Historical performance filter
            asset_stats = self.db.get_asset_stats(asset)
            if asset_stats.get("total_trades", 0) >= 5:
                win_rate = asset_stats.get("win_rate", 0.5)
                if win_rate < 0.40:  # Skip assets with poor history
                    continue
            
            filtered_confidence.append(opp)
            asset_categories_used.add(category)
            
            # Limit to max positions per cycle
            if len(filtered_confidence) >= self.max_positions_per_cycle:
                break
        
        high_confidence = filtered_confidence
        
        if not high_confidence:
            print(f"⚠️ No assets passed strict quality filters")
            return {"invested": 0, "positions": []}
        
        # Group by category for better visualization
        by_category = {}
        if assets_by_category:
            for opp in high_confidence:
                category = self.get_asset_category(opp['asset'], assets_by_category)
                if category not in by_category:
                    by_category[category] = []
                by_category[category].append(opp)
        
        print(f"\n✅ Found {len(high_confidence)} high-confidence opportunities:")
        if by_category:
            for category, opps in by_category.items():
                print(f"\n   📁 {category.upper()} ({len(opps)} opportunities):")
                for opp in opps[:5]:  # Show top 5 per category
                    print(f"      {opp['asset']}: {opp['signal_direction']} - {opp['confidence_score']:.1f}% confidence")
                    print(f"         Factors: {', '.join(opp['confidence_factors'][:2])}")
        else:
            for opp in high_confidence[:10]:
                print(f"   {opp['asset']}: {opp['signal_direction']} - {opp['confidence_score']:.1f}% confidence")
                print(f"      Factors: {', '.join(opp['confidence_factors'][:3])}")
        
        # Get current balance for investment calculation
        try:
            balance = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            current_balance = balance.balance
        except:
            current_balance = self.initial_balance if self.initial_balance else 1000.0
        
        # Check recent performance before investing
        recent_stats = self.db.get_recent_performance(limit=10)
        if recent_stats:
            win_rate = recent_stats.get("win_rate", 0.5)
            loss_streak = recent_stats.get("loss_streak", 0)
            
            # Circuit breaker: Stop trading if loss streak is too high
            if loss_streak >= self.loss_streak_limit:
                print(f"🛑 CIRCUIT BREAKER: {loss_streak} consecutive losses - pausing trading")
                return {"invested": 0, "positions": []}
            
            # Circuit breaker: Stop trading if win rate is too low
            if win_rate < self.win_rate_threshold and recent_stats.get("total_trades", 0) >= 5:
                print(f"🛑 CIRCUIT BREAKER: Win rate {win_rate:.1%} below threshold {self.win_rate_threshold:.1%}")
                return {"invested": 0, "positions": []}
        
        # Check total exposure limit
        total_exposure = sum(
            pos_info.get("amount", 0) 
            for positions in self.active_positions.values() 
            for pos_info in positions
        )
        
        # Invest in top opportunities
        positions_created = []
        total_invested = 0.0
        
        for opp in high_confidence:
            # Check if we've hit exposure limit
            if (total_invested + total_exposure) / current_balance > self.max_total_exposure:
                print(f"⚠️ Reached maximum exposure limit ({self.max_total_exposure*100:.1f}%)")
                break
            try:
                direction = OrderDirection.CALL if opp["signal_direction"] == "CALL" else OrderDirection.PUT
                
                # Calculate investment amount with volatility and inner confidence
                volatility = opp.get("volatility", 0.0)
                inner_conf = opp.get("inner_confidence")
                recent_performance = self.db.get_recent_performance(limit=10)
                amount = self.calculate_investment_amount(
                    opp["confidence_score"], 
                    current_balance,
                    volatility=volatility,
                    inner_confidence=inner_conf,
                    recent_performance=recent_performance
                )
                
                if amount <= 0:  # Skip if invalid amount
                    continue
                
                order = await self.client.place_order(
                    asset=opp["asset"],
                    amount=amount,
                    direction=direction,
                    duration=300  # 5 minutes
                )
                
                # Get payout percentage for this asset
                payout_percentage = opp.get("payout_percentage") or self.asset_payout_percentages.get(opp["asset"])
                
                # Save to database with payout percentage
                self.db.save_trade(
                    asset=opp["asset"],
                    direction=opp["signal_direction"],
                    amount=amount,
                    duration=300,
                    order_id=order.order_id,
                    signal_strength=opp["confidence_score"],
                    confidence_score=opp["confidence_score"],
                    payout_percentage=payout_percentage
                )
                
                # Log payout information if available
                payout_percentage = opp.get("payout_percentage") or self.asset_payout_percentages.get(opp["asset"])
                if payout_percentage:
                    expected_profit = amount * (payout_percentage / 100)
                    print(f"   💰 Payout: {payout_percentage:.1f}% | Expected profit if win: ${expected_profit:.2f}")
                
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
                    "analysis": opp  # Include full analysis for Telegram
                }
                positions_created.append(position_data)
                
                total_invested += amount
                
                # Enhanced decision logging
                inner_conf = opp.get('inner_confidence', 'N/A')
                inner_conf_str = f"{inner_conf:.1f}%" if isinstance(inner_conf, (int, float)) else str(inner_conf)
                macd_info = opp.get('macd', {})
                bb_info = opp.get('bollinger', {})
                
                pct_of_balance = (amount / current_balance * 100) if current_balance > 0 else 0
                print(f"💰 {opp['asset']}: ${amount:.2f} {opp['signal_direction']} ({pct_of_balance:.2f}% of balance)")
                print(f"   📊 Analysis: Confidence {opp['confidence_score']:.1f}% | Inner: {inner_conf_str}")
                volatility = opp.get('volatility', 0.0)
                if volatility > 0:
                    print(f"   📉 Volatility: {volatility:.4f} | Trend: {opp.get('trend', 'N/A')}")
                if macd_info:
                    print(f"   📈 MACD: {macd_info.get('histogram', 0):.4f} | Signal: {macd_info.get('signal', 0):.4f}")
                if bb_info:
                    print(f"   📊 Bollinger: Position {bb_info.get('position', 0.5):.2f} | Width {bb_info.get('width', 0):.2f}%")
                print(f"   ✅ Top factors: {', '.join(opp['confidence_factors'][:3])}")
                
                # Send Telegram notification
                if self.telegram:
                    try:
                        await self.telegram.send_position_signal(position_data, current_balance)
                    except Exception as e:
                        print(f"⚠️ Failed to send Telegram notification: {e}")
                
            except Exception as e:
                print(f"❌ {opp['asset']}: Failed to invest - {e}")
                import traceback
                traceback.print_exc()
        
        print(f"\n💵 Total invested: ${total_invested:.2f}")
        return {"invested": total_invested, "positions": positions_created}
    
    async def double_down_analysis(self) -> Dict:
        """Analyze existing positions and double down on losing positions with comprehensive checks"""
        print(f"\n{'='*70}")
        print(f"📈 DOUBLE-DOWN ANALYSIS PHASE")
        print(f"{'='*70}\n")
        
        doubled_down = []
        total_additional = 0.0
        
        # Get current balance for risk management
        try:
            balance = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            current_balance = balance.balance
        except:
            current_balance = self.initial_balance if self.initial_balance else 1000.0
        
        for asset, positions in self.active_positions.items():
            if not positions:
                continue
            
            # Check ALL positions, not just the first one
            # Find the most recent losing position to double down on
            losing_positions = []
            
            for idx, position in enumerate(positions):
                try:
                    order_result = await self.client.check_order_result(position["order"].order_id)
                    if not order_result:
                        continue
                    
                    profit = order_result.profit if order_result.profit is not None else 0.0
                    time_remaining = (order_result.expires_at - datetime.now()).total_seconds()
                    
                    # Check if position is losing and has enough time remaining
                    if profit < 0 and time_remaining > 60:  # At least 1 minute remaining
                        losing_positions.append({
                            "index": idx,
                            "position": position,
                            "profit": profit,
                            "time_remaining": time_remaining,
                            "order_result": order_result
                        })
                except Exception as e:
                    print(f"⚠️ {asset}: Error checking position {idx}: {e}")
                    continue
            
            if not losing_positions:
                print(f"✅ {asset}: No losing positions found")
                continue
            
            # Sort by most recent (highest index) and most losing
            losing_positions.sort(key=lambda x: (x["index"], x["profit"]))
            target_position = losing_positions[-1]  # Most recent losing position
            
            pos_info = target_position["position"]
            current_profit = target_position["profit"]
            time_remaining = target_position["time_remaining"]
            
            print(f"🔍 {asset}: Found {len(losing_positions)} losing position(s), targeting most recent")
            print(f"   💸 Current loss: ${current_profit:.2f} | Time remaining: {time_remaining/60:.1f} min")
            
            # Comprehensive checks before doubling down
            original_direction = pos_info["analysis"]["signal_direction"]
            original_order_direction = pos_info["direction"]
            
            # Check 1: Maximum positions per asset (allow up to 5, but with smart sizing)
            max_positions = 5
            if len(positions) >= max_positions:
                print(f"⏭️ {asset}: Skipping - already have {len(positions)} positions (max {max_positions})")
                continue
            
            # Check 2: Total exposure limit (max 10% of balance per asset)
            total_exposure = sum(p["amount"] for p in positions)
            max_exposure_per_asset = current_balance * 0.10
            if total_exposure >= max_exposure_per_asset:
                print(f"⏭️ {asset}: Skipping - total exposure ${total_exposure:.2f} exceeds 10% of balance")
                continue
            
            # Check 3: Calculate smart double down amount
            # Double the LAST position amount (which could be a previous double down)
            last_position_amount = positions[-1]["amount"]
            proposed_double_amount = last_position_amount * 2.0
            
            # Check 4: Ensure we can afford it (don't use more than 15% of balance for this double down)
            max_single_double = current_balance * 0.15
            double_amount = min(proposed_double_amount, max_single_double)
            
            # Check 5: Ensure total exposure after double down doesn't exceed 15% of balance
            new_total_exposure = total_exposure + double_amount
            if new_total_exposure > current_balance * 0.15:
                # Adjust double amount to stay within limit
                double_amount = max(1.0, (current_balance * 0.15) - total_exposure)
                print(f"   ⚠️ Adjusted double amount to ${double_amount:.2f} to stay within 15% limit")
            
            # Check 6: Re-analyze asset for volatility and trend
            analysis = await self.deep_analyze_asset(asset)
            if "error" in analysis:
                print(f"⏭️ {asset}: Skipping - analysis error")
                continue
            
            volatility = analysis.get("volatility", 0.0)
            trend = analysis.get("trend", "sideways")
            confidence = analysis.get("confidence_score", 0)
            
            # Check 7: Volatility check - be more cautious in high volatility
            if volatility > 0.05:  # High volatility threshold
                # Reduce double down amount in high volatility
                double_amount *= 0.7
                print(f"   ⚠️ High volatility detected ({volatility:.4f}), reducing double down by 30%")
            
            # Check 8: Time remaining check - need at least 1 minute
            if time_remaining < 60:
                print(f"⏭️ {asset}: Skipping - insufficient time remaining ({time_remaining:.0f}s)")
                continue
            
            # Check 9: Minimum amount check
            if double_amount < 1.0:
                print(f"⏭️ {asset}: Skipping - calculated amount too small (${double_amount:.2f})")
                continue
            
            # All checks passed - proceed with double down
            try:
                direction = original_order_direction
                
                order = await self.client.place_order(
                    asset=asset,
                    amount=double_amount,
                    direction=direction,
                    duration=300
                )
                
                # Get payout percentage for double down
                payout_percentage = self.asset_payout_percentages.get(asset)
                
                self.db.save_trade(
                    asset=asset,
                    direction=original_direction,
                    amount=double_amount,
                    duration=300,
                    order_id=order.order_id,
                    signal_strength=confidence,
                    confidence_score=confidence,
                    payout_percentage=payout_percentage
                )
                
                positions.append({
                    "order": order,
                    "analysis": analysis,
                    "direction": direction,
                    "amount": double_amount,
                    "timestamp": datetime.now()
                })
                
                double_down_data = {
                    "asset": asset,
                    "direction": original_direction,
                    "amount": double_amount,
                    "confidence": confidence,
                    "original_profit": current_profit,
                    "position_number": len(positions)
                }
                doubled_down.append(double_down_data)
                
                total_additional += double_amount
                
                # Enhanced double down logging
                print(f"📉 {asset}: DOUBLED DOWN ${double_amount:.2f} (Position #{len(positions)})")
                print(f"   💸 Target position losing: ${current_profit:.2f}")
                print(f"   📊 Direction: {original_direction} | Total positions: {len(positions)}")
                print(f"   💰 Total exposure: ${new_total_exposure:.2f} ({new_total_exposure/current_balance*100:.1f}% of balance)")
                print(f"   📈 Analysis: Confidence {confidence:.1f}% | Volatility: {volatility:.4f} | Trend: {trend}")
                
                # Send Telegram notification
                if self.telegram:
                    try:
                        await self.telegram.send_double_down_signal(double_down_data, current_balance)
                    except Exception as e:
                        print(f"⚠️ Failed to send Telegram notification: {e}")
                
            except Exception as e:
                print(f"❌ {asset}: Failed to double down - {e}")
                import traceback
                traceback.print_exc()
        
        if doubled_down:
            print(f"\n💵 Additional invested: ${total_additional:.2f}")
        else:
            print("⚠️ No losing positions qualified for doubling down")
        
        return {"doubled_down": len(doubled_down), "additional": total_additional}
    
    async def check_all_positions(self) -> Dict:
        """Check results of all active positions"""
        print(f"\n{'='*70}")
        print(f"📊 FINAL RESULTS")
        print(f"{'='*70}\n")
        
        # Get balance before checking results for validation
        balance_before_value = None
        try:
            balance_before = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            balance_before_value = balance_before.balance
        except:
            pass
        
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
                    # PRIMARY SOURCE OF TRUTH: OrderStatus from API
                    is_win = result.status == OrderStatus.WIN
                    is_lose = result.status == OrderStatus.LOSE
                    
                    # Get profit
                    profit = result.profit if result.profit is not None else 0.0
                    
                    # If status is CLOSED or unclear, infer from profit
                    if not is_win and not is_lose:
                        if profit > 0:
                            is_win = True
                        elif profit < 0:
                            is_lose = True
                    
                    # Final determination - trust OrderStatus
                    final_win = is_win
                    
                    # Ensure profit sign matches status
                    if is_win:
                        # WIN: profit should be positive
                        if profit <= 0:
                            # Use default payout if profit is 0 or negative
                            profit = pos_info['amount'] * 0.8  # Default 80% payout
                    elif is_lose:
                        # LOSE: profit should be negative (loss of investment)
                        if profit >= 0:
                            # Full loss if profit is 0 or positive
                            profit = -pos_info['amount']
                    
                    # Update database
                    self.db.update_trade_result(
                        order.order_id, 
                        result.status.value, 
                        profit, 
                        final_win,
                        actual_payout=result.payout
                    )
                    
                    # Count wins/losses
                    if final_win:
                        wins += 1
                    else:
                        losses += 1
                    
                    total_profit += profit
                    
                    # Display result
                    emoji = "🎉" if final_win else "❌"
                    result_text = "WIN" if final_win else "LOSS"
                    print(f"{emoji} {asset}: {result_text} ${profit:+.2f} (${pos_info['amount']:.2f} invested)")
                    print(f"   📊 Status: {result.status.value}")
                    
                    # Calculate ROI
                    if pos_info['amount'] > 0:
                        roi = (profit / pos_info['amount'] * 100)
                        print(f"   💰 ROI: {roi:+.1f}%")
                    
                    # Send Telegram notification
                    if self.telegram:
                        try:
                            result_data = {
                                "asset": asset,
                                "win": final_win,
                                "profit": profit,
                                "amount": pos_info['amount'],
                                "direction": pos_info['direction'].value if hasattr(pos_info['direction'], 'value') else str(pos_info['direction'])
                            }
                            await self.telegram.send_result_signal(result_data)
                        except Exception as e:
                            print(f"⚠️ Failed to send Telegram notification: {e}")
        
        # Validate total profit against balance change
        if balance_before_value is not None:
            try:
                await asyncio.sleep(2)  # Wait for balance to update
                balance_after = await self._get_balance_with_retry(max_retries=3, delay=1.0)
                balance_after_value = balance_after.balance
                balance_change = balance_after_value - balance_before_value
                
                if abs(total_profit - balance_change) > 0.01:
                    print(f"\n⚠️ VALIDATION: Calculated ${total_profit:.2f} vs Balance change ${balance_change:.2f} (diff: ${abs(total_profit - balance_change):.2f})")
                else:
                    print(f"\n✅ Balance validated: Profit ${total_profit:.2f} matches balance change")
            except Exception as e:
                print(f"⚠️ Could not validate balance: {e}")
        
        return {
            "total_profit": total_profit,
            "wins": wins,
            "losses": losses,
            "total_trades": wins + losses
        }
    
    async def run_5_minute_session(self, assets: List[str], assets_by_category: Dict = None, cycle_num: int = 1) -> Dict:
        """Run complete 5-minute trading session"""
        cycle_start_balance = None
        try:
            balance = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            cycle_start_balance = balance.balance
        except:
            cycle_start_balance = self.initial_balance
        
        self.session_start = datetime.now()
        session_duration = timedelta(minutes=5)  # Changed from 15 to 5 minutes
        
        print(f"\n{'='*70}")
        print(f"🚀 CYCLE {cycle_num} - 5-MINUTE DEEP ANALYSIS SESSION")  # Updated text
        print(f"{'='*70}")
        print(f"⏰ Session will run until: {(self.session_start + session_duration).strftime('%H:%M:%S')}")
        print(f"💰 Cycle Start Balance: ${cycle_start_balance:.2f}")
        print(f"🎯 Strategy: Deep analysis, high confidence only (80%+), ~2% of balance per trade")
        print(f"{'='*70}\n")
        
        # Phase 1: Initial deep analysis and investment (first 40 seconds instead of 2 minutes)
        initial_result = await self.initial_analysis_and_investment(assets, assets_by_category)
        
        if initial_result["invested"] == 0:
            print("⚠️ No initial investments made. Session ending.")
            return {"profit": 0, "wins": 0, "losses": 0, "trades": 0}
        
        # Phase 2: Monitor and double down (40 seconds to 3 minutes 20 seconds remaining)
        check_interval = 60  # Check every 1 minute instead of 3 minutes
        elapsed = (datetime.now() - self.session_start).total_seconds()
        
        # Stop 1 minute 40 seconds before end instead of 5 minutes
        while elapsed < (session_duration.total_seconds() - 100):  
            await asyncio.sleep(check_interval)
            elapsed = (datetime.now() - self.session_start).total_seconds()
            
            remaining = (session_duration.total_seconds() - elapsed) / 60
            print(f"\n⏰ {remaining:.1f} minutes remaining...")
            
            # Double down on strong positions
            await self.double_down_analysis()
        
        # Phase 3: Wait for all positions to complete (1 minute 40 seconds instead of 5 minutes)
        print(f"\n⏳ Waiting for all positions to complete...")
        await asyncio.sleep(100)  # Wait 1 minute 40 seconds for orders to complete
        
        # Phase 4: Check final results
        results = await self.check_all_positions()
        
        # Clear active positions for next cycle
        self.active_positions.clear()
        
        # Final summary
        try:
            balance = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            cycle_profit = balance.balance - cycle_start_balance
        except:
            cycle_profit = results["total_profit"]
        
        try:
            balance = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            cycle_end_balance = balance.balance
        except:
            cycle_end_balance = cycle_start_balance + cycle_profit
        
        print(f"\n{'='*70}")
        print(f"📊 CYCLE {cycle_num} SUMMARY")
        print(f"{'='*70}")
        print(f"💰 Cycle Start: ${cycle_start_balance:.2f}")
        print(f"💰 Cycle End: ${cycle_end_balance:.2f}")
        print(f"💰 Cycle Profit: ${cycle_profit:+.2f}")
        print(f"📈 Wins: {results['wins']} | Losses: {results['losses']}")
        print(f"📊 Win Rate: {(results['wins'] / results['total_trades'] * 100) if results['total_trades'] > 0 else 0:.1f}%")
        print(f"{'='*70}\n")
        
        # Send Telegram summary
        if self.telegram:
            try:
                summary_data = {
                    "cycle_num": cycle_num,
                    "profit": cycle_profit,
                    "wins": results["wins"],
                    "losses": results["losses"],
                    "trades": results["total_trades"],
                    "start_balance": cycle_start_balance,
                    "end_balance": cycle_end_balance
                }
                await self.telegram.send_summary_signal(summary_data)
            except Exception as e:
                print(f"⚠️ Failed to send Telegram summary: {e}")
        
        return {
            "profit": cycle_profit,
            "wins": results["wins"],
            "losses": results["losses"],
            "trades": results["total_trades"]
        }
    
    async def run_8_hour_session(self, assets: List[str], assets_by_category: Dict = None):
        """Run 8-hour session with multiple 5-minute cycles"""
        total_cycles = 96  # 8 hours = 480 minutes / 5 minutes = 96 cycles
        session_start = datetime.now()
        session_end = session_start + timedelta(hours=8)
        
        print(f"\n{'='*70}")
        print(f"🚀 STARTING 8-HOUR TRADING SESSION")
        print(f"{'='*70}")
        print(f"⏰ Session Start: {session_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"⏰ Session End: {session_end.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🔄 Total Cycles: {total_cycles} (5 minutes each)")
        print(f"💰 Initial Balance: ${self.initial_balance:.2f}")
        print(f"{'='*70}\n")
        
        total_profit = 0.0
        total_wins = 0
        total_losses = 0
        total_trades = 0
        
        for cycle in range(1, total_cycles + 1):
            cycle_start_time = datetime.now()
            
            # Check if we've exceeded 8 hours
            if cycle_start_time >= session_end:
                print(f"\n⏰ 8-hour session completed. Stopping.")
                break
            
            # Run 15-minute cycle
            cycle_result = await self.run_5_minute_session(assets, assets_by_category, cycle_num=cycle)
            self.cycle_results.append(cycle_result)
            
            total_profit += cycle_result.get("profit", 0)
            total_wins += cycle_result.get("wins", 0)
            total_losses += cycle_result.get("losses", 0)
            total_trades += cycle_result.get("trades", 0)
            
            # Wait a bit between cycles (except after last cycle)
            if cycle < total_cycles:
                wait_time = 30  # 30 seconds between cycles
                print(f"⏸️  Waiting {wait_time}s before next cycle...\n")
                await asyncio.sleep(wait_time)
        
        # Final session summary
        try:
            balance = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            final_balance = balance.balance
            session_profit = final_balance - self.initial_balance
        except:
            final_balance = self.initial_balance + total_profit
            session_profit = total_profit
        
        print(f"\n{'='*70}")
        print(f"🎉 8-HOUR SESSION COMPLETE")
        print(f"{'='*70}")
        print(f"💰 Initial Balance: ${self.initial_balance:.2f}")
        print(f"💰 Final Balance: ${final_balance:.2f}")
        print(f"💰 Total Profit: ${session_profit:+.2f}")
        print(f"📊 Total Trades: {total_trades}")
        print(f"📈 Total Wins: {total_wins} | Total Losses: {total_losses}")
        print(f"📊 Overall Win Rate: {(total_wins / total_trades * 100) if total_trades > 0 else 0:.1f}%")
        print(f"🔄 Cycles Completed: {len(self.cycle_results)}")
        
        # Show cycle-by-cycle breakdown
        print(f"\n📋 Cycle Breakdown:")
        for i, result in enumerate(self.cycle_results, 1):
            print(f"   Cycle {i}: ${result.get('profit', 0):+.2f} ({result.get('wins', 0)}W/{result.get('losses', 0)}L)")
        
        print(f"{'='*70}\n")


# Connection test and SSID parsing (keeping existing code)
async def test_connection(ssid: str, is_demo: bool = False, uid: int = 0, platform: int = 1) -> bool:
    print("=" * 60)
    print("🔍 Testing Connection to PocketOption...")
    print("=" * 60)
    
    client = None
    try:
        client = AsyncPocketOptionClient(ssid, is_demo=is_demo, enable_logging=False)
        print(f"📡 Connecting to {'DEMO' if is_demo else 'LIVE'} account...")
        await client.connect()
        
        if not client.is_connected:
            print("❌ Connection failed")
            return False
        
        print("✅ Connection established!")
        await asyncio.sleep(2)
        
        print("📊 Testing data retrieval...")
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


def parse_session_string(session_string: str) -> Dict[str, any]:
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
        
    except Exception as e:
        result["session_id"] = session_string
        return result


async def main():
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
        
        # Comprehensive OTC assets organized by category
        # Using actual available asset symbols from PocketOption
        otc_assets_by_category = {
            "cryptocurrencies": [
                "BTCUSD",  # Bitcoin (check if _otc version exists)
                "ETHUSD",  # Ethereum
                "LNKUSD",  # Chainlink
                "DOTUSD",  # Polkadot
                # Note: Some crypto assets may not have _otc suffix, try both
            ],
            "forex": [
                "AUDCHF_otc",  # AUD/CHF OTC
                "AUDNZD_otc",  # AUD/NZD OTC
                "AUDUSD_otc",  # AUD/USD OTC
                "AUDCAD_otc",  # AUD/CAD OTC
                "CADCHF_otc",  # CAD/CHF OTC
                "CHFJPY_otc",  # CHF/JPY OTC
                "CHFNOK_otc",  # CHF/NOK OTC
                "EURCHF_otc",  # EUR/CHF OTC
                "EURNZD_otc",  # EUR/NZD OTC
                "EURUSD_otc",  # EUR/USD OTC
                "EURGBP_otc",  # EUR/GBP OTC
                "EURJPY_otc",  # EUR/JPY OTC
                "GBPAUD_otc",  # GBP/AUD OTC
                "GBPUSD_otc",  # GBP/USD OTC
                "GBPJPY_otc",  # GBP/JPY OTC
                "USDJPY_otc",  # USD/JPY OTC
                "USDCHF_otc",  # USD/CHF OTC
                "USDCAD_otc",  # USD/CAD OTC
                "NZDUSD_otc",  # NZD/USD OTC
                "NZDJPY_otc",  # NZD/JPY OTC
            ],
            "commodities": [
                "XAUUSD_otc",  # Gold OTC
                "XAGUSD_otc",  # Silver OTC
                "UKBrent_otc",  # Brent Oil OTC
                "USCrude_otc",  # WTI Crude Oil OTC
            ],
            "stocks": [
                "#AAPL_otc",  # Apple OTC
                "#MSFT_otc",  # Microsoft OTC
                "#BA_otc",  # Boeing Company OTC
                "#VISA_otc",  # VISA OTC
                "#JNJ_otc",  # Johnson & Johnson OTC
                "#PFE_otc",  # Pfizer Inc OTC
                "#AXP_otc",  # American Express OTC
                "#CSCO_otc",  # Cisco OTC
                "#FB_otc",  # FACEBOOK INC OTC
                "#MCD_otc",  # McDonald's OTC
                "#TSLA_otc",  # Tesla OTC
                "#BABA_otc",  # Alibaba OTC
                "#AMZN_otc",  # Amazon OTC
                "#NFLX_otc",  # Netflix OTC
                "#INTC_otc",  # Intel OTC
                "#XOM_otc",  # Exxon Mobil OTC
                "#CITI_otc",  # Citigroup OTC
                "#TWITTER_otc",  # Twitter OTC
            ]
        }
        
        # Expand crypto list - try both _otc and regular versions
        crypto_base = ["BTCUSD", "ETHUSD", "LNKUSD", "DOTUSD"]
        crypto_assets = []
        for crypto in crypto_base:
            crypto_assets.append(f"{crypto}_otc")  # Try OTC version first
            crypto_assets.append(crypto)  # Fallback to regular
        
        # Remove duplicates while preserving order
        seen = set()
        unique_crypto = []
        for asset in crypto_assets:
            if asset not in seen:
                seen.add(asset)
                unique_crypto.append(asset)
        
        otc_assets_by_category["cryptocurrencies"] = unique_crypto
        
        # Flatten all assets into a single list
        otc_assets = []
        for category, assets in otc_assets_by_category.items():
            otc_assets.extend(assets)
        
        print(f"📊 Asset Categories:")
        print(f"   Cryptocurrencies: {len(otc_assets_by_category['cryptocurrencies'])} assets")
        print(f"   Forex: {len(otc_assets_by_category['forex'])} assets")
        print(f"   Commodities: {len(otc_assets_by_category['commodities'])} assets")
        print(f"   Stocks: {len(otc_assets_by_category['stocks'])} assets")
        print(f"   Total: {len(otc_assets)} assets\n")
        
        # Run 8-hour session with 5-minute cycles
        await bot.run_8_hour_session(otc_assets, otc_assets_by_category)
        
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
