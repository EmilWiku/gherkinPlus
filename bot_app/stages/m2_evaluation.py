"""
M2 Evaluation Stage - Version 3 implementation
Selects best signals based on M2 criteria
"""
import asyncio
import os
from typing import List, Dict
from m2_analysis import M2Analyzer


class M2EvaluationStage:
    """
    M2-based evaluation stage that analyzes candles using M2 criteria
    and selects the best signals.
    """
    
    def __init__(self, min_m2_score: float = 65.0, top_signals: int = 5):
        """
        Initialize M2 evaluation stage.
        
        Args:
            min_m2_score: Minimum M2 score to consider (default 65.0)
            top_signals: Maximum number of top signals to return (default 5)
        """
        self.m2_analyzer = M2Analyzer()
        self.min_m2_score = min_m2_score
        self.top_signals = top_signals
    
    async def analyze_asset(self, asset: str, client, target_beautiful_time=None) -> Dict:
        """
        Analyze a single asset using M2 criteria.
        
        Args:
            asset: Asset symbol
            client: PocketOption client
            target_beautiful_time: Target beautiful time for signal placement (datetime, optional)
        
        Returns:
            Analysis dict with M2 score, signal direction, and analysis data
        """
        try:
            # Get candle data
            candles_1m = await client.get_candles(asset=asset, timeframe=60, count=100)
            candles_5m = await client.get_candles(asset=asset, timeframe=300, count=50)
            
            if not candles_1m or len(candles_1m) < 10:
                return {"error": "Insufficient data", "asset": asset}
            
            # Calculate M2 score
            m2_analysis = self.m2_analyzer.calculate_m2_score(candles_1m, candles_5m or [])
            
            if "error" in m2_analysis:
                return m2_analysis
            
            # Add asset and timestamp info
        except Exception as e:
            return {"error": str(e), "asset": asset}
        
        from datetime import datetime
        from beautiful_time import get_next_beautiful_time, get_beautiful_time_range, format_beautiful_time_range
        
        # Use provided target beautiful time, or calculate next one if not provided
        if target_beautiful_time:
            beautiful_start = target_beautiful_time
        else:
            current_time = datetime.now()
            beautiful_start = get_next_beautiful_time(current_time)
        
        beautiful_start, beautiful_end = get_beautiful_time_range(beautiful_start)
        
        m2_analysis["asset"] = asset
        m2_analysis["time_placed"] = beautiful_start
        m2_analysis["prognosis_close_time"] = beautiful_end
        m2_analysis["beautiful_time_range"] = format_beautiful_time_range(beautiful_start, beautiful_end)

        # First chart: strict Pocket-like M2 slice (last 50 candles).
        chart_tf = int(os.getenv("BOT_CHART_TIMEFRAME_SEC", "120"))
        chart_count = int(os.getenv("BOT_CHART_CANDLES", "50"))
        try:
            if hasattr(client, "get_pocket_m2_last_candles"):
                m2_analysis["chart_candles"] = await client.get_pocket_m2_last_candles(asset, count=chart_count)
            else:
                m2_analysis["chart_candles"] = await client.get_candles(
                    asset=asset, timeframe=chart_tf, count=chart_count
                )
            m2_analysis["chart_timeframe_sec"] = chart_tf
        except Exception:
            # Fallback to 1m slice when M2 feed is unavailable.
            m2_analysis["chart_candles"] = m2_analysis.get("candles_1m", [])[-chart_count:]
            m2_analysis["chart_timeframe_sec"] = 60

        # Chart line and price in Telegram: last *closed* bar on the chart (same as Pocket),
        # not live tick — otherwise the dashed line sits above/below the last candle body.
        cc = m2_analysis.get("chart_candles") or []
        if cc:
            last_close = float(cc[-1].close)
            m2_analysis["chart_last_close"] = last_close
            m2_analysis["current_price"] = last_close

        if hasattr(client, "get_live_price"):
            try:
                live = await client.get_live_price(asset)
                if live is not None and live > 0:
                    m2_analysis["live_quote"] = live
            except Exception:
                pass

        return m2_analysis
    
    async def find_best_opportunities(self, assets: List[str], client, target_beautiful_time=None) -> List[Dict]:
        """
        Find and select the best trading opportunities using M2 criteria.
        
        Args:
            assets: List of asset symbols
            client: PocketOption client
            target_beautiful_time: Target beautiful time for signal placement (datetime)
        
        Returns:
            List of top N best opportunities sorted by M2 score
        """
        print(f"🔍 Analyzing {len(assets)} assets using M2 criteria...")
        
        # Analyze all assets in parallel with target beautiful time
        tasks = [self.analyze_asset(asset, client, target_beautiful_time=target_beautiful_time) for asset in assets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out errors and collect debug info
        analyses = []
        error_count = 0
        
        print(f"\n{'='*70}")
        print(f"📊 DEBUG: M2 Analysis Results for All Assets")
        print(f"{'='*70}")
        
        for i, result in enumerate(results):
            asset = assets[i] if i < len(assets) else "UNKNOWN"
            
            if isinstance(result, Exception):
                print(f"❌ {asset}: Error - {str(result)[:50]}")
                error_count += 1
                continue
            
            if "error" in result and result["error"]:
                print(f"⚠️ {asset}: {result['error']}")
                error_count += 1
                continue
            
            # Get analysis data
            m2_score = result.get("m2_score", 0)
            signal_direction = result.get("signal_direction", "None")
            pattern_analysis = result.get("pattern_analysis", {})
            pattern_1m = pattern_analysis.get("pattern_1m", {})
            pattern_name = pattern_1m.get("pattern", "Regular")
            pattern_dir = pattern_1m.get("direction", "neutral")
            
            # Score breakdown
            pattern_score = result.get("pattern_score", 0)
            confirmation_score = result.get("confirmation_score", 0)
            momentum_score = result.get("momentum_score", 0)
            consistency_score = result.get("consistency_score", 0)
            
            # Status indicator
            status = "✅" if m2_score >= self.min_m2_score and signal_direction else "❌"
            
            # Print debug info
            print(f"{status} {asset}:")
            print(f"   M2 Score: {m2_score:.2f}% | Signal: {signal_direction} | Pattern: {pattern_name} ({pattern_dir})")
            print(f"   Breakdown: Pattern={pattern_score:.1f} Confirmation={confirmation_score:.1f} Momentum={momentum_score:.1f} Consistency={consistency_score:.1f}")
            
            analyses.append(result)
        
        print(f"{'='*70}")
        print(f"📈 Summary: {len(analyses)} successful analyses, {error_count} errors")
        print(f"🎯 Minimum M2 Score Required: {self.min_m2_score}%")
        print(f"{'='*70}\n")
        
        # Select best signals
        best_signals = self.m2_analyzer.select_best_signals(
            analyses, 
            top_n=self.top_signals,
            min_score=self.min_m2_score
        )
        
        if best_signals:
            print(f"✅ Selected top {len(best_signals)} signals based on M2 criteria:")
            for signal in best_signals:
                asset = signal.get("asset", "UNKNOWN")
                direction = signal.get("signal_direction", "UNKNOWN")
                m2_score = signal.get("m2_score", 0)
                pattern = signal.get("pattern_analysis", {}).get("pattern_1m", {}).get("pattern", "Unknown")
                print(f"   • {asset}: {direction} (M2 Score: {m2_score:.1f}%, Pattern: {pattern})")
        else:
            print(f"⚠️ No signals meet M2 criteria (min score: {self.min_m2_score}%)")
            # Show top 5 anyway for debugging
            if analyses:
                sorted_analyses = sorted(analyses, key=lambda x: x.get("m2_score", 0), reverse=True)
                top_5 = sorted_analyses[:5]
                print(f"\n🔍 Top 5 scores (below threshold):")
                for analysis in top_5:
                    asset = analysis.get("asset", "UNKNOWN")
                    m2_score = analysis.get("m2_score", 0)
                    signal = analysis.get("signal_direction", "None")
                    print(f"   • {asset}: {m2_score:.2f}% (Signal: {signal})")
        
        return best_signals

