"""
Refactored trading bot using a modular stages architecture.
"""
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import asyncio
import os
from pathlib import Path

import pandas as pd

from pocketoptionapi_async import AsyncPocketOptionClient
from pocketoptionapi_async.models import Balance

from config import TradingConfig
from database import TradeDatabase
from technical_analysis import TechnicalAnalyzer
from confidence_scorer import ConfidenceScorer
from risk_manager import RiskManager

from stages.testing import TestingStage, DefaultTestingStage
from stages.evaluation import EvaluationStage, DefaultEvaluationStage
from stages.order_placement import OrderPlacementStage, DefaultOrderPlacementStage
from stages.notification import NotificationStage, DefaultNotificationStage, NullNotificationStage
from stages.logging import LoggingStage, DefaultLoggingStage


class DeepTradingBot:
    """
    Main trading bot: connect, evaluate assets, size risk, place orders,
    monitor positions, notify, and log.
    """
    
    def __init__(self, ssid: str, is_demo: bool = True, 
                 telegram_bot_token: Optional[str] = None, 
                 telegram_channel_id: Optional[str] = None,
                 # Stage injections for flexibility
                 testing_stage: Optional[TestingStage] = None,
                 evaluation_stage: Optional[EvaluationStage] = None,
                 order_placement_stage: Optional[OrderPlacementStage] = None,
                 notification_stage: Optional[NotificationStage] = None,
                 logging_stage: Optional[LoggingStage] = None):
        self.ssid = ssid
        self.is_demo = is_demo
        self.client = None
        self.initial_balance = None
        
        # Core components
        self.config = TradingConfig
        db_path = os.environ.get("TRADE_DB_PATH", "artifacts/trading_metrics.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = TradeDatabase(db_path)
        self.technical_analyzer = TechnicalAnalyzer()
        self.confidence_scorer = ConfidenceScorer()
        self.risk_manager = RiskManager()
        
        # State
        self.active_positions = {}  # {asset: [position_info, ...]}
        self.asset_inner_confidence = {}  # Cache: {asset: confidence}
        self.asset_payout_percentages = {}  # Cache: {asset: payout%}
        self.historical_trades = {}  # Loaded from Excel
        self.asset_performance = {}  # Asset performance from historical data
        
        # Circuit breaker state
        self.circuit_breaker_state = {
            "consecutive_losses": 0,
            "losses_this_hour": [],
            "active": False,
            "until": None
        }
        self.session_start_balance = None
        
        # Initialize stages (use provided or defaults)
        self.testing_stage = testing_stage or DefaultTestingStage()
        self.evaluation_stage = evaluation_stage or DefaultEvaluationStage(
            self.confidence_scorer, self.technical_analyzer, self.risk_manager, self.config
        )
        self.order_placement_stage = order_placement_stage or DefaultOrderPlacementStage(self.risk_manager)
        
        # Initialize Telegram if provided
        telegram_notifier = None
        if telegram_bot_token and telegram_channel_id:
            try:
                from telegram_notifier import TelegramNotifier
                telegram_notifier = TelegramNotifier(telegram_bot_token, telegram_channel_id)
                print("✅ Telegram notifier initialized")
            except Exception as e:
                print(f"⚠️ Failed to initialize Telegram: {e}")
        
        self.notification_stage = notification_stage or (DefaultNotificationStage(telegram_notifier) if telegram_notifier else NullNotificationStage())
        self.logging_stage = logging_stage or DefaultLoggingStage()
        
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
        await self.notification_stage.close()
    
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
    
    async def find_trading_opportunities(self, assets: List[str], 
                                        assets_by_category: Optional[Dict] = None) -> List[Dict]:
        """Find and filter trading opportunities using EvaluationStage"""
        return await self.evaluation_stage.find_opportunities(
            assets, self.client, self.db, assets_by_category,
            self.asset_inner_confidence, self.asset_payout_percentages, self.asset_performance
        )
    
    async def place_trades(self, opportunities: List[Dict], 
                          assets_by_category: Optional[Dict] = None) -> Dict:
        """Place trades using OrderPlacementStage"""
        async def get_balance():
            return await self._get_balance_with_retry(max_retries=3, delay=1.0)
        
        result = await self.order_placement_stage.place_trades(
            opportunities, self.client, self.db, self.config,
            self.active_positions, self.session_start_balance,
            self.circuit_breaker_state, get_balance
        )
        
        # Send notifications for each position
        for position in result.get("positions", []):
            try:
                balance = await get_balance()
                current_balance = balance.balance if isinstance(balance, Balance) else balance
                await self.notification_stage.send_position_signal(position, current_balance)
                self.logging_stage.log_position_opened(position)
            except Exception as e:
                self.logging_stage.log_error(f"Failed to notify/log position: {e}")
        
        return result
    
    async def check_all_positions(self) -> Dict:
        """Check results using OrderPlacementStage"""
        async def get_balance():
            return await self._get_balance_with_retry(max_retries=3, delay=1.0)
        
        results = await self.order_placement_stage.check_all_positions(
            self.active_positions, self.client, self.db,
            self.notification_stage, get_balance
        )
        
        # Update circuit breaker state
        if results.get("wins", 0) > 0:
            self.circuit_breaker_state["consecutive_losses"] = 0
        if results.get("losses", 0) > 0:
            self.circuit_breaker_state["consecutive_losses"] += results["losses"]
            for _ in range(results["losses"]):
                self.circuit_breaker_state["losses_this_hour"].append(datetime.now())
        
        return results
    
    async def run_cycle(self, assets: List[str], assets_by_category: Optional[Dict] = None, 
                       cycle_num: int = 1) -> Dict:
        """Run a single 5-minute trading cycle"""
        try:
            balance = await self._get_balance_with_retry(max_retries=3, delay=1.0)
            cycle_start_balance = balance.balance
        except:
            cycle_start_balance = self.initial_balance
        
        self.logging_stage.log_cycle_start(cycle_num, cycle_start_balance)
        
        # Phase 1: Find opportunities and place trades
        opportunities = await self.find_trading_opportunities(assets, assets_by_category)
        trade_result = await self.place_trades(opportunities, assets_by_category)
        
        if trade_result["invested"] == 0:
            print("⚠️ No trades placed this cycle")
            return {"profit": 0, "wins": 0, "losses": 0, "trades": 0}
        
        # Phase 2: Monitor and double down
        session_duration = timedelta(minutes=self.config.CYCLE_DURATION_MINUTES)
        session_start = datetime.now()
        check_interval = self.config.CHECK_INTERVAL_SECONDS
        
        elapsed = (datetime.now() - session_start).total_seconds()
        stop_time = session_duration.total_seconds() - 100  # Stop 1m40s before end
        
        while elapsed < stop_time:
            await asyncio.sleep(check_interval)
            elapsed = (datetime.now() - session_start).total_seconds()
            remaining = (session_duration.total_seconds() - elapsed) / 60
            print(f"\n⏰ {remaining:.1f} minutes remaining...")
            
            async def get_balance():
                return await self._get_balance_with_retry(max_retries=3, delay=1.0)
            
            await self.order_placement_stage.double_down_analysis(
                self.active_positions, self.client, self.db, self.config,
                self.evaluation_stage, get_balance
            )
        
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
        
        self.logging_stage.log_cycle_end(cycle_num, cycle_profit, results["wins"], results["losses"])
        
        # Telegram summary
        await self.notification_stage.send_summary_signal({
            "cycle_num": cycle_num,
            "profit": cycle_profit,
            "wins": results["wins"],
            "losses": results["losses"],
            "trades": results["total_trades"],
            "start_balance": cycle_start_balance,
            "end_balance": cycle_end_balance
        })
        
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
        print(f"🔄 Cycle Duration: {self.config.CYCLE_DURATION_MINUTES} minutes each")
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

