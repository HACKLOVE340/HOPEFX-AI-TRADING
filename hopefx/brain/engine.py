"""hopefx.brain.engine — singleton brain instance"""
from brain.brain import HOPEFXBrain, SystemState
brain = HOPEFXBrain()
__all__ = ["brain", "HOPEFXBrain", "SystemState"]
