"""Support and Resistance Level Detection

Identifies price levels where the market has historically found
significant buying or selling pressure:

- Swing-high / swing-low based S/R
- Volume-weighted S/R (when volume data is available)
- Round-number / psychological levels
- Fibonacci retracement levels
- Dynamic levels (moving-average based)
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PriceLevel:
    """A support, resistance, or pivot price level."""

    price: float
    level_type: str              # 'support', 'resistance', 'pivot'
    strength: float              # 0.0 – 1.0 (higher = stronger)
    touch_count: int             # Number of times price tested this level
    last_touch: Optional[datetime]  # Datetime of last touch, or None
    method: str                  # 'swing', 'fibonacci', 'round_number', etc.
    is_active: bool
    description: str = ""

    def to_dict(self) -> Dict:
        last_touch_str = (
            self.last_touch.isoformat() if self.last_touch is not None else None
        )
        return {
            "price": self.price,
            "level_type": self.level_type,
            "strength": self.strength,
            "touch_count": self.touch_count,
            "last_touch": last_touch_str,
            "method": self.method,
            "is_active": self.is_active,
            "description": self.description,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@dataclass
class SRLevel:
    """A single support or resistance level (legacy)."""

    price: float
    level_type: str          # 'support' or 'resistance'
    strength: float          # 0.0 – 1.0  (higher = stronger)
    touches: int             # Number of times price tested this level
    origin: str              # 'swing', 'volume', 'psychological'
    start_index: int = 0
    end_index: int = 0

    def to_dict(self) -> Dict:
        return {
            "price": self.price,
            "level_type": self.level_type,
            "strength": self.strength,
            "touches": self.touches,
            "origin": self.origin,
            "start_index": self.start_index,
            "end_index": self.end_index,
        }


@dataclass
class SRZone:
    """A merged zone of closely spaced S/R levels."""

    low_price: float
    high_price: float
    mid_price: float
    zone_type: str           # 'support', 'resistance', 'mixed'
    strength: float          # 0.0 – 1.0
    touch_count: int
    levels: List[SRLevel] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "low_price": self.low_price,
            "high_price": self.high_price,
            "mid_price": self.mid_price,
            "zone_type": self.zone_type,
            "strength": self.strength,
            "touch_count": self.touch_count,
        }


# ---------------------------------------------------------------------------
# Swing-based helpers
# ---------------------------------------------------------------------------

def _find_swing_highs(
    highs: List[float],
    window: int = 5,
) -> List[Tuple[int, float]]:
    """Return (index, price) pairs for swing highs."""
    results = []
    for i in range(window, len(highs) - window):
        high_window = highs[i - window: i + window + 1]
        if highs[i] == max(high_window):
            results.append((i, highs[i]))
    return results


def _find_swing_lows(
    lows: List[float],
    window: int = 5,
) -> List[Tuple[int, float]]:
    """Return (index, price) pairs for swing lows."""
    results = []
    for i in range(window, len(lows) - window):
        low_window = lows[i - window: i + window + 1]
        if lows[i] == min(low_window):
            results.append((i, lows[i]))
    return results


def _count_touches(
    price: float,
    highs: List[float],
    lows: List[float],
    tolerance: float,
) -> int:
    """Count how many bars came within *tolerance* of *price*."""
    count = 0
    for h, lo in zip(highs, lows):
        if lo - tolerance <= price <= h + tolerance:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Swing S/R detection
# ---------------------------------------------------------------------------

def _build_swing_levels(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    window: int,
    tolerance: float,
) -> List[SRLevel]:
    """Build S/R levels from swing highs and lows."""
    swing_highs = _find_swing_highs(highs, window)
    swing_lows = _find_swing_lows(lows, window)
    levels: List[SRLevel] = []

    current_price = closes[-1] if closes else 0.0

    for idx, price in swing_highs:
        touches = _count_touches(price, highs, lows, tolerance)
        lvl_type = "resistance" if price > current_price else "support"
        strength = min(1.0, touches / 10.0)
        levels.append(SRLevel(
            price=round(price, 5),
            level_type=lvl_type,
            strength=strength,
            touches=touches,
            origin="swing",
            start_index=idx,
            end_index=idx,
        ))

    for idx, price in swing_lows:
        touches = _count_touches(price, highs, lows, tolerance)
        lvl_type = "support" if price < current_price else "resistance"
        strength = min(1.0, touches / 10.0)
        levels.append(SRLevel(
            price=round(price, 5),
            level_type=lvl_type,
            strength=strength,
            touches=touches,
            origin="swing",
            start_index=idx,
            end_index=idx,
        ))

    return levels


# ---------------------------------------------------------------------------
# Psychological / round-number levels
# ---------------------------------------------------------------------------

def _round_level_step(current_price: float) -> float:
    """Choose an appropriate round-number step for the price magnitude."""
    magnitude = math.floor(math.log10(max(current_price, 1)))
    return 10 ** (magnitude - 1)


def _build_psychological_levels(
    closes: List[float],
    tolerance: float,
    count: int = 10,
) -> List[SRLevel]:
    """Generate round-number S/R levels near the current price."""
    if not closes:
        return []

    current_price = closes[-1]
    step = _round_level_step(current_price)
    levels: List[SRLevel] = []

    # Centre the grid on current price
    base = round(current_price / step) * step
    half = count // 2

    for k in range(-half, half + 1):
        price = round(base + k * step, 5)
        if price <= 0:
            continue

        # Rough proximity check
        dist_ratio = abs(price - current_price) / current_price
        if dist_ratio > 0.10:
            continue

        touches = _count_touches(price, closes, closes, tolerance)
        lvl_type = "support" if price <= current_price else "resistance"
        strength = min(1.0, 0.3 + touches * 0.07)

        levels.append(SRLevel(
            price=price,
            level_type=lvl_type,
            strength=strength,
            touches=touches,
            origin="psychological",
        ))

    return levels


# ---------------------------------------------------------------------------
# Zone merging
# ---------------------------------------------------------------------------

def _merge_levels_into_zones(
    levels: List[SRLevel],
    merge_pct: float = 0.005,
) -> List[SRZone]:
    """Merge closely spaced levels into S/R zones."""
    if not levels:
        return []

    sorted_levels = sorted(levels, key=lambda x: x.price)
    zones: List[SRZone] = []
    current_group: List[SRLevel] = [sorted_levels[0]]

    for level in sorted_levels[1:]:
        ref_price = current_group[0].price
        pct_diff = abs(level.price - ref_price) / ref_price if ref_price else 1.0

        if pct_diff <= merge_pct:
            current_group.append(level)
        else:
            zones.append(_group_to_zone(current_group))
            current_group = [level]

    if current_group:
        zones.append(_group_to_zone(current_group))

    return zones


def _group_to_zone(group: List[SRLevel]) -> SRZone:
    """Convert a group of nearby SRLevel objects into a SRZone."""
    prices = [lv.price for lv in group]
    low_p = min(prices)
    high_p = max(prices)
    mid_p = (low_p + high_p) / 2

    types = {lv.level_type for lv in group}
    if len(types) == 1:
        zone_type = types.pop()
    else:
        zone_type = "mixed"

    avg_strength = sum(lv.strength for lv in group) / len(group)
    total_touches = sum(lv.touches for lv in group)

    return SRZone(
        low_price=round(low_p, 5),
        high_price=round(high_p, 5),
        mid_price=round(mid_p, 5),
        zone_type=zone_type,
        strength=round(min(1.0, avg_strength), 4),
        touch_count=total_touches,
        levels=group,
    )


# ---------------------------------------------------------------------------
# Volume-weighted S/R (optional, requires volume data)
# ---------------------------------------------------------------------------

def _build_volume_levels(
    closes: List[float],
    volumes: List[float],
    bins: int = 20,
) -> List[SRLevel]:
    """Identify price levels with disproportionately high traded volume."""
    if not closes or not volumes or len(closes) != len(volumes):
        return []

    min_p = min(closes)
    max_p = max(closes)
    if min_p == max_p:
        return []

    bucket = (max_p - min_p) / bins
    vol_by_bin: Dict[int, float] = {}

    for price, vol in zip(closes, volumes):
        idx = min(int((price - min_p) / bucket), bins - 1)
        vol_by_bin[idx] = vol_by_bin.get(idx, 0.0) + vol

    total_vol = sum(vol_by_bin.values())
    if total_vol == 0:
        return []

    avg_vol = total_vol / bins
    current_price = closes[-1]
    levels: List[SRLevel] = []

    for idx, vol in vol_by_bin.items():
        if vol < avg_vol * 1.5:
            continue

        price = round(min_p + (idx + 0.5) * bucket, 5)
        strength = min(1.0, vol / total_vol * bins)
        lvl_type = "support" if price <= current_price else "resistance"

        levels.append(SRLevel(
            price=price,
            level_type=lvl_type,
            strength=strength,
            touches=0,
            origin="volume",
        ))

    return levels


# ---------------------------------------------------------------------------
# Main detector class
# ---------------------------------------------------------------------------

class SupportResistanceDetector:
    """
    Detect support and resistance levels from OHLCV data.

    Usage::

        detector = SupportResistanceDetector()
        result = detector.detect_levels(df)
        for lvl in result["support"]:
            print(lvl.price, lvl.strength)
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialise the detector.

        Args:
            config: Optional dict with keys sensitivity, swing_window, min_bars,
                    round_number_increment.
        """
        cfg = config or {}
        self.sensitivity: float = float(cfg.get("sensitivity", 0.003))
        self.swing_window: int = int(cfg.get("swing_window", 5))
        self.min_bars: int = int(cfg.get("min_bars", 30))
        round_number_increment = float(cfg.get("round_number_increment", 50.0))
        if round_number_increment <= 0:
            raise ValueError(
                "round_number_increment must be greater than 0 to compute "
                "round-number support/resistance levels."
            )
        self.round_number_increment: float = round_number_increment
        # Legacy attributes kept for backward compatibility
        self._window = self.swing_window
        self._tolerance_pct = self.sensitivity
        self._merge_pct = float(cfg.get("merge_pct", 0.005))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_ohlcv_cols(self, df) -> Optional[Dict[str, str]]:
        """Return lower-cased column name map or None if df is invalid."""
        try:
            import pandas as pd
            if not isinstance(df, pd.DataFrame) or df.empty:
                return None
        except ImportError:
            # pandas unavailable: fall back to duck-typing
            if df is None or not hasattr(df, "columns"):
                return None
            is_empty = getattr(df, "empty", None)
            if isinstance(is_empty, bool) and is_empty:
                return None
        try:
            cols = {str(c).lower(): c for c in df.columns}
        except Exception:
            return None
        return cols

    def _tolerance_for(self, price: float) -> float:
        return price * self._tolerance_pct

    # ------------------------------------------------------------------
    # New public API
    # ------------------------------------------------------------------

    def detect_levels(
        self,
        df,
        current_price: Optional[float] = None,
    ) -> Dict[str, List[PriceLevel]]:
        """
        Detect support, resistance, and pivot levels.

        Args:
            df: OHLCV DataFrame.
            current_price: Optional reference price for classification.
                           Defaults to last close.

        Returns:
            Dict with keys 'support', 'resistance', 'pivot', each a list
            of PriceLevel objects.
        """
        result: Dict[str, List[PriceLevel]] = {
            "support": [],
            "resistance": [],
            "pivot": [],
        }

        cols = self._get_ohlcv_cols(df)
        if cols is None:
            return result

        if not all(c in cols for c in ("high", "low", "close")):
            return result

        closes = df[cols["close"]].tolist()
        if len(closes) < self.min_bars:
            return result
        if current_price is None:
            current_price = float(closes[-1]) if closes else 0.0

        all_levels: List[PriceLevel] = []
        all_levels.extend(self.get_swing_levels(df))
        all_levels.extend(self.get_fibonacci_levels(df))
        all_levels.extend(self.get_round_number_levels(df))

        if "volume" in cols:
            all_levels.extend(self.get_volume_levels(df))

        all_levels.extend(self.get_dynamic_levels(df))

        for level in all_levels:
            classification = self.classify_level(level, current_price)
            level.level_type = classification
            result[classification].append(level)

        return result

    def get_swing_levels(self, df) -> List[PriceLevel]:
        """
        Get support/resistance levels from swing highs and lows.

        Args:
            df: OHLCV DataFrame.

        Returns:
            List of PriceLevel objects.
        """
        cols = self._get_ohlcv_cols(df)
        if cols is None:
            return []
        if not all(c in cols for c in ("high", "low", "close")):
            return []

        highs = df[cols["high"]].tolist()
        lows = df[cols["low"]].tolist()
        closes = df[cols["close"]].tolist()

        current_price = closes[-1] if closes else 0.0
        tolerance = current_price * self.sensitivity

        levels: List[PriceLevel] = []
        swing_highs = _find_swing_highs(highs, self.swing_window)
        swing_lows = _find_swing_lows(lows, self.swing_window)

        for _, price in swing_highs:
            touches = _count_touches(price, highs, lows, tolerance)
            lvl_type = "resistance" if price > current_price else "support"
            strength = min(1.0, touches / 10.0)
            levels.append(PriceLevel(
                price=round(price, 5),
                level_type=lvl_type,
                strength=strength,
                touch_count=touches,
                last_touch=None,
                method="swing",
                is_active=True,
            ))

        for _, price in swing_lows:
            touches = _count_touches(price, highs, lows, tolerance)
            lvl_type = "support" if price < current_price else "resistance"
            strength = min(1.0, touches / 10.0)
            levels.append(PriceLevel(
                price=round(price, 5),
                level_type=lvl_type,
                strength=strength,
                touch_count=touches,
                last_touch=None,
                method="swing",
                is_active=True,
            ))

        return levels

    def get_fibonacci_levels(self, df) -> List[PriceLevel]:
        """
        Get Fibonacci retracement levels.

        Args:
            df: OHLCV DataFrame.

        Returns:
            List of up to 7 PriceLevel objects with method='fibonacci'.
        """
        cols = self._get_ohlcv_cols(df)
        if cols is None:
            return []
        if not all(c in cols for c in ("high", "low")):
            return []

        price_max = float(df[cols["high"]].max())
        price_min = float(df[cols["low"]].min())
        price_range = price_max - price_min

        if price_range <= 0:
            return []

        fib_ratios = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
        levels: List[PriceLevel] = []

        for ratio in fib_ratios:
            price = price_max - ratio * price_range
            strength = round(min(1.0, 0.5 + ratio * 0.2), 4)
            levels.append(PriceLevel(
                price=price,
                level_type="pivot",
                strength=strength,
                touch_count=0,
                last_touch=None,
                method="fibonacci",
                is_active=True,
                description=f"Fibonacci {ratio * 100:.1f}% level",
            ))

        return levels

    def get_round_number_levels(self, df) -> List[PriceLevel]:
        """
        Get round-number / psychological levels.

        Args:
            df: OHLCV DataFrame.

        Returns:
            List of PriceLevel objects with method='round_number'.
        """
        cols = self._get_ohlcv_cols(df)
        if cols is None:
            return []
        if "close" not in cols:
            return []

        closes = df[cols["close"]].tolist()
        if not closes:
            return []

        current_price = closes[-1]
        increment = self.round_number_increment
        base = math.floor(current_price / increment) * increment

        levels: List[PriceLevel] = []
        for offset in range(-3, 4):
            price = base + offset * increment
            if price <= 0:
                continue
            lvl_type = "support" if price <= current_price else "resistance"
            levels.append(PriceLevel(
                price=price,
                level_type=lvl_type,
                strength=0.6,
                touch_count=0,
                last_touch=None,
                method="round_number",
                is_active=True,
                description=f"Round number level {price}",
            ))

        return levels

    def get_volume_levels(self, df) -> List[PriceLevel]:
        """
        Get volume-weighted price levels.

        Args:
            df: OHLCV DataFrame.

        Returns:
            List of PriceLevel objects with method='volume'.
        """
        cols = self._get_ohlcv_cols(df)
        if cols is None:
            return []
        if not all(c in cols for c in ("close", "volume")):
            return []

        closes = df[cols["close"]].tolist()
        volumes = df[cols["volume"]].tolist()

        sr_levels = _build_volume_levels(closes, volumes)
        levels: List[PriceLevel] = []
        for sr in sr_levels:
            levels.append(PriceLevel(
                price=sr.price,
                level_type=sr.level_type,
                strength=sr.strength,
                touch_count=0,
                last_touch=None,
                method="volume",
                is_active=True,
            ))
        return levels

    def get_dynamic_levels(self, df) -> List[PriceLevel]:
        """
        Get dynamic levels based on moving averages.

        Args:
            df: OHLCV DataFrame.

        Returns:
            List of PriceLevel objects with method='dynamic'.
        """
        cols = self._get_ohlcv_cols(df)
        if cols is None:
            return []
        if "close" not in cols:
            return []

        closes = df[cols["close"]].tolist()
        if len(closes) < 20:
            return []

        ma20 = sum(closes[-20:]) / 20.0
        current_price = closes[-1]
        lvl_type = "support" if ma20 < current_price else "resistance"

        return [PriceLevel(
            price=round(ma20, 5),
            level_type=lvl_type,
            strength=0.5,
            touch_count=0,
            last_touch=None,
            method="dynamic",
            is_active=True,
            description="20-period moving average",
        )]

    def classify_level(
        self, level: PriceLevel, current_price: float
    ) -> str:
        """
        Classify a price level as 'support', 'resistance', or 'pivot'.

        A level within *sensitivity* of current_price is classified as 'pivot'.

        Args:
            level: The PriceLevel to classify.
            current_price: The current market price.

        Returns:
            'support', 'resistance', or 'pivot'.
        """
        band = current_price * self.sensitivity
        diff = abs(level.price - current_price)
        if diff <= band:
            return "pivot"
        if level.price < current_price:
            return "support"
        return "resistance"

    # ------------------------------------------------------------------
    # Legacy methods kept for backward compatibility
    # ------------------------------------------------------------------

    def detect(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: Optional[List[float]] = None,
    ) -> List[SRLevel]:
        """
        Detect all support and resistance levels (legacy API).

        Args:
            highs: Bar high prices.
            lows: Bar low prices.
            closes: Bar close prices.
            volumes: Optional bar volumes for volume-weighted levels.

        Returns:
            Sorted list of SRLevel objects.
        """
        if not closes:
            return []

        tolerance = self._tolerance_for(closes[-1])

        swing_levels = _build_swing_levels(
            highs, lows, closes, self._window, tolerance
        )
        psych_levels = _build_psychological_levels(closes, tolerance)

        all_levels = swing_levels + psych_levels

        if volumes:
            vol_levels = _build_volume_levels(closes, volumes)
            all_levels += vol_levels

        return sorted(all_levels, key=lambda x: x.price)

    def detect_zones(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: Optional[List[float]] = None,
    ) -> List[SRZone]:
        """
        Detect S/R zones by merging nearby individual levels (legacy API).

        Args:
            highs: Bar high prices.
            lows: Bar low prices.
            closes: Bar close prices.
            volumes: Optional bar volumes.

        Returns:
            List of SRZone objects sorted by mid price.
        """
        levels = self.detect(highs, lows, closes, volumes)
        zones = _merge_levels_into_zones(levels, self._merge_pct)
        return sorted(zones, key=lambda z: z.mid_price)

    def get_nearest_levels(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        current_price: float,
        n: int = 3,
    ) -> Dict:
        """
        Return the *n* closest support and resistance levels to *current_price*
        (legacy API).

        Args:
            highs: Bar high prices.
            lows: Bar low prices.
            closes: Bar close prices.
            current_price: The current market price.
            n: Number of levels to return on each side.

        Returns:
            Dict with 'support' and 'resistance' lists.
        """
        levels = self.detect(highs, lows, closes)

        supports = sorted(
            [lv for lv in levels if lv.price <= current_price],
            key=lambda x: current_price - x.price,
        )[:n]

        resistances = sorted(
            [lv for lv in levels if lv.price > current_price],
            key=lambda x: x.price - current_price,
        )[:n]

        return {
            "support": [lv.to_dict() for lv in supports],
            "resistance": [lv.to_dict() for lv in resistances],
        }

    def is_near_level(
        self,
        price: float,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        tolerance_pct: Optional[float] = None,
    ) -> bool:
        """
        Check whether *price* is close to any detected S/R level (legacy API).

        Args:
            price: Price to test.
            highs: Bar high prices.
            lows: Bar low prices.
            closes: Bar close prices.
            tolerance_pct: Override the instance tolerance if provided.

        Returns:
            True if *price* is within tolerance of any S/R level.
        """
        tol_pct = tolerance_pct if tolerance_pct is not None else self._tolerance_pct
        tolerance = price * tol_pct
        levels = self.detect(highs, lows, closes)

        return any(
            abs(lv.price - price) <= tolerance
            for lv in levels
        )
