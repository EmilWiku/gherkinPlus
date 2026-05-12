"""
Generate Example Visualization
Creates a sample PNG to preview what will be sent to Telegram
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "bot_app"))
sys.path.insert(0, str(_REPO / "PocketOptionAPI"))

ARTIFACTS = _REPO / "artifacts"
ARTIFACTS.mkdir(parents=True, exist_ok=True)

try:
    from advanced_visualization import AdvancedVisualizer
    HAS_ADVANCED = True
except ImportError as e:
    print(f"Warning: Could not import AdvancedVisualizer: {e}")
    HAS_ADVANCED = False

try:
    from pocketoptionapi_async.models import Candle
except ImportError:
    # Fallback if models not available
    from dataclasses import dataclass
    from datetime import datetime
    
    @dataclass
    class Candle:
        timestamp: datetime
        open: float
        high: float
        low: float
        close: float
        asset: str
        timeframe: int

# Create sample candle data for demonstration
def create_sample_candles() -> List[Candle]:
    """Create sample candle data for visualization"""
    candles = []
    base_price = 1.08500
    current_time = datetime.now()
    
    # Generate 50 candles with realistic price movement
    import random
    random.seed(42)  # For reproducible results
    
    for i in range(50):
        timestamp = current_time - timedelta(minutes=50-i)
        
        # Simulate price movement
        price_change = random.uniform(-0.0005, 0.0005)
        base_price += price_change
        
        # Create OHLC
        open_price = base_price
        close_price = base_price + random.uniform(-0.0003, 0.0003)
        high_price = max(open_price, close_price) + random.uniform(0, 0.0002)
        low_price = min(open_price, close_price) - random.uniform(0, 0.0002)
        
        candle = Candle(
            timestamp=timestamp,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            asset="EURUSD_otc",
            timeframe=60
        )
        candles.append(candle)
    
    return candles


def create_sample_m2_analysis() -> dict:
    """Create sample M2 analysis data"""
    candles = create_sample_candles()
    
    return {
        "asset": "EURUSD_otc",
        "candles_1m": candles,
        "current_price": candles[-1].close,
        "m2_score": 78.5,
        "signal_direction": "CALL",
        "pattern_score": 22.5,
        "confirmation_score": 20.0,
        "momentum_score": 18.0,
        "consistency_score": 18.0,
        "pattern_analysis": {
            "pattern_1m": {
                "pattern": "Bullish Engulfing",
                "direction": "bullish",
                "strength": 85
            },
            "pattern_5m": {
                "pattern": "Hammer",
                "direction": "bullish",
                "strength": 70
            },
            "combined_direction": "bullish"
        },
        "time_placed": datetime.now(),
        "prognosis_close_time": datetime.now() + timedelta(minutes=5)
    }


async def main():
    """Generate example visualization PNG"""
    print("🎨 Generating example visualization...")
    
    if not HAS_ADVANCED:
        print("❌ AdvancedVisualizer not available. Please install dependencies:")
        print("   pip install plotly seaborn pandas numpy")
        return
    
    # Create sample data
    m2_analysis = create_sample_m2_analysis()
    
    # Create visualizer
    visualizer = AdvancedVisualizer(style='dark')
    
    # Generate chart (will use Plotly if available, otherwise matplotlib)
    print("📊 Creating comprehensive chart...")
    try:
        chart_buffer = visualizer.create_comprehensive_chart(m2_analysis, "EURUSD_otc")
        
        # Save to file
        output_path = str(ARTIFACTS / "example_telegram_visualization.png")
        with open(output_path, 'wb') as f:
            f.write(chart_buffer.read())
        
        print(f"✅ Example visualization saved to: {output_path}")
        
        # Also create Seaborn version if available
        try:
            print("📊 Creating Seaborn chart...")
            seaborn_buffer = visualizer.create_seaborn_chart(m2_analysis, "EURUSD_otc")
            
            output_path_seaborn = str(ARTIFACTS / "example_telegram_visualization_seaborn.png")
            with open(output_path_seaborn, 'wb') as f:
                f.write(seaborn_buffer.read())
            
            print(f"✅ Seaborn visualization saved to: {output_path_seaborn}")
        except Exception as e:
            print(f"⚠️ Could not create Seaborn chart: {e}")
        
        print("\n🎉 Example visualizations generated successfully!")
        print("   These show what will be sent to Telegram messages.")
        
    except Exception as e:
        print(f"❌ Error generating visualization: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

