"""
Design System - 2025 Infographics Standards
Modern color palettes, typography, and design elements
"""
from typing import Tuple, List, Dict
from PIL import Image, ImageDraw, ImageFont
import math


class DesignSystem:
    """
    Design system following 2025 infographics standards:
    - Modern gradients and color palettes
    - Bold typography with clear hierarchy
    - 3D depth effects
    - Asymmetrical layouts
    - Professional, sales-oriented aesthetics
    """
    
    # Modern Color Palettes (2025 trends)
    COLORS = {
        # Primary palette - vibrant, attention-catching
        'primary': {
            'gradient_start': '#6366F1',  # Indigo
            'gradient_end': '#8B5CF6',    # Purple
            'accent': '#EC4899',          # Pink
            'vibrant': '#10B981',         # Emerald
        },
        # Success/Bullish palette
        'success': {
            'base': '#10B981',            # Emerald
            'light': '#34D399',           # Light emerald
            'dark': '#059669',            # Dark emerald
            'gradient': ('#10B981', '#34D399'),
            'glass': (16, 185, 129, 40),  # RGBA with transparency
        },
        # Danger/Bearish palette
        'danger': {
            'base': '#EF4444',            # Red
            'light': '#F87171',           # Light red
            'dark': '#DC2626',            # Dark red
            'gradient': ('#EF4444', '#F87171'),
            'glass': (239, 68, 68, 40),
        },
        # Warning/Neutral palette
        'warning': {
            'base': '#F59E0B',            # Amber
            'light': '#FBBF24',           # Light amber
            'dark': '#D97706',            # Dark amber
            'gradient': ('#F59E0B', '#FBBF24'),
            'glass': (245, 158, 11, 40),
        },
        # Info/Neutral palette
        'info': {
            'base': '#3B82F6',            # Blue
            'light': '#60A5FA',           # Light blue
            'dark': '#2563EB',            # Dark blue
            'gradient': ('#3B82F6', '#60A5FA'),
            'glass': (59, 130, 246, 40),
        },
        # Background palette - White/Light theme
        'bg': {
            'dark': '#FFFFFF',            # White
            'darker': '#F8F9FA',          # Light gray
            'panel': '#FFFFFF',           # White
            'panel_light': '#F1F3F5',     # Light gray
            'overlay': (248, 249, 250, 200), # Light gray with transparency
        },
        # Text palette - Dark text for light backgrounds
        'text': {
            'primary': '#1F2937',         # Dark gray
            'secondary': '#4B5563',       # Medium gray
            'tertiary': '#6B7280',        # Light gray
            'inverse': '#FFFFFF',         # White text for dark backgrounds
        },
        # Score-based colors
        'score': {
            'excellent': '#10B981',       # Green for 80+
            'good': '#3B82F6',            # Blue for 65-79
            'moderate': '#F59E0B',        # Amber for 50-64
            'low': '#EF4444',             # Red for <50
        }
    }
    
    # Typography settings
    TYPOGRAPHY = {
        'title': {'size': 32, 'weight': 'bold'},
        'heading': {'size': 24, 'weight': 'bold'},
        'subheading': {'size': 18, 'weight': 'semibold'},
        'body': {'size': 14, 'weight': 'regular'},
        'caption': {'size': 12, 'weight': 'regular'},
        'small': {'size': 10, 'weight': 'regular'},
    }
    
    # Spacing system (8px grid)
    SPACING = {
        'xs': 4,
        'sm': 8,
        'md': 16,
        'lg': 24,
        'xl': 32,
        'xxl': 48,
    }
    
    # Border radius (rounded corners)
    RADIUS = {
        'sm': 8,
        'md': 12,
        'lg': 16,
        'xl': 24,
        'full': 9999,
    }
    
    @staticmethod
    def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
        """Convert hex color to RGB tuple"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    @staticmethod
    def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
        """Convert RGB tuple to hex color"""
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
    
    @staticmethod
    def create_gradient(size: Tuple[int, int], color_start: str, color_end: str, 
                       direction: str = 'vertical') -> Image.Image:
        """
        Create a gradient image
        
        Args:
            size: (width, height) tuple
            color_start: Starting color (hex)
            color_end: Ending color (hex)
            direction: 'vertical', 'horizontal', or 'diagonal'
        """
        width, height = size
        gradient = Image.new('RGB', size)
        
        start_rgb = DesignSystem.hex_to_rgb(color_start)
        end_rgb = DesignSystem.hex_to_rgb(color_end)
        
        if direction == 'vertical':
            for y in range(height):
                ratio = y / height
                r = int(start_rgb[0] * (1 - ratio) + end_rgb[0] * ratio)
                g = int(start_rgb[1] * (1 - ratio) + end_rgb[1] * ratio)
                b = int(start_rgb[2] * (1 - ratio) + end_rgb[2] * ratio)
                for x in range(width):
                    gradient.putpixel((x, y), (r, g, b))
        elif direction == 'horizontal':
            for x in range(width):
                ratio = x / width
                r = int(start_rgb[0] * (1 - ratio) + end_rgb[0] * ratio)
                g = int(start_rgb[1] * (1 - ratio) + end_rgb[1] * ratio)
                b = int(start_rgb[2] * (1 - ratio) + end_rgb[2] * ratio)
                for y in range(height):
                    gradient.putpixel((x, y), (r, g, b))
        else:  # diagonal
            for y in range(height):
                for x in range(width):
                    ratio = (x + y) / (width + height)
                    r = int(start_rgb[0] * (1 - ratio) + end_rgb[0] * ratio)
                    g = int(start_rgb[1] * (1 - ratio) + end_rgb[1] * ratio)
                    b = int(start_rgb[2] * (1 - ratio) + end_rgb[2] * ratio)
                    gradient.putpixel((x, y), (r, g, b))
        
        return gradient
    
    @staticmethod
    def get_score_color(score: float) -> str:
        """Get color based on score value"""
        if score >= 80:
            return DesignSystem.COLORS['score']['excellent']
        elif score >= 65:
            return DesignSystem.COLORS['score']['good']
        elif score >= 50:
            return DesignSystem.COLORS['score']['moderate']
        else:
            return DesignSystem.COLORS['score']['low']
    
    @staticmethod
    def get_direction_color(direction: str) -> Dict[str, str]:
        """Get color palette based on signal direction"""
        if direction == "CALL":
            return DesignSystem.COLORS['success']
        elif direction == "PUT":
            return DesignSystem.COLORS['danger']
        else:
            return DesignSystem.COLORS['warning']
    
    @staticmethod
    def create_shadow_effect(image: Image.Image, blur_radius: int = 10, 
                            offset: Tuple[int, int] = (0, 4), 
                            opacity: int = 100) -> Image.Image:
        """
        Create a shadow effect behind an image (simulated with blur)
        Note: For true blur, would need ImageFilter, but this creates depth effect
        """
        from PIL import ImageFilter
        
        shadow = Image.new('RGBA', image.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        
        # Draw black rectangle with transparency
        shadow_draw.rectangle([offset[0], offset[1], 
                              image.width + offset[0], image.height + offset[1]],
                             fill=(0, 0, 0, opacity))
        
        # Apply blur if available
        try:
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        except:
            pass  # If blur not available, use solid shadow
        
        # Composite with original image
        result = Image.new('RGBA', 
                          (image.width + abs(offset[0]) + blur_radius * 2,
                           image.height + abs(offset[1]) + blur_radius * 2),
                          (0, 0, 0, 0))
        
        shadow_x = blur_radius + max(0, offset[0])
        shadow_y = blur_radius + max(0, offset[1])
        result.paste(shadow, (shadow_x, shadow_y), shadow)
        
        img_x = blur_radius + max(0, -offset[0])
        img_y = blur_radius + max(0, -offset[1])
        result.paste(image, (img_x, img_y), image if image.mode == 'RGBA' else None)
        
        return result
    
    @staticmethod
    def create_3d_depth(draw: ImageDraw.Draw, coords: Tuple[int, int, int, int],
                       color: str, depth: int = 3, direction: str = 'bottom_right'):
        """
        Create 3D depth effect using multiple rectangles with offset colors
        """
        x1, y1, x2, y2 = coords
        base_rgb = DesignSystem.hex_to_rgb(color)
        
        if direction == 'bottom_right':
            for i in range(depth):
                offset = depth - i
                # Darken color for depth
                shade = int(255 * (1 - (i + 1) / (depth + 1)))
                depth_color = (
                    max(0, base_rgb[0] - shade),
                    max(0, base_rgb[1] - shade),
                    max(0, base_rgb[2] - shade)
                )
                draw.rectangle([x1 + offset, y1 + offset, x2 + offset, y2 + offset],
                             fill=depth_color)
        elif direction == 'top_left':
            for i in range(depth):
                offset = depth - i
                shade = int(255 * (1 - (i + 1) / (depth + 1)))
                depth_color = (
                    min(255, base_rgb[0] + shade),
                    min(255, base_rgb[1] + shade),
                    min(255, base_rgb[2] + shade)
                )
                draw.rectangle([x1 - offset, y1 - offset, x2 - offset, y2 - offset],
                             fill=depth_color)
        
        # Draw main rectangle on top
        draw.rectangle([x1, y1, x2, y2], fill=color)

