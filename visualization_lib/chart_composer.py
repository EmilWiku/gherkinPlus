"""
Chart Composer - Main composer for creating complete M2 analysis visualizations
Combines all components into a modern, sales-oriented infographic
"""
from typing import Dict, Optional, List
from PIL import Image, ImageDraw, ImageFont
import io
from datetime import datetime

try:
    from .design_system import DesignSystem
    from .chart_renderer import ChartRenderer
    from .score_components import ScoreComponents
except ImportError:
    from visualization_lib.design_system import DesignSystem
    from visualization_lib.chart_renderer import ChartRenderer
    from visualization_lib.score_components import ScoreComponents

try:
    from pocketoptionapi_async.models import Candle
except ImportError:
    Candle = None  # Optional dependency


class ChartComposer:
    """
    Main composer for creating complete M2 analysis visualizations
    following 2025 infographics standards
    """
    
    def __init__(self, width: int = 1600, height: int = 1800):  # Larger canvas
        """
        Initialize the chart composer
        
        Args:
            width: Total image width
            height: Total image height
        """
        self.width = width
        self.height = height
        self.design = DesignSystem()
        self.chart_renderer = ChartRenderer(width=1200, height=500)
        self.score_components = ScoreComponents()
    
    def create_m2_visualization(self, m2_analysis: Dict, asset_name: str = "Asset") -> io.BytesIO:
        """
        Create a complete M2 analysis visualization
        
        Args:
            m2_analysis: M2 analysis result dictionary
            asset_name: Name of the asset
            
        Returns:
            BytesIO buffer containing the complete visualization image
        """
        # Create base image with beautiful gradient background
        gradient_bg = self.design.create_gradient(
            (self.width, self.height),
            '#F0F4F8',  # Very light blue-gray at top
            '#FFFFFF',  # White at bottom
            'vertical'
        )
        img = gradient_bg.copy()
        draw = ImageDraw.Draw(img)
        
        # Add subtle pattern/texture effect (very subtle grid dots)
        dot_spacing = 50
        dot_color = '#E8EDF3'  # Very light gray-blue
        for y in range(0, self.height, dot_spacing):
            for x in range(0, self.width, dot_spacing):
                draw.ellipse([x - 1, y - 1, x + 1, y + 1], fill=dot_color)
        
        # Layout sections - reduced padding for better space usage
        padding = 30
        current_y = padding
        
        # 1. Header section with title and signal badge
        header_height = self._draw_header(draw, asset_name, m2_analysis, current_y)
        
        # Draw signal badge separately - larger
        signal_direction = m2_analysis.get("signal_direction")
        if signal_direction:
            badge = self.score_components.create_signal_badge(signal_direction, size=(280, 85))
            badge_x = self.width - 310
            badge_y = current_y + 10
            if badge.mode == 'RGBA':
                img.paste(badge, (badge_x, badge_y), badge)
            else:
                img.paste(badge, (badge_x, badge_y))
        
        current_y += header_height + 20
        draw = ImageDraw.Draw(img)  # Recreate draw after image modifications
        
        # 2. Main chart section
        candles_1m = m2_analysis.get("candles_1m", [])
        current_price = m2_analysis.get("current_price", 0)
        signal_direction = m2_analysis.get("signal_direction")
        
        # Get pattern analysis for chart annotations
        pattern_analysis = m2_analysis.get("pattern_analysis", {})
        
        chart_img = self.chart_renderer.render_candlestick_chart(
            candles_1m, current_price, signal_direction, pattern_analysis
        )
        chart_y_pos = current_y
        img.paste(chart_img, (padding, chart_y_pos))
        current_y += chart_img.height + 25
        
        # 3. Score section - Main M2 score gauge (larger)
        m2_score = m2_analysis.get("m2_score", 0)
        score_gauge = self.score_components.create_score_gauge(
            m2_score, size=(280, 280), label="M2 Score"
        )
        score_x = padding + 30
        score_y = current_y + 10
        if score_gauge.mode == 'RGBA':
            img.paste(score_gauge, (score_x, score_y), score_gauge)
        else:
            img.paste(score_gauge, (score_x, score_y))
        
        # 4. Score breakdown - Progress bars (larger, better spacing)
        breakdown_start_x = score_x + 320
        breakdown_y = current_y + 40
        
        pattern_score = m2_analysis.get("pattern_score", 0)
        confirmation_score = m2_analysis.get("confirmation_score", 0)
        momentum_score = m2_analysis.get("momentum_score", 0)
        consistency_score = m2_analysis.get("consistency_score", 0)
        
        scores = [
            ("Pattern", pattern_score, 30),
            ("Confirmation", confirmation_score, 30),
            ("Momentum", momentum_score, 30),
            ("Consistency", consistency_score, 30),
        ]
        
        for i, (label, value, max_val) in enumerate(scores):
            progress_bar = self.score_components.create_progress_bar(
                value, max_val, width=450, height=45, label=label, show_value=True
            )
            if progress_bar.mode == 'RGBA':
                img.paste(progress_bar, (breakdown_start_x, breakdown_y + i * 65), progress_bar)
            else:
                img.paste(progress_bar, (breakdown_start_x, breakdown_y + i * 65))
        
        current_y += 340  # Increased for larger elements
        
        # 5. Pattern analysis cards (larger)
        pattern_section_y = current_y
        self._draw_pattern_cards(img, draw, m2_analysis, padding, pattern_section_y)
        current_y += 180  # Increased for larger cards
        
        # 6. Key metrics section - positioned to fill canvas
        metrics_y = current_y
        self._draw_key_metrics(draw, m2_analysis, padding, metrics_y)
        
        # Convert to BytesIO
        buf = io.BytesIO()
        img.save(buf, format='PNG', quality=95, optimize=True)
        buf.seek(0)
        
        return buf
    
    def _draw_header(self, draw: ImageDraw.Draw, asset_name: str, 
                    m2_analysis: Dict, y_start: int) -> int:
        """Draw header section with title and signal badge"""
        signal_direction = m2_analysis.get("signal_direction")
        m2_score = m2_analysis.get("m2_score", 0)
        
        # Title - larger
        try:
            title_font = ImageFont.truetype("arial.ttf", 48)
            subtitle_font = ImageFont.truetype("arial.ttf", 18)
        except:
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
        
        title_text = f"{asset_name} - M2 Analysis"
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        
        # Draw title
        title_x = (self.width - title_width) // 2
        draw.text((title_x, y_start), title_text,
                 fill='#1F2937', font=title_font)
        
        # Signal badge (top right) - will be drawn separately after header
        header_height = 110
        
        return header_height
    
    def _draw_pattern_cards(self, img: Image.Image, draw: ImageDraw.Draw, m2_analysis: Dict,
                           x_start: int, y_start: int):
        """Draw pattern analysis info cards"""
        pattern_analysis = m2_analysis.get("pattern_analysis", {})
        pattern_1m = pattern_analysis.get("pattern_1m", {})
        pattern_5m = pattern_analysis.get("pattern_5m", {})
        
        cards = [
            ("1m Pattern", pattern_1m.get("pattern", "N/A"), 
             f"{pattern_1m.get('direction', 'N/A')} ({pattern_1m.get('strength', 0)}%)",
             self.design.COLORS['success']['base']),
            ("5m Pattern", pattern_5m.get("pattern", "N/A"),
             f"{pattern_5m.get('direction', 'N/A')} ({pattern_5m.get('strength', 0)}%)",
             self.design.COLORS['info']['base']),
            ("Combined", pattern_analysis.get("combined_direction", "N/A").upper(),
             "Direction",
             self.design.get_direction_color(m2_analysis.get("signal_direction")).get('base', 
                                                                                       self.design.COLORS['warning']['base']))
        ]
        
        card_width = 320
        card_height = 150
        spacing = 40
        start_x = x_start + 50
        
        for i, (title, value, subtitle, color) in enumerate(cards):
            card_x = start_x + i * (card_width + spacing)
            card_img = self.score_components.create_info_card(
                title, value, size=(card_width, card_height), color=color
            )
            
            # Paste card directly onto main image
            if card_img.mode == 'RGBA':
                img.paste(card_img, (card_x, y_start), card_img)
            else:
                img.paste(card_img, (card_x, y_start))
        
        draw = ImageDraw.Draw(img)  # Recreate draw after image modifications
    
    def _draw_key_metrics(self, draw: ImageDraw.Draw, m2_analysis: Dict,
                         x_start: int, y_start: int):
        """Draw key metrics section - larger fonts"""
        try:
            label_font = ImageFont.truetype("arial.ttf", 14)
            value_font = ImageFont.truetype("arial.ttf", 20)
        except:
            label_font = ImageFont.load_default()
            value_font = ImageFont.load_default()
        
        # Current price
        current_price = m2_analysis.get("current_price", 0)
        time_placed = m2_analysis.get("time_placed", datetime.now())
        prognosis_close = m2_analysis.get("prognosis_close_time", datetime.now())
        
        metrics = [
            ("Current Price", f"${current_price:.5f}"),
            ("Time Placed", time_placed.strftime("%H:%M:%S") if isinstance(time_placed, datetime) else str(time_placed)),
            ("Prognosis Close", prognosis_close.strftime("%H:%M:%S") if isinstance(prognosis_close, datetime) else str(prognosis_close)),
        ]
        
        metric_width = 320
        spacing = 80
        start_x = x_start + 100
        
        for i, (label, value) in enumerate(metrics):
            x = start_x + i * (metric_width + spacing)
            y = y_start
            
            # Label
            label_bbox = draw.textbbox((0, 0), label, font=label_font)
            draw.text((x, y), label,
                     fill='#6B7280', font=label_font)
            
            # Value - larger font
            value_bbox = draw.textbbox((0, 0), value, font=value_font)
            value_height = value_bbox[3] - value_bbox[1]
            draw.text((x, y + 25), value,
                     fill='#1F2937', font=value_font)

