"""
Confidence Scoring System
"""
from typing import List, Dict
from pocketoptionapi_async.models import Candle
from pocketoptionapi_async.utils import calculate_volatility
from technical_analysis import TechnicalAnalyzer


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
        
        # 2. RSI extreme conditions (20-25 points)
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

