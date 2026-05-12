"""
Trading Configuration Constants
"""

class TradingConfig:
    """Centralized trading thresholds and risk parameters."""
    # Entry thresholds
    MIN_CONFIDENCE = 90.0  # Minimum confidence to enter trade (balanced with historical modifiers)
    MIN_CONFIDENCE_FACTORS = 6  # Minimum number of confidence factors
    MIN_ADX = 30.0  # Minimum ADX for trend strength
    MIN_HISTORICAL_WIN_RATE = 0.30  # Hard block only if <30% (very poor), otherwise use as modifier
    HISTORICAL_BLOCK_THRESHOLD = 0.30  # Only block assets with <30% win rate
    HISTORICAL_LARGE_LOSS_THRESHOLD = -200.0  # Only block if lost >$200
    MIN_OTC_INNER_CONFIDENCE = 85.0  # Minimum inner confidence for OTC
    
    # Position sizing
    MIN_POSITION_PCT = 0.08  # 8% of balance (at 90% confidence)
    MAX_POSITION_PCT = 0.10  # 10% of balance (at 100% confidence)
    MAX_TOTAL_EXPOSURE_PCT = 0.12  # 12% of balance total exposure (allows 1-2 positions)
    MAX_POSITIONS_PER_CYCLE = 2  # Maximum positions per cycle
    
    # Double down rules (disabled by default)
    ENABLE_DOUBLE_DOWN = False
    MAX_POSITIONS_PER_ASSET = 1  # One position per asset
    MAX_EXPOSURE_PER_ASSET_PCT = 0.10  # 10% per asset max (matches MAX_POSITION_PCT)
    MAX_TOTAL_EXPOSURE_AFTER_DD_PCT = 0.12  # 12% after double down (if enabled)
    DOUBLE_DOWN_MULTIPLIER = 1.0  # Same size when doubling is off
    MIN_TIME_REMAINING_DD = 60  # 1 minute minimum for double down
    HIGH_VOLATILITY_THRESHOLD = 0.05  # Volatility threshold for reduction
    
    # Circuit breakers
    ENABLE_CIRCUIT_BREAKER = True
    MAX_CONSECUTIVE_LOSSES = 3  # Stop trading after 3 consecutive losses
    MAX_LOSSES_PER_HOUR = 5  # Stop trading if 5 losses in 1 hour
    MAX_DRAWDOWN_PCT = 0.10  # Stop trading if 10% drawdown from session start
    CIRCUIT_BREAKER_COOLDOWN_MINUTES = 30  # Wait 30 minutes before resuming
    
    # Trading duration
    CYCLE_DURATION_MINUTES = 5
    SESSION_DURATION_HOURS = 8
    CHECK_INTERVAL_SECONDS = 60  # Check positions every minute

