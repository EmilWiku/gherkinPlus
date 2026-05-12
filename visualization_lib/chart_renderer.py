"""
Chart Renderer - Modern candlestick charts with 2025 design standards
"""
from typing import List, Tuple, Optional, Dict
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import math
try:
    from .design_system import DesignSystem
except ImportError:
    from visualization_lib.design_system import DesignSystem

try:
    from pocketoptionapi_async.models import Candle
except ImportError:
    Candle = None  # Optional dependency


class ChartRenderer:
    """Render modern candlestick charts with depth and style"""
    
    def __init__(self, width: int = 1200, height: int = 400):
        self.width = width
        self.height = height
        self.design = DesignSystem()
    
    def render_candlestick_chart(self, candles: List[Candle], 
                                 current_price: float = None,
                                 signal_direction: Optional[str] = None,
                                 pattern_analysis: Optional[Dict] = None) -> Image.Image:
        """
        Render a modern candlestick chart
        
        Args:
            candles: List of Candle objects
            current_price: Current price to highlight
            signal_direction: "CALL" or "PUT" for signal indication
        """
        if not candles or len(candles) < 5:
            return self._create_empty_chart()
        
        # Create base image with white background
        chart_img = Image.new('RGB', (self.width, self.height), 
                             '#FFFFFF')  # White background
        draw = ImageDraw.Draw(chart_img)
        
        # Calculate chart area (with padding) - reduced for better space usage
        padding = 50
        chart_x = padding
        chart_y = padding
        chart_w = self.width - padding * 2
        chart_h = self.height - padding * 2
        
        # Calculate price range
        all_highs = [c.high for c in candles]
        all_lows = [c.low for c in candles]
        price_min = min(all_lows)
        price_max = max(all_highs)
        price_range = price_max - price_min
        price_padding = price_range * 0.1  # 10% padding
        price_min -= price_padding
        price_max += price_padding
        price_range = price_max - price_min
        
        # Calculate candle dimensions - make them more visible
        candle_count = len(candles)
        # Wider candles for better visibility
        candle_width = max(4, min(chart_w / candle_count * 0.8, 8))
        candle_spacing = chart_w / candle_count
        
        # Draw grid lines
        self._draw_grid(draw, chart_x, chart_y, chart_w, chart_h, price_min, price_max)
        
        # Draw candlesticks
        for i, candle in enumerate(candles):
            x_center = chart_x + (i + 0.5) * candle_spacing
            self._draw_candle(draw, candle, x_center, chart_y, chart_h,
                            candle_width, price_min, price_max)
        
        # Highlight current price
        if current_price:
            self._draw_price_line(draw, current_price, chart_x, chart_y, chart_w, chart_h,
                                 price_min, price_max, signal_direction)
        
        # Draw price labels
        self._draw_price_labels(draw, chart_x, chart_y, chart_h, price_min, price_max)
        
        # Draw pattern annotation if available
        if pattern_analysis:
            pattern_1m = pattern_analysis.get("pattern_1m", {})
            if pattern_1m:
                self._draw_pattern_annotation(draw, chart_x, chart_y, chart_w, chart_h,
                                            pattern_1m, candles, price_min, price_max)
        
        return chart_img
    
    def _draw_grid(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int,
                   price_min: float, price_max: float):
        """Draw grid lines with modern styling"""
        grid_color = '#E5E7EB'  # Light gray for white background
        text_color = '#6B7280'  # Medium gray text
        
        # Horizontal grid lines (price levels)
        num_lines = 5
        for i in range(num_lines + 1):
            y_pos = y + (h / num_lines) * i
            draw.line([(x, y_pos), (x + w, y_pos)], fill=grid_color, width=1)
    
    def _draw_candle(self, draw: ImageDraw.Draw, candle: Candle, x_center: float,
                    chart_y: int, chart_h: int, width: float,
                    price_min: float, price_max: float):
        """Draw a single candlestick with modern 3D effect"""
        price_range = price_max - price_min
        
        # Calculate positions
        high_y = chart_y + chart_h - ((candle.high - price_min) / price_range) * chart_h
        low_y = chart_y + chart_h - ((candle.low - price_min) / price_range) * chart_h
        open_y = chart_y + chart_h - ((candle.open - price_min) / price_range) * chart_h
        close_y = chart_y + chart_h - ((candle.close - price_min) / price_range) * chart_h
        
        is_bullish = candle.close >= candle.open
        color = self.design.COLORS['success']['base'] if is_bullish else self.design.COLORS['danger']['base']
        
        # Draw wick first - make it clearly visible
        wick_x = int(x_center)
        wick_width = 2
        # Draw wick
        draw.line([(wick_x, int(high_y)), (wick_x, int(low_y))], 
                 fill=color, width=wick_width)
        
        # Draw body - ensure minimum size for visibility
        body_top = min(open_y, close_y)
        body_bottom = max(open_y, close_y)
        body_center_y = (body_top + body_bottom) / 2
        body_height = abs(close_y - open_y)
        
        # For doji (very small body), draw a horizontal line
        if body_height < 2:
            body_left = int(x_center - width / 2)
            body_right = int(x_center + width / 2)
            # Draw horizontal line for doji
            draw.line([(body_left, int(body_center_y)), (body_right, int(body_center_y))],
                     fill=color, width=2)
        else:
            # Normal body
            body_left = int(x_center - width / 2)
            body_right = int(x_center + width / 2)
            
            # Ensure minimum width
            if body_right - body_left < 3:
                body_left = int(x_center - 2)
                body_right = int(x_center + 2)
            
            # Draw main body - solid color for better visibility
            draw.rectangle([body_left, int(body_top), body_right, int(body_bottom)],
                          fill=color, outline=color)
            
            # Add highlight stripe for bullish candles
            if body_height > 3 and candle.close >= candle.open:
                highlight_height = max(1, int(body_height * 0.25))
                highlight_color = tuple(min(255, c + 60) for c in self.design.hex_to_rgb(color))
                highlight_hex = self.design.rgb_to_hex(highlight_color)
                draw.rectangle([body_left, int(body_top), body_right, 
                              int(body_top + highlight_height)],
                             fill=highlight_hex)
    
    def _draw_price_line(self, draw: ImageDraw.Draw, price: float,
                        chart_x: int, chart_y: int, chart_w: int, chart_h: int,
                        price_min: float, price_max: float,
                        signal_direction: Optional[str] = None):
        """Draw current price line with price label"""
        price_range = price_max - price_min
        y_pos = chart_y + chart_h - ((price - price_min) / price_range) * chart_h
        
        # Subtle line color for white background
        line_color = '#9CA3AF'  # Medium gray
        
        # Draw subtle dashed line
        dash_length = 10
        gap_length = 5
        x = chart_x
        while x < chart_x + chart_w:
            end_x = min(x + dash_length, chart_x + chart_w)
            draw.line([(x, int(y_pos)), (end_x, int(y_pos))],
                     fill=line_color, width=1)
            x += dash_length + gap_length
        
        # Draw price label box on the right
        try:
            font = ImageFont.truetype("arial.ttf", 10)
        except:
            font = ImageFont.load_default()
        
        price_text = f"${price:.5f}"
        text_bbox = draw.textbbox((0, 0), price_text, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
        
        label_x = chart_x + chart_w - text_w - 8
        label_y = int(y_pos) - text_h // 2
        
        # Background box for label
        draw.rectangle([label_x - 4, label_y - 2, label_x + text_w + 4, label_y + text_h + 2],
                      fill='#FFFFFF', outline=line_color, width=1)
        draw.text((label_x, label_y), price_text, fill='#1F2937', font=font)
    
    def _draw_price_labels(self, draw: ImageDraw.Draw, chart_x: int, chart_y: int,
                          chart_h: int, price_min: float, price_max: float):
        """Draw price labels on the left side"""
        text_color = '#4B5563'  # Medium gray for white background
        num_labels = 5
        
        try:
            font = ImageFont.truetype("arial.ttf", 10)
        except:
            font = ImageFont.load_default()
        
        for i in range(num_labels + 1):
            ratio = i / num_labels
            price = price_max - (price_max - price_min) * ratio
            y_pos = chart_y + chart_h * ratio
            price_text = f"${price:.5f}"
            
            draw.text((chart_x - 55, y_pos - 6), price_text, fill=text_color, font=font)
    
    def _draw_pattern_annotation(self, draw: ImageDraw.Draw, chart_x: int, chart_y: int,
                                chart_w: int, chart_h: int, pattern_1m: Dict,
                                candles: List[Candle], price_min: float, price_max: float):
        """Draw pattern annotation card on chart"""
        if not candles:
            return
        
        pattern_name = pattern_1m.get("pattern", "Regular")
        pattern_dir = pattern_1m.get("direction", "neutral")
        pattern_strength = pattern_1m.get("strength", 0)
        
        # Get colors based on pattern direction
        if pattern_dir == "bullish":
            color = self.design.COLORS['success']['base']
        elif pattern_dir == "bearish":
            color = self.design.COLORS['danger']['base']
        else:
            color = self.design.COLORS['warning']['base']
        
        # Position card in upper left area - larger
        card_x = chart_x + 20
        card_y = chart_y + 15
        card_width = 220
        card_height = 85
        
        # Draw card background - clean white card for light theme
        draw.rectangle([card_x, card_y, card_x + card_width, card_y + card_height],
                      fill='#FFFFFF', outline='#E5E7EB', width=2)
        
        # Pattern name text - larger fonts
        try:
            title_font = ImageFont.truetype("arial.ttf", 14)
            value_font = ImageFont.truetype("arial.ttf", 12)
        except:
            title_font = ImageFont.load_default()
            value_font = ImageFont.load_default()
        
        pattern_text = f"{pattern_name}"
        strength_text = f"{pattern_dir.upper()} ({pattern_strength:.0f}%)"
        
        # Draw pattern name
        text_bbox = draw.textbbox((0, 0), pattern_text, font=title_font)
        text_w = text_bbox[2] - text_bbox[0]
        draw.text((card_x + (card_width - text_w) // 2, card_y + 15),
                 pattern_text, fill='#1F2937', font=title_font)
        
        # Draw strength text
        strength_bbox = draw.textbbox((0, 0), strength_text, font=value_font)
        strength_w = strength_bbox[2] - strength_bbox[0]
        draw.text((card_x + (card_width - strength_w) // 2, card_y + 40),
                 strength_text, fill='#6B7280', font=value_font)
    
    def _create_empty_chart(self) -> Image.Image:
        """Create an empty chart with message"""
        img = Image.new('RGB', (self.width, self.height), 
                       self.design.COLORS['bg']['dark'])
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype("arial.ttf", 24)
        except:
            font = ImageFont.load_default()
        
        text = "Insufficient Data"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (self.width - text_width) // 2
        y = (self.height - text_height) // 2
        
        draw.text((x, y), text, fill=self.design.COLORS['text']['secondary'], font=font)
        
        return img

