# visualization_lib

Composable chart rendering for M2 / signal payloads: `ChartComposer`, design tokens, and PNG buffers suitable for Telegram.

## Quick usage

```python
from visualization_lib import ChartComposer

composer = ChartComposer(width=1400, height=1800)
chart_buffer = composer.create_m2_visualization(m2_analysis, asset_name="BTCUSD")
chart_buffer.seek(0)
with open("chart.png", "wb") as f:
    f.write(chart_buffer.read())
```

## Layout

- `design_system.py` — colors, typography, spacing
- `chart_renderer.py` — candlestick / overlays
- `chart_composer.py` — high-level `ChartComposer`
- `score_components.py` — gauges and score widgets

See `requirements/visualization.txt` for optional dependencies (plotly, matplotlib, etc.).
