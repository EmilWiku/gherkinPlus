"""
M2 Criteria Analysis Module - Advanced candle pattern analysis and signal selection
M2 = Multi-Method Multi-Timeframe Analysis
"""
from typing import List, Dict, Tuple, Optional
from pocketoptionapi_async.models import Candle
from datetime import datetime, timedelta
import math


class M2Analyzer:
    """
    M2 (Multi-Method Multi-Timeframe) Analysis
    Combines multiple candle pattern recognition methods across timeframes
    to identify the strongest trading signals.
    """
    
    @staticmethod
    def identify_candle_patterns(candle: Candle, prev_candle: Optional[Candle] = None, 
                                 prev_prev_candle: Optional[Candle] = None) -> Dict:
        """
        Identify candle patterns and calculate pattern strength.
        
        Patterns analyzed:
        - Doji (indecision)
        - Hammer (bullish reversal)
        - Shooting Star (bearish reversal)
        - Engulfing (strong reversal)
        - Marubozu (strong continuation)
        - Spinning Top (indecision)
        
        Returns:
            Dict with pattern name, direction, and strength (0-100)
        """
        if not candle:
            return {"pattern": None, "direction": None, "strength": 0}
        
        body = abs(candle.close - candle.open)
        total_range = candle.high - candle.low
        upper_shadow = candle.high - max(candle.open, candle.close)
        lower_shadow = min(candle.open, candle.close) - candle.low
        
        # Avoid division by zero
        if total_range == 0:
            return {"pattern": None, "direction": None, "strength": 0}
        
        body_ratio = body / total_range
        upper_shadow_ratio = upper_shadow / total_range
        lower_shadow_ratio = lower_shadow / total_range
        is_bullish = candle.close > candle.open
        
        pattern = None
        direction = None
        strength = 0
        
        # Doji - very small body, indicates indecision
        if body_ratio < 0.1:
            pattern = "Doji"
            direction = "neutral"
            strength = 30
            # Stronger doji if shadows are small
            if upper_shadow_ratio < 0.2 and lower_shadow_ratio < 0.2:
                strength = 40
        
        # Hammer - small body at top, long lower shadow, bullish
        elif body_ratio < 0.3 and lower_shadow_ratio > 0.6 and upper_shadow_ratio < 0.2:
            pattern = "Hammer"
            direction = "bullish"
            strength = 70
            if is_bullish:
                strength = 80
        
        # Inverted Hammer / Shooting Star
        elif body_ratio < 0.3 and upper_shadow_ratio > 0.6 and lower_shadow_ratio < 0.2:
            pattern = "Shooting Star" if is_bullish else "Inverted Hammer"
            direction = "bearish" if is_bullish else "bullish"
            strength = 70 if is_bullish else 65
        
        # Engulfing patterns (need previous candle)
        elif prev_candle:
            prev_body = abs(prev_candle.close - prev_candle.open)
            prev_is_bullish = prev_candle.close > prev_candle.open
            
            # Bullish Engulfing
            if not prev_is_bullish and is_bullish and \
               candle.open < prev_candle.close and candle.close > prev_candle.open and \
               body > prev_body * 1.2:
                pattern = "Bullish Engulfing"
                direction = "bullish"
                strength = 85
                if body > prev_body * 2:
                    strength = 95
            
            # Bearish Engulfing
            elif prev_is_bullish and not is_bullish and \
                 candle.open > prev_candle.close and candle.close < prev_candle.open and \
                 body > prev_body * 1.2:
                pattern = "Bearish Engulfing"
                direction = "bearish"
                strength = 85
                if body > prev_body * 2:
                    strength = 95
        
        # Marubozu - no shadows, strong momentum
        elif body_ratio > 0.95:
            pattern = "Marubozu"
            direction = "bullish" if is_bullish else "bearish"
            strength = 80
        
        # Spinning Top - small body, equal shadows
        elif body_ratio < 0.3 and abs(upper_shadow_ratio - lower_shadow_ratio) < 0.2:
            pattern = "Spinning Top"
            direction = "neutral"
            strength = 30
        
        # Regular candle - calculate strength based on body size
        # Very generous scoring: minimum 50 for any candle with direction
        else:
            if is_bullish:
                direction = "bullish"
                # Minimum 50, maximum 80 for regular candles
                strength = max(50, min(80, 45 + int(body_ratio * 80)))  # Range: 50-80
            else:
                direction = "bearish"
                strength = max(50, min(80, 45 + int(body_ratio * 80)))  # Range: 50-80
        
        return {
            "pattern": pattern,
            "direction": direction,
            "strength": strength,
            "body_ratio": body_ratio,
            "is_bullish": is_bullish
        }
    
    @staticmethod
    def analyze_multi_timeframe_patterns(candles_1m: List[Candle], 
                                        candles_5m: List[Candle]) -> Dict:
        """
        Analyze patterns across multiple timeframes for confirmation.
        
        Returns:
            Dict with combined analysis across timeframes
        """
        if not candles_1m or len(candles_1m) < 2:
            return {"error": "Insufficient data"}
        
        # Analyze 1m timeframe
        current_1m = candles_1m[-1]
        prev_1m = candles_1m[-2] if len(candles_1m) >= 2 else None
        prev_prev_1m = candles_1m[-3] if len(candles_1m) >= 3 else None
        
        pattern_1m = M2Analyzer.identify_candle_patterns(current_1m, prev_1m, prev_prev_1m)
        
        # Analyze 5m timeframe
        pattern_5m = None
        if candles_5m and len(candles_5m) >= 2:
            current_5m = candles_5m[-1]
            prev_5m = candles_5m[-2] if len(candles_5m) >= 2 else None
            pattern_5m = M2Analyzer.identify_candle_patterns(current_5m, prev_5m)
        else:
            # Use 1m data if 5m not available
            pattern_5m = {"pattern": None, "direction": None, "strength": 0}
        
        # Multi-timeframe confirmation
        confirmation_score = 0
        combined_direction = None
        
        # Check if both timeframes agree
        if pattern_1m["direction"] and pattern_5m["direction"]:
            if pattern_1m["direction"] == pattern_5m["direction"] and \
               pattern_1m["direction"] != "neutral":
                confirmation_score = 30  # Base confirmation bonus
                combined_direction = pattern_1m["direction"]
            elif pattern_1m["direction"] != "neutral" and pattern_5m["direction"] == "neutral":
                combined_direction = pattern_1m["direction"]
                confirmation_score = 10
            elif pattern_5m["direction"] != "neutral" and pattern_1m["direction"] == "neutral":
                combined_direction = pattern_5m["direction"]
                confirmation_score = 10
        
        # Calculate combined strength
        base_strength = (pattern_1m["strength"] + pattern_5m["strength"]) / 2
        total_strength = min(100, base_strength + confirmation_score)
        
        return {
            "pattern_1m": pattern_1m,
            "pattern_5m": pattern_5m,
            "combined_direction": combined_direction,
            "combined_strength": total_strength,
            "confirmation_score": confirmation_score,
            "current_price_1m": current_1m.close,
            "current_price_5m": candles_5m[-1].close if candles_5m else current_1m.close
        }
    
    @staticmethod
    def calculate_m2_score(candles_1m: List[Candle], candles_5m: List[Candle]) -> Dict:
        """
        Calculate M2 score combining multiple criteria.
        
        M2 Criteria:
        1. Candle pattern strength (40%)
        2. Multi-timeframe confirmation (25%)
        3. Price momentum (20%)
        4. Pattern consistency (15%)
        
        Returns:
            Dict with M2 score, signal direction, and analysis details
        """
        if not candles_1m or len(candles_1m) < 5:
            return {"error": "Insufficient data"}
        
        # Get pattern analysis
        pattern_analysis = M2Analyzer.analyze_multi_timeframe_patterns(candles_1m, candles_5m)
        
        if "error" in pattern_analysis:
            return pattern_analysis
        
        # Criterion 1: Candle Pattern Strength (40 points max)
        # Use best timeframe, then boost
        pattern_1m_strength = pattern_analysis["pattern_1m"].get("strength", 0)
        pattern_5m_strength = pattern_analysis["pattern_5m"].get("strength", 0) if pattern_analysis["pattern_5m"] else 0
        max_pattern_strength = max(pattern_1m_strength, pattern_5m_strength)
        avg_pattern_strength = (pattern_1m_strength + pattern_5m_strength) / 2 if pattern_5m_strength > 0 else pattern_1m_strength
        
        # Very generous scaling: use max but boost base score
        pattern_score = (max_pattern_strength * 0.6)  # 60% of strength goes to score
        # Minimum base score for any candle with direction
        if pattern_analysis["combined_direction"] and pattern_analysis["combined_direction"] != "neutral":
            pattern_score = max(pattern_score, 20)  # At least 20 points if there's any direction
        
        # Bonus if both timeframes have decent patterns
        if pattern_1m_strength > 30 and pattern_5m_strength > 30:
            pattern_score += 8  # Bigger bonus for dual confirmation
        elif avg_pattern_strength > 30:
            pattern_score += 5  # Bonus for average quality
        
        # Criterion 2: Multi-timeframe Confirmation (25 points max)
        # Give points for any alignment
        confirmation_bonus = pattern_analysis["confirmation_score"]
        combined_dir = pattern_analysis["combined_direction"]
        
        if confirmation_bonus >= 30:  # Perfect alignment
            confirmation_score = 25
        elif confirmation_bonus >= 10:  # Partial alignment
            confirmation_score = 20  # Increased
        elif combined_dir and combined_dir != "neutral":
            # If we have any direction, give base points
            if pattern_1m_strength > 0 or pattern_5m_strength > 0:
                confirmation_score = 15  # Increased from 8
            else:
                confirmation_score = 10
        else:
            # Even neutral gets some points if patterns exist
            if pattern_1m_strength > 20 or (pattern_5m_strength and pattern_5m_strength > 20):
                confirmation_score = 5
            else:
                confirmation_score = 0
        
        # Criterion 3: Price Momentum (20 points max)
        # Give points for any movement
        momentum_score = 0
        if len(candles_1m) >= 6:
            # Compare last 3 candles vs previous 3
            recent_avg = sum(c.close for c in candles_1m[-3:]) / 3
            previous_avg = sum(c.close for c in candles_1m[-6:-3]) / 3
            momentum_pct = ((recent_avg - previous_avg) / previous_avg * 100) if previous_avg > 0 else 0
            
            combined_dir = pattern_analysis["combined_direction"]
            abs_momentum = abs(momentum_pct)
            
            if combined_dir == "bullish" and momentum_pct > 0:
                # Very generous: 0.1% move = 5 points, 0.5% = 15 points, 1% = 20 points
                momentum_score = min(20, 5 + abs_momentum * 15)
            elif combined_dir == "bearish" and momentum_pct < 0:
                momentum_score = min(20, 5 + abs_momentum * 15)
            elif combined_dir and combined_dir != "neutral":
                # Give points even if momentum is small or slightly contradictory
                if abs_momentum > 0.05:  # Any movement at all
                    momentum_score = min(15, abs_momentum * 20)
                else:
                    momentum_score = 5  # Base points for having direction
            else:
                # Even neutral gets points for any momentum
                if abs_momentum > 0.1:
                    momentum_score = 3
        
        # Criterion 4: Pattern Consistency (15 points max)
        # Very lenient: give points for any consistency
        consistency_score = 0
        if len(candles_1m) >= 5:
            # Check last 5 candles for consistent direction
            recent_candles = candles_1m[-5:] if len(candles_1m) >= 5 else candles_1m
            bullish_count = sum(1 for c in recent_candles if c.close > c.open)
            bearish_count = len(recent_candles) - bullish_count
            
            combined_dir = pattern_analysis["combined_direction"]
            
            if combined_dir == "bullish":
                if bullish_count >= 3:
                    consistency_score = (bullish_count / len(recent_candles)) * 15
                elif bullish_count >= 2:
                    consistency_score = 10  # Increased partial credit
                elif bullish_count >= 1:
                    consistency_score = 5  # Even 1 matching candle gets points
            elif combined_dir == "bearish":
                if bearish_count >= 3:
                    consistency_score = (bearish_count / len(recent_candles)) * 15
                elif bearish_count >= 2:
                    consistency_score = 10  # Increased partial credit
                elif bearish_count >= 1:
                    consistency_score = 5  # Even 1 matching candle gets points
            elif combined_dir and combined_dir != "neutral":
                # Even if direction doesn't match exactly, give base points
                consistency_score = 3
        
        # Calculate total M2 score
        m2_score = pattern_score + confirmation_score + momentum_score + consistency_score
        m2_score = min(100, max(0, m2_score))
        
        # Determine signal direction (lenient)
        signal_direction = None
        combined_dir = pattern_analysis["combined_direction"]
        # Very low threshold - just need some score and a direction
        if m2_score >= 30 and combined_dir and combined_dir != "neutral":
            if combined_dir == "bullish":
                signal_direction = "CALL"
            elif combined_dir == "bearish":
                signal_direction = "PUT"
        
        return {
            "m2_score": m2_score,
            "signal_direction": signal_direction,
            "pattern_score": pattern_score,
            "confirmation_score": confirmation_score,
            "momentum_score": momentum_score,
            "consistency_score": consistency_score,
            "pattern_analysis": pattern_analysis,
            "candles_1m": candles_1m,
            "candles_5m": candles_5m,
            "current_price": candles_1m[-1].close
        }
    
    @staticmethod
    def select_best_signals(analyses: List[Dict], top_n: int = 5, min_score: float = 65.0) -> List[Dict]:
        """
        Select the best signals based on M2 scores.
        
        Args:
            analyses: List of analysis results from calculate_m2_score
            top_n: Number of top signals to return
            min_score: Minimum M2 score required
        
        Returns:
            List of top N analyses sorted by M2 score
        """
        # Filter valid analyses with signals
        valid_signals = [
            a for a in analyses 
            if not a.get("error") and a.get("signal_direction") and a.get("m2_score", 0) >= min_score
        ]
        
        # Sort by M2 score (descending)
        valid_signals.sort(key=lambda x: x.get("m2_score", 0), reverse=True)
        
        # Return top N
        return valid_signals[:top_n]

