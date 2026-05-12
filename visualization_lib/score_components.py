"""
Score Visualization Components - Modern gauges, progress bars, and badges
"""
from typing import Dict, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont
import math
try:
    from .design_system import DesignSystem
except ImportError:
    from visualization_lib.design_system import DesignSystem


class ScoreComponents:
    """Create modern score visualization components"""
    
    def __init__(self):
        self.design = DesignSystem()
    
    @staticmethod
    def _draw_rounded_rectangle(draw: ImageDraw.Draw, bbox: tuple, radius: int, fill=None, outline=None, width=1):
        """Draw a rounded rectangle (compatibility helper)"""
        x1, y1, x2, y2 = bbox
        
        # Use rounded_rectangle if available (PIL 8.0.0+), otherwise draw manually
        try:
            draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)
        except (AttributeError, TypeError):
            # Fallback: draw regular rectangle (rounded_rectangle not available)
            draw.rectangle(bbox, fill=fill, outline=outline, width=width)
    
    def create_score_gauge(self, score: float, size: Tuple[int, int] = (200, 200),
                          label: str = "M2 Score") -> Image.Image:
        """
        Create a modern circular gauge/radial progress indicator
        
        Args:
            score: Score value (0-100)
            size: (width, height) tuple
            label: Label text
        """
        width, height = size
        center_x, center_y = width // 2, height // 2
        radius = min(width, height) // 2 - 20
        
        # Create image with transparency
        img = Image.new('RGBA', size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Get color based on score
        color = self.design.get_score_color(score)
        color_rgb = self.design.hex_to_rgb(color)
        
        # Draw background circle (light gray for white theme)
        bg_color = '#E5E7EB'  # Light gray
        draw.ellipse([center_x - radius, center_y - radius,
                     center_x + radius, center_y + radius],
                    outline=bg_color, width=18, fill=None)
        
        # Calculate arc for score (0 to score percentage of 360 degrees)
        # Start from top (-90 degrees), go clockwise
        score_angle = (score / 100) * 360
        start_angle = -90  # Start from top
        end_angle = start_angle + score_angle
        
        # Draw score arc using pieslice for filled arc effect
        arc_thickness = 18  # Thicker for larger gauge
        inner_radius = radius - arc_thickness
        bbox_outer = [center_x - radius, center_y - radius, center_x + radius, center_y + radius]
        bbox_inner = [center_x - inner_radius, center_y - inner_radius,
                     center_x + inner_radius, center_y + inner_radius]
        
        if score_angle > 0:
            # Draw filled pie slice
            draw.pieslice(bbox_outer, start=start_angle, end=end_angle, fill=color, outline=None)
            # Erase inner part by drawing background color
            draw.pieslice(bbox_inner, start=start_angle, end=end_angle, 
                         fill=(0, 0, 0, 0), outline=None)  # Transparent to reveal background
            # Redraw inner circle with white background
            draw.ellipse(bbox_inner, fill='#FFFFFF', outline=None)
        
        # Draw score text in center - larger fonts
        try:
            score_font = ImageFont.truetype("arial.ttf", 52)
            label_font = ImageFont.truetype("arial.ttf", 18)
        except:
            score_font = ImageFont.load_default()
            label_font = ImageFont.load_default()
        
        score_text = f"{score:.1f}%"
        bbox = draw.textbbox((0, 0), score_text, font=score_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        draw.text((center_x - text_width // 2, center_y - text_height // 2 - 12),
                 score_text, fill=color, font=score_font)
        
        # Draw label
        label_bbox = draw.textbbox((0, 0), label, font=label_font)
        label_width = label_bbox[2] - label_bbox[0]
        draw.text((center_x - label_width // 2, center_y + text_height // 2 + 12),
                 label, fill='#4B5563', font=label_font)
        
        return img
    
    def create_progress_bar(self, value: float, max_value: float = 30,
                           width: int = 250, height: int = 30,
                           label: str = "", show_value: bool = True) -> Image.Image:
        """
        Create a modern progress bar with 3D effect
        
        Args:
            value: Current value
            max_value: Maximum value
            width: Bar width
            height: Bar height
            label: Label text
            show_value: Whether to show value text
        """
        percentage = min(100, (value / max_value) * 100) if max_value > 0 else 0
        color = self.design.get_score_color(percentage)
        
        img = Image.new('RGBA', (width, height + 25 if label else height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Background - light gray for white theme
        bg_color = '#F3F4F6'  # Light gray background
        radius = height // 2
        self._draw_rounded_rectangle(draw, [0, 0, width, height], radius=radius, fill=bg_color)
        
        # Progress fill
        fill_width = int((percentage / 100) * width)
        if fill_width > 0:
            # Draw shadow for depth
            shadow_color = tuple(max(0, c - 40) for c in self.design.hex_to_rgb(color))
            self._draw_rounded_rectangle(draw, [2, 2, fill_width + 2, height + 2], 
                                  radius=radius, fill=self.design.rgb_to_hex(shadow_color))
            
            # Main fill
            self._draw_rounded_rectangle(draw, [0, 0, fill_width, height], 
                                  radius=radius, fill=color)
            
            # Highlight on top (3D effect)
            highlight_height = max(3, height // 4)
            highlight_color = tuple(min(255, c + 40) for c in self.design.hex_to_rgb(color))
            self._draw_rounded_rectangle(draw, [0, 0, fill_width, highlight_height], 
                                  radius=radius, fill=self.design.rgb_to_hex(highlight_color))
        
        # Value text - positioned outside bar for better readability (larger)
        if show_value:
            try:
                font = ImageFont.truetype("arial.ttf", 13)
            except:
                font = ImageFont.load_default()
            
            value_text = f"{value:.1f}/{max_value:.1f}"
            bbox = draw.textbbox((0, 0), value_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            text_x = width - text_width - 8  # Position to the right
            text_y = (height - text_height) // 2
            
            # Draw text in dark color for white background
            draw.text((text_x, text_y), value_text, fill='#1F2937', font=font)
        
        # Label - positioned above bar (larger)
        if label:
            try:
                label_font = ImageFont.truetype("arial.ttf", 11)
            except:
                label_font = ImageFont.load_default()
            
            draw.text((0, -18), label, 
                     fill='#4B5563', font=label_font, weight='bold')
        
        return img
    
    def create_info_card(self, title: str, value: str, 
                        size: Tuple[int, int] = (180, 100),
                        color: Optional[str] = None) -> Image.Image:
        """
        Create a modern info card with title and value
        
        Args:
            title: Card title
            value: Card value
            size: (width, height) tuple
            color: Accent color (optional)
        """
        width, height = size
        img = Image.new('RGBA', size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Background - clean white card
        bg_color = '#FFFFFF'
        radius = 8
        self._draw_rounded_rectangle(draw, [0, 0, width, height], radius=radius, fill=bg_color)
        
        # Border with accent color
        if color:
            border_width = 2
            self._draw_rounded_rectangle(draw, [border_width // 2, border_width // 2,
                                   width - border_width // 2, height - border_width // 2],
                                  radius=radius, outline=color, width=border_width)
        
        # Title - larger font
        try:
            title_font = ImageFont.truetype("arial.ttf", 11)
            value_font = ImageFont.truetype("arial.ttf", 24)
        except:
            title_font = ImageFont.load_default()
            value_font = ImageFont.load_default()
        
        # Center title text manually
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]
        title_h = title_bbox[3] - title_bbox[1]
        draw.text((width // 2 - title_w // 2, 12), title, 
                 fill='#6B7280',
                 font=title_font)
        
        # Value - larger and centered
        value_bbox = draw.textbbox((0, 0), value, font=value_font)
        value_w = value_bbox[2] - value_bbox[0]
        value_h = value_bbox[3] - value_bbox[1]
        value_color = color if color else '#1F2937'
        
        draw.text((width // 2 - value_w // 2, height - 35 - value_h // 2), value,
                 fill=value_color, font=value_font)
        
        return img
    
    def create_signal_badge(self, direction: str, size: Tuple[int, int] = (200, 60)) -> Image.Image:
        """
        Create a modern signal badge
        
        Args:
            direction: "CALL" or "PUT"
            size: (width, height) tuple
        """
        width, height = size
        img = Image.new('RGBA', size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        colors = self.design.get_direction_color(direction)
        color = colors['base']
        
        # Badge background with gradient
        radius = height // 2
        gradient = self.design.create_gradient(size, colors['gradient'][0], colors['gradient'][1])
        
        # Create mask for rounded rectangle
        mask = Image.new('L', size, 0)
        mask_draw = ImageDraw.Draw(mask)
        self._draw_rounded_rectangle(mask_draw, [0, 0, width, height], radius=radius, fill=255)
        
        img.paste(gradient, (0, 0), mask)
        
        # Badge text - clean design without emoji (larger)
        try:
            font = ImageFont.truetype("arial.ttf", 28)
        except:
            font = ImageFont.load_default()
        
        text = direction  # Just the text, no emoji
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.text((width // 2 - text_w // 2, height // 2 - text_h // 2), text,
                 fill='white', font=font)
        
        return img

