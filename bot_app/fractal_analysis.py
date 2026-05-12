"""
Fractal Analysis Module - Deep candle pattern analysis using fractal indicators
"""
from typing import List, Dict, Tuple, Optional
from pocketoptionapi_async.models import Candle
import math


class FractalAnalyzer:
    """
    Fractal analysis for identifying market structure, support/resistance levels,
    and potential reversal points based on candle patterns.
    """
    
    @staticmethod
    def identify_fractals(candles: List[Candle], period: int = 2) -> Dict:
        """
        Identify fractal patterns (local highs and lows).
        
        A fractal is a pattern where:
        - Bullish fractal: Low is lower than the N candles before and after
        - Bearish fractal: High is higher than the N candles before and after
        
        Args:
            candles: List of candle data
            period: Number of candles to check on each side (default 2 for 5-candle pattern)
        
        Returns:
            Dict with bullish_fractals, bearish_fractals, and fractal_points
        """
        if len(candles) < period * 2 + 1:
            return {
                "bullish_fractals": [],
                "bearish_fractals": [],
                "fractal_points": []
            }
        
        bullish_fractals = []  # Support levels (local lows)
        bearish_fractals = []  # Resistance levels (local highs)
        fractal_points = []    # All fractals with type and index
        
        for i in range(period, len(candles) - period):
            candle = candles[i]
            
            # Check for bullish fractal (support)
            is_bullish_fractal = True
            for j in range(i - period, i + period + 1):
                if j != i and candles[j].low <= candle.low:
                    is_bullish_fractal = False
                    break
            
            if is_bullish_fractal:
                bullish_fractals.append({
                    "index": i,
                    "price": candle.low,
                    "timestamp": candle.timestamp
                })
                fractal_points.append({
                    "index": i,
                    "type": "support",
                    "price": candle.low,
                    "timestamp": candle.timestamp
                })
            
            # Check for bearish fractal (resistance)
            is_bearish_fractal = True
            for j in range(i - period, i + period + 1):
                if j != i and candles[j].high >= candle.high:
                    is_bearish_fractal = False
                    break
            
            if is_bearish_fractal:
                bearish_fractals.append({
                    "index": i,
                    "price": candle.high,
                    "timestamp": candle.timestamp
                })
                fractal_points.append({
                    "index": i,
                    "type": "resistance",
                    "price": candle.high,
                    "timestamp": candle.timestamp
                })
        
        return {
            "bullish_fractals": bullish_fractals,
            "bearish_fractals": bearish_fractals,
            "fractal_points": fractal_points
        }
    
    @staticmethod
    def analyze_fractal_structure(candles: List[Candle], fractals: Dict) -> Dict:
        """
        Analyze fractal structure to determine market direction and strength.
        
        Returns:
            Dict with trend_direction, trend_strength, support_level, resistance_level,
            distance_to_support, distance_to_resistance, fractal_count
        """
        if not candles:
            return {
                "trend_direction": "neutral",
                "trend_strength": 0.0,
                "support_level": 0.0,
                "resistance_level": 0.0,
                "distance_to_support": 0.0,
                "distance_to_resistance": 0.0,
                "fractal_count": 0
            }
        
        current_price = candles[-1].close
        bullish_fractals = fractals.get("bullish_fractals", [])
        bearish_fractals = fractals.get("bearish_fractals", [])
        
        # Find nearest support and resistance
        supports = [f["price"] for f in bullish_fractals if f["price"] < current_price]
        resistances = [f["price"] for f in bearish_fractals if f["price"] > current_price]
        
        support_level = max(supports) if supports else min([c.low for c in candles[-50:]]) if candles else current_price
        resistance_level = min(resistances) if resistances else max([c.high for c in candles[-50:]]) if candles else current_price
        
        # Calculate distances
        distance_to_support = ((current_price - support_level) / current_price * 100) if current_price > 0 else 0
        distance_to_resistance = ((resistance_level - current_price) / current_price * 100) if current_price > 0 else 0
        
        # Determine trend direction based on recent fractals
        recent_bullish = [f for f in bullish_fractals if f["index"] >= len(candles) - 20]
        recent_bearish = [f for f in bearish_fractals if f["index"] >= len(candles) - 20]
        
        # Analyze trend: if making higher lows and higher highs -> bullish
        # If making lower highs and lower lows -> bearish
        trend_direction = "neutral"
        trend_strength = 0.0
        
        if len(recent_bullish) >= 2 and len(recent_bearish) >= 2:
            # Check for higher lows (bullish)
            recent_bullish_sorted = sorted(recent_bullish[-2:], key=lambda x: x["index"])
            recent_bearish_sorted = sorted(recent_bearish[-2:], key=lambda x: x["index"])
            
            if recent_bullish_sorted[-1]["price"] > recent_bullish_sorted[0]["price"]:
                trend_direction = "bullish"
                trend_strength = abs(recent_bullish_sorted[-1]["price"] - recent_bullish_sorted[0]["price"]) / current_price * 100
            elif recent_bearish_sorted[-1]["price"] < recent_bearish_sorted[0]["price"]:
                trend_direction = "bearish"
                trend_strength = abs(recent_bearish_sorted[0]["price"] - recent_bearish_sorted[-1]["price"]) / current_price * 100
        
        # Count total fractals
        fractal_count = len(bullish_fractals) + len(bearish_fractals)
        
        return {
            "trend_direction": trend_direction,
            "trend_strength": trend_strength,
            "support_level": support_level,
            "resistance_level": resistance_level,
            "distance_to_support": distance_to_support,
            "distance_to_resistance": distance_to_resistance,
            "fractal_count": fractal_count,
            "recent_bullish_fractals": len(recent_bullish),
            "recent_bearish_fractals": len(recent_bearish)
        }
    
    @staticmethod
    def calculate_fractal_confidence(candles: List[Candle], fractal_structure: Dict) -> float:
        """
        Calculate confidence score (0-100) based on fractal analysis.
        
        Higher confidence when:
        - Clear trend with multiple confirming fractals
        - Price near key support/resistance
        - Strong fractal structure
        - Multiple fractals in same direction
        
        Args:
            candles: List of candle data
            fractal_structure: Result from analyze_fractal_structure
        
        Returns:
            Confidence score 0-100
        """
        if not candles or len(candles) < 10:
            return 0.0
        
        confidence = 0.0
        current_price = candles[-1].close
        trend_direction = fractal_structure.get("trend_direction", "neutral")
        trend_strength = fractal_structure.get("trend_strength", 0.0)
        distance_to_support = fractal_structure.get("distance_to_support", 0.0)
        distance_to_resistance = fractal_structure.get("distance_to_resistance", 0.0)
        fractal_count = fractal_structure.get("fractal_count", 0)
        
        # Base confidence from trend strength (0-40 points)
        if trend_strength > 0.5:
            confidence += 40
        elif trend_strength > 0.3:
            confidence += 30
        elif trend_strength > 0.1:
            confidence += 20
        elif trend_direction != "neutral":
            confidence += 10
        
        # Confidence from fractal count (0-25 points)
        if fractal_count >= 8:
            confidence += 25
        elif fractal_count >= 6:
            confidence += 20
        elif fractal_count >= 4:
            confidence += 15
        elif fractal_count >= 2:
            confidence += 10
        
        # Confidence from proximity to key levels (0-20 points)
        # When price is near support in uptrend or near resistance in downtrend
        if trend_direction == "bullish" and distance_to_support < 0.5:
            confidence += 20  # Near support in uptrend - good buy signal
        elif trend_direction == "bearish" and distance_to_resistance < 0.5:
            confidence += 20  # Near resistance in downtrend - good sell signal
        elif trend_direction == "bullish" and distance_to_support < 1.0:
            confidence += 15
        elif trend_direction == "bearish" and distance_to_resistance < 1.0:
            confidence += 15
        
        # Confidence from recent fractal activity (0-15 points)
        recent_bullish = fractal_structure.get("recent_bullish_fractals", 0)
        recent_bearish = fractal_structure.get("recent_bearish_fractals", 0)
        
        if trend_direction == "bullish" and recent_bullish >= 2:
            confidence += 15
        elif trend_direction == "bearish" and recent_bearish >= 2:
            confidence += 15
        elif (trend_direction == "bullish" and recent_bullish >= 1) or \
             (trend_direction == "bearish" and recent_bearish >= 1):
            confidence += 10
        
        return min(100.0, max(0.0, confidence))
    
    @staticmethod
    def determine_signal_direction(candles: List[Candle], fractal_structure: Dict, 
                                   confidence: float, min_confidence: float = 75.0) -> Optional[str]:
        """
        Determine trading signal direction based on fractal analysis.
        
        Returns:
            "CALL" for bullish signal, "PUT" for bearish signal, None if confidence too low
        """
        if confidence < min_confidence:
            return None
        
        trend_direction = fractal_structure.get("trend_direction", "neutral")
        
        if trend_direction == "bullish":
            return "CALL"
        elif trend_direction == "bearish":
            return "PUT"
        
        return None

