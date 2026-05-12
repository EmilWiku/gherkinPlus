"""
Advanced Visualization Module
Uses modern Python visualization libraries (Plotly, Seaborn, Matplotlib)
to create beautiful, publication-quality charts for Telegram messages
"""
import io
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle, FancyBboxPatch, Circle, Wedge
from matplotlib.patches import Polygon, FancyArrowPatch
from matplotlib.colors import LinearSegmentedColormap, to_rgba
from PIL import Image
import warnings
warnings.filterwarnings('ignore')

# Optional dependencies - gracefully handle if not installed
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import seaborn as sns
    HAS_SEABORN = True
except ImportError:
    HAS_SEABORN = False

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import plotly.io as pio
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

try:
    from pocketoptionapi_async.models import Candle
except ImportError:
    Candle = None


class AdvancedVisualizer:
    """
    Advanced visualization generator using multiple libraries
    Creates beautiful, modern charts optimized for Telegram
    """
    
    # Russian translations
    RUSSIAN_TEXTS = {
        "M2 Analysis": "M2 Анализ",
        "Signal": "Сигнал",
        "M2 Score": "M2 Оценка",
        "Volume": "Объем",
        "M2 Score Breakdown": "Разбивка оценки M2",
        "Pattern Analysis": "Анализ паттернов",
        "Price Chart": "График цены",
        "Time": "Время",
        "Price": "Цена",
        "Points": "Баллы",
        "1m Pattern": "Паттерн 1м",
        "5m Pattern": "Паттерн 5м",
        "Pattern": "Паттерн",
        "Confirmation": "Подтверждение",
        "Momentum": "Импульс",
        "Consistency": "Последовательность",
        "Current": "Текущая",
    }
    
    # Modern color palette inspired by 2025 design trends
    COLORS = {
        'bg_dark': '#0F172A',      # Slate 900
        'bg_light': '#F8FAFC',     # Slate 50
        'panel': '#1E293B',         # Slate 800
        'panel_light': '#F1F5F9',   # Slate 100
        'text_primary': '#F1F5F9',  # Slate 100
        'text_secondary': '#CBD5E1', # Slate 300
        'accent_green': '#10B981',  # Emerald 500
        'accent_red': '#EF4444',     # Red 500
        'accent_blue': '#3B82F6',   # Blue 500
        'accent_purple': '#8B5CF6',  # Violet 500
        'accent_yellow': '#F59E0B',  # Amber 500
        'accent_cyan': '#06B6D4',    # Cyan 500
        'gradient_start': '#6366F1',  # Indigo 500
        'gradient_end': '#8B5CF6',    # Violet 500
    }
    
    def __init__(self, style: str = 'dark'):
        """
        Initialize visualizer
        
        Args:
            style: 'dark' or 'light' theme
        """
        self.style = style
        self._setup_style()
    
    def _setup_style(self):
        """Setup matplotlib and seaborn styles"""
        if self.style == 'dark':
            plt.style.use('dark_background')
            if HAS_SEABORN:
                sns.set_style("darkgrid", {
                    "axes.facecolor": self.COLORS['panel'],
                    "figure.facecolor": self.COLORS['bg_dark'],
                    "axes.labelcolor": self.COLORS['text_primary'],
                    "text.color": self.COLORS['text_primary'],
                })
        else:
            if HAS_SEABORN:
                plt.style.use('seaborn-v0_8-whitegrid')
                sns.set_style("whitegrid")
    
    def create_comprehensive_chart(self, m2_analysis: Dict, asset_name: str = "Asset") -> io.BytesIO:
        """
        Create a comprehensive, beautiful chart combining multiple visualizations
        
        Args:
            m2_analysis: M2 analysis result dictionary
            asset_name: Name of the asset
            
        Returns:
            BytesIO buffer containing the complete visualization
        """
        # Try Plotly first, fallback to matplotlib if not available
        if HAS_PLOTLY:
            return self._create_plotly_chart(m2_analysis, asset_name)
        else:
            return self._create_matplotlib_chart(m2_analysis, asset_name)
    
    def _create_plotly_chart(self, m2_analysis: Dict, asset_name: str) -> io.BytesIO:
        """
        Create beautiful Plotly chart and export as PNG
        """
        # Prefer M2 chart series (Pocket Option terminal alignment); else fall back to analysis M1.
        chart_series = m2_analysis.get("chart_candles") or m2_analysis.get("candles_1m", [])
        if not chart_series or len(chart_series) < 5:
            return self._create_empty_chart("Insufficient data")
        chart_tf = int(m2_analysis.get("chart_timeframe_sec", getattr(chart_series[0], "timeframe", 60))) if chart_series else 60
        tf_label = self._timeframe_label(chart_tf)

        # Prepare data
        df = self._candles_to_dataframe(chart_series[-50:])  # Last 50 bars on chart TF
        
        # Handle both DataFrame and dict
        if HAS_PANDAS and isinstance(df, pd.DataFrame):
            timestamps = df['timestamp'].tolist()
            opens = df['open'].tolist()
            highs = df['high'].tolist()
            lows = df['low'].tolist()
            closes = df['close'].tolist()
            has_volume = 'volume' in df.columns and df['volume'].notna().any()
            volumes = df['volume'].tolist() if has_volume else None
        else:
            timestamps = df['timestamp']
            opens = df['open']
            highs = df['high']
            lows = df['low']
            closes = df['close']
            has_volume = 'volume' in df
            volumes = df.get('volume') if has_volume else None

        # Horizontal line must match the last candle on this slice (same as Pocket M2).
        last_close_chart = float(closes[-1])
        current_price = last_close_chart
        
        # White premium theme for modern Telegram chart cards.
        is_light = self.style != 'dark'
        paper_bg = '#FFFFFF' if is_light else self.COLORS['bg_dark']
        panel_bg = '#F8FAFC' if is_light else self.COLORS['panel']
        text_primary = '#0F172A' if is_light else self.COLORS['text_primary']
        text_secondary = '#475569' if is_light else self.COLORS['text_secondary']
        grid_color = 'rgba(15,23,42,0.08)' if is_light else 'rgba(255,255,255,0.1)'
        template_name = 'plotly_white' if is_light else 'plotly_dark'

        # Create subplots
        fig = make_subplots(
            rows=4, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.5, 0.15, 0.15, 0.2],
            subplot_titles=('', self.RUSSIAN_TEXTS['Volume'], self.RUSSIAN_TEXTS['M2 Score Breakdown'], self.RUSSIAN_TEXTS['Pattern Analysis']),
            specs=[[{"secondary_y": False}],
                   [{"secondary_y": True}],
                   [{"secondary_y": False}],
                   [{"secondary_y": False}]]
        )
        
        # Main candlestick chart
        fig.add_trace(
            go.Candlestick(
                x=timestamps,
                open=opens,
                high=highs,
                low=lows,
                close=closes,
                name='Price',
                increasing_line_color=self.COLORS['accent_green'],
                decreasing_line_color=self.COLORS['accent_red'],
                increasing_fillcolor=self.COLORS['accent_green'],
                decreasing_fillcolor=self.COLORS['accent_red'],
                whiskerwidth=0.6,
            ),
            row=1, col=1
        )
        
        # Add current price line
        signal_direction = m2_analysis.get("signal_direction")
        
        fig.add_hline(
            y=current_price,
            line_dash="dash",
            line_color=self.COLORS['accent_yellow'],
            line_width=2,
            annotation_text=f"Закрытие последней свечи ({tf_label}): ${current_price:.5f}",
            row=1, col=1
        )
        
        # Add moving averages
        if len(closes) >= 20:
            if HAS_PANDAS and isinstance(df, pd.DataFrame):
                df['MA20'] = df['close'].rolling(window=20).mean()
                ma20_values = df['MA20'].tolist()
            else:
                # Manual MA calculation
                ma20_values = []
                for i in range(len(closes)):
                    if i < 19:
                        ma20_values.append(closes[i])
                    else:
                        ma20_values.append(sum(closes[i-19:i+1]) / 20)
            
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=ma20_values,
                    name='MA20',
                    line=dict(color=self.COLORS['accent_blue'], width=2),
                    opacity=0.7
                ),
                row=1, col=1
            )
        
        # Activity chart (Volume + synthetic market energy when volume is missing)
        bar_colors = [
            self.COLORS['accent_green'] if closes[i] >= opens[i] else self.COLORS['accent_red']
            for i in range(len(closes))
        ]
        if volumes:
            activity_values = volumes
            activity_name = self.RUSSIAN_TEXTS['Volume']
        else:
            # Synthetic "energy": combines candle range and body to avoid empty section.
            activity_values = []
            for i in range(len(closes)):
                true_range = max(0.0, highs[i] - lows[i])
                body_size = abs(closes[i] - opens[i])
                activity_values.append((true_range * 0.7 + body_size * 0.3) * 100000)
            activity_name = "Рыночная активность"

        fig.add_trace(
            go.Bar(
                x=timestamps,
                y=activity_values,
                name=activity_name,
                marker_color=bar_colors,
                opacity=0.65,
            ),
            row=2, col=1
        )

        # Add volatility trend as an additional infographic layer.
        volatility = []
        for i in range(len(closes)):
            rng = max(0.0, highs[i] - lows[i])
            base = max(1e-9, closes[i])
            volatility.append((rng / base) * 100.0)

        rolling_vol = []
        window = 8
        for i in range(len(volatility)):
            start = max(0, i - window + 1)
            part = volatility[start:i + 1]
            rolling_vol.append(sum(part) / len(part))

        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=rolling_vol,
                name='Волатильность %',
                mode='lines',
                line=dict(color=self.COLORS['accent_purple'], width=2.5, dash='dot'),
            ),
            row=2, col=1, secondary_y=True
        )
        
        # M2 Score breakdown - Horizontal bar chart
        scores = {
            self.RUSSIAN_TEXTS['Pattern']: m2_analysis.get("pattern_score", 0),
            self.RUSSIAN_TEXTS['Confirmation']: m2_analysis.get("confirmation_score", 0),
            self.RUSSIAN_TEXTS['Momentum']: m2_analysis.get("momentum_score", 0),
            self.RUSSIAN_TEXTS['Consistency']: m2_analysis.get("consistency_score", 0),
        }
        
        colors_list = [
            self.COLORS['accent_green'],
            self.COLORS['accent_blue'],
            self.COLORS['accent_yellow'],
            self.COLORS['accent_purple']
        ]
        
        fig.add_trace(
            go.Bar(
                x=list(scores.values()),
                y=list(scores.keys()),
                orientation='h',
                name='Scores',
                marker_color=colors_list,
                text=[f"{v:.1f}" for v in scores.values()],
                textposition='outside',
            ),
            row=3, col=1
        )
        
        # Pattern analysis - Gauge chart for M2 score
        m2_score = m2_analysis.get("m2_score", 0)
        pattern_analysis = m2_analysis.get("pattern_analysis", {})
        pattern_1m = pattern_analysis.get("pattern_1m", {})
        
        # Create gauge using bar chart
        fig.add_trace(
            go.Bar(
                x=['M2 Score'],
                y=[m2_score],
                name='M2 Score',
                marker=dict(
                    color=self._get_score_color(m2_score),
                    line=dict(color='#E2E8F0' if is_light else 'white', width=2)
                ),
                text=[f"{m2_score:.1f}%"],
                textposition='inside',
                textfont=dict(size=24, color='white' if not is_light else '#0F172A', family='Arial Black'),
            ),
            row=4, col=1
        )
        
        # Update layout
        signal_ru = "ВВЕРХ" if signal_direction == "CALL" else "ВНИЗ" if signal_direction == "PUT" else signal_direction or 'N/A'
        fig.update_layout(
            title=dict(
                text=f"<b>{asset_name} - {self.RUSSIAN_TEXTS['M2 Analysis']}</b> ({tf_label} · как в Pocket Option)<br>" +
                     f"<span style='color:{self.COLORS['accent_yellow']}'>{self.RUSSIAN_TEXTS['Signal']}: {signal_ru}</span> | " +
                     f"<span style='color:{self._get_score_color(m2_score)}'>{self.RUSSIAN_TEXTS['M2 Score']}: {m2_score:.1f}%</span>",
                x=0.5,
                font=dict(size=22, color=text_primary),
            ),
            height=1400,
            showlegend=True,
            template=template_name,
            paper_bgcolor=paper_bg,
            plot_bgcolor=panel_bg,
            font=dict(color=text_primary, size=13),
            xaxis_rangeslider_visible=False,
            legend=dict(
                orientation='v',
                bgcolor='rgba(255,255,255,0.75)' if is_light else 'rgba(15,23,42,0.35)',
                bordercolor='#E2E8F0' if is_light else 'rgba(255,255,255,0.1)',
                borderwidth=1,
                font=dict(color=text_secondary, size=11),
            ),
            margin=dict(l=70, r=40, t=90, b=40),
        )

        fig.update_yaxes(
            showgrid=False,
            title_text='Vol %',
            title_font=dict(color=self.COLORS['accent_purple'], size=10),
            tickfont=dict(color=self.COLORS['accent_purple'], size=10),
            row=2,
            col=1,
            secondary_y=True,
        )
        
        # Update axes
        fig.update_xaxes(
            showgrid=True,
            gridcolor=grid_color,
            tickfont=dict(color=text_secondary),
            row=1, col=1
        )
        fig.update_yaxes(
            showgrid=True,
            gridcolor=grid_color,
            tickfont=dict(color=text_secondary),
            row=1, col=1
        )
        
        # Set y-axis range for score gauge
        fig.update_yaxes(range=[0, 100], row=4, col=1)
        
        # Export to PNG
        img_bytes = pio.to_image(fig, format='png', width=1600, height=1400, scale=2)
        
        return io.BytesIO(img_bytes)
    
    def _create_matplotlib_chart(self, m2_analysis: Dict, asset_name: str = "Asset") -> io.BytesIO:
        """
        Create beautiful chart using Matplotlib (fallback when Plotly/Seaborn not available)
        """
        chart_series = m2_analysis.get("chart_candles") or m2_analysis.get("candles_1m", [])
        if not chart_series or len(chart_series) < 5:
            return self._create_empty_chart("Insufficient data")
        
        # Create figure with subplots
        fig = plt.figure(figsize=(16, 12))
        if self.style == 'dark':
            fig.patch.set_facecolor(self.COLORS['bg_dark'])
        else:
            fig.patch.set_facecolor(self.COLORS['bg_light'])
        
        gs = fig.add_gridspec(3, 2, height_ratios=[2, 1, 1], width_ratios=[2, 1],
                             hspace=0.3, wspace=0.3,
                             left=0.08, right=0.95, top=0.93, bottom=0.07)
        
        # Prepare data
        if HAS_PANDAS:
            df = self._candles_to_dataframe(chart_series[-30:])
        else:
            df = self._candles_to_dict(chart_series[-30:])
        
        # Main candlestick chart
        ax_main = fig.add_subplot(gs[0, :])
        self._plot_candlesticks_seaborn(ax_main, df, m2_analysis)
        
        # Score breakdown - Horizontal bar
        ax_scores = fig.add_subplot(gs[1, 0])
        self._plot_score_breakdown(ax_scores, m2_analysis)
        
        # M2 Score Gauge
        ax_gauge = fig.add_subplot(gs[1, 1])
        self._plot_score_gauge(ax_gauge, m2_analysis)
        
        # Pattern cards
        ax_patterns = fig.add_subplot(gs[2, :])
        self._plot_pattern_cards(ax_patterns, m2_analysis)
        
        # Save to buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=200, bbox_inches='tight',
                   facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close()
        buf.seek(0)
        
        return buf
    
    def _plot_candlesticks_seaborn(self, ax, df, m2_analysis: Dict):
        """Plot candlestick chart using Seaborn styling"""
        # Handle both DataFrame and dict
        if HAS_PANDAS and isinstance(df, pd.DataFrame):
            # DataFrame case
            for i, row in df.iterrows():
                open_price = row['open']
                high_price = row['high']
                low_price = row['low']
                close_price = row['close']
                self._plot_single_candle(ax, i, open_price, high_price, low_price, close_price)
        else:
            # Dict case
            for i in range(len(df['open'])):
                open_price = df['open'][i]
                high_price = df['high'][i]
                low_price = df['low'][i]
                close_price = df['close'][i]
                self._plot_single_candle(ax, i, open_price, high_price, low_price, close_price)
        
        # Add moving average and current price
        self._add_indicators(ax, df, m2_analysis)
    
    def _plot_single_candle(self, ax, i, open_price, high_price, low_price, close_price):
        """Plot a single candlestick"""
        color = self.COLORS['accent_green'] if close_price >= open_price else self.COLORS['accent_red']
        
        # Wick
        ax.plot([i, i], [low_price, high_price], color=color, linewidth=1.5, alpha=0.8)
        
        # Body
        body_bottom = min(open_price, close_price)
        body_top = max(open_price, close_price)
        body_height = abs(close_price - open_price)
        
        if body_height > 0:
            rect = Rectangle((i - 0.3, body_bottom), 0.6, body_height,
                           facecolor=color, edgecolor='white', linewidth=1, alpha=0.8)
            ax.add_patch(rect)
        else:
            # Doji
            ax.plot([i, i], [low_price, high_price], color=color, linewidth=2, alpha=0.6)
    
    def _add_indicators(self, ax, df, m2_analysis: Dict):
        """Add moving average and current price line"""
        # Add moving average with enhanced visual styling
        if HAS_PANDAS and isinstance(df, pd.DataFrame) and len(df) >= 20:
            df['MA20'] = df['close'].rolling(window=20).mean()
            ma20_values = df['MA20'].tolist()
            x_values = range(len(df))
        elif len(df['close']) >= 20:
            # Manual MA calculation
            closes = df['close']
            ma20_values = []
            for j in range(len(closes)):
                if j < 19:
                    ma20_values.append(closes[j])
                else:
                    ma20_values.append(sum(closes[j-19:j+1]) / 20)
            x_values = range(len(closes))
        
        if len(ma20_values) >= 20:
            # Draw MA20 with glow effect (multiple layers for depth)
            # Outer glow layer (thicker, more transparent)
            ax.plot(x_values, ma20_values, color=self.COLORS['accent_blue'],
                   linewidth=6, label='MA20', alpha=0.15, zorder=1)
            # Middle layer
            ax.plot(x_values, ma20_values, color=self.COLORS['accent_blue'],
                   linewidth=4, alpha=0.3, zorder=2)
            # Main line (thicker and more prominent)
            ax.plot(x_values, ma20_values, color=self.COLORS['accent_blue'],
                   linewidth=3, label='MA20', alpha=0.9, zorder=3,
                   linestyle='-', solid_capstyle='round')
        
        # Last candle close on the plotted slice (same visual as Pocket)
        if HAS_PANDAS and isinstance(df, pd.DataFrame):
            current_price = float(df['close'].iloc[-1])
        else:
            current_price = float(df['close'][-1])
        ax.axhline(y=current_price, color=self.COLORS['accent_yellow'],
                  linestyle='--', linewidth=2, alpha=0.8,
                  label=f"Close последней свечи: ${current_price:.5f}")
        
        # Styling
        ax.set_title(f"{m2_analysis.get('asset', 'Asset')} - {self.RUSSIAN_TEXTS['Price Chart']}", 
                    fontsize=16, fontweight='bold', color=self.COLORS['text_primary'])
        ax.set_xlabel(self.RUSSIAN_TEXTS['Time'], fontsize=12, color=self.COLORS['text_secondary'])
        ax.set_ylabel(self.RUSSIAN_TEXTS['Price'], fontsize=12, color=self.COLORS['text_secondary'])
        ax.legend(loc='upper left', facecolor=self.COLORS['panel'], 
                edgecolor='none', labelcolor=self.COLORS['text_primary'])
        ax.grid(True, alpha=0.2, color=self.COLORS['text_secondary'])
        
        if self.style == 'dark':
            ax.set_facecolor(self.COLORS['panel'])
        else:
            ax.set_facecolor(self.COLORS['panel_light'])
    
    def _plot_score_breakdown(self, ax, m2_analysis: Dict):
        """Plot score breakdown as horizontal bars"""
        scores = {
            self.RUSSIAN_TEXTS['Pattern']: m2_analysis.get("pattern_score", 0),
            self.RUSSIAN_TEXTS['Confirmation']: m2_analysis.get("confirmation_score", 0),
            self.RUSSIAN_TEXTS['Momentum']: m2_analysis.get("momentum_score", 0),
            self.RUSSIAN_TEXTS['Consistency']: m2_analysis.get("consistency_score", 0),
        }
        
        colors_list = [
            self.COLORS['accent_green'],
            self.COLORS['accent_blue'],
            self.COLORS['accent_yellow'],
            self.COLORS['accent_purple']
        ]
        
        y_pos = np.arange(len(scores))
        values = list(scores.values())
        
        bars = ax.barh(y_pos, values, color=colors_list, alpha=0.8, edgecolor='white', linewidth=1.5)
        
        # Add value labels
        for i, (bar, val) in enumerate(zip(bars, values)):
            ax.text(val + 1, i, f'{val:.1f}', va='center', 
                   fontsize=11, fontweight='bold', color=self.COLORS['text_primary'])
        
        ax.set_yticks(y_pos)
        ax.set_yticklabels(list(scores.keys()), color=self.COLORS['text_primary'])
        ax.set_xlabel(self.RUSSIAN_TEXTS['Points'], fontsize=11, color=self.COLORS['text_secondary'])
        ax.set_title(self.RUSSIAN_TEXTS['M2 Score Breakdown'], fontsize=13, fontweight='bold', 
                    color=self.COLORS['text_primary'])
        ax.set_xlim(0, max(30, max(values) * 1.2))
        ax.grid(True, alpha=0.2, axis='x', color=self.COLORS['text_secondary'])
        
        if self.style == 'dark':
            ax.set_facecolor(self.COLORS['panel'])
        else:
            ax.set_facecolor(self.COLORS['panel_light'])
    
    def _plot_score_gauge(self, ax, m2_analysis: Dict):
        """Plot M2 score as a gauge/speedometer"""
        m2_score = m2_analysis.get("m2_score", 0)
        color = self._get_score_color(m2_score)
        
        # Create gauge using pie chart
        sizes = [m2_score, 100 - m2_score]
        # Convert color to RGBA tuple for matplotlib
        from matplotlib.colors import to_rgba
        color_rgba = to_rgba(color)
        colors_gauge = [color_rgba, (0.5, 0.5, 0.5, 0.3)]  # Gray with transparency
        explode = (0.05, 0)
        
        wedges, texts = ax.pie(sizes, explode=explode, colors=colors_gauge,
                              startangle=90, counterclock=False,
                              wedgeprops=dict(width=0.5, edgecolor='white', linewidth=2))
        
        # Add center text
        ax.text(0, 0, f'{m2_score:.1f}%', ha='center', va='center',
               fontsize=32, fontweight='bold', color=self.COLORS['text_primary'])
        ax.text(0, -0.3, self.RUSSIAN_TEXTS['M2 Score'], ha='center', va='center',
               fontsize=14, color=self.COLORS['text_secondary'])
        
        ax.set_title(self.RUSSIAN_TEXTS['M2 Score'], fontsize=13, fontweight='bold',
                    color=self.COLORS['text_primary'], pad=20)
    
    def _plot_pattern_cards(self, ax, m2_analysis: Dict):
        """Plot pattern analysis as info cards"""
        pattern_analysis = m2_analysis.get("pattern_analysis", {})
        pattern_1m = pattern_analysis.get("pattern_1m", {})
        pattern_5m = pattern_analysis.get("pattern_5m", {})
        
        ax.axis('off')
        
        # Create card-like visualization
        signal_dir = m2_analysis.get("signal_direction", "N/A")
        signal_dir_ru = "ВВЕРХ" if signal_dir == "CALL" else "ВНИЗ" if signal_dir == "PUT" else signal_dir
        pattern_1m_dir = pattern_1m.get('direction', 'N/A')
        pattern_5m_dir = pattern_5m.get('direction', 'N/A')
        pattern_1m_dir_ru = "Бычий" if pattern_1m_dir == "bullish" else "Медвежий" if pattern_1m_dir == "bearish" else pattern_1m_dir
        pattern_5m_dir_ru = "Бычий" if pattern_5m_dir == "bullish" else "Медвежий" if pattern_5m_dir == "bearish" else pattern_5m_dir
        
        cards = [
            (self.RUSSIAN_TEXTS['1m Pattern'], pattern_1m.get("pattern", "N/A"), 
             f"{pattern_1m_dir_ru} ({pattern_1m.get('strength', 0)}%)",
             self.COLORS['accent_green']),
            (self.RUSSIAN_TEXTS['5m Pattern'], pattern_5m.get("pattern", "N/A"),
             f"{pattern_5m_dir_ru} ({pattern_5m.get('strength', 0)}%)",
             self.COLORS['accent_blue']),
            (self.RUSSIAN_TEXTS['Signal'], signal_dir_ru,
             f"M2: {m2_analysis.get('m2_score', 0):.1f}%",
             self._get_score_color(m2_analysis.get("m2_score", 0))),
        ]
        
        # Calculate centered positioning
        num_cards = len(cards)
        card_width = 0.28  # Slightly smaller to ensure fit
        spacing = 0.04
        total_width = num_cards * card_width + (num_cards - 1) * spacing
        start_x = (1.0 - total_width) / 2  # Center the cards
        
        for i, (title, value, subtitle, color) in enumerate(cards):
            x = start_x + i * (card_width + spacing)
            
            # Card background
            card = FancyBboxPatch((x, 0.1), card_width, 0.8,
                                 boxstyle="round,pad=0.02",
                                 facecolor=color, alpha=0.2,
                                 edgecolor=color, linewidth=2,
                                 transform=ax.transAxes)
            ax.add_patch(card)
            
            # Title
            ax.text(x + card_width/2, 0.7, title, ha='center', va='center',
                   fontsize=12, fontweight='bold', color=self.COLORS['text_primary'],
                   transform=ax.transAxes)
            
            # Value
            ax.text(x + card_width/2, 0.45, value, ha='center', va='center',
                   fontsize=14, fontweight='bold', color=color,
                   transform=ax.transAxes)
            
            # Subtitle
            ax.text(x + card_width/2, 0.25, subtitle, ha='center', va='center',
                   fontsize=10, color=self.COLORS['text_secondary'],
                   transform=ax.transAxes)
    
    def _candles_to_dataframe(self, candles: List):
        """Convert candle list to pandas DataFrame or dict"""
        data = {
            'timestamp': [c.timestamp for c in candles],
            'open': [c.open for c in candles],
            'high': [c.high for c in candles],
            'low': [c.low for c in candles],
            'close': [c.close for c in candles],
        }
        
        # Add volume if available
        if hasattr(candles[0], 'volume') and candles[0].volume is not None:
            data['volume'] = [c.volume for c in candles]
        
        if HAS_PANDAS:
            return pd.DataFrame(data)
        else:
            return data
    
    def _candles_to_dict(self, candles: List) -> dict:
        """Convert candle list to dict (fallback when pandas not available)"""
        return self._candles_to_dataframe(candles)
    
    def _get_score_color(self, score: float) -> str:
        """Get color based on score"""
        if score >= 80:
            return self.COLORS['accent_green']
        elif score >= 65:
            return self.COLORS['accent_blue']
        elif score >= 50:
            return self.COLORS['accent_yellow']
        else:
            return self.COLORS['accent_red']

    @staticmethod
    def _timeframe_label(tf_seconds: int) -> str:
        if tf_seconds < 60:
            return f"S{tf_seconds}"
        if tf_seconds % 3600 == 0:
            return f"H{tf_seconds // 3600}"
        if tf_seconds % 60 == 0:
            return f"M{tf_seconds // 60}"
        return f"{tf_seconds}s"
    
    def _create_empty_chart(self, message: str) -> io.BytesIO:
        """Create empty chart with message"""
        fig, ax = plt.subplots(figsize=(12, 8))
        if self.style == 'dark':
            fig.patch.set_facecolor(self.COLORS['bg_dark'])
            ax.set_facecolor(self.COLORS['panel'])
            text_color = self.COLORS['text_primary']
        else:
            fig.patch.set_facecolor(self.COLORS['bg_light'])
            ax.set_facecolor(self.COLORS['panel_light'])
            text_color = '#1F2937'
        
        ax.text(0.5, 0.5, message, ha='center', va='center',
               transform=ax.transAxes, fontsize=16, color=text_color, fontweight='bold')
        ax.axis('off')
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight',
                   facecolor=fig.get_facecolor())
        plt.close()
        buf.seek(0)
        return buf

