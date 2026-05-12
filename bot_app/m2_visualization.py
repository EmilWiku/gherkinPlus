"""
M2 Visualization Module - Create charts with M2 pattern analysis
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle, FancyBboxPatch, FancyArrowPatch
from matplotlib.patches import Circle, Wedge
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap
from typing import List, Dict, Optional
from pocketoptionapi_async.models import Candle
from datetime import datetime
import io
import numpy as np


class M2Visualizer:
    """Create visualizations of candles with M2 pattern analysis"""
    
    @staticmethod
    def create_m2_chart(m2_analysis: Dict, asset_name: str = "Asset") -> io.BytesIO:
        """
        Create a beautiful candlestick chart with M2 pattern analysis annotations.
        
        Args:
            m2_analysis: M2 analysis result with candles and pattern data
            asset_name: Name of the asset
        
        Returns:
            BytesIO buffer containing the image
        """
        # Modern glassmorphism theme colors
        bg_color = '#0a0e27'  # Deep dark blue
        bg_gradient_start = '#1a1f3a'  # Gradient start
        panel_color = '#1a2332'  # Glass panel base
        panel_glass = '#252d42'  # Glass overlay
        grid_color = '#2a3441'  # Subtle grid
        text_color = '#f0f4f8'  # Bright light text
        accent_green = '#00ffaa'  # Vibrant green
        accent_red = '#ff6b9d'  # Modern pink/red
        accent_yellow = '#ffd93d'  # Bright yellow
        accent_blue = '#5dade2'  # Bright blue
        
        # Glassmorphism colors (semi-transparent) - matplotlib format (r, g, b, alpha) 0-1
        glass_green = (0, 1.0, 0.67, 0.15)  # rgba(0, 255, 170, 0.15)
        glass_red = (1.0, 0.42, 0.62, 0.15)  # rgba(255, 107, 157, 0.15)
        glass_blue = (0.36, 0.68, 0.89, 0.15)  # rgba(93, 173, 226, 0.15)
        glass_yellow = (1.0, 0.85, 0.24, 0.15)  # rgba(255, 217, 61, 0.15)
        glass_panel = (0.145, 0.176, 0.259, 0.6)  # rgba(37, 45, 66, 0.6)
        glass_overlay = (1.0, 1.0, 1.0, 0.05)  # rgba(255, 255, 255, 0.05)
        
        candles_1m = m2_analysis.get("candles_1m", [])
        if not candles_1m or len(candles_1m) < 5:
            # Return empty image if no data
            fig, ax = plt.subplots(figsize=(12, 8))
            ax.text(0.5, 0.5, 'Insufficient data', ha='center', va='center', 
                   transform=ax.transAxes, fontsize=16, color=text_color,
                   fontweight='bold')
            fig.patch.set_facecolor(bg_color)
            ax.set_facecolor(panel_color)
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight', facecolor=bg_color)
            plt.close()
            buf.seek(0)
            return buf
        
        pattern_analysis = m2_analysis.get("pattern_analysis", {})
        pattern_1m = pattern_analysis.get("pattern_1m", {})
        signal_direction = m2_analysis.get("signal_direction")
        m2_score = m2_analysis.get("m2_score", 0)
        
        # Use last 30 candles for better visualization
        display_candles = candles_1m[-30:] if len(candles_1m) >= 30 else candles_1m
        
        # Prepare data
        timestamps = [c.timestamp for c in display_candles]
        opens = [c.open for c in display_candles]
        highs = [c.high for c in display_candles]
        lows = [c.low for c in display_candles]
        closes = [c.close for c in display_candles]
        
        # Create figure with subplots - larger and more spacious
        fig = plt.figure(figsize=(16, 10))
        fig.patch.set_facecolor(bg_color)
        gs = fig.add_gridspec(3, 1, height_ratios=[4, 1.2, 1], hspace=0.35, 
                             left=0.08, right=0.95, top=0.95, bottom=0.08)
        
        # Add gradient background to figure
        gradient_bg = np.linspace(0, 1, 100)
        for i in range(len(gradient_bg)-1):
            alpha = 0.03 * (1 - abs(i - 50) / 50)
            fig.patch.set_facecolor(bg_color)
        
        # Main candlestick chart with glassmorphism
        ax = fig.add_subplot(gs[0, 0])
        # Glass effect background - layered
        ax.set_facecolor(panel_color)
        # Add glass overlay effect
        glass_rect = Rectangle((0, 0), 1, 1, transform=ax.transAxes,
                              facecolor=glass_overlay, edgecolor='none', zorder=0)
        ax.add_patch(glass_rect)
        
        # Plot candles with glassmorphism and puffy styling
        for i, (ts, o, h, l, c) in enumerate(zip(timestamps, opens, highs, lows, closes)):
            is_up = c >= o
            color = accent_green if is_up else accent_red
            glass_color = glass_green if is_up else glass_red
            body_bottom = min(o, c)
            body_top = max(o, c)
            body_height = abs(c - o)
            
            # Draw wick with glow effect (multiple layers for depth)
            ax.plot([ts, ts], [l, h], color=color, linewidth=3, alpha=0.3, zorder=1)  # Outer glow
            ax.plot([ts, ts], [l, h], color=color, linewidth=2, alpha=0.6, zorder=2)  # Middle
            ax.plot([ts, ts], [l, h], color=color, linewidth=1.5, alpha=0.9, zorder=3)  # Core
            
            # Draw body with glassmorphism and puffy effect
            if body_height > 0:
                ts_num = mdates.date2num(ts)
                width = 0.0006  # Wider for puffy look
                
                # Shadow/glow layer (behind)
                shadow = Rectangle((ts_num - width/2 - 0.00005, body_bottom - 0.0001), 
                                  width + 0.0001, body_height + 0.0002,
                                  facecolor=color, alpha=0.2, zorder=1)
                ax.add_patch(shadow)
                
                # Glass overlay layer
                glass_layer = Rectangle((ts_num - width/2, body_bottom), 
                                       width, body_height,
                                       facecolor=glass_color, edgecolor='none', zorder=2)
                ax.add_patch(glass_layer)
                
                # Main body with transparency
                rect = Rectangle((ts_num - width/2, body_bottom), 
                               width, body_height, 
                               facecolor=color, edgecolor='white', 
                               alpha=0.85, linewidth=2, zorder=3)
                ax.add_patch(rect)
                
                # Highlight/shine effect (puffy look)
                if is_up:
                    highlight = Rectangle((ts_num - width/2, body_top - body_height*0.15), 
                                        width, body_height*0.15,
                                        facecolor='white', alpha=0.4, zorder=4)
                    ax.add_patch(highlight)
                    # Top edge glow
                    top_glow = Rectangle((ts_num - width/2, body_top - 0.00005), 
                                       width, 0.0001,
                                       facecolor='white', alpha=0.6, zorder=5)
                    ax.add_patch(top_glow)
                else:
                    highlight = Rectangle((ts_num - width/2, body_bottom), 
                                        width, body_height*0.15,
                                        facecolor='white', alpha=0.4, zorder=4)
                    ax.add_patch(highlight)
                    # Bottom edge glow
                    bottom_glow = Rectangle((ts_num - width/2, body_bottom - 0.00005), 
                                           width, 0.0001,
                                           facecolor='white', alpha=0.6, zorder=5)
                    ax.add_patch(bottom_glow)
            else:
                # Doji - draw with glow
                ax.plot([ts, ts], [l, h], color=color, linewidth=4, alpha=0.3, zorder=1)
                ax.plot([ts, ts], [l, h], color=color, linewidth=2.5, alpha=0.7, zorder=2)
                ax.plot([ts, ts], [l, h], color=color, linewidth=1.5, alpha=0.9, zorder=3)
        
        # Highlight current price with glassmorphism glow
        current_candle = display_candles[-1]
        current_price = current_candle.close
        current_ts = timestamps[-1]
        
        # Multiple glow layers for puffy effect
        for glow_size, alpha_val in [(12, 0.1), (8, 0.15), (4, 0.25)]:
            ax.axhline(y=current_price, color=accent_yellow, linestyle='--', 
                      linewidth=glow_size, alpha=alpha_val, zorder=0)
        ax.axhline(y=current_price, color=accent_yellow, linestyle='--', 
                  linewidth=2.5, alpha=0.8, label='Current Price', zorder=1)
        
        # Puffy current price marker with multiple layers
        for size, alpha, edge in [(400, 0.2, None), (300, 0.4, None), (200, 0.7, 'white')]:
            ax.scatter(current_ts, current_price, color=accent_yellow, s=size, 
                      zorder=10 if edge else 9, marker='*', 
                      edgecolors=edge, linewidths=3 if edge else 0,
                      label='Current Price' if edge else '')
        
        # Add pattern annotation with glassmorphism card
        pattern_name = pattern_1m.get("pattern", "Regular")
        pattern_dir = pattern_1m.get("direction", "neutral")
        pattern_color = accent_green if pattern_dir == "bullish" else \
                       accent_red if pattern_dir == "bearish" else accent_yellow
        pattern_glass = glass_green if pattern_dir == "bullish" else \
                       glass_red if pattern_dir == "bearish" else glass_yellow
        
        # Glassmorphism annotation card
        annotation_text = f'{pattern_name}\n{pattern_1m.get("strength", 0)}%'
        # Create glass card background
        card_x, card_y = 0.12, 0.88  # Position in axes coordinates
        card_width, card_height = 0.15, 0.10
        
        # Shadow layer
        shadow_card = FancyBboxPatch((card_x - 0.002, card_y - card_height - 0.002), 
                                    card_width + 0.004, card_height + 0.004,
                                    boxstyle="round,pad=0.01", 
                                    facecolor='black', alpha=0.3,
                                    transform=ax.transAxes, zorder=8)
        ax.add_patch(shadow_card)
        
        # Glass layer
        glass_card = FancyBboxPatch((card_x, card_y - card_height), 
                                   card_width, card_height,
                                   boxstyle="round,pad=0.01", 
                                   facecolor=pattern_glass,
                                   edgecolor=pattern_color, linewidth=2.5,
                                   transform=ax.transAxes, zorder=9)
        ax.add_patch(glass_card)
        
        # White overlay for glass effect
        white_overlay = FancyBboxPatch((card_x, card_y - card_height*0.3), 
                                      card_width, card_height*0.3,
                                      boxstyle="round,pad=0.01", 
                                      facecolor='white', alpha=0.15,
                                      transform=ax.transAxes, zorder=10)
        ax.add_patch(white_overlay)
        
        # Text on glass card
        ax.text(card_x + card_width/2, card_y - card_height/2, annotation_text,
               transform=ax.transAxes, fontsize=10, fontweight='bold', 
               color='white', ha='center', va='center', zorder=11)
        
        # Arrow with glow - simplified approach
        # Use offset points for arrow start (from card edge)
        ax.annotate('', xy=(current_ts, current_price), 
                   xytext=(25, 0), textcoords='offset points',
                   arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0.2',
                                 color=pattern_color, lw=2.5, alpha=0.8,
                                 shrinkA=8, shrinkB=8),
                   zorder=7)
        
        # Glassmorphism title card
        title_text = f'{asset_name} - M2 Analysis'
        title_x, title_y = 0.5, 1.02
        title_width, title_height = 0.35, 0.08
        
        # Title shadow
        title_shadow = FancyBboxPatch((title_x - title_width/2 - 0.003, title_y - title_height - 0.003), 
                                     title_width + 0.006, title_height + 0.006,
                                     boxstyle="round,pad=0.01", 
                                     facecolor='black', alpha=0.4,
                                     transform=ax.transAxes, zorder=8)
        ax.add_patch(title_shadow)
        
        # Title glass card
        title_card = FancyBboxPatch((title_x - title_width/2, title_y - title_height), 
                                   title_width, title_height,
                                   boxstyle="round,pad=0.01", 
                                   facecolor=glass_panel,
                                   edgecolor=accent_blue, linewidth=2.5,
                                   transform=ax.transAxes, zorder=9)
        ax.add_patch(title_card)
        
        # Title glass highlight
        title_highlight = FancyBboxPatch((title_x - title_width/2, title_y - title_height*0.4), 
                                        title_width, title_height*0.4,
                                        boxstyle="round,pad=0.01", 
                                        facecolor='white', alpha=0.1,
                                        transform=ax.transAxes, zorder=10)
        ax.add_patch(title_highlight)
        
        # Title text
        ax.text(title_x, title_y - title_height/2, title_text, transform=ax.transAxes,
               fontsize=18, fontweight='bold', color=text_color,
               ha='center', va='center', zorder=11)
        
        ax.set_xlabel('Time', color=text_color, fontsize=11, fontweight='500')
        ax.set_ylabel('Price', color=text_color, fontsize=11, fontweight='500')
        
        # Format x-axis dates with better styling
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=5))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right', 
                color=text_color, fontsize=9)
        plt.setp(ax.yaxis.get_majorticklabels(), color=text_color, fontsize=9)
        
        # Beautiful grid
        ax.grid(True, alpha=0.2, color=grid_color, linestyle='-', linewidth=0.8)
        ax.set_axisbelow(True)
        
        # Hide spines and add custom borders
        for spine in ax.spines.values():
            spine.set_visible(False)
        
        # Add subtle border
        ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes,
                             fill=False, edgecolor=grid_color, linewidth=1.5,
                             clip_on=False, zorder=10))
        
        # Glassmorphism signal badges with puffy effect
        if signal_direction:
            signal_color = accent_green if signal_direction == "CALL" else accent_red
            signal_glass = glass_green if signal_direction == "CALL" else glass_red
            signal_emoji = "🚀" if signal_direction == "CALL" else "⬇️"
            signal_text = f'{signal_emoji} SIGNAL: {signal_direction}'
            
            # Signal badge with glassmorphism
            badge_x, badge_y = 0.02, 0.98
            badge_width, badge_height = 0.22, 0.08
            
            # Shadow
            signal_shadow = FancyBboxPatch((badge_x - 0.002, badge_y - badge_height - 0.002), 
                                         badge_width + 0.004, badge_height + 0.004,
                                         boxstyle="round,pad=0.01", 
                                         facecolor='black', alpha=0.4,
                                         transform=ax.transAxes, zorder=8)
            ax.add_patch(signal_shadow)
            
            # Glass card
            signal_card = FancyBboxPatch((badge_x, badge_y - badge_height), 
                                        badge_width, badge_height,
                                        boxstyle="round,pad=0.01", 
                                        facecolor=signal_glass,
                                        edgecolor=signal_color, linewidth=3,
                                        transform=ax.transAxes, zorder=9)
            ax.add_patch(signal_card)
            
            # Glass highlight
            signal_highlight = FancyBboxPatch((badge_x, badge_y - badge_height*0.3), 
                                             badge_width, badge_height*0.3,
                                             boxstyle="round,pad=0.01", 
                                             facecolor='white', alpha=0.2,
                                             transform=ax.transAxes, zorder=10)
            ax.add_patch(signal_highlight)
            
            # Signal text
            ax.text(badge_x + badge_width/2, badge_y - badge_height/2, signal_text,
                   transform=ax.transAxes, fontsize=13, fontweight='bold', 
                   color='white', ha='center', va='center', zorder=11)
            
            # M2 score badge with glassmorphism
            score_color = accent_green if m2_score >= 70 else accent_yellow if m2_score >= 50 else accent_blue
            score_glass = glass_green if m2_score >= 70 else glass_yellow if m2_score >= 50 else glass_blue
            score_text = f'M2: {m2_score:.1f}%'
            
            score_badge_x, score_badge_y = 0.98, 0.98
            score_badge_width, score_badge_height = 0.18, 0.08
            
            # Score shadow
            score_shadow = FancyBboxPatch((score_badge_x - score_badge_width - 0.002, 
                                          score_badge_y - score_badge_height - 0.002), 
                                         score_badge_width + 0.004, score_badge_height + 0.004,
                                         boxstyle="round,pad=0.01", 
                                         facecolor='black', alpha=0.4,
                                         transform=ax.transAxes, zorder=8)
            ax.add_patch(score_shadow)
            
            # Score glass card
            score_card = FancyBboxPatch((score_badge_x - score_badge_width, 
                                        score_badge_y - score_badge_height), 
                                       score_badge_width, score_badge_height,
                                       boxstyle="round,pad=0.01", 
                                       facecolor=score_glass,
                                       edgecolor=score_color, linewidth=3,
                                       transform=ax.transAxes, zorder=9)
            ax.add_patch(score_card)
            
            # Score highlight
            score_highlight = FancyBboxPatch((score_badge_x - score_badge_width, 
                                             score_badge_y - score_badge_height*0.3), 
                                            score_badge_width, score_badge_height*0.3,
                                            boxstyle="round,pad=0.01", 
                                            facecolor='white', alpha=0.2,
                                            transform=ax.transAxes, zorder=10)
            ax.add_patch(score_highlight)
            
            # Score text
            ax.text(score_badge_x - score_badge_width/2, score_badge_y - score_badge_height/2, 
                   score_text, transform=ax.transAxes, fontsize=12, fontweight='bold', 
                   color='white', ha='center', va='center', zorder=11)
        
        # Beautiful legend
        legend = ax.legend(loc='upper left', facecolor=panel_color, 
                          edgecolor=grid_color, labelcolor=text_color, 
                          framealpha=0.95, fontsize=10, 
                          borderpad=0.8, handlelength=2)
        legend.get_frame().set_linewidth(1.5)
        
        # Glassmorphism score breakdown subplot
        ax_score = fig.add_subplot(gs[1, 0])
        ax_score.set_facecolor(panel_color)
        # Add glass overlay
        score_glass_bg = Rectangle((0, 0), 1, 1, transform=ax_score.transAxes,
                                  facecolor=glass_overlay, edgecolor='none', zorder=0)
        ax_score.add_patch(score_glass_bg)
        
        scores = {
            'Pattern': m2_analysis.get("pattern_score", 0),
            'Confirmation': m2_analysis.get("confirmation_score", 0),
            'Momentum': m2_analysis.get("momentum_score", 0),
            'Consistency': m2_analysis.get("consistency_score", 0)
        }
        
        # Glassmorphism colors with transparency
        colors = [accent_green, accent_blue, accent_yellow, '#c084fc']
        glass_purple = (0.75, 0.52, 0.99, 0.15)  # rgba(192, 132, 252, 0.15)
        glass_colors = [glass_green, glass_blue, glass_yellow, glass_purple]
        
        bars = ax_score.bar(scores.keys(), scores.values(), 
                           color=colors, alpha=0.7, 
                           edgecolor='white', linewidth=2.5, 
                           width=0.65, zorder=2)
        
        # Add glassmorphism effect to bars (puffy look)
        for i, bar in enumerate(bars):
            height = bar.get_height()
            if height > 0:
                # Shadow behind bar
                shadow = Rectangle((bar.get_x() - 0.01, bar.get_y() - 0.3), 
                                 bar.get_width() + 0.02, height + 0.3,
                                 facecolor='black', alpha=0.2, zorder=1)
                ax_score.add_patch(shadow)
                
                # Glass overlay layer
                glass_bar = Rectangle((bar.get_x(), bar.get_y()), 
                                     bar.get_width(), height,
                                     facecolor=glass_colors[i], zorder=3)
                ax_score.add_patch(glass_bar)
                
                # White highlight on top (puffy effect)
                highlight = Rectangle((bar.get_x(), bar.get_y() + height*0.7), 
                                    bar.get_width(), height*0.3,
                                    facecolor='white', alpha=0.25, zorder=4)
                ax_score.add_patch(highlight)
        
        ax_score.set_ylabel('Points', color=text_color, fontsize=11, fontweight='500')
        ax_score.set_title('M2 Score Breakdown', color=text_color, fontsize=13, 
                          fontweight='bold', pad=10)
        ax_score.set_ylim(0, max(30, max(scores.values()) * 1.15))
        ax_score.tick_params(axis='y', colors=text_color, labelsize=9)
        ax_score.tick_params(axis='x', colors=text_color, labelsize=10, 
                            labelrotation=0, pad=8)
        ax_score.grid(True, alpha=0.2, color=grid_color, linestyle='-', 
                     linewidth=0.8, axis='y', zorder=0)
        ax_score.set_axisbelow(True)
        
        # Hide spines
        for spine in ax_score.spines.values():
            spine.set_visible(False)
        
        # Glassmorphism value labels on bars
        for i, bar in enumerate(bars):
            height = bar.get_height()
            if height > 0:
                label_x = bar.get_x() + bar.get_width()/2.
                label_y = height + 0.8
                label_text = f'{height:.1f}'
                
                # Label shadow
                label_shadow = FancyBboxPatch((label_x - 0.03, label_y - 0.015), 
                                            0.06, 0.03,
                                            boxstyle="round,pad=0.01", 
                                            facecolor='black', alpha=0.3,
                                            transform=ax_score.transData, zorder=5)
                ax_score.add_patch(label_shadow)
                
                # Glass label card
                label_card = FancyBboxPatch((label_x - 0.03, label_y - 0.015), 
                                          0.06, 0.03,
                                          boxstyle="round,pad=0.01", 
                                          facecolor=glass_colors[i],
                                          edgecolor=colors[i], linewidth=2,
                                          transform=ax_score.transData, zorder=6)
                ax_score.add_patch(label_card)
                
                # Label text
                ax_score.text(label_x, label_y, label_text,
                            ha='center', va='center',
                            color='white', fontweight='bold', fontsize=10, zorder=7)
        
        # Glassmorphism pattern details subplot with puffy cards
        ax_details = fig.add_subplot(gs[2, 0])
        ax_details.set_facecolor(panel_color)
        # Glass overlay
        details_glass_bg = Rectangle((0, 0), 1, 1, transform=ax_details.transAxes,
                                    facecolor=glass_overlay, edgecolor='none', zorder=0)
        ax_details.add_patch(details_glass_bg)
        ax_details.axis('off')
        
        pattern_5m = pattern_analysis.get("pattern_5m", {})
        pattern_5m_name = pattern_5m.get("pattern", "N/A")
        pattern_5m_dir = pattern_5m.get("direction", "N/A")
        pattern_5m_str = pattern_5m.get("strength", 0)
        
        # Create puffy glassmorphism info cards
        info_y = 0.5
        card_height = 0.38
        card_width = 0.30
        
        def create_glass_card(x, y, width, height, color, glass_color, label, content, z_start=1):
            """Helper to create glassmorphism card with shadow and highlights"""
            # Shadow (behind)
            shadow = FancyBboxPatch((x - 0.004, y - height/2 - 0.004), 
                                   width + 0.008, height + 0.008,
                                   boxstyle="round,pad=0.015", 
                                   facecolor='black', alpha=0.3,
                                   transform=ax_details.transAxes, zorder=z_start)
            ax_details.add_patch(shadow)
            
            # Glass card
            card = FancyBboxPatch((x, y - height/2), width, height,
                                 boxstyle="round,pad=0.015", 
                                 facecolor=glass_color,
                                 edgecolor=color, linewidth=2.5,
                                 transform=ax_details.transAxes, zorder=z_start+1)
            ax_details.add_patch(card)
            
            # Glass highlight (top portion)
            highlight = FancyBboxPatch((x, y - height*0.25), width, height*0.25,
                                      boxstyle="round,pad=0.015", 
                                      facecolor='white', alpha=0.15,
                                      transform=ax_details.transAxes, zorder=z_start+2)
            ax_details.add_patch(highlight)
            
            # Label text
            ax_details.text(x + width/2, y + height*0.15, label,
                           transform=ax_details.transAxes,
                           fontsize=9, color=text_color, ha='center', va='center',
                           fontweight='bold', alpha=0.8, zorder=z_start+3)
            
            # Content text
            ax_details.text(x + width/2, y - height*0.15, content,
                           transform=ax_details.transAxes,
                           fontsize=10, color=text_color, ha='center', va='top',
                           fontweight='600', zorder=z_start+3)
        
        # Card 1: 1m Pattern
        card1_content = f'{pattern_1m.get("pattern", "N/A")}\n{pattern_1m.get("direction", "N/A")} ({pattern_1m.get("strength", 0)}%)'
        create_glass_card(0.02, info_y, card_width, card_height, 
                         accent_green, glass_green, '1m Pattern', card1_content, 1)
        
        # Card 2: 5m Pattern
        card2_content = f'{pattern_5m_name}\n{pattern_5m_dir} ({pattern_5m_str}%)'
        create_glass_card(0.35, info_y, card_width, card_height,
                         accent_blue, glass_blue, '5m Pattern', card2_content, 1)
        
        # Card 3: Combined Direction
        combined_dir = pattern_analysis.get("combined_direction", "N/A")
        dir_color = accent_green if combined_dir == "bullish" else accent_red if combined_dir == "bearish" else accent_yellow
        dir_glass = glass_green if combined_dir == "bullish" else glass_red if combined_dir == "bearish" else glass_yellow
        card3_content = combined_dir.upper()
        create_glass_card(0.68, info_y, 0.30, card_height,
                         dir_color, dir_glass, 'Direction', card3_content, 1)
        
        
        plt.tight_layout()
        
        # Save to buffer with high quality
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=200, bbox_inches='tight', 
                   facecolor=bg_color, edgecolor='none', 
                   pad_inches=0.1)
        plt.close()
        buf.seek(0)
        
        return buf

