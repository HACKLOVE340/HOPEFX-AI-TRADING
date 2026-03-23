"""
Historical data loader with caching and validation.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

import aiohttp
import pandas as pd

from src.core.config import settings
from src.core.exceptions import DataError
from src.core.logging_config import get_logger
from src.infrastructure.cache import get_cache

logger = get_logger(__name__)


class HistoricalDataLoader:
    """
    Production historical data loader with multi-source support.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        default_source: Literal["polygon", "oanda", "file"] = "polygon",
    ):
        self.cache_dir = cache_dir or settings.data_dir / "historical"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_source = default_source
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def load(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1min",
        source: Literal["polygon", "oanda", "file", "cache"] | None = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """
        Load historical data with caching.

        Args:
            symbol: Trading pair (e.g., "XAUUSD")
            start: Start datetime
            end: End datetime
            timeframe: Bar frequency
            source: Data source
            use_cache: Whether to use cache

        Returns:
            DataFrame with OHLCV columns
        """
        source = source or self.default_source

        # Check cache first
        if use_cache:
            cached = await self._load_from_cache(symbol, start, end, timeframe)
            if cached is not None:
                logger.info(f"Loaded {symbol} from cache")
                return cached

        # Load from source
        if source == "polygon":
            data = await self._load_from_polygon(symbol, start, end, timeframe)
        elif source == "oanda":
            data = await self._load_from_oanda(symbol, start, end, timeframe)
        elif source == "file":
            data = await self._load_from_file(symbol, start, end)
        else:
            raise DataError(f"Unknown source: {source}")

        # Save to cache
        if use_cache and data is not None:
            await self._save_to_cache(symbol, start, end, timeframe, data)

        return data

    async def _load_from_cache(
        self, symbol: str, start: datetime, end: datetime, timeframe: str
    ) -> pd.DataFrame | None:
        """Load from Redis cache."""
        try:
            cache = await get_cache()
            cache_key = f"hist:{symbol}:{timeframe}:{start.strftime('%Y%m%d')}:{end.strftime('%Y%m%d')}"

            data = await cache.get(cache_key)
            if data:
                return pd.read_json(data)
        except Exception as e:
            logger.warning(f"Cache load failed: {e}")

        return None

    async def _save_to_cache(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str,
        data: pd.DataFrame,
    ) -> None:
        """Save to Redis cache."""
        try:
            cache = await get_cache()
            cache_key = f"hist:{symbol}:{timeframe}:{start.strftime('%Y%m%d')}:{end.strftime('%Y%m%d')}"

            await cache.set(
                cache_key,
                data.to_json(),
                ttl=86400,  # 24 hours
            )
        except Exception as e:
            logger.warning(f"Cache save failed: {e}")

    async def _load_from_polygon(
        self, symbol: str, start: datetime, end: datetime, timeframe: str
    ) -> pd.DataFrame:
        """Load from Polygon.io."""
        from src.data.feeds.polygon import PolygonDataFeed

        feed = PolygonDataFeed(symbols=[symbol])
        bars = await feed.get_historical(symbol, start, end, timeframe)

        if not bars:
            raise DataError(f"No data returned from Polygon for {symbol}")

        # Convert to DataFrame
        data = {
            "open": [float(b.open) for b in bars],
            "high": [float(b.high) for b in bars],
            "low": [float(b.low) for b in bars],
            "close": [float(b.close) for b in bars],
            "volume": [b.volume for b in bars],
        }
        index = [b.timestamp for b in bars]

        return pd.DataFrame(data, index=index)

    async def _load_from_oanda(
        self, symbol: str, start: datetime, end: datetime, timeframe: str
    ) -> pd.DataFrame:
        """Load historical OHLCV data from the OANDA v20 REST API.

        The symbol should be in the OANDA instrument format, e.g. ``XAU_USD``
        (underscores) or the slash form ``XAUUSD``/``XAU/USD``, which is
        normalised automatically.

        Timeframe mapping follows OANDA granularity codes:
        ``1min`` → M1, ``5min`` → M5, ``15min`` → M15, ``30min`` → M30,
        ``1h`` / ``1hour`` → H1, ``4h`` → H4, ``1d`` / ``1day`` → D,
        ``1w`` → W, ``1M`` → M.
        """
        import os

        api_key = os.environ.get("OANDA_API_KEY", "")
        account_env = os.environ.get("OANDA_ENVIRONMENT", "practice")
        if not api_key:
            raise DataError(
                "OANDA_API_KEY environment variable is not set. "
                "Cannot load historical data from OANDA."
            )

        # Normalise symbol → OANDA instrument (e.g. XAUUSD → XAU_USD)
        instrument = symbol.upper().replace("/", "")
        if len(instrument) == 6 and "_" not in instrument:
            instrument = f"{instrument[:3]}_{instrument[3:]}"
        else:
            instrument = instrument.replace("/", "_")

        # Timeframe → OANDA granularity
        _TF_MAP: dict[str, str] = {
            "1min": "M1",
            "1m": "M1",
            "5min": "M5",
            "5m": "M5",
            "15min": "M15",
            "15m": "M15",
            "30min": "M30",
            "30m": "M30",
            "1h": "H1",
            "1hour": "H1",
            "4h": "H4",
            "4hour": "H4",
            "1d": "D",
            "1day": "D",
            "d": "D",
            "1w": "W",
            "1week": "W",
            "w": "W",
            "1M": "M",
            "1month": "M",
        }
        granularity = _TF_MAP.get(timeframe.lower(), "M1")

        base_url = (
            "https://api-fxtrade.oanda.com"
            if account_env == "live"
            else "https://api-fxpractice.oanda.com"
        )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        records: list[dict] = []
        # OANDA returns max 5000 candles per request; paginate with `from`/`to`
        page_start = start
        session = await self._get_session()

        while page_start < end:
            params = {
                "granularity": granularity,
                "from": page_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "count": 5000,
                "price": "M",  # mid prices
            }
            url = f"{base_url}/v3/instruments/{instrument}/candles"

            async with session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise DataError(
                        f"OANDA API error {resp.status} for {instrument}: {text[:200]}"
                    )
                data = await resp.json()

            candles = data.get("candles", [])
            if not candles:
                break

            for c in candles:
                if not c.get("complete", True):
                    continue
                mid = c.get("mid", {})
                records.append(
                    {
                        "timestamp": pd.Timestamp(c["time"]),
                        "open": float(mid.get("o", 0)),
                        "high": float(mid.get("h", 0)),
                        "low": float(mid.get("l", 0)),
                        "close": float(mid.get("c", 0)),
                        "volume": int(c.get("volume", 0)),
                    }
                )

            # Advance window past the last returned candle
            last_ts = pd.Timestamp(candles[-1]["time"])
            next_start = last_ts.to_pydatetime() + pd.Timedelta(seconds=1)
            if next_start <= page_start:
                break  # guard against infinite loop
            page_start = next_start

        if not records:
            raise DataError(
                f"No OANDA candles returned for {instrument} [{start} – {end}]"
            )

        df = pd.DataFrame(records).set_index("timestamp")
        df.index = pd.to_datetime(df.index, utc=True)
        df.sort_index(inplace=True)
        return df

    async def _load_from_file(
        self, symbol: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Load from local CSV/Parquet file."""
        file_path = self.cache_dir / f"{symbol}.parquet"

        if not file_path.exists():
            raise DataError(f"Local file not found: {file_path}")

        df = pd.read_parquet(file_path)

        # Filter by date
        mask = (df.index >= start) & (df.index <= end)
        return df.loc[mask]

    async def save_to_file(
        self,
        symbol: str,
        data: pd.DataFrame,
        format: Literal["parquet", "csv"] = "parquet",
    ) -> None:
        """Save data to local file."""
        if format == "parquet":
            file_path = self.cache_dir / f"{symbol}.parquet"
            data.to_parquet(file_path)
        else:
            file_path = self.cache_dir / f"{symbol}.csv"
            data.to_csv(file_path)

        logger.info(f"Saved {symbol} to {file_path}")

    async def close(self) -> None:
        """Close resources."""
        if self._session and not self._session.closed:
            await self._session.close()
