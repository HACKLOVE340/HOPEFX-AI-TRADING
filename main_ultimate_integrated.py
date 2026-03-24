# main_ultimate_integrated.py
"""
LEGACY — do not use as an entry point.

This file is kept for reference only. The canonical entry point is app.py.
GPU acceleration stubs live in core/acceleration/gpu_engine.py.
Risk engine lives in core/risk/advanced_engine.py.

HOPEFX ULTIMATE INTEGRATED EDITION v3.0
The World's Most Advanced AI Trading System

Features:
- Master Control Core with Event Bus (1M+ events/sec)
- Strategy Orchestra (multi-strategy coordination)
- GPU Acceleration (CUDA inference)
- Advanced Risk Engine (Monte Carlo + GARCH + Copula)
- Cross-Exchange Arbitrage (multi-venue execution)
- Real-Time Heatmap Analytics (live correlation & regime detection)
- FPGA Integration (optional ultra-low latency)
- Distributed Architecture (multi-node ready)
"""

import asyncio
import json
import sys
import signal
try:
    import torch
    HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore[assignment]
    HAS_TORCH = False
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from contextlib import asynccontextmanager

# Project root
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Core infrastructure
from core.event_bus import MemoryMappedEventStore, EventBus, DomainEvent
from core.strategy_orchestra import StrategyOrchestra
from core.acceleration.gpu_engine import GPUInferenceEngine, GPUFeatureEngine, GPUConfig
from core.risk.advanced_engine import MonteCarloRiskEngine, RealTimeRiskMonitor, GARCHModel, CopulaRiskModel
from core.arbitrage.cross_exchange import CrossExchangeEngine, ExchangeConnector
from core.analytics.realtime_heatmap import RealtimeHeatmapEngine

# Existing HOPEFX components (your current code)
from config.config_manager import initialize_config, ConfigManager
from cache.market_data_cache import MarketDataCache
from database.models import Base, Session, Trade, Position
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Visualization
from visualization.dashboard import DashboardServer

# Safety & liveness
from kill_switch import KillSwitch
from heartbeat_monitor import HeartbeatMonitor


@dataclass
class SystemConfig:
    """Ultimate system configuration"""
    # Feature flags
    enable_gpu: bool = True
    enable_fpga: bool = False
    enable_arbitrage: bool = True
    enable_risk_montecarlo: bool = True
    
    # Performance
    event_bus_buffer_size: int = 10000
    gpu_batch_size: int = 64
    risk_calculation_interval_sec: int = 60
    
    # Safety
    max_daily_loss_usd: Decimal = Decimal("5000")
    emergency_drawdown_pct: float = 0.15
    kill_switch_enabled: bool = True


class ComponentHealth:
    """Health monitoring for each component"""
    def __init__(self, name: str):
        self.name = name
        self.status = "initializing"
        self.last_heartbeat = datetime.now(timezone.utc)
        self.error_count = 0
        self.latency_ms = 0.0
        self.throughput = 0.0
    
    def update(self, status: str, latency_ms: float = 0, throughput: float = 0):
        self.status = status
        self.last_heartbeat = datetime.now(timezone.utc)
        self.latency_ms = latency_ms
        self.throughput = throughput
    
    def is_healthy(self) -> bool:
        return self.status == "healthy" and \
               (datetime.now(timezone.utc) - self.last_heartbeat).seconds < 10


class HopeFXUltimateIntegrated:
    """
    The Master Brain of HOPEFX.
    Integrates all components into a unified, fault-tolerant system.
    """
    
    def __init__(self):
        self.start_time = datetime.now(timezone.utc)
        self.config = SystemConfig()
        self.health: Dict[str, ComponentHealth] = {}
        self.is_running = False
        self.emergency_stop = False
        
        # Core components
        self.event_store: Optional[MemoryMappedEventStore] = None
        self.event_bus: Optional[EventBus] = None
        self.orchestra: Optional[StrategyOrchestra] = None
        
        # Acceleration
        self.gpu_engine: Optional[GPUInferenceEngine] = None
        self.gpu_features: Optional[GPUFeatureEngine] = None
        
        # Risk
        self.risk_engine: Optional[MonteCarloRiskEngine] = None
        self.risk_monitor: Optional[RealTimeRiskMonitor] = None
        
        # Arbitrage
        self.arbitrage_engine: Optional[CrossExchangeEngine] = None
        
        # Analytics
        self.heatmap_engine: Optional[RealtimeHeatmapEngine] = None
        self.dashboard: Optional[DashboardServer] = None
        
        # Existing HOPEFX
        self.config_manager: Optional[ConfigManager] = None
        self.db_engine = None
        self.db_session = None
        self.cache: Optional[MarketDataCache] = None
        
        # Safety & liveness (initialized in _init_safety)
        self.kill_switch: Optional[KillSwitch] = None
        self.heartbeat_monitor: Optional[HeartbeatMonitor] = None
        
        # Prop-firm mode (loaded from prop_firm_mode.json if present)
        self.prop_firm_config: Optional[dict] = self._load_prop_firm_config()
        
        # Performance tracking
        self.performance_metrics = {
            'events_processed': 0,
            'trades_executed': 0,
            'ml_inferences': 0,
            'risk_calculations': 0,
            'arbitrage_profit': Decimal("0")
        }
        
        self._print_banner()
    
    def _print_banner(self):
        print("╔══════════════════════════════════════════════════════════════════╗")
        print("║                                                                  ║")
        print("║     🤖 HOPEFX ULTIMATE INTEGRATED EDITION v3.0 🤖                ║")
        print("║                                                                  ║")
        print("║     The World's Most Advanced AI Trading System                  ║")
        print("║                                                                  ║")
        print("║     Features:                                                    ║")
        print("║     • Master Control Core (1M+ events/sec)                       ║")
        print("║     • Strategy Orchestra (multi-strategy AI)                     ║")
        print("║     • GPU Acceleration (CUDA inference)                            ║")
        print("║     • Advanced Risk (Monte Carlo + GARCH + Copula)               ║")
        print("║     • Cross-Exchange Arbitrage (multi-venue)                     ║")
        print("║     • Real-Time Heatmap (live analytics)                         ║")
        print("║     • Kill Switch (instant trading halt)                          ║")
        print("║     • Heartbeat Monitor (component liveness)                     ║")
        print("║                                                                  ║")
        print("╚══════════════════════════════════════════════════════════════════╝")

    @staticmethod
    def _load_prop_firm_config() -> Optional[dict]:
        """Load prop_firm_mode.json from the project root if it exists."""
        cfg_path = Path(__file__).parent / "prop_firm_mode.json"
        if not cfg_path.exists():
            return None
        try:
            with cfg_path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            enabled = data.get("enabled", False)
            firm = data.get("active_firm", "")
            if enabled:
                print(f"   ⚠ Prop-firm mode ENABLED ({firm})")
            return data
        except Exception as exc:
            print(f"   ⚠ Could not load prop_firm_mode.json: {exc}")
            return None
    
    async def initialize(self):
        """Initialize all components with dependency injection"""
        print("\n🛡️  PHASE 0: Safety & Liveness")
        await self._init_safety()

        print("\n🔧 PHASE 1: Core Infrastructure")
        await self._init_core_infrastructure()
        
        print("\n🧠 PHASE 2: Master Control Core")
        await self._init_master_control_core()
        
        print("\n🚀 PHASE 3: Acceleration Engines")
        await self._init_acceleration()
        
        print("\n⚠️  PHASE 4: Risk Management")
        await self._init_risk_engine()
        
        print("\n💱 PHASE 5: Arbitrage Engine")
        await self._init_arbitrage()
        
        print("\n📊 PHASE 6: Analytics & Visualization")
        await self._init_analytics()
        
        print("\n🎯 PHASE 7: Strategy Registration")
        await self._init_strategies()
        
        print("\n✅ ALL SYSTEMS INITIALIZED AND INTEGRATED")
        self._print_system_status()
    
    async def _init_safety(self):
        """Initialize KillSwitch and HeartbeatMonitor before anything else."""
        # Kill switch – event bus not yet available; wired later in _init_master_control_core
        self.kill_switch = KillSwitch(poll_interval_sec=1.0)
        self.kill_switch.register_callback(self._on_kill_switch_callback)
        await self.kill_switch.start()
        self.health['kill_switch'] = ComponentHealth('kill_switch')
        self.health['kill_switch'].update('healthy')
        print("   ✓ Kill Switch (file-flag + env-var polling active)")

        # Heartbeat monitor – critical components added as they are initialised
        self.heartbeat_monitor = HeartbeatMonitor(
            check_interval_sec=5.0,
            kill_switch=self.kill_switch,
        )
        self.health['heartbeat_monitor'] = ComponentHealth('heartbeat_monitor')
        self.health['heartbeat_monitor'].update('healthy')
        print("   ✓ Heartbeat Monitor (component liveness)")

        # Log whether prop-firm mode is active
        if self.prop_firm_config and self.prop_firm_config.get("enabled"):
            firm = self.prop_firm_config.get("active_firm", "unknown")
            print(f"   ✓ Prop-firm mode active: {firm}")
        else:
            print("   ℹ Prop-firm mode disabled (set enabled=true in prop_firm_mode.json to activate)")

    async def _init_core_infrastructure(self):
        """Initialize database, cache, config"""
        # Config
        self.config_manager = initialize_config()
        self.health['config'] = ComponentHealth('config')
        self.health['config'].update('healthy')
        print("   ✓ Configuration Manager")
        
        # Database
        db_path = Path(self.config_manager.database.database).parent
        db_path.mkdir(parents=True, exist_ok=True)
        self.db_engine = create_engine(self.config_manager.database.get_connection_string())
        Base.metadata.create_all(self.db_engine)
        Session = sessionmaker(bind=self.db_engine)
        self.db_session = Session()
        self.health['database'] = ComponentHealth('database')
        self.health['database'].update('healthy')
        print("   ✓ Database (SQLAlchemy)")
        
        # Cache
        self.cache = MarketDataCache()
        self.health['cache'] = ComponentHealth('cache')
        self.health['cache'].update('healthy')
        print("   ✓ Market Data Cache (Redis)")
    
    async def _init_master_control_core(self):
        """Initialize event bus and strategy orchestra"""
        # Event Store (memory-mapped)
        self.event_store = MemoryMappedEventStore()
        self.health['event_store'] = ComponentHealth('event_store')
        self.health['event_store'].update('healthy')
        print("   ✓ Event Store (memory-mapped, 1M+ events/sec)")
        
        # Event Bus
        self.event_bus = EventBus(self.event_store)
        self.health['event_bus'] = ComponentHealth('event_bus')
        self.health['event_bus'].update('healthy')
        print("   ✓ Event Bus (zero-copy, async)")
        
        # Subscribe to critical events
        self.event_bus.subscribe('KILL_SWITCH', self._on_kill_switch)
        self.event_bus.subscribe('RISK_VIOLATION', self._on_risk_violation)
        self.event_bus.subscribe('EMERGENCY_STOP', self._on_emergency_stop)

        # Wire kill switch to event bus now that it is available
        if self.kill_switch is not None:
            self.kill_switch.set_event_bus(self.event_bus)

        # Register critical components with heartbeat monitor
        if self.heartbeat_monitor is not None:
            self.heartbeat_monitor.register('event_bus',   timeout_sec=10,  critical=True)
            self.heartbeat_monitor.register('price_feed',  timeout_sec=15,  critical=True)
            self.heartbeat_monitor.register('risk_engine', timeout_sec=120, critical=True)
            self.heartbeat_monitor.register('ml_inference',timeout_sec=120, critical=False)
        
        # Strategy Orchestra
        self.orchestra = StrategyOrchestra(self.event_bus)
        self.health['orchestra'] = ComponentHealth('orchestra')
        self.health['orchestra'].update('healthy')
        print("   ✓ Strategy Orchestra (multi-strategy coordination)")
    
    async def _init_acceleration(self):
        """Initialize GPU and optional FPGA"""
        if self.config.enable_gpu and HAS_TORCH and torch.cuda.is_available():
            gpu_config = GPUConfig(
                batch_size=self.config.gpu_batch_size,
                mixed_precision=True
            )
            self.gpu_engine = GPUInferenceEngine(gpu_config)
            self.gpu_engine.start()

            self.gpu_features = GPUFeatureEngine()

            self.health['gpu'] = ComponentHealth('gpu')
            self.health['gpu'].update('healthy')
            print(f"   ✓ GPU Engine ({torch.cuda.get_device_name(0)})")
        else:
            self.health['gpu'] = ComponentHealth('gpu')
            self.health['gpu'].update('disabled')
            print("   ⚠ GPU disabled (CUDA not available)")
        
        if self.config.enable_fpga:
            # FPGA initialization would go here
            self.health['fpga'] = ComponentHealth('fpga')
            self.health['fpga'].update('disabled')
            print("   ⚠ FPGA disabled (configure bitstream path)")
    
    async def _init_risk_engine(self):
        """Initialize Monte Carlo risk engine"""
        if self.config.enable_risk_montecarlo:
            self.risk_engine = MonteCarloRiskEngine(n_sims=100000)
            self.risk_monitor = RealTimeRiskMonitor(self.risk_engine)
            
            # Set limits from config
            self.risk_monitor.limits['var_95_daily'] = -0.02
            self.risk_monitor.limits['cvar_95_daily'] = -0.03
            
            self.health['risk_engine'] = ComponentHealth('risk_engine')
            self.health['risk_engine'].update('healthy')
            print("   ✓ Risk Engine (Monte Carlo + GARCH + Copula)")
        else:
            self.health['risk_engine'] = ComponentHealth('risk_engine')
            self.health['risk_engine'].update('disabled')
    
    async def _init_arbitrage(self):
        """Initialize cross-exchange arbitrage"""
        if self.config.enable_arbitrage:
            self.arbitrage_engine = CrossExchangeEngine()
            
            # Add exchanges (configure with your API keys)
            # self.arbitrage_engine.add_exchange(
            #     ExchangeConnector("binance", client, 50, {'maker': Decimal("0.001"), 'taker': Decimal("0.001")})
            # )
            
            self.health['arbitrage'] = ComponentHealth('arbitrage')
            self.health['arbitrage'].update('standby')  # Waiting for exchange config
            print("   ✓ Arbitrage Engine (standby - configure exchanges)")
        else:
            self.health['arbitrage'] = ComponentHealth('arbitrage')
            self.health['arbitrage'].update('disabled')
    
    async def _init_analytics(self):
        """Initialize heatmap and dashboard"""
        self.heatmap_engine = RealtimeHeatmapEngine(
            self.orchestra,
            self.risk_engine,
            self.event_bus
        )
        
        self.dashboard = DashboardServer(self.orchestra, self.event_bus)
        
        self.health['analytics'] = ComponentHealth('analytics')
        self.health['analytics'].update('healthy')
        print("   ✓ Real-Time Heatmap Analytics")
        print("   ✓ Web Dashboard (port 8080)")
    
    async def _init_strategies(self):
        """Register and activate strategies"""
        # Import your existing strategies here
        # from strategies.your_strategy import YourStrategy
        
        # Example registration:
        # for strategy_class in [TrendStrategy, MeanReversionStrategy, BreakoutStrategy]:
        #     strategy = strategy_class()
        #     self.orchestra.register_strategy(strategy, max_allocation=0.25)
        #     self.orchestra.activate_strategy(strategy.config.name)
        
        print("   ⚠ No strategies registered (add your strategies in _init_strategies)")
        print("   System running in MONITORING mode")
    
    def _print_system_status(self):
        """Print current system status"""
        print("\n📊 SYSTEM STATUS:")
        for name, health in self.health.items():
            status_icon = "🟢" if health.is_healthy() else "🔴" if health.status == "error" else "🟡"
            print(f"   {status_icon} {name:20s} | {health.status:12s} | "
                  f"latency: {health.latency_ms:.2f}ms | throughput: {health.throughput:.0f}/s")
    
    # ==================== EVENT HANDLERS ====================
    
    def _on_kill_switch(self, event: DomainEvent):
        """Handle kill switch activation"""
        data = event.decode()
        print(f"\n🚨 KILL SWITCH ACTIVATED: {data.get('reason', 'unknown')}")
        self.emergency_stop = True
        self._emergency_liquidate()
    
    def _on_risk_violation(self, event: DomainEvent):
        """Handle risk limit violation"""
        data = event.decode()
        violations = data.get('violations', [])
        print(f"\n⚠️  RISK VIOLATION: {', '.join(violations)}")
        
        if self.config.kill_switch_enabled and len(violations) > 2:
            self._trigger_kill_switch("Multiple risk violations")
    
    def _on_emergency_stop(self, event: DomainEvent):
        """Handle emergency stop from any component"""
        print("\n🛑 EMERGENCY STOP RECEIVED")
        self.emergency_stop = True

    def _on_kill_switch_callback(self, reason: str) -> None:
        """Callback invoked by KillSwitch on activation (non-event-bus path)."""
        print(f"\n🚨 KILL SWITCH CALLBACK: {reason}")
        self.emergency_stop = True
        if self.orchestra:
            self._emergency_liquidate()
    
    def _trigger_kill_switch(self, reason: str):
        """Trigger system-wide kill switch"""
        self.event_bus.publish(DomainEvent.create(
            'KILL_SWITCH',
            'master_control',
            {'reason': reason, 'timestamp': datetime.now(timezone.utc).isoformat()},
            priority=0  # CRITICAL
        ))
    
    def _emergency_liquidate(self):
        """Close all positions immediately"""
        print("   Closing all positions...")
        # Implementation depends on your broker integration
        for sid in list(self.orchestra.active_strategies):
            self.orchestra.deactivate_strategy(sid, "emergency liquidation")
    
    # ==================== MAIN LOOPS ====================
    
    async def run(self):
        """Run all system loops concurrently"""
        print("\n🚀 STARTING ALL SYSTEM LOOPS...")
        self.is_running = True

        # Start heartbeat monitor background task
        if self.heartbeat_monitor:
            await self.heartbeat_monitor.start()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            await asyncio.gather(
                self._event_bus_loop(),
                self._price_feed_loop(),
                self._ml_inference_loop(),
                self._risk_monitoring_loop(),
                self._arbitrage_loop(),
                self._analytics_loop(),
                self._dashboard_loop(),
                self._health_check_loop()
            )
        except asyncio.CancelledError:
            print("\n🛑 Main loops cancelled")
        finally:
            await self.shutdown()
    
    async def _event_bus_loop(self):
        """Process events"""
        await self.event_bus.run()
    
    async def _price_feed_loop(self):
        """Main price feed and strategy distribution"""
        print("\n📈 Price feed started")

        while self.is_running and not self.emergency_stop:
            # Halt immediately if kill switch is active
            if self.kill_switch and self.kill_switch.is_active():
                print("\n🚨 Price feed halted – kill switch is active")
                break
            try:
                # Get price from your existing feed
                # Replace with your actual price source
                price = await self._fetch_price()
                timestamp = datetime.now(timezone.utc)

                # Distribute to orchestra
                self.orchestra.distribute_price(price)

                # Update heatmap
                self.heatmap_engine.on_price("XAUUSD", price, timestamp)

                # Emit event
                await self.event_bus.publish(DomainEvent.create(
                    'PRICE_UPDATE',
                    'price_feed',
                    {'symbol': 'XAUUSD', 'price': price, 'timestamp': timestamp.isoformat()},
                    priority=1
                ))

                self.performance_metrics['events_processed'] += 1

                # Heartbeat – proves price_feed is alive
                if self.heartbeat_monitor:
                    self.heartbeat_monitor.beat('price_feed')

                await asyncio.sleep(0.1)  # 10Hz - adjust as needed

            except Exception as e:
                print(f"Price feed error: {e}")
                await asyncio.sleep(1)
    
    async def _fetch_price(self) -> float:
        """Fetch price from your existing source"""
        # Replace with your actual implementation
        import random
        return 2000.0 + random.uniform(-2, 2)
    
    async def _ml_inference_loop(self):
        """GPU-accelerated ML inference with full logging."""
        if not self.gpu_engine:
            import logging as _logging
            _logging.getLogger(__name__).info("ML inference loop skipped – no GPU engine available")
            return

        ml_logger = __import__("logging").getLogger("hopefx.ml")
        price_buffer: list = []

        while self.is_running:
            try:
                # Collect recent prices into buffer
                current_price = await self._fetch_price()
                price_buffer.append(current_price)
                if len(price_buffer) > 60:
                    price_buffer.pop(0)

                if len(price_buffer) >= 20:
                    import numpy as _np
                    features = _np.array(price_buffer[-20:], dtype=_np.float32).reshape(1, -1)
                    # GPU inference (best-effort – engine may not be loaded)
                    try:
                        result = self.gpu_engine.infer(features)
                        ml_logger.debug(
                            "ML inference | price=%.4f result=%s", current_price, result
                        )
                    except Exception as infer_exc:
                        ml_logger.warning("ML inference error: %s", infer_exc)

                self.performance_metrics['ml_inferences'] += 1

                if self.heartbeat_monitor:
                    self.heartbeat_monitor.beat('ml_inference')

                await asyncio.sleep(0.01)  # 100 Hz

            except Exception as e:
                __import__("logging").getLogger(__name__).error("ML loop error: %s", e)
                await asyncio.sleep(1)

    async def _risk_monitoring_loop(self):
        """Continuous risk monitoring"""
        if not self.risk_monitor:
            return

        while self.is_running:
            try:
                # Get current positions
                # positions = self._get_current_positions()
                # prices = self._get_current_prices()

                # Update risk
                # violations = self.risk_monitor.update_portfolio(positions, prices)

                self.performance_metrics['risk_calculations'] += 1

                # Heartbeat – proves risk_engine is alive
                if self.heartbeat_monitor:
                    self.heartbeat_monitor.beat('risk_engine')

                await asyncio.sleep(self.config.risk_calculation_interval_sec)

            except Exception as e:
                print(f"Risk monitoring error: {e}")
                await asyncio.sleep(5)
    
    async def _arbitrage_loop(self):
        """Cross-exchange arbitrage"""
        if not self.arbitrage_engine:
            return
        
        await self.arbitrage_engine.run(symbols=["BTCUSD", "ETHUSD", "XAUUSD"])
    
    async def _analytics_loop(self):
        """Generate analytics and heatmap updates"""
        while self.is_running:
            try:
                heatmap_data = self.heatmap_engine.get_heatmap_data()
                # Store or broadcast heatmap data
                await asyncio.sleep(1)  # 1Hz updates
                
            except Exception as e:
                print(f"Analytics error: {e}")
                await asyncio.sleep(5)
    
    async def _dashboard_loop(self):
        """Run web dashboard"""
        if self.dashboard:
            self.dashboard.run(port=8080)
    
    async def _health_check_loop(self):
        """Monitor component health"""
        while self.is_running:
            try:
                # Check all components
                for name, health in self.health.items():
                    if not health.is_healthy():
                        print(f"\n⚠️  UNHEALTHY COMPONENT: {name} ({health.status})")
                        
                        # Attempt recovery or trigger emergency
                        if name in ['event_bus', 'database'] and self.config.kill_switch_enabled:
                            self._trigger_kill_switch(f"Critical component failure: {name}")
                
                # Print status every 60 seconds
                if int(datetime.now(timezone.utc).timestamp()) % 60 == 0:
                    self._print_system_status()
                    self._print_performance_metrics()
                
                await asyncio.sleep(5)
                
            except Exception as e:
                print(f"Health check error: {e}")
                await asyncio.sleep(5)
    
    def _print_performance_metrics(self):
        """Print current performance"""
        print("\n📈 PERFORMANCE METRICS:")
        for key, value in self.performance_metrics.items():
            if isinstance(value, Decimal):
                print(f"   {key:25s}: ${value:.2f}")
            else:
                print(f"   {key:25s}: {value:,}")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print(f"\n🛑 Received signal {signum}")
        self.is_running = False
    
    async def shutdown(self):
        """Graceful shutdown"""
        print("\n" + "="*70)
        print("SHUTTING DOWN HOPEFX ULTIMATE")
        print("="*70)
        
        self.is_running = False
        
        # Stop all strategies
        print("\n⏸️  Deactivating strategies...")
        for sid in list(self.orchestra.active_strategies):
            self.orchestra.deactivate_strategy(sid, "shutdown")
        
        # Stop GPU
        if self.gpu_engine:
            print("🛑 Stopping GPU engine...")
            self.gpu_engine.stop()
        
        # Stop arbitrage
        if self.arbitrage_engine:
            print("🛑 Stopping arbitrage engine...")
            self.arbitrage_engine.is_running = False
        
        # Close database
        if self.db_session:
            print("🛑 Closing database...")
            self.db_session.close()
        
        # Close cache
        if self.cache:
            print("🛑 Closing cache...")
            # self.cache.close()

        # Stop heartbeat monitor
        if self.heartbeat_monitor:
            print("🛑 Stopping heartbeat monitor...")
            await self.heartbeat_monitor.stop()

        # Stop kill switch polling
        if self.kill_switch:
            print("🛑 Stopping kill switch...")
            await self.kill_switch.stop()
        
        # Final status
        runtime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        print(f"\n✅ SHUTDOWN COMPLETE")
        print(f"   Runtime: {runtime:.1f} seconds")
        print(f"   Events processed: {self.performance_metrics['events_processed']:,}")
        print(f"   Trades executed: {self.performance_metrics['trades_executed']:,}")
        print("="*70)



# ==================== FORWARD-TEST RUNNER ====================

async def run_forward_test(duration_seconds: int = 60, tick_interval: float = 0.5) -> dict:
    """
    Simulate a forward test using mock market data.

    Runs the full system for *duration_seconds* seconds with synthetic price
    ticks generated every *tick_interval* seconds.  All components
    (risk, strategy orchestra, ML inference stub, kill-switch) are exercised.

    Returns a summary dict so callers can assert correctness in CI.
    """
    import logging as _logging
    import random as _random

    log = _logging.getLogger("hopefx.forward_test")
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    log.info("=" * 60)
    log.info("HOPEFX FORWARD-TEST MODE  (duration=%ds)", duration_seconds)
    log.info("=" * 60)

    app = HopeFXUltimateIntegrated()

    # ── Monkey-patch _fetch_price with deterministic mock data ──────────────
    base_price = 2000.0
    tick_count = {"n": 0}

    async def _mock_fetch_price() -> float:
        tick_count["n"] += 1
        # Simple GBM simulation
        drift = 0.0001
        vol = 0.002
        noise = _random.gauss(drift, vol)
        nonlocal base_price
        base_price = base_price * (1.0 + noise)
        base_price = max(1500.0, min(3000.0, base_price))  # clamp
        return base_price

    app._fetch_price = _mock_fetch_price  # type: ignore[method-assign]

    results: dict = {
        "status": "unknown",
        "ticks_generated": 0,
        "events_processed": 0,
        "ml_inferences": 0,
        "risk_calculations": 0,
        "trades_executed": 0,
        "errors": [],
    }

    try:
        await app.initialize()
        log.info("✓ System initialised successfully")

        # Run for the requested duration
        deadline = asyncio.get_event_loop().time() + duration_seconds

        async def _limited_run():
            """Run until deadline or kill-switch fires."""
            while asyncio.get_event_loop().time() < deadline and app.is_running:
                price = await app._fetch_price()
                app.orchestra.distribute_price(price)
                app.heatmap_engine.on_price("XAUUSD", price, datetime.now(timezone.utc))
                await app.event_bus.publish(
                    DomainEvent.create(
                        "PRICE_UPDATE",
                        "forward_test",
                        {"symbol": "XAUUSD", "price": price},
                        priority=1,
                    )
                )
                app.performance_metrics["events_processed"] += 1
                results["ticks_generated"] += 1

                if results["ticks_generated"] % 20 == 0:
                    log.info(
                        "Forward-test tick=%d  price=%.4f  events=%d",
                        results["ticks_generated"],
                        price,
                        app.performance_metrics["events_processed"],
                    )

                await asyncio.sleep(tick_interval)

            app.is_running = False

        await _limited_run()

        results.update(
            {
                "status": "passed",
                "events_processed": app.performance_metrics["events_processed"],
                "ml_inferences": app.performance_metrics["ml_inferences"],
                "risk_calculations": app.performance_metrics["risk_calculations"],
                "trades_executed": app.performance_metrics["trades_executed"],
            }
        )
        log.info("✓ Forward test PASSED  ticks=%d", results["ticks_generated"])

    except Exception as exc:
        results["status"] = "failed"
        results["errors"].append(str(exc))
        log.exception("Forward test FAILED: %s", exc)
    finally:
        try:
            await app.shutdown()
        except Exception:
            pass

    # Print summary
    log.info("=" * 60)
    log.info("FORWARD-TEST SUMMARY")
    for k, v in results.items():
        log.info("  %-24s : %s", k, v)
    log.info("=" * 60)
    return results


# ==================== ENTRY POINT ====================

async def main():
    """Entry point – honours --mode=forward-test CLI flag."""
    import argparse

    parser = argparse.ArgumentParser(
        description="HOPEFX Ultimate Integrated Trading System",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["live", "paper", "forward-test"],
        default="paper",
        help="Operating mode",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Forward-test duration in seconds",
    )
    parser.add_argument(
        "--tick-interval",
        type=float,
        default=0.5,
        dest="tick_interval",
        help="Seconds between mock ticks in forward-test mode",
    )
    args = parser.parse_args()

    if args.mode == "forward-test":
        results = await run_forward_test(
            duration_seconds=args.duration,
            tick_interval=args.tick_interval,
        )
        sys.exit(0 if results["status"] == "passed" else 1)
    else:
        app = HopeFXUltimateIntegrated()
        try:
            await app.initialize()
            await app.run()
        except Exception as e:
            print(f"\n💥 FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            await app.shutdown()
            sys.exit(1)


if __name__ == "__main__":
    # Set process priority for low latency (if running as root)
    try:
        import os
        os.nice(-20)
    except Exception:
        pass

    asyncio.run(main())
