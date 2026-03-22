"""hopefx.execution.oms — OMS singleton shim"""
from src.execution.oms import OMS, OrderManagementSystem
from src.brokers.paper import PaperBroker

# Singleton with paper broker for tests/imports that just need the object
oms = OMS(broker=PaperBroker())
__all__ = ["oms", "OMS", "OrderManagementSystem"]
