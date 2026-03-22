"""Data layer - market data and feature engineering."""

def __getattr__(name):
    if name == "TickValidator":
        from src.data.validators import TickValidator
        return TickValidator
    if name == "FeatureEngineer":
        from src.data.features import FeatureEngineer
        return FeatureEngineer
    raise AttributeError(f"module 'src.data' has no attribute {name!r}")

__all__ = ["TickValidator", "FeatureEngineer"]
