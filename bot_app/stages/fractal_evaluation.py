"""
Fractal-based Evaluation Stage - Version 2 implementation
"""
import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from fractal_analysis import FractalAnalyzer


class FractalEvaluationStage:
    """
    Fractal-based evaluation stage that analyzes candles deeply using fractal patterns.
    No historical data analysis involved.
    """
    
    def __init__(self, min_confidence: float = 75.0):
        """
        Initialize fractal evaluation stage.
        
        Args:
            min_confidence: Minimum confidence threshold to generate signal
        """
        self.fractal_analyzer = FractalAnalyzer()
        self.min_confidence = min_confidence
    
    async def analyze_asset(self, asset: str, client) -> Dict:
        """
        Analyze a single asset using fractal analysis.
        
        Args:
            asset: Asset symbol
            client: PocketOption client
        
        Returns:
            Analysis dict with signal_direction, confidence_score, and fractal data
        """
        try:
            # Get candle data - use more candles for better fractal analysis
            candles_1m = await client.get_candles(asset=asset, timeframe=60, count=100)
            candles_5m = await client.get_candles(asset=asset, timeframe=300, count=50)
            
            if not candles_1m or len(candles_1m) < 30:
                return {"error": "Insufficient data", "asset": asset}
            
            # Use 5m candles for fractal analysis (better for structure)
            analysis_candles = candles_5m if candles_5m and len(candles_5m) >= 20 else candles_1m
            
            # Identify fractals
            fractals = self.fractal_analyzer.identify_fractals(analysis_candles, period=2)
            
            # Analyze fractal structure
            fractal_structure = self.fractal_analyzer.analyze_fractal_structure(analysis_candles, fractals)
            
            # Calculate confidence
            confidence = self.fractal_analyzer.calculate_fractal_confidence(analysis_candles, fractal_structure)
            
            # Determine signal direction
            signal_direction = self.fractal_analyzer.determine_signal_direction(
                analysis_candles, fractal_structure, confidence, self.min_confidence
            )
            
            current_price = analysis_candles[-1].close
            current_time = datetime.now()
            
            # Calculate prognosis close time (5 minutes from now, standard binary option duration)
            prognosis_close_time = current_time + timedelta(minutes=5)
            
            return {
                "asset": asset,
                "signal_direction": signal_direction,
                "confidence_score": confidence,
                "current_price": current_price,
                "time_placed": current_time,
                "prognosis_close_time": prognosis_close_time,
                "fractals": fractals,
                "fractal_structure": fractal_structure,
                "candles": analysis_candles,  # For visualization
                "error": None
            }
        except Exception as e:
            return {"error": str(e), "asset": asset}
    
    async def find_opportunities(self, assets: List[str], client) -> List[Dict]:
        """
        Find trading opportunities using fractal analysis.
        
        Args:
            assets: List of asset symbols
            client: PocketOption client
        
        Returns:
            List of validated opportunities with sufficient confidence
        """
        print(f"🔍 Analyzing {len(assets)} assets using fractal analysis...")
        
        # Analyze all assets in parallel
        tasks = [self.analyze_asset(asset, client) for asset in assets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter opportunities
        opportunities = []
        
        for result in results:
            if isinstance(result, Exception):
                continue
            
            if "error" in result and result["error"]:
                continue
            
            # Only include if we have a signal direction (confidence threshold met)
            if result.get("signal_direction"):
                confidence = result.get("confidence_score", 0)
                if confidence >= self.min_confidence:
                    opportunities.append(result)
        
        # Sort by confidence (highest first)
        opportunities.sort(key=lambda x: x.get("confidence_score", 0), reverse=True)
        
        print(f"✅ Found {len(opportunities)} high-confidence fractal signals")
        
        return opportunities

