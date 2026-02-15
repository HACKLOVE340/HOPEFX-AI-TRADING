"""
Component Status Module

This module provides utilities for checking component availability,
versions, and overall system health.

Author: HOPEFX Development Team
Version: 1.0.0
"""

import sys
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


logger = logging.getLogger(__name__)


class ComponentHealth(Enum):
    """Component health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass
class ComponentStatus:
    """Status information for a component."""
    name: str
    available: bool
    version: str
    health: ComponentHealth
    error: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    features: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'name': self.name,
            'available': self.available,
            'version': self.version,
            'health': self.health.value,
            'error': self.error,
            'dependencies': self.dependencies,
            'features': self.features,
        }


# Framework version
FRAMEWORK_VERSION = '1.0.0'


def get_framework_version() -> str:
    """Get the framework version."""
    return FRAMEWORK_VERSION


def get_component_status(component_name: str) -> ComponentStatus:
    """
    Get the status of a specific component.
    
    Args:
        component_name: Name of the component to check
        
    Returns:
        ComponentStatus object with component information
    """
    component_map = {
        'config': _check_config,
        'cache': _check_cache,
        'database': _check_database,
        'brokers': _check_brokers,
        'strategies': _check_strategies,
        'risk': _check_risk,
        'notifications': _check_notifications,
        'ml': _check_ml,
        'backtesting': _check_backtesting,
        'news': _check_news,
        'analytics': _check_analytics,
        'monetization': _check_monetization,
        'payments': _check_payments,
        'social': _check_social,
        'mobile': _check_mobile,
        'charting': _check_charting,
    }
    
    if component_name not in component_map:
        return ComponentStatus(
            name=component_name,
            available=False,
            version='unknown',
            health=ComponentHealth.UNKNOWN,
            error=f"Unknown component: {component_name}"
        )
    
    return component_map[component_name]()


def get_all_component_statuses() -> Dict[str, ComponentStatus]:
    """
    Get the status of all components.
    
    Returns:
        Dictionary mapping component names to their status
    """
    components = [
        'config', 'cache', 'database', 'brokers', 'strategies',
        'risk', 'notifications', 'ml', 'backtesting', 'news',
        'analytics', 'monetization', 'payments', 'social',
        'mobile', 'charting'
    ]
    
    return {name: get_component_status(name) for name in components}


def _check_config() -> ComponentStatus:
    """Check config component."""
    try:
        from config import __version__, ConfigManager
        return ComponentStatus(
            name='config',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            features=['encryption', 'multi-environment', 'validation']
        )
    except ImportError as e:
        return ComponentStatus(
            name='config',
            available=False,
            version='unknown',
            health=ComponentHealth.UNAVAILABLE,
            error=str(e)
        )


def _check_cache() -> ComponentStatus:
    """Check cache component."""
    try:
        from cache import __version__, MarketDataCache
        return ComponentStatus(
            name='cache',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            dependencies=['redis'],
            features=['multi-timeframe', 'TTL', 'statistics']
        )
    except ImportError as e:
        return ComponentStatus(
            name='cache',
            available=False,
            version='unknown',
            health=ComponentHealth.UNAVAILABLE,
            error=str(e)
        )


def _check_database() -> ComponentStatus:
    """Check database component."""
    try:
        from database import __version__, Base
        return ComponentStatus(
            name='database',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            dependencies=['sqlalchemy'],
            features=['ORM', 'migrations', 'multi-database']
        )
    except ImportError as e:
        return ComponentStatus(
            name='database',
            available=False,
            version='unknown',
            health=ComponentHealth.UNAVAILABLE,
            error=str(e)
        )


def _check_brokers() -> ComponentStatus:
    """Check brokers component."""
    try:
        from brokers import __version__, BrokerFactory
        return ComponentStatus(
            name='brokers',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            features=['OANDA', 'Binance', 'Alpaca', 'MT5', 'IB', 'Paper Trading']
        )
    except ImportError as e:
        return ComponentStatus(
            name='brokers',
            available=False,
            version='unknown',
            health=ComponentHealth.UNAVAILABLE,
            error=str(e)
        )


def _check_strategies() -> ComponentStatus:
    """Check strategies component."""
    try:
        from strategies import __version__, StrategyManager
        return ComponentStatus(
            name='strategies',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            features=['11 strategies', 'Strategy Brain', 'SMC ICT', 'ITS-8-OS']
        )
    except ImportError as e:
        return ComponentStatus(
            name='strategies',
            available=False,
            version='unknown',
            health=ComponentHealth.UNAVAILABLE,
            error=str(e)
        )


def _check_risk() -> ComponentStatus:
    """Check risk component."""
    try:
        from risk import __version__, RiskManager
        return ComponentStatus(
            name='risk',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            features=['position sizing', 'drawdown monitoring', 'daily limits']
        )
    except ImportError as e:
        return ComponentStatus(
            name='risk',
            available=False,
            version='unknown',
            health=ComponentHealth.UNAVAILABLE,
            error=str(e)
        )


def _check_notifications() -> ComponentStatus:
    """Check notifications component."""
    try:
        from notifications import __version__, NotificationManager
        return ComponentStatus(
            name='notifications',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            features=['Discord', 'Telegram', 'Email', 'SMS', 'Slack']
        )
    except ImportError as e:
        return ComponentStatus(
            name='notifications',
            available=False,
            version='unknown',
            health=ComponentHealth.UNAVAILABLE,
            error=str(e)
        )


def _check_ml() -> ComponentStatus:
    """Check ML component."""
    try:
        from ml import __version__, LSTMPricePredictor
        return ComponentStatus(
            name='ml',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            dependencies=['tensorflow', 'scikit-learn'],
            features=['LSTM', 'Random Forest', 'feature engineering']
        )
    except ImportError as e:
        return ComponentStatus(
            name='ml',
            available=False,
            version='unknown',
            health=ComponentHealth.DEGRADED,
            error=str(e)
        )


def _check_backtesting() -> ComponentStatus:
    """Check backtesting component."""
    try:
        from backtesting import __version__, BacktestEngine
        return ComponentStatus(
            name='backtesting',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            features=['engine', 'optimization', 'walk-forward', 'reports']
        )
    except ImportError as e:
        return ComponentStatus(
            name='backtesting',
            available=False,
            version='unknown',
            health=ComponentHealth.DEGRADED,
            error=str(e)
        )


def _check_news() -> ComponentStatus:
    """Check news component."""
    try:
        from news import __version__, MultiSourceAggregator
        return ComponentStatus(
            name='news',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            features=['sentiment analysis', 'impact prediction', 'economic calendar']
        )
    except ImportError as e:
        return ComponentStatus(
            name='news',
            available=False,
            version='unknown',
            health=ComponentHealth.DEGRADED,
            error=str(e),
            dependencies=['feedparser', 'textblob']
        )


def _check_analytics() -> ComponentStatus:
    """Check analytics component."""
    try:
        from analytics import __version__, PortfolioOptimizer
        return ComponentStatus(
            name='analytics',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            features=['portfolio optimization', 'options analysis', 'simulations']
        )
    except ImportError as e:
        return ComponentStatus(
            name='analytics',
            available=False,
            version='unknown',
            health=ComponentHealth.DEGRADED,
            error=str(e)
        )


def _check_monetization() -> ComponentStatus:
    """Check monetization component."""
    try:
        from monetization import __version__, SubscriptionManager
        return ComponentStatus(
            name='monetization',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            features=['subscriptions', 'pricing tiers', 'invoices', 'licenses']
        )
    except ImportError as e:
        return ComponentStatus(
            name='monetization',
            available=False,
            version='unknown',
            health=ComponentHealth.DEGRADED,
            error=str(e)
        )


def _check_payments() -> ComponentStatus:
    """Check payments component."""
    try:
        from payments import __version__, WalletManager
        return ComponentStatus(
            name='payments',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            features=['wallet', 'crypto', 'fintech', 'compliance']
        )
    except ImportError as e:
        return ComponentStatus(
            name='payments',
            available=False,
            version='unknown',
            health=ComponentHealth.DEGRADED,
            error=str(e)
        )


def _check_social() -> ComponentStatus:
    """Check social component."""
    try:
        from social import __version__, CopyTradingEngine
        return ComponentStatus(
            name='social',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            features=['copy trading', 'marketplace', 'leaderboards']
        )
    except ImportError as e:
        return ComponentStatus(
            name='social',
            available=False,
            version='unknown',
            health=ComponentHealth.DEGRADED,
            error=str(e)
        )


def _check_mobile() -> ComponentStatus:
    """Check mobile component."""
    try:
        from mobile import __version__, MobileAPI
        return ComponentStatus(
            name='mobile',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            features=['mobile API', 'push notifications', 'analytics']
        )
    except ImportError as e:
        return ComponentStatus(
            name='mobile',
            available=False,
            version='unknown',
            health=ComponentHealth.DEGRADED,
            error=str(e)
        )


def _check_charting() -> ComponentStatus:
    """Check charting component."""
    try:
        from charting import __version__, ChartEngine
        return ComponentStatus(
            name='charting',
            available=True,
            version=__version__,
            health=ComponentHealth.HEALTHY,
            features=['chart engine', 'indicators', 'drawing tools']
        )
    except ImportError as e:
        return ComponentStatus(
            name='charting',
            available=False,
            version='unknown',
            health=ComponentHealth.DEGRADED,
            error=str(e)
        )


def print_component_status_report() -> None:
    """Print a formatted component status report to console."""
    print("\n" + "=" * 70)
    print("HOPEFX AI TRADING FRAMEWORK - COMPONENT STATUS REPORT")
    print("=" * 70)
    print(f"Framework Version: {FRAMEWORK_VERSION}")
    print("-" * 70)
    
    statuses = get_all_component_statuses()
    
    available_count = sum(1 for s in statuses.values() if s.available)
    total_count = len(statuses)
    
    for name, status in statuses.items():
        icon = "✓" if status.available else "✗"
        health_icon = {
            ComponentHealth.HEALTHY: "🟢",
            ComponentHealth.DEGRADED: "🟡",
            ComponentHealth.UNAVAILABLE: "🔴",
            ComponentHealth.UNKNOWN: "⚪",
        }.get(status.health, "⚪")
        
        print(f"{health_icon} {icon} {name:15} v{status.version:8} - {status.health.value}")
        
        if status.features:
            print(f"     Features: {', '.join(status.features[:3])}")
        
        if status.error:
            print(f"     Error: {status.error[:60]}...")
    
    print("-" * 70)
    print(f"Total: {available_count}/{total_count} components available")
    print("=" * 70 + "\n")


if __name__ == '__main__':
    print_component_status_report()
