# main_mcc_wrapper.py
"""
Wrapper that integrates MCC with your existing HOPEFX main.py
WITHOUT breaking anything.
"""

from core.mcc.master_control import MasterControlCore, MCCConfig
from config.config_manager import ConfigManager
from cache.market_data_cache import MarketDataCache

# Import your existing strategies
from strategies.your_existing_strategy import YourExistingStrategy


def main_with_mcc():
    """Your existing main.py enhanced with MCC"""
    
    # 1. Initialize your existing components (UNCHANGED)
    config = ConfigManager()
    cache = MarketDataCache()
    
    # 2. Initialize MCC with your components
    mcc = MasterControlCore(MCCConfig(
        max_strategies_active=3,
        emergency_drawdown_pct=0.10
    ))
    mcc.initialize(config, cache)
    
    # 3. Register your existing strategies (NO CHANGES NEEDED)
    strategy1 = YourExistingStrategy()
    mcc.register_strategy(strategy1, max_allocation=0.30)
    
    # 4. Add new strategies if you want
    # from strategies.new_strategy import NewStrategy
    # mcc.register_strategy(NewStrategy(), max_allocation=0.20)
    
    # 5. Activate strategies
    mcc.activate_strategy(strategy1.config.name)
    
    # 6. Your existing price feed loop - just add one line!
    print("\n🔄 Starting price feed (your existing code)...")
    
    try:
        while True:
            # YOUR EXISTING CODE:
            price = get_price_from_your_feed()  # Your existing function
            
            # ADD THIS ONE LINE to enable MCC:
            mcc.on_price_update("XAUUSD", price)
            
            # Your existing processing continues...
            
    except KeyboardInterrupt:
        mcc.stop()


if __name__ == "__main__":
    main_with_mcc()
