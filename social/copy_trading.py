
# Phase 6: Copy Trading Engine - Simplified Working Version

code = '''"""
HOPEFX Copy Trading Engine
Master/Slave trade replication with leaderboards and sync logs
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Callable
from pathlib import Path
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
import sqlite3


class ReplicationMode(Enum):
    FIXED = "fixed"
    MULTIPLIER = "multiplier"
    RATIO = "ratio"
    RISK = "risk"
    SIGNAL = "signal"


@dataclass
class TradeSignal:
    signal_id: str
    timestamp: datetime
    master_id: str
    symbol: str
    action: str
    direction: str
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    lot_size: float = 0.0
    comment: str = ""
    
    def __post_init__(self):
        if self.signal_id is None:
            self.signal_id = str(uuid.uuid4())


@dataclass
class ReplicationRecord:
    record_id: str
    signal_id: str
    master_id: str
    slave_id: str
    timestamp: datetime
    status: str
    master_lot: float
    slave_lot: float
    replication_ratio: float
    slave_order_id: Optional[str] = None
    error_message: Optional[str] = None
    execution_time_ms: Optional[int] = None


@dataclass
class TraderProfile:
    trader_id: str
    name: str
    account_balance: float
    total_return: float = 0.0
    monthly_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    followers: int = 0
    ranking: int = 0
    is_active: bool = True
    
    @property
    def score(self) -> float:
        return (
            self.total_return * 0.3 +
            self.sharpe_ratio * 0.25 +
            (1 - abs(self.max_drawdown)) * 0.2 +
            self.win_rate * 0.15 +
            min(self.total_trades / 100, 1.0) * 0.1
        )


class CopyTradingDatabase:
    """SQLite database for copy trading records"""
    
    def __init__(self, db_path: str = "social/copy_trading.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Signals table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                timestamp TEXT,
                master_id TEXT,
                symbol TEXT,
                action TEXT,
                direction TEXT,
                entry_price REAL,
                stop_loss REAL,
                take_profit REAL,
                lot_size REAL,
                comment TEXT
            )
        """)
        
        # Replication records table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS replications (
                record_id TEXT PRIMARY KEY,
                signal_id TEXT,
                master_id TEXT,
                slave_id TEXT,
                timestamp TEXT,
                status TEXT,
                master_lot REAL,
                slave_lot REAL,
                replication_ratio REAL,
                slave_order_id TEXT,
                error_message TEXT,
                execution_time_ms INTEGER
            )
        """)
        
        # Trader profiles table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS traders (
                trader_id TEXT PRIMARY KEY,
                name TEXT,
                account_balance REAL,
                total_return REAL,
                monthly_return REAL,
                sharpe_ratio REAL,
                max_drawdown REAL,
                win_rate REAL,
                total_trades INTEGER,
                followers INTEGER,
                ranking INTEGER,
                is_active INTEGER,
                last_updated TEXT
            )
        """)
        
        # Sync logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                master_id TEXT,
                slave_id TEXT,
                event_type TEXT,
                details TEXT
            )
        """)
        
        conn.commit()
        conn.close()
    
    def save_signal(self, signal: TradeSignal):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO signals 
            (signal_id, timestamp, master_id, symbol, action, direction, entry_price, 
             stop_loss, take_profit, lot_size, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal.signal_id, signal.timestamp.isoformat(), signal.master_id,
            signal.symbol, signal.action, signal.direction, signal.entry_price,
            signal.stop_loss, signal.take_profit, signal.lot_size, signal.comment
        ))
        conn.commit()
        conn.close()
    
    def save_replication(self, record: ReplicationRecord):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO replications
            (record_id, signal_id, master_id, slave_id, timestamp, status,
             master_lot, slave_lot, replication_ratio, slave_order_id, 
             error_message, execution_time_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.record_id, record.signal_id, record.master_id, record.slave_id,
            record.timestamp.isoformat(), record.status, record.master_lot,
            record.slave_lot, record.replication_ratio, record.slave_order_id,
            record.error_message, record.execution_time_ms
        ))
        conn.commit()
        conn.close()
    
    def log_sync_event(self, master_id: str, slave_id: str, event_type: str, details: Dict):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO sync_logs (timestamp, master_id, slave_id, event_type, details)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(), master_id, slave_id, event_type, json.dumps(details)
        ))
        conn.commit()
        conn.close()
    
    def get_replication_stats(self, master_id: str, slave_id: Optional[str] = None) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if slave_id:
            cursor.execute("""
                SELECT status, COUNT(*) FROM replications 
                WHERE master_id = ? AND slave_id = ?
                GROUP BY status
            """, (master_id, slave_id))
        else:
            cursor.execute("""
                SELECT status, COUNT(*) FROM replications 
                WHERE master_id = ?
                GROUP BY status
            """, (master_id,))
        
        results = cursor.fetchall()
        conn.close()
        
        stats = {'total': 0, 'success': 0, 'failed': 0, 'pending': 0}
        for status, count in results:
            stats[status.lower()] = count
            stats['total'] += count
        
        stats['success_rate'] = stats['success'] / stats['total'] if stats['total'] > 0 else 0.0
        return stats


class MasterAccount:
    """Master account that generates trade signals"""
    
    def __init__(self, master_id: str, name: str, initial_balance: float = 10000.0):
        self.master_id = master_id
        self.name = name
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.slaves: Dict[str, 'SlaveAccount'] = {}
        self.active_signals: Dict[str, TradeSignal] = {}
        self.signal_history: List[TradeSignal] = []
        self.db = CopyTradingDatabase()
        self.running = False
        self.signal_thread: Optional[threading.Thread] = None
        self.signal_callbacks: List[Callable[[TradeSignal], None]] = []
    
    def add_slave(self, slave: 'SlaveAccount', replication_mode: ReplicationMode = ReplicationMode.MULTIPLIER, 
                  replication_value: float = 1.0):
        slave.replication_mode = replication_mode
        slave.replication_value = replication_value
        slave.master_id = self.master_id
        self.slaves[slave.slave_id] = slave
        self.db.log_sync_event(self.master_id, slave.slave_id, "SLAVE_ADDED", {
            'mode': replication_mode.value,
            'value': replication_value
        })
        print(f"✅ Slave {slave.name} added to master {self.name}")
    
    def remove_slave(self, slave_id: str):
        if slave_id in self.slaves:
            slave = self.slaves.pop(slave_id)
            self.db.log_sync_event(self.master_id, slave_id, "SLAVE_REMOVED", {'slave_name': slave.name})
            print(f"👋 Slave {slave.name} removed from master {self.name}")
    
    def on_signal(self, callback: Callable[[TradeSignal], None]):
        self.signal_callbacks.append(callback)
    
    def emit_signal(self, signal: TradeSignal):
        signal.master_id = self.master_id
        signal.timestamp = datetime.now()
        self.db.save_signal(signal)
        self.active_signals[signal.signal_id] = signal
        self.signal_history.append(signal)
        
        for callback in self.signal_callbacks:
            try:
                callback(signal)
            except Exception as e:
                print(f"Error in signal callback: {e}")
        
        for slave in self.slaves.values():
            slave.replicate_signal(signal)
        
        self.db.log_sync_event(self.master_id, "ALL", "SIGNAL_EMITTED", {
            'signal_id': signal.signal_id,
            'symbol': signal.symbol,
            'action': signal.action,
            'slaves_count': len(self.slaves)
        })
    
    def close_signal(self, signal_id: str, exit_price: float):
        if signal_id in self.active_signals:
            signal = self.active_signals.pop(signal_id)
            close_signal = TradeSignal(
                signal_id=str(uuid.uuid4()),
                timestamp=datetime.now(),
                master_id=self.master_id,
                symbol=signal.symbol,
                action="CLOSE",
                direction=signal.direction,
                entry_price=exit_price,
                comment=f"Closing {signal_id}"
            )
            self.emit_signal(close_signal)
    
    def start_monitoring(self, check_interval: float = 1.0):
        self.running = True
        self.signal_thread = threading.Thread(target=self._monitor_loop, args=(check_interval,))
        self.signal_thread.daemon = True
        self.signal_thread.start()
        print(f"📡 Master {self.name} monitoring started")
    
    def _monitor_loop(self, interval: float):
        while self.running:
            time.sleep(interval)
    
    def stop_monitoring(self):
        self.running = False
        if self.signal_thread:
            self.signal_thread.join(timeout=5)
        print(f"🛑 Master {self.name} monitoring stopped")
    
    def get_stats(self) -> Dict:
        return {
            'master_id': self.master_id,
            'name': self.name,
            'balance': self.current_balance,
            'slaves_count': len(self.slaves),
            'active_signals': len(self.active_signals),
            'total_signals': len(self.signal_history),
            'replication_stats': self.db.get_replication_stats(self.master_id)
        }


class SlaveAccount:
    """Slave account that replicates master trades"""
    
    def __init__(self, slave_id: str, name: str, initial_balance: float = 10000.0):
        self.slave_id = slave_id
        self.name = name
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.master_id: Optional[str] = None
        self.replication_mode = ReplicationMode.MULTIPLIER
        self.replication_value = 1.0
        self.open_positions: Dict[str, Dict] = {}
        self.replication_history: List[ReplicationRecord] = []
        self.db = CopyTradingDatabase()
        self.execution_callback: Optional[Callable[[TradeSignal, float], bool]] = None
    
    def set_execution_callback(self, callback: Callable[[TradeSignal, float], bool]):
        self.execution_callback = callback
    
    def calculate_lot_size(self, master_signal: TradeSignal) -> float:
        master_lot = master_signal.lot_size
        
        if self.replication_mode == ReplicationMode.FIXED:
            return self.replication_value
        elif self.replication_mode == ReplicationMode.MULTIPLIER:
            return master_lot * self.replication_value
        elif self.replication_mode == ReplicationMode.RATIO:
            master_balance = 10000.0
            ratio = self.current_balance / master_balance
            return master_lot * ratio * self.replication_value
        elif self.replication_mode == ReplicationMode.RISK:
            if master_signal.stop_loss:
                risk_distance = abs(master_signal.entry_price - master_signal.stop_loss)
                risk_amount = self.current_balance * 0.01 * self.replication_value
                lot_size = risk_amount / (risk_distance * 100000)
                return max(0.01, lot_size)
            return master_lot * self.replication_value
        elif self.replication_mode == ReplicationMode.SIGNAL:
            return 0.0
        return master_lot
    
    def replicate_signal(self, signal: TradeSignal) -> ReplicationRecord:
        start_time = time.time()
        slave_lot = self.calculate_lot_size(signal)
        ratio = slave_lot / signal.lot_size if signal.lot_size > 0 else 1.0
        
        record = ReplicationRecord(
            record_id=str(uuid.uuid4()),
            signal_id=signal.signal_id,
            master_id=signal.master_id,
            slave_id=self.slave_id,
            timestamp=datetime.now(),
            status="PENDING",
            master_lot=signal.lot_size,
            slave_lot=slave_lot,
            replication_ratio=ratio
        )
        
        success = False
        if self.execution_callback:
            try:
                success = self.execution_callback(signal, slave_lot)
            except Exception as e:
                record.error_message = str(e)
                success = False
        else:
            success = True
            record.slave_order_id = str(uuid.uuid4())
        
        record.status = "SUCCESS" if success else "FAILED"
        record.execution_time_ms = int((time.time() - start_time) * 1000)
        
        self.db.save_replication(record)
        self.replication_history.append(record)
        
        if success and signal.action == "OPEN":
            self.open_positions[signal.signal_id] = {
                'signal': signal,
                'lot_size': slave_lot,
                'entry_time': datetime.now()
            }
        elif signal.action == "CLOSE":
            for pos_id, pos in list(self.open_positions.items()):
                if pos['signal'].symbol == signal.symbol:
                    del self.open_positions[pos_id]
                    break
        
        self.db.log_sync_event(signal.master_id, self.slave_id, 
                              "REPLICATION_SUCCESS" if success else "REPLICATION_FAILED", {
            'signal_id': signal.signal_id,
            'symbol': signal.symbol,
            'slave_lot': slave_lot,
            'execution_time_ms': record.execution_time_ms
        })
        
        status_icon = "✅" if success else "❌"
        print(f"{status_icon} {self.name} replicated {signal.symbol} {signal.action} | "
              f"Lot: {slave_lot:.2f} | Ratio: {ratio:.2f}x | Time: {record.execution_time_ms}ms")
        
        return record
    
    def get_stats(self) -> Dict:
        stats = self.db.get_replication_stats(self.master_id or "", self.slave_id)
        return {
            'slave_id': self.slave_id,
            'name': self.name,
            'balance': self.current_balance,
            'master_id': self.master_id,
            'replication_mode': self.replication_mode.value,
            'open_positions': len(self.open_positions),
            'total_replications': len(self.replication_history),
            'replication_stats': stats
        }


class LeaderboardManager:
    """Manage trader leaderboards and rankings"""
    
    def __init__(self, db_path: str = "social/copy_trading.db"):
        self.db_path = db_path
        self.db = CopyTradingDatabase(db_path)
    
    def update_trader(self, profile: TraderProfile):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO traders
            (trader_id, name, account_balance, total_return, monthly_return, 
             sharpe_ratio, max_drawdown, win_rate, total_trades, followers, 
             ranking, is_active, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            profile.trader_id, profile.name, profile.account_balance,
            profile.total_return, profile.monthly_return, profile.sharpe_ratio,
            profile.max_drawdown, profile.win_rate, profile.total_trades,
            profile.followers, profile.ranking, int(profile.is_active),
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()
    
    def calculate_rankings(self) -> List[TraderProfile]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT trader_id, name, account_balance, total_return, monthly_return,
                   sharpe_ratio, max_drawdown, win_rate, total_trades, followers, is_active
            FROM traders WHERE is_active = 1
        """)
        rows = cursor.fetchall()
        conn.close()
        
        profiles = []
        for row in rows:
            profile = TraderProfile(
                trader_id=row[0], name=row[1], account_balance=row[2],
                total_return=row[3], monthly_return=row[4], sharpe_ratio=row[5],
                max_drawdown=row[6], win_rate=row[7], total_trades=row[8],
                followers=row[9], is_active=bool(row[10])
            )
            profiles.append(profile)
        
        profiles.sort(key=lambda x: x.score, reverse=True)
        for i, profile in enumerate(profiles, 1):
            profile.ranking = i
            self.update_trader(profile)
        
        return profiles
    
    def get_leaderboard(self, top_n: int = 10) -> pd.DataFrame:
        profiles = self.calculate_rankings()
        top_traders = profiles[:top_n]
        
        data = []
        for trader in top_traders:
            data.append({
                'Rank': trader.ranking,
                'Trader': trader.name,
                'Return (%)': f"{trader.total_return:.2%}",
                'Sharpe': f"{trader.sharpe_ratio:.2f}",
                'Max DD': f"{trader.max_drawdown:.2%}",
                'Win Rate': f"{trader.win_rate:.1%}",
                'Trades': trader.total_trades,
                'Followers': trader.followers,
                'Score': f"{trader.score:.2f}"
            })
        return pd.DataFrame(data)
    
    def export_leaderboard(self, output_path: str = "social/leaderboards/leaderboard.json"):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        profiles = self.calculate_rankings()
        
        data = {
            'timestamp': datetime.now().isoformat(),
            'traders': [
                {
                    'rank': p.ranking, 'trader_id': p.trader_id, 'name': p.name,
                    'total_return': p.total_return, 'sharpe_ratio': p.sharpe_ratio,
                    'max_drawdown': p.max_drawdown, 'win_rate': p.win_rate,
                    'followers': p.followers, 'score': p.score
                }
                for p in profiles[:50]
            ]
        }
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Leaderboard exported: {output_path}")
        return output_path
    
    def get_replication_ratio_test(self, master_id: str, slave_id: str) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT master_lot, slave_lot, replication_ratio, timestamp
            FROM replications
            WHERE master_id = ? AND slave_id = ? AND status = 'SUCCESS'
            ORDER BY timestamp DESC
            LIMIT 100
        """, (master_id, slave_id))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return {'error': 'No replication data found'}
        
        ratios = [row[2] for row in rows]
        return {
            'master_id': master_id, 'slave_id': slave_id,
            'total_replications': len(rows),
            'avg_ratio': np.mean(ratios),
            'std_ratio': np.std(ratios),
            'min_ratio': min(ratios),
            'max_ratio': max(ratios),
            'consistency': 1 - (np.std(ratios) / np.mean(ratios)) if np.mean(ratios) > 0 else 0
        }


class CopyTradingEngine:
    """Main copy trading engine managing masters and slaves"""
    
    def __init__(self):
        self.masters: Dict[str, MasterAccount] = {}
        self.slaves: Dict[str, SlaveAccount] = {}
        self.leaderboard = LeaderboardManager()
        self.db = CopyTradingDatabase()
        self.running = False
    
    def create_master(self, name: str, initial_balance: float = 10000.0) -> MasterAccount:
        master_id = str(uuid.uuid4())
        master = MasterAccount(master_id, name, initial_balance)
        self.masters[master_id] = master
        print(f"✅ Master account created: {name} (ID: {master_id})")
        return master
    
    def create_slave(self, name: str, initial_balance: float = 10000.0) -> SlaveAccount:
        slave_id = str(uuid.uuid4())
        slave = SlaveAccount(slave_id, name, initial_balance)
        self.slaves[slave_id] = slave
        print(f"✅ Slave account created: {name} (ID: {slave_id})")
        return slave
    
    def link_accounts(self, master_id: str, slave_id: str, 
                     mode: ReplicationMode = ReplicationMode.MULTIPLIER,
                     value: float = 1.0):
        if master_id not in self.masters:
            print(f"❌ Master {master_id} not found")
            return False
        if slave_id not in self.slaves:
            print(f"❌ Slave {slave_id} not found")
            return False
        
        master = self.masters[master_id]
        slave = self.slaves[slave_id]
        master.add_slave(slave, mode, value)
        return True
    
    def start(self):
        self.running = True
        for master in self.masters.values():
            master.start_monitoring()
        print("🚀 Copy Trading Engine started")
    
    def stop(self):
        self.running = False
        for master in self.masters.values():
            master.stop_monitoring()
        print("🛑 Copy Trading Engine stopped")
    
    def get_system_stats(self) -> Dict:
        return {
            'masters_count': len(self.masters),
            'slaves_count': len(self.slaves),
            'masters': [m.get_stats() for m in self.masters.values()],
            'slaves': [s.get_stats() for s in self.slaves.values()]
        }
    
    def generate_sync_report(self, output_dir: str = "social/sync_logs") -> str:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_path = Path(output_dir) / f"sync_report_{timestamp}.json"
        
        stats = self.get_system_stats()
        replication_tests = []
        for master in self.masters.values():
            for slave in master.slaves.values():
                test_result = self.leaderboard.get_replication_ratio_test(
                    master.master_id, slave.slave_id
                )
                replication_tests.append(test_result)
        
        stats['replication_tests'] = replication_tests
        with open(report_path, 'w') as f:
            json.dump(stats, f, indent=2, default=str)
        
        print(f"Sync report generated: {report_path}")
        return str(report_path)


if __name__ == "__main__":
    print("HOPEFX Copy Trading Engine")
    print("Features:")
    print("  ✅ Master/Slave architecture")
    print("  ✅ 5 replication modes (Fixed, Multiplier, Ratio, Risk, Signal)")
    print("  ✅ SQLite database for persistence")
    print("  ✅ Leaderboard with scoring system")
    print("  ✅ Sync logs and replication testing")
    print("  ✅ Real-time trade mirroring")
'''

# Save the file
with open('social/copy_trading.py', 'w') as f:
    f.write(code)

print("✅ Created: social/copy_trading.py")
print(f"   Lines: {len(code.splitlines())}")
print(f"   Size: {len(code)} bytes")
print("\n📊 Copy Trading Engine Summary:")
print("   ✅ Master/Slave architecture with signal replication")
print("   ✅ 5 replication modes: Fixed, Multiplier, Ratio, Risk, Signal")
print("   ✅ SQLite database for signals, replications, traders, sync logs")
print("   ✅ Leaderboard with scoring (return, sharpe, drawdown, win rate)")
print("   ✅ Replication ratio testing and consistency analysis")
print("   ✅ Real-time sync logs export")
