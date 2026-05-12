"""
Trading Stages - Modular architecture for different processing stages

Each stage can be swapped with different implementations:
- TestingStage: Test connection to trading platform
- EvaluationStage: Evaluate trading opportunities
- OrderPlacementStage: Place and manage orders
- NotificationStage: Send notifications (Telegram, etc.)
- LoggingStage: Log debug information
"""

from .testing import TestingStage, DefaultTestingStage
from .evaluation import EvaluationStage, DefaultEvaluationStage
from .order_placement import OrderPlacementStage, DefaultOrderPlacementStage
from .notification import NotificationStage, DefaultNotificationStage
from .logging import LoggingStage, DefaultLoggingStage

# Version 2 - Fractal stages
try:
    from .fractal_evaluation import FractalEvaluationStage
    from .fractal_notification import FractalNotificationStage
    fractal_imported = True
except ImportError:
    fractal_imported = False

# Version 3 - M2 stages
try:
    from .m2_evaluation import M2EvaluationStage
    from .m2_notification import M2NotificationStage
    m2_imported = True
except ImportError:
    m2_imported = False

# Build __all__ list
__all__ = [
    'TestingStage',
    'DefaultTestingStage',
    'EvaluationStage',
    'DefaultEvaluationStage',
    'OrderPlacementStage',
    'DefaultOrderPlacementStage',
    'NotificationStage',
    'DefaultNotificationStage',
    'LoggingStage',
    'DefaultLoggingStage',
]

if fractal_imported:
    __all__.extend(['FractalEvaluationStage', 'FractalNotificationStage'])

if m2_imported:
    __all__.extend(['M2EvaluationStage', 'M2NotificationStage'])

