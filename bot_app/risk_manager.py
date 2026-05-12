"""
Risk Management Module
"""
from typing import Dict, Optional, Tuple
from config import TradingConfig


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

