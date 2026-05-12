"""
Alternate PocketOption bot layout: candle-based signals with a smaller surface area.
"""

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "bot_app"))
sys.path.insert(0, str(_REPO / "PocketOptionAPI"))

import asyncio
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from pocketoptionapi_async import AsyncPocketOptionClient, OrderDirection
from pocketoptionapi_async.models import Candle, OrderResult, OrderStatus
from telegram_notifier import TelegramNotifier
from env_setup import get_pocket_option_ssid, load_dotenv_early, require_env


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Trading configuration"""
    # Entry criteria
    MIN_RSI_OVERSOLD = 30  # RSI below this = oversold (CALL signal)
    MAX_RSI_OVERBOUGHT = 70  # RSI above this = overbought (PUT signal)
    MIN_CONFIDENCE = 70  # Minimum confidence to trade
    
    # Position sizing (percentage of balance)
    MIN_POSITION_PCT = 0.01  # 1%
    MAX_POSITION_PCT = 0.03  # 3%
    
    # Trading settings
    TRADE_DURATION = 300  # 5 minutes in seconds
    CYCLE_INTERVAL = 300  # 5 minutes between cycles
    MAX_POSITIONS = 3  # Maximum concurrent positions
    
    # Assets to trade (using valid asset names from API constants)
    ASSETS = [
        # Forex - High payout OTC pairs
        "EURUSD_otc", "GBPUSD_otc", "USDJPY_otc",
        "AUDUSD_otc", "USDCAD_otc", "USDCHF_otc",
        "EURGBP_otc", "GBPJPY_otc", "EURJPY_otc",
        "AUDCAD_otc", "AUDCHF_otc", "AUDJPY_otc",
        "CADCHF_otc", "CADJPY_otc", "CHFJPY_otc",
        "EURCHF_otc", "EURNZD_otc", "NZDJPY_otc",
        "NZDUSD_otc",
        # Commodities
        "XAUUSD_otc",  # Gold OTC
        "XAGUSD_otc",  # Silver OTC
        # Crypto - use regular names (no _otc suffix, as per API constants)
        "BTCUSD",  # Bitcoin
        "ETHUSD",  # Ethereum
        "DOTUSD",  # Polkadot
        "LNKUSD",  # Chainlink
    ]


# ============================================================================
# TECHNICAL ANALYSIS
# ============================================================================

class TechnicalAnalysis:
    """Simple technical analysis based on candles"""
    
    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> float:
        """Calculate RSI (Relative Strength Index)"""
        if len(prices) < period + 1:
            return 50.0  # Neutral
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def calculate_sma(prices: List[float], period: int) -> float:
        """Calculate Simple Moving Average"""
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        return sum(prices[-period:]) / period
    
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        
        multiplier = 2 / (period + 1)
        ema = prices[0]
        
        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    @staticmethod
    def determine_trend(prices: List[float], short_period: int = 9, long_period: int = 21) -> str:
        """Determine trend direction using moving averages"""
        if len(prices) < long_period:
            return "neutral"
        
        sma_short = TechnicalAnalysis.calculate_sma(prices, short_period)
        sma_long = TechnicalAnalysis.calculate_sma(prices, long_period)
        current = prices[-1]
        
        if sma_short > sma_long and current > sma_short:
            return "bullish"
        elif sma_short < sma_long and current < sma_short:
            return "bearish"
        else:
            return "neutral"
    
    @staticmethod
    def analyze_asset(candles_1m: List[Candle], candles_5m: Optional[List[Candle]] = None) -> Dict:
        """
        Analyze asset and return trading signal
        
        Returns:
            Dict with: signal (CALL/PUT/None), confidence (0-100), reasons
        """
        if not candles_1m or len(candles_1m) < 30:
            return {"signal": None, "confidence": 0, "reasons": ["Insufficient data"]}
        
        closes_1m = [c.close for c in candles_1m]
        current_price = closes_1m[-1]
        
        # Calculate indicators for 1m
        rsi_1m = TechnicalAnalysis.calculate_rsi(closes_1m)
        sma_9_1m = TechnicalAnalysis.calculate_sma(closes_1m, 9)
        sma_21_1m = TechnicalAnalysis.calculate_sma(closes_1m, 21)
        ema_12_1m = TechnicalAnalysis.calculate_ema(closes_1m, 12)
        trend_1m = TechnicalAnalysis.determine_trend(closes_1m)
        
        # Calculate indicators for 5m if available
        if candles_5m and len(candles_5m) >= 21:
            closes_5m = [c.close for c in candles_5m]
            rsi_5m = TechnicalAnalysis.calculate_rsi(closes_5m)
            trend_5m = TechnicalAnalysis.determine_trend(closes_5m)
        else:
            rsi_5m = rsi_1m
            trend_5m = trend_1m
        
        # Initialize signal
        signal = None
        confidence = 0
        reasons = []
        
        # Signal 1: RSI Extremes (strong signal)
        if rsi_1m < Config.MIN_RSI_OVERSOLD and rsi_5m < 35:
            signal = "CALL"
            confidence += 40
            reasons.append(f"RSI oversold (1m: {rsi_1m:.1f}, 5m: {rsi_5m:.1f})")
        elif rsi_1m > Config.MAX_RSI_OVERBOUGHT and rsi_5m > 65:
            signal = "PUT"
            confidence += 40
            reasons.append(f"RSI overbought (1m: {rsi_1m:.1f}, 5m: {rsi_5m:.1f})")
        
        # Signal 2: Trend alignment
        if trend_1m == trend_5m and trend_1m != "neutral":
            if signal is None:
                signal = "CALL" if trend_1m == "bullish" else "PUT"
            confidence += 25
            reasons.append(f"Trend alignment: {trend_1m} (1m & 5m)")
        elif trend_1m != "neutral":
            confidence += 10
            reasons.append(f"1m trend: {trend_1m}")
        
        # Signal 3: Moving average alignment
        if current_price > sma_9_1m > sma_21_1m:
            if signal is None:
                signal = "CALL"
            elif signal == "CALL":
                confidence += 15
            reasons.append("Price above SMAs (bullish)")
        elif current_price < sma_9_1m < sma_21_1m:
            if signal is None:
                signal = "PUT"
            elif signal == "PUT":
                confidence += 15
            reasons.append("Price below SMAs (bearish)")
        
        # Signal 4: EMA crossover
        if ema_12_1m > sma_21_1m and current_price > ema_12_1m:
            if signal == "CALL":
                confidence += 10
            reasons.append("EMA bullish crossover")
        elif ema_12_1m < sma_21_1m and current_price < ema_12_1m:
            if signal == "PUT":
                confidence += 10
            reasons.append("EMA bearish crossover")
        
        # Ensure confidence is capped at 100
        confidence = min(100, confidence)
        
        return {
            "signal": signal,
            "confidence": confidence,
            "reasons": reasons,
            "rsi_1m": rsi_1m,
            "rsi_5m": rsi_5m,
            "trend_1m": trend_1m,
            "trend_5m": trend_5m,
            "current_price": current_price
        }


# ============================================================================
# TRADING BOT
# ============================================================================

class TradingBot:
    """Main trading bot"""
    
    def __init__(self, ssid: str, is_demo: bool = True, 
                 telegram_token: Optional[str] = None,
                 telegram_channel: Optional[str] = None):
        """
        Initialize trading bot
        
        Args:
            ssid: PocketOption SSID
            is_demo: Use demo account
            telegram_token: Telegram bot token (optional)
            telegram_channel: Telegram channel ID (optional)
        """
        self.client = AsyncPocketOptionClient(ssid, is_demo=is_demo, enable_logging=False)
        self.telegram = None
        if telegram_token and telegram_channel:
            self.telegram = TelegramNotifier(telegram_token, telegram_channel)
        
        self.active_positions: Dict[str, OrderResult] = {}
        self.cycle_count = 0
        
    async def connect(self):
        """Connect to PocketOption"""
        await self.client.connect()
        balance = await self.client.get_balance()
        print(f"✅ Connected! Balance: ${balance.balance:.2f} {balance.currency}")
        
        if self.telegram:
            await self.telegram.send_message(
                f"🤖 <b>Бот запущен</b>\n"
                f"💰 Баланс: ${balance.balance:.2f} {balance.currency}\n"
                f"🔄 Начало торговли..."
            )
    
    async def disconnect(self):
        """Disconnect from PocketOption"""
        if self.telegram:
            await self.telegram.close()
        await self.client.disconnect()
        print("✅ Disconnected")
    
    def calculate_position_size(self, confidence: float, balance: float) -> float:
        """Calculate position size based on confidence"""
        # Scale from MIN to MAX based on confidence
        confidence_ratio = (confidence - Config.MIN_CONFIDENCE) / (100 - Config.MIN_CONFIDENCE)
        confidence_ratio = max(0, min(1, confidence_ratio))
        
        percentage = Config.MIN_POSITION_PCT + (
            confidence_ratio * (Config.MAX_POSITION_PCT - Config.MIN_POSITION_PCT)
        )
        
        amount = balance * percentage
        return max(1.0, min(amount, balance * Config.MAX_POSITION_PCT))
    
    async def analyze_and_trade(self):
        """Analyze all assets and place trades"""
        balance = await self.client.get_balance()
        current_balance = balance.balance
        
        if len(self.active_positions) >= Config.MAX_POSITIONS:
            print(f"⏸️  Maximum positions reached ({Config.MAX_POSITIONS})")
            return
        
        print(f"\n📊 Cycle #{self.cycle_count + 1} - Analyzing {len(Config.ASSETS)} assets...")
        print(f"💰 Balance: ${current_balance:.2f} | Active positions: {len(self.active_positions)}")
        
        opportunities = []
        
        # Analyze each asset
        for asset in Config.ASSETS:
            try:
                # Skip if already trading this asset
                if asset in self.active_positions:
                    continue
                
                # Get candles
                candles_1m = await self.client.get_candles(asset, timeframe=60, count=50)
                candles_5m = await self.client.get_candles(asset, timeframe=300, count=20)
                
                if not candles_1m or len(candles_1m) < 30:
                    continue
                
                # Analyze
                analysis = TechnicalAnalysis.analyze_asset(candles_1m, candles_5m)
                
                if analysis["signal"] and analysis["confidence"] >= Config.MIN_CONFIDENCE:
                    opportunities.append({
                        "asset": asset,
                        "signal": analysis["signal"],
                        "confidence": analysis["confidence"],
                        "reasons": analysis["reasons"],
                        "rsi_1m": analysis["rsi_1m"],
                        "rsi_5m": analysis["rsi_5m"],
                        "trend_1m": analysis["trend_1m"],
                        "trend_5m": analysis["trend_5m"]
                    })
                    
            except Exception as e:
                print(f"❌ {asset}: Error - {e}")
                continue
        
        # Sort by confidence (highest first)
        opportunities.sort(key=lambda x: x["confidence"], reverse=True)
        
        # Place trades (up to MAX_POSITIONS)
        trades_placed = 0
        for opp in opportunities:
            if len(self.active_positions) >= Config.MAX_POSITIONS:
                break
            
            try:
                # Calculate position size
                amount = self.calculate_position_size(opp["confidence"], current_balance)
                
                # Determine direction
                direction = OrderDirection.CALL if opp["signal"] == "CALL" else OrderDirection.PUT
                
                # Place order
                order = await self.client.place_order(
                    asset=opp["asset"],
                    amount=amount,
                    direction=direction,
                    duration=Config.TRADE_DURATION
                )
                
                # Track position
                self.active_positions[opp["asset"]] = order
                
                # Log
                pct = (amount / current_balance * 100) if current_balance > 0 else 0
                print(f"✅ {opp['asset']}: ${amount:.2f} {opp['signal']} "
                      f"(Confidence: {opp['confidence']:.1f}%, {pct:.2f}% of balance)")
                print(f"   📈 Reasons: {', '.join(opp['reasons'][:2])}")
                
                # Telegram notification
                if self.telegram:
                    position_data = {
                        "asset": opp["asset"],
                        "direction": opp["signal"],
                        "amount": amount,
                        "confidence": opp["confidence"],
                        "order_id": order.order_id,
                        "analysis": {
                            "rsi_1m": opp["rsi_1m"],
                            "rsi_5m": opp["rsi_5m"],
                            "trend_1m": opp["trend_1m"],
                            "trend_5m": opp["trend_5m"],
                            "trend": opp["trend_1m"],  # For telegram formatting
                            "confidence_factors": opp["reasons"]  # For telegram formatting
                        }
                    }
                    await self.telegram.send_position_signal(position_data, current_balance)
                
                trades_placed += 1
                
            except Exception as e:
                print(f"❌ {opp['asset']}: Failed to place order - {e}")
                continue
        
        if trades_placed == 0:
            print("ℹ️  No trading opportunities found")
        
        self.cycle_count += 1
    
    async def check_positions(self):
        """Check active positions and update results"""
        if not self.active_positions:
            return
        
        balance = await self.client.get_balance()
        current_balance = balance.balance
        
        completed = []
        
        for asset, order in list(self.active_positions.items()):
            try:
                # Check order result
                result = await self.client.check_order_result(order.order_id)
                
                if result and result.status in [OrderStatus.WIN, OrderStatus.LOSS]:
                    # Position closed
                    completed.append({
                        "asset": asset,
                        "order": order,
                        "result": result,
                        "profit": result.profit,
                        "win": result.status == OrderStatus.WIN
                    })
                    del self.active_positions[asset]
                    
            except Exception as e:
                print(f"⚠️  {asset}: Error checking position - {e}")
                continue
        
        # Send notifications for completed trades
        for trade in completed:
            win_emoji = "🟢" if trade["win"] else "🔴"
            print(f"{win_emoji} {trade['asset']}: {'WIN' if trade['win'] else 'LOSS'} "
                  f"(${trade['profit']:+.2f})")
            
            if self.telegram:
                result_data = {
                    "asset": trade["asset"],
                    "direction": "CALL" if trade["order"].direction == OrderDirection.CALL else "PUT",
                    "profit": trade["profit"],
                    "amount": trade["order"].amount,
                    "win": trade["win"],
                    "order_id": trade["order"].order_id
                }
                await self.telegram.send_result_signal(result_data)
    
    async def run_cycle(self):
        """Run one trading cycle"""
        try:
            # Check existing positions
            await self.check_positions()
            
            # Analyze and place new trades
            await self.analyze_and_trade()
            
        except Exception as e:
            print(f"❌ Cycle error: {e}")
    
    async def run_forever(self):
        """Run trading bot continuously"""
        print("🚀 Starting trading bot...")
        print(f"📊 Assets: {len(Config.ASSETS)}")
        print(f"⏱️  Cycle interval: {Config.CYCLE_INTERVAL}s ({Config.CYCLE_INTERVAL/60:.1f} minutes)")
        print(f"💰 Position size: {Config.MIN_POSITION_PCT*100:.1f}% - {Config.MAX_POSITION_PCT*100:.1f}% of balance")
        print(f"🎯 Min confidence: {Config.MIN_CONFIDENCE}%")
        
        await self.connect()
        
        try:
            while True:
                await self.run_cycle()
                print(f"\n⏳ Waiting {Config.CYCLE_INTERVAL}s until next cycle...\n")
                await asyncio.sleep(Config.CYCLE_INTERVAL)
                
        except KeyboardInterrupt:
            print("\n⏹️  Stopping bot...")
        finally:
            await self.disconnect()


# ============================================================================
# MAIN
# ============================================================================

async def main():
    """Main entry point"""
    load_dotenv_early()
    SSID = get_pocket_option_ssid()
    IS_DEMO = False  # Set to False for real account

    telegram_token = require_env("TELEGRAM_BOT_TOKEN")
    telegram_channel = require_env("TELEGRAM_CHANNEL_ID")

    # Create and run bot
    bot = TradingBot(SSID, is_demo=IS_DEMO,
                     telegram_token=telegram_token,
                     telegram_channel=telegram_channel)

    await bot.run_forever()


if __name__ == "__main__":
    asyncio.run(main())

