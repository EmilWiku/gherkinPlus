"""
Database layer for tracking trades and performance
"""
import sqlite3
from typing import Dict, Optional

class TradeDatabase:
    """SQLite database for tracking trades and performance"""
    
    def __init__(self, db_path: str = "trading_metrics.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create trades table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                asset TEXT NOT NULL,
                direction TEXT NOT NULL,
                amount REAL NOT NULL,
                duration INTEGER NOT NULL,
                order_id TEXT UNIQUE,
                signal_strength REAL,
                confidence_score REAL,
                status TEXT,
                profit REAL,
                win INTEGER DEFAULT 0,
                payout_percentage REAL,
                expected_profit REAL
            )
        ''')
        
        # Migrate: add missing columns
        try:
            cursor.execute("PRAGMA table_info(trades)")
            columns = [column[1] for column in cursor.fetchall()]
            for col in ['confidence_score', 'payout_percentage', 'expected_profit']:
                if col not in columns:
                    cursor.execute(f'ALTER TABLE trades ADD COLUMN {col} REAL')
            conn.commit()
        except Exception:
            pass
        
        conn.commit()
        conn.close()
    
    def save_trade(self, asset: str, direction: str, amount: float, duration: int,
                   order_id: str, signal_strength: float, confidence_score: float,
                   payout_percentage: Optional[float] = None):
        """Save a trade to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        expected_profit = amount * (payout_percentage / 100) if payout_percentage else None
        
        try:
            cursor.execute('''
                INSERT INTO trades (asset, direction, amount, duration, order_id,
                                  signal_strength, confidence_score, payout_percentage, expected_profit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (asset, direction, amount, duration, order_id, signal_strength, 
                  confidence_score, payout_percentage, expected_profit))
            conn.commit()
        except sqlite3.OperationalError:
            # Fallback if columns don't exist
            cursor.execute('''
                INSERT INTO trades (asset, direction, amount, duration, order_id, signal_strength, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (asset, direction, amount, duration, order_id, signal_strength, confidence_score))
            conn.commit()
        finally:
            conn.close()
    
    def update_trade_result(self, order_id: str, status: str, profit: float, win: bool):
        """Update trade result - uses OrderStatus as source of truth"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE trades SET status = ?, profit = ?, win = ?
            WHERE order_id = ?
        ''', (status, profit, 1 if win else 0, order_id))
        conn.commit()
        conn.close()
        
        return win
    
    def get_asset_stats(self, asset: str) -> Dict:
        """Get performance statistics for an asset"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN win = 0 THEN 1 ELSE 0 END) as losses,
                AVG(profit) as avg_profit,
                SUM(profit) as total_profit
            FROM trades
            WHERE asset = ? AND win IS NOT NULL
        ''', (asset,))
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0] > 0:
            return {
                "total_trades": row[0],
                "wins": row[1] or 0,
                "losses": row[2] or 0,
                "win_rate": (row[1] or 0) / row[0] if row[0] > 0 else 0.0,
                "avg_profit": row[3] or 0.0,
                "total_profit": row[4] or 0.0
            }
        return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.5, "avg_profit": 0.0, "total_profit": 0.0}

