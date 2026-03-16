#!/usr/bin/env python3
"""
HOPEFX Ultimate Edition v2.0
Master Control Core with Strategy Orchestra
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Existing HOPEFX components
from config.config_manager import initialize_config
from cache.market_data_cache import MarketDataCache
from database.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# New Master Control Core
from core.event_bus import MemoryMappedEventStore, EventBus
from core.strategy_orchestra import StrategyOrchestra

# Import your strategies here
# from strategies.your_strategy import YourStrategy


class HopeFXUltimate:
    """Ultimate HOPEFX with Master Control Core"""
    
    def __init__(self):
        print("╔══════════════════════════════════════════════════════════════╗")
        print("║     HOPEFX AI TRADING - ULTIMATE EDITION v2.0               ║")
        print("║     Master Control Core + Strategy Orchestra                 ║")
        print("╚══════════════════════════════════════════════════════════════╝")
        
        self.config = None
        self.db_engine = None
        self.db_session = None
        self.cache = None
        self.event_store = None
        self.event_bus = None
        self.orchestra = None
        self.running = False
    
    def initialize(self):
        """Initialize all components"""
        print("\n📡 Phase 1: Core Infrastructure")
        self.config = initialize_config()
        
        # Database
        db_path = Path(self.config.database.database).parent
        db_path.mkdir(parents=True, exist_ok=True)
        self.db_engine = create_engine(self.config.database.get_connection_string())
        Base.metadata.create_all(self.db_engine)
        Session = sessionmaker(bind=self.db_engine)
        self.db_session = Session()
        print("   ✓ Database connected")
        
        # Cache
        self.cache = MarketDataCache()
        print("   ✓ Cache initialized")
        
        print("\n🧠 Phase 2: Master Control Core")
        self.event_store = MemoryMappedEventStore()
        self.event_bus = EventBus(self.event_store)
        self.orchestra = StrategyOrchestra(self.event_bus)
        print("   ✓ Event bus: 1M+ events/sec")
        print("   ✓ Strategy orchestra: Active")
        
        print("\n🎯 Phase 3: Strategy Registration")
        self._register_strategies()
        
        print("\n✅ All systems initialized")
    
    def _register_strategies(self):
        """Register your strategies here"""
        # Example:
        # strategy = YourStrategy()
        # self.orchestra.register_strategy(strategy, max_allocation=0.30)
        # self.orchestra.activate_strategy(strategy.config.name)
        
        print("   ⚠ No strategies registered (add your strategies here)")
        print("   Running in monitoring mode")
    
    async def price_feed(self):
        """Simulated price feed - replace with your actual feed"""
        import random
        base_price = 2000.0
        
        while self.running:
            price = base_price + random.uniform(-5, 5)
            self.orchestra.distribute_price(price)
            await asyncio.sleep(0.1)  # 10Hz
    
    async def event_loop(self):
        """Run event bus"""
        await self.event_bus.run()
    
    async def monitor(self):
        """Status monitoring"""
        while self.running:
            await asyncio.sleep(5)
            metrics = self.event_bus.get_metrics()
            heatmap = self.orchestra.get_heatmap_data()
            print(f"\n📊 Status: {metrics['published']} events | "
                  f"{heatmap['active_count']} active strategies | "
                  f"Regime: {heatmap['current_regime']}")
    
    async def run(self):
        """Main loop"""
        print("\n🚀 Starting Ultimate HOPEFX...")
        self.running = True
        
        await asyncio.gather(
            self.price_feed(),
            self.event_loop(),
            self.monitor()
        )
    
    def shutdown(self):
        """Graceful shutdown"""
        print("\n🛑 Shutting down...")
        self.running = False
        for sid in list(self.orchestra.active_strategies):
            self.orchestra.deactivate_strategy(sid, "shutdown")
        if self.db_session:
            self.db_session.close()
        print("✅ Shutdown complete")


async def main():
    app = HopeFXUltimate()
    app.initialize()
    try:
        await app.run()
    except KeyboardInterrupt:
        app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
