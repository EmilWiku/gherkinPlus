"""
Beautiful Time Utility
Calculates "beautiful times" for signal timing (e.g., :42, :44, :46, :48, :50)
"""
from datetime import datetime, timedelta
from typing import List, Tuple


def get_beautiful_time_minutes() -> List[int]:
    """
    Get list of beautiful minute marks.
    Beautiful times are: 42, 44, 46, 48, 50, 52, 54, 56, 58, 00, 02, 04, 06, 08, 10, etc.
    Basically every 2 minutes starting from :42
    
    Returns:
        List of minute values (0-59)
    """
    # Generate every 2 minutes starting from 42, wrapping around
    minutes = []
    start = 42
    for i in range(30):  # 30 intervals of 2 minutes = 60 minutes total
        minute = (start + i * 2) % 60
        minutes.append(minute)
    return sorted(set(minutes))  # Remove duplicates and sort


def get_next_beautiful_time(current_time: datetime = None) -> datetime:
    """
    Get the next beautiful time from current time.
    
    Args:
        current_time: Current datetime (default: now)
    
    Returns:
        Next beautiful time datetime
    """
    if current_time is None:
        current_time = datetime.now()
    
    beautiful_minutes = get_beautiful_time_minutes()
    current_minute = current_time.minute
    current_second = current_time.second
    
    # Find next beautiful minute
    next_minute = None
    for minute in beautiful_minutes:
        if minute > current_minute:
            next_minute = minute
            break
    
    # If no minute found in current hour, use first beautiful minute of next hour
    if next_minute is None:
        next_minute = beautiful_minutes[0]
        # Move to next hour
        next_time = current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        # Same hour, just update minute
        next_time = current_time.replace(minute=next_minute, second=0, microsecond=0)
    
    # If we're already past the second mark, move to next minute
    if next_time <= current_time:
        next_time = next_time + timedelta(minutes=2)
    
    return next_time


def get_beautiful_time_range(start_time: datetime) -> Tuple[datetime, datetime]:
    """
    Get beautiful time range (start and end) for a signal.
    End time is 2 minutes after start time.
    
    Args:
        start_time: Start time (should be a beautiful time)
    
    Returns:
        Tuple of (start_time, end_time) where end_time is start_time + 2 minutes
    """
    end_time = start_time + timedelta(minutes=2)
    return (start_time, end_time)


def format_beautiful_time_range(start_time: datetime, end_time: datetime) -> str:
    """
    Format beautiful time range in Russian format.
    
    Args:
        start_time: Start datetime
        end_time: End datetime
    
    Returns:
        Formatted string like "07:42:00 до 07:44:00"
    """
    start_str = start_time.strftime("%H:%M:%S")
    end_str = end_time.strftime("%H:%M:%S")
    return f"{start_str} до {end_str}"


def is_beautiful_time(time: datetime = None) -> bool:
    """
    Check if current time is a beautiful time.
    
    Args:
        time: Time to check (default: now)
    
    Returns:
        True if time is a beautiful time
    """
    if time is None:
        time = datetime.now()
    
    beautiful_minutes = get_beautiful_time_minutes()
    return time.minute in beautiful_minutes and time.second == 0

