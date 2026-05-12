"""
Order Placement Stage - Interface and implementations for placing orders
"""
import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from pocketoptionapi_async import OrderDirection
from pocketoptionapi_async.models import Balance


class OrderPlacementStage(ABC):
    """Abstract interface for order placement stage"""
    
    @abstractmethod
    async def place_trades(self, opportunities: List[Dict], client, db, config,
                          active_positions: Dict, session_start_balance: Optional[float],
                          circuit_breaker_state: Dict, get_balance_func) -> Dict:
        """
        Place trades on validated opportunities.
        
        Args:
            opportunities: List of validated trading opportunities
            client: PocketOption client
            db: Database instance
            config: TradingConfig instance
            active_positions: Dict tracking active positions
            session_start_balance: Starting balance for drawdown calculation
            circuit_breaker_state: Dict with circuit breaker state
            get_balance_func: Async function to get current balance
        
        Returns:
            Dict with invested amount and positions created
        """
        pass
    
    @abstractmethod
    async def check_circuit_breaker(self, circuit_breaker_state: Dict, config,
                                   session_start_balance: Optional[float],
                                   get_balance_func) -> Tuple[bool, str]:
        """
        Check if circuit breaker should stop trading.
        
        Returns:
            (can_trade, reason)
        """
        pass
    
    @abstractmethod
    async def double_down_analysis(self, active_positions: Dict, client, db, config,
                                  evaluation_stage, get_balance_func) -> Dict:
        """
        Analyze and execute double-down opportunities.
        
        Returns:
            Dict with doubled_down count and additional investment
        """
        pass
    
    @abstractmethod
    async def check_all_positions(self, active_positions: Dict, client, db,
                                 telegram_notifier, get_balance_func) -> Dict:
        """
        Check results of all active positions.
        
        Returns:
            Dict with total_profit, wins, losses, total_trades
        """
        pass


class DefaultOrderPlacementStage(OrderPlacementStage):
    """Default implementation of order placement stage"""
    
    def __init__(self, risk_manager):
        """
        Initialize with required components.
        
        Args:
            risk_manager: RiskManager instance
        """
        self.risk_manager = risk_manager
    
    async def check_circuit_breaker(self, circuit_breaker_state: Dict, config,
                                   session_start_balance: Optional[float],
                                   get_balance_func) -> Tuple[bool, str]:
        """Check if circuit breaker should stop trading"""
        if not config.ENABLE_CIRCUIT_BREAKER:
            return True, "Circuit breaker disabled"
        
        # Check if circuit breaker is in cooldown
        if circuit_breaker_state.get("active") and circuit_breaker_state.get("until"):
            if datetime.now() < circuit_breaker_state["until"]:
                remaining = (circuit_breaker_state["until"] - datetime.now()).total_seconds() / 60
                return False, f"Circuit breaker active - {remaining:.1f} minutes remaining"
            else:
                # Cooldown expired, reset
                circuit_breaker_state["active"] = False
                circuit_breaker_state["until"] = None
                circuit_breaker_state["consecutive_losses"] = 0
                print("✅ Circuit breaker cooldown expired - resuming trading")
        
        # Check consecutive losses
        if circuit_breaker_state.get("consecutive_losses", 0) >= config.MAX_CONSECUTIVE_LOSSES:
            circuit_breaker_state["active"] = True
            circuit_breaker_state["until"] = datetime.now() + timedelta(minutes=config.CIRCUIT_BREAKER_COOLDOWN_MINUTES)
            return False, f"Circuit breaker: {circuit_breaker_state['consecutive_losses']} consecutive losses (max: {config.MAX_CONSECUTIVE_LOSSES})"
        
        # Check losses per hour
        now = datetime.now()
        losses_this_hour = circuit_breaker_state.get("losses_this_hour", [])
        losses_this_hour = [loss_time for loss_time in losses_this_hour 
                           if (now - loss_time).total_seconds() < 3600]
        circuit_breaker_state["losses_this_hour"] = losses_this_hour
        
        if len(losses_this_hour) >= config.MAX_LOSSES_PER_HOUR:
            circuit_breaker_state["active"] = True
            circuit_breaker_state["until"] = datetime.now() + timedelta(minutes=config.CIRCUIT_BREAKER_COOLDOWN_MINUTES)
            return False, f"Circuit breaker: {len(losses_this_hour)} losses in last hour (max: {config.MAX_LOSSES_PER_HOUR})"
        
        # Drawdown check will be done in place_trades when we have balance
        
        return True, "OK"
    
    async def place_trades(self, opportunities: List[Dict], client, db, config,
                          active_positions: Dict, session_start_balance: Optional[float],
                          circuit_breaker_state: Dict, get_balance_func) -> Dict:
        """Place trades on validated opportunities"""
        if not opportunities:
            print(f"⚠️ Нет возможностей для торговли - все активы отфильтрованы")
            return {"invested": 0, "positions": []}
        
        # Check circuit breaker
        can_trade, reason = await self.check_circuit_breaker(
            circuit_breaker_state, config, session_start_balance, get_balance_func
        )
        if not can_trade:
            print(f"🛑 {reason}")
            return {"invested": 0, "positions": []}
        
        print(f"\n💰 Подготовка к размещению {len(opportunities)} сделок...")
        
        # Get current balance
        try:
            balance = await get_balance_func()
            current_balance = balance.balance if isinstance(balance, Balance) else balance
            print(f"   💵 Текущий баланс: ${current_balance:.2f}")
            
            # Check drawdown
            if session_start_balance and config.ENABLE_CIRCUIT_BREAKER:
                drawdown = (session_start_balance - current_balance) / session_start_balance
                if drawdown >= config.MAX_DRAWDOWN_PCT:
                    circuit_breaker_state["active"] = True
                    circuit_breaker_state["until"] = datetime.now() + timedelta(minutes=config.CIRCUIT_BREAKER_COOLDOWN_MINUTES)
                    print(f"🛑 Circuit breaker: {drawdown:.1%} drawdown (max: {config.MAX_DRAWDOWN_PCT:.1%})")
                    return {"invested": 0, "positions": []}
        except:
            current_balance = session_start_balance if session_start_balance else 1000.0
            print(f"   ⚠️ Не удалось получить баланс, используем: ${current_balance:.2f}")
        
        # Check total exposure
        total_exposure = sum(
            pos.get("amount", 0)
            for positions in active_positions.values()
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
            if (total_invested + total_exposure) / current_balance > config.MAX_TOTAL_EXPOSURE_PCT:
                print(f"⚠️ Reached maximum exposure limit ({config.MAX_TOTAL_EXPOSURE_PCT*100:.1f}%)")
                break
            
            try:
                # Use analysis direction directly
                signal_direction = opp["signal_direction"]
                direction = OrderDirection.CALL if signal_direction == "CALL" else OrderDirection.PUT
                
                # Calculate position size
                asset_stats = db.get_asset_stats(opp["asset"])
                amount = self.risk_manager.calculate_position_size(
                    opp["confidence_score"],
                    current_balance,
                    volatility=opp.get("volatility", 0.0),
                    inner_confidence=opp.get("inner_confidence"),
                    asset_stats=asset_stats
                )
                
                if amount <= 0:
                    continue
                
                # Place order
                order = await client.place_order(
                    asset=opp["asset"],
                    amount=amount,
                    direction=direction,
                    duration=300  # 5 minutes
                )
                
                # Save to database
                payout = opp.get("payout_percentage")
                db.save_trade(
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
                if opp["asset"] not in active_positions:
                    active_positions[opp["asset"]] = []
                
                active_positions[opp["asset"]].append({
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
                
            except Exception as e:
                print(f"❌ {opp['asset']}: Failed to invest - {e}")
        
        print(f"\n💵 Total invested: ${total_invested:.2f}")
        return {"invested": total_invested, "positions": positions_created}
    
    async def double_down_analysis(self, active_positions: Dict, client, db, config,
                                  evaluation_stage, get_balance_func) -> Dict:
        """Double down analysis - DISABLED by default"""
        if not config.ENABLE_DOUBLE_DOWN:
            return {"doubled_down": 0, "additional": 0}
        
        # Implementation would go here, but it's disabled by default
        return {"doubled_down": 0, "additional": 0}
    
    async def check_all_positions(self, active_positions: Dict, client, db,
                                 telegram_notifier, get_balance_func) -> Dict:
        """Check results of all active positions"""
        from pocketoptionapi_async.models import OrderStatus
        
        print(f"\n{'='*70}")
        print(f"📊 FINAL RESULTS")
        print(f"{'='*70}\n")
        
        balance_before = None
        try:
            balance_before = await get_balance_func()
            balance_before_value = balance_before.balance if isinstance(balance_before, Balance) else balance_before
        except:
            balance_before_value = None
        
        total_profit = 0.0
        wins = 0
        losses = 0
        
        for asset, positions in active_positions.items():
            for pos_info in positions:
                order = pos_info["order"]
                
                # Check result with retries
                result = None
                for attempt in range(10):
                    result = await client.check_order_result(order.order_id)
                    if result and result.status in [OrderStatus.WIN, OrderStatus.LOSE, OrderStatus.CLOSED]:
                        break
                    await asyncio.sleep(2)
                
                if result:
                    # Get profit
                    profit = result.profit if result.profit is not None else 0.0
                    
                    # Determine win/loss based on actual profit value
                    if profit > 0:
                        final_win = True
                    elif profit < 0:
                        final_win = False
                    else:
                        final_win = result.status == OrderStatus.WIN
                    
                    # Update database
                    db.update_trade_result(
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
                    if telegram_notifier:
                        try:
                            await telegram_notifier.send_result_signal({
                                "asset": asset,
                                "win": final_win,
                                "profit": profit,
                                "amount": pos_info['amount'],
                                "direction": pos_info['direction'].value if hasattr(pos_info['direction'], 'value') else str(pos_info['direction'])
                            })
                        except Exception:
                            pass
        
        return {
            "total_profit": total_profit,
            "wins": wins,
            "losses": losses,
            "total_trades": wins + losses
        }

