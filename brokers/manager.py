
# Create broker manager and examples
manager_code = '''"""
HOPEFX Broker Manager
Manage multiple broker connections
"""

from typing import Dict, Optional
from .base import BaseBroker


class BrokerManager:
    """Manage multiple broker connections"""
    
    def __init__(self):
        self.brokers: Dict[str, BaseBroker] = {}
        self.active_broker: Optional[str] = None
    
    def add_broker(self, name: str, broker: BaseBroker):
        """Add broker to manager"""
        self.brokers[name] = broker
        if self.active_broker is None:
            self.active_broker = name
    
    def connect_all(self) -> Dict[str, bool]:
        """Connect to all brokers"""
        results = {}
        for name, broker in self.brokers.items():
            results[name] = broker.connect()
        return results
    
    def disconnect_all(self):
        """Disconnect from all brokers"""
        for broker in self.brokers.values():
            broker.disconnect()
    
    def get_broker(self, name: Optional[str] = None) -> Optional[BaseBroker]:
        """Get broker by name or active broker"""
        if name is None:
            name = self.active_broker
        return self.brokers.get(name)
    
    def heartbeat_all(self) -> Dict[str, bool]:
        """Check health of all connections"""
        return {name: broker.heartbeat() for name, broker in self.brokers.items()}
'''

with open('brokers/manager.py', 'w') as f:
    f.write(manager_code)

print("✅ Created: brokers/manager.py")

# Create example files
examples = {
    'oanda_example.py': '''#!/usr/bin/env python3
"""
OANDA Connection Example
Demonstrates live tick capture and heartbeat logging
"""

import os
from dotenv import load_dotenv
from brokers import OANDABroker

load_dotenv()

API_KEY = os.getenv("OANDA_API_KEY")
ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")

def on_tick(tick):
    print(f"[{tick.source}] {tick.symbol} | Bid: {tick.bid:.5f} | Ask: {tick.ask:.5f}")

def main():
    broker = OANDABroker(api_key=API_KEY, account_id=ACCOUNT_ID, paper_trading=True)
    
    if not broker.connect():
        return
    
    broker.on_tick(on_tick)
    
    account = broker.get_account_info()
    print(f"\\nBalance: ${account.balance:,.2f}")
    print(f"Equity: ${account.equity:,.2f}")
    
    print("\\nStarting tick stream for XAUUSD...")
    broker.start_tick_stream(["XAU/USD"])
    
    import time
    time.sleep(60)
    
    broker.disconnect()
    print("\\nCheck brokers/logs/oanda_connection.log for details")

if __name__ == "__main__":
    main()
''',
    
    'mt5_example.py': '''#!/usr/bin/env python3
"""
MetaTrader 5 Connection Example
"""

from brokers import MetaTrader5Broker

def on_tick(tick):
    print(f"[{tick.source}] {tick.symbol} | Bid: {tick.bid:.5f} | Ask: {tick.ask:.5f}")

def main():
    broker = MetaTrader5Broker(login=12345678, password="your_password", server="YourBroker-Server")
    
    if not broker.connect():
        return
    
    broker.on_tick(on_tick)
    
    account = broker.get_account_info()
    print(f"\\nAccount: {account.account_id}")
    print(f"Balance: ${account.balance:,.2f}")
    print(f"Leverage: 1:{account.leverage}")
    
    positions = broker.get_positions()
    print(f"\\nPositions: {len(positions)}")
    
    broker.start_tick_stream(["XAUUSD"], interval=1.0)
    
    import time
    time.sleep(60)
    
    broker.disconnect()

if __name__ == "__main__":
    main()
''',
    
    'ib_example.py': '''#!/usr/bin/env python3
"""
Interactive Brokers Connection Example
"""

from brokers import InteractiveBrokersBroker

def main():
    broker = InteractiveBrokersBroker(host="127.0.0.1", port=7497, client_id=1)
    
    if not broker.connect():
        print("Make sure TWS is running with API enabled")
        return
    
    account = broker.get_account_info()
    print(f"\\nAccount ID: {account.account_id}")
    print(f"Paper Trading: {broker.paper_trading}")
    
    import time
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    
    broker.disconnect()

if __name__ == "__main__":
    main()
'''
}

for filename, content in examples.items():
    with open(f'brokers/examples/{filename}', 'w') as f:
        f.write(content)
    print(f"✅ Created: brokers/examples/{filename}")

print("\n📊 Phase 4 Complete: Broker Integration")
print("\nSupported Brokers:")
print("  ✅ OANDA - REST API + Streaming")
print("  ✅ MetaTrader 5 - Local terminal")
print("  ✅ Interactive Brokers - TWS/Gateway")
print("\nFeatures:")
print("  ✅ Live tick capture with callbacks")
print("  ✅ Heartbeat logging to brokers/logs/")
print("  ✅ Account info retrieval")
print("  ✅ Order placement")
print("  ✅ Connection state management")
print("  ✅ Example scripts in brokers/examples/")
