"""
Fractal Visualization Module - Create chart images with fractal patterns
"""
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
from typing import List, Dict, Optional
from pocketoptionapi_async.models import Candle
from datetime import datetime
import io
import os


class FractalVisualizer:
    """Create visualizations of candles with fractal patterns"""
    
    @staticmethod
    def create_fractal_chart(candles: List[Candle], fractals: Dict, 
                            signal_direction: Optional[str] = None,
                            asset_name: str = "Asset") -> io.BytesIO:
        """
        Create a candlestick chart with fractal patterns marked.
        
        Args:
            candles: List of candle data
            fractals: Fractal data from FractalAnalyzer
            signal_direction: "CALL" or "PUT" to indicate signal
            asset_name: Name of the asset for title
        
        Returns:
            BytesIO buffer containing the image
        """
        if not candles or len(candles) < 5:
            # Return empty image if no data
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.text(0.5, 0.5, 'Insufficient data', ha='center', va='center', transform=ax.transAxes)
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            plt.close()
            buf.seek(0)
            return buf
        
        # Prepare data - ensure timestamps are datetime objects
        timestamps = []
        for c in candles:
            if isinstance(c.timestamp, datetime):
                timestamps.append(c.timestamp)
            else:
                # Try to convert if it's not already a datetime
                try:
                    if isinstance(c.timestamp, (int, float)):
                        timestamps.append(datetime.fromtimestamp(c.timestamp))
                    else:
                        timestamps.append(datetime.now())  # Fallback
                except:
                    timestamps.append(datetime.now())
        
        opens = [c.open for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        
        # Create figure
        fig, ax = plt.subplots(figsize=(12, 7))
        fig.patch.set_facecolor('#1e1e1e')
        ax.set_facecolor('#2d2d2d')
        
        # Plot candles
        for i, (ts, o, h, l, c) in enumerate(zip(timestamps, opens, highs, lows, closes)):
            color = '#26a69a' if c >= o else '#ef5350'  # Green for up, red for down
            body_bottom = min(o, c)
            body_top = max(o, c)
            body_height = abs(c - o)
            
            # Draw wick
            ax.plot([ts, ts], [l, h], color=color, linewidth=1, alpha=0.8)
            
            # Draw body
            if body_height > 0:
                ts_num = mdates.date2num(ts)
                rect = Rectangle((ts_num - 0.0003, body_bottom), 
                               0.0006, body_height, 
                               facecolor=color, edgecolor=color, alpha=0.8)
                ax.add_patch(rect)
            else:
                ax.plot([ts, ts], [l, h], color=color, linewidth=2)
        
        # Mark fractals
        bullish_fractals = fractals.get("bullish_fractals", [])
        bearish_fractals = fractals.get("bearish_fractals", [])
        
        # Mark support levels (bullish fractals)
        for fractal in bullish_fractals:
            idx = fractal["index"]
            if idx < len(candles):
                ts = candles[idx].timestamp
                price = fractal["price"]
                ax.scatter(ts, price, color='#00ff00', marker='^', s=150, 
                          zorder=5, edgecolors='white', linewidths=1.5,
                          label='Support' if fractal == bullish_fractals[0] else '')
        
        # Mark resistance levels (bearish fractals)
        for fractal in bearish_fractals:
            idx = fractal["index"]
            if idx < len(candles):
                ts = candles[idx].timestamp
                price = fractal["price"]
                ax.scatter(ts, price, color='#ff0000', marker='v', s=150, 
                          zorder=5, edgecolors='white', linewidths=1.5,
                          label='Resistance' if fractal == bearish_fractals[0] else '')
        
        # Highlight current price
        current_candle = candles[-1]
        current_price = current_candle.close
        ax.axhline(y=current_price, color='yellow', linestyle='--', linewidth=2, 
                  alpha=0.7, label='Current Price')
        
        # Formatting
        ax.set_title(f'{asset_name} - Fractal Analysis', 
                    color='white', fontsize=14, fontweight='bold', pad=15)
        ax.set_xlabel('Time', color='white', fontsize=10)
        ax.set_ylabel('Price', color='white', fontsize=10)
        
        # Format x-axis dates
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=5))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right', color='white')
        plt.setp(ax.yaxis.get_majorticklabels(), color='white')
        
        # Grid
        ax.grid(True, alpha=0.3, color='gray', linestyle='--')
        ax.spines['bottom'].set_color('white')
        ax.spines['top'].set_color('white')
        ax.spines['right'].set_color('white')
        ax.spines['left'].set_color('white')
        
        # Add signal indicator
        if signal_direction:
            signal_color = '#00ff00' if signal_direction == "CALL" else '#ff0000'
            signal_text = f'SIGNAL: {signal_direction} 🚀' if signal_direction == "CALL" else f'SIGNAL: {signal_direction} ⬇️'
            ax.text(0.02, 0.98, signal_text, transform=ax.transAxes,
                   fontsize=12, fontweight='bold', color=signal_color,
                   verticalalignment='top', bbox=dict(boxstyle='round', 
                   facecolor='black', alpha=0.7, edgecolor=signal_color, linewidth=2))
        
        # Legend
        ax.legend(loc='upper left', facecolor='black', edgecolor='white', 
                 labelcolor='white', framealpha=0.8)
        
        # Adjust layout
        plt.tight_layout()
        
        # Save to buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', 
                   facecolor='#1e1e1e', edgecolor='none')
        plt.close()
        buf.seek(0)
        
        return buf

