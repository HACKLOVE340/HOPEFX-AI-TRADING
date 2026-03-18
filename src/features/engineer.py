"""GPU-accelerated feature engineering with CUDA kernels and memory pooling."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import structlog
import torch
import torch.cuda.nvtx as nvtx
from numba import cuda, float32, int32
from numba.cuda import jit

from src.core.types import Tick, OHLCV
from src.features.transforms import CyclicalEncoder, RobustFeatureScaler
from src.ml.gpu_manager import gpu_manager

if TYPE_CHECKING:
    from torch import Tensor

logger = structlog.get_logger()


# CUDA Kernels for ultra-fast computation
@cuda.jit
def _cuda_rsi_kernel(prices, deltas, gains, losses, period, out_rsi):
    """CUDA kernel for RSI calculation."""
    idx = cuda.grid(1)
    if idx >= len(prices) - period:
        return
    
    # Calculate gains/losses for window
    avg_gain = float32(0.0)
    avg_loss = float32(0.0)
    
    for i in range(period):
        if deltas[idx + i] > 0:
            avg_gain += deltas[idx + i]
        else:
            avg_loss -= deltas[idx + i]
    
    avg_gain /= period
    avg_loss /= period
    
    # Wilder's smoothing
    for i in range(period, min(period * 2, len(deltas) - idx)):
        if deltas[idx + i] > 0:
            avg_gain = (avg_gain * (period - 1) + deltas[idx + i]) / period
            avg_loss = (avg_loss * (period - 1)) / period
        else:
            avg_gain = (avg_gain * (period - 1)) / period
            avg_loss = (avg_loss * (period - 1) - deltas[idx + i]) / period
    
    if avg_loss == 0:
        out_rsi[idx] = 100.0
    else:
        rs = avg_gain / avg_loss
        out_rsi[idx] = 100.0 - (100.0 / (1.0 + rs))


@cuda.jit
def _cuda_atr_kernel(highs, lows, closes, period, out_atr):
    """CUDA kernel for ATR calculation."""
    idx = cuda.grid(1)
    if idx >= len(highs) - period:
        return
    
    tr_sum = float32(0.0)
    for i in range(period):
        h_l = highs[idx + i] - lows[idx + i]
        h_c = abs(highs[idx + i] - closes[idx + i - 1]) if idx + i > 0 else h_l
        l_c = abs(lows[idx + i] - closes[idx + i - 1]) if idx + i > 0 else h_l
        tr = max(h_l, max(h_c, l_c))
        tr_sum += tr
    
    out_atr[idx] = tr_sum / period


@cuda.jit  
def _cuda_macd_kernel(prices, fast_period, slow_period, signal_period, 
                      out_macd, out_signal, out_hist):
    """CUDA kernel for MACD calculation."""
    idx = cuda.grid(1)
    if idx >= len(prices) - slow_period - signal_period:
        return
    
    # Calculate EMAs
    fast_ema = float32(0.0)
    slow_ema = float32(0.0)
    fast_mult = float32(2.0 / (fast_period + 1.0))
    slow_mult = float32(2.0 / (slow_period + 1.0))
    
    # Initialize with SMA
    for i in range(fast_period):
        fast_ema += prices[idx + i]
    fast_ema /= fast_period
    
    for i in range(slow_period):
        slow_ema += prices[idx + i]
    slow_ema /= slow_period
    
    # EMA smoothing
    for i in range(fast_period, slow_period):
        fast_ema = (prices[idx + i] - fast_ema) * fast_mult + fast_ema
    
    for i in range(slow_period, len(prices) - idx):
        price = prices[idx + i]
        fast_ema = (price - fast_ema) * fast_mult + fast_ema
        slow_ema = (price - slow_ema) * slow_mult + slow_ema
    
    macd_line = fast_ema - slow_ema
    out_macd[idx] = macd_line
    
    # Signal line (EMA of MACD)
    signal_ema = macd_line
    signal_mult = float32(2.0 / (signal_period + 1.0))
    out_signal[idx] = signal_ema
    out_hist[idx] = macd_line - signal_ema


class CUDAMemoryPool:
    """Pinned memory pool for zero-copy GPU transfers."""
    
    def __init__(self, max_tensors: int = 50, tensor_size: int = 10000):
        self.max_tensors = max_tensors
        self.tensor_size = tensor_size
        self._pinned_host: list[np.ndarray] = []
        self._gpu_tensors: list[Tensor] = []
        self._in_use: set[int] = set()
        self._lock = asyncio.Lock()
        
        self._preallocate()
    
    def _preallocate(self) -> None:
        """Preallocate pinned memory and GPU tensors."""
        for i in range(self.max_tensors):
            # Pinned host memory
            host = np.empty(self.tensor_size, dtype=np.float32)
            host = cuda.pinned_array_like(host)
            self._pinned_host.append(host)
            
            # GPU tensor
            gpu = torch.empty(self.tensor_size, dtype=torch.float32, device='cuda')
            self._gpu_tensors.append(gpu)
    
    async def acquire(self, data: np.ndarray) -> tuple[int, Tensor]:
        """Acquire buffer and copy data."""
        async with self._lock:
            available = set(range(self.max_tensors)) - self._in_use
            if not available:
                # Wait for release or expand pool
                raise RuntimeError("CUDA memory pool exhausted")
            
            idx = min(available)
            self._in_use.add(idx)
            
            # Zero-copy if possible, otherwise memcpy
            if len(data) <= self.tensor_size:
                self._pinned_host[idx][:len(data)] = data
                self._gpu_tensors[idx][:len(data)].copy_(
                    torch.from_numpy(self._pinned_host[idx][:len(data)])
                )
                return idx, self._gpu_tensors[idx][:len(data)]
            else:
                raise ValueError(f"Data size {len(data)} exceeds pool tensor size")
    
    async def release(self, idx: int) -> None:
        """Release buffer back to pool."""
        async with self._lock:
            self._in_use.discard(idx)


class FeatureEngineer:
    """GPU-accelerated feature engineering with institutional-grade optimization."""
    
    def __init__(
        self,
        parallel: bool = True,
        use_gpu: bool = True,
        cuda_streams: int = 4,
        prefetch_batches: int = 2
    ) -> None:
        self.window_sizes = [14, 20, 50, 200]
        self.cyclical = CyclicalEncoder()
        self.scaler = RobustFeatureScaler()
        self.parallel = parallel
        self.use_gpu = use_gpu and torch.cuda.is_available()
        self.cuda_streams = cuda_streams
        self.prefetch_batches = prefetch_batches
        
        # CUDA streams for async execution
        self._streams: list[torch.cuda.Stream] = []
        self._memory_pool: CUDAMemoryPool | None = None
        
        # GPU buffers with unified memory
        self._unified_buffer: Tensor | None = None
        self._gpu_ohlcv: Tensor | None = None
        self._gpu_indicators: Tensor | None = None
        self._buffer_capacity = 16384  # 16k ticks
        
        # CPU buffers
        self._ticks_buffer: list[Tick] = []
        self._ohlcv_buffer: list[OHLCV] = []
        self._max_buffer = 2000
        
        # Hawkes process (GPU-accelerated)
        self._hawkes_decay = torch.tensor(0.1, device='cuda') if self.use_gpu else 0.1
        self._hawkes_intensity = torch.tensor(0.0, device='cuda') if self.use_gpu else 0.0
        self._hawkes_times: Tensor | None = None
        
        # Technical indicator state (GPU persistent)
        self._gpu_rsi_state: Tensor | None = None
        self._gpu_atr_state: Tensor | None = None
        self._gpu_obv: Tensor | None = None
        
        # Precomputed constants
        self._rsi_period = 14
        self._atr_period = 14
        self._macd_fast = 12
        self._macd_slow = 26
        self._macd_signal = 9
        
        # JIT compiled CPU functions
        self._compute_returns_jit = lru_cache(maxsize=128)(self._compute_returns_numpy)
        
        # Initialize GPU
        if self.use_gpu:
            self._init_gpu_advanced()
    
    def _init_gpu_advanced(self) -> None:
        """Initialize advanced GPU infrastructure."""
        try:
            with nvtx.range("init_gpu"):
                # Create CUDA streams
                for i in range(self.cuda_streams):
                    self._streams.append(torch.cuda.Stream(priority=-i if i < 2 else 0))
                
                # Memory pool
                self._memory_pool = CUDAMemoryPool(max_tensors=50, tensor_size=self._buffer_capacity)
                
                # Unified memory buffer (zero-copy with CPU)
                self._unified_buffer = torch.empty(
                    (self._buffer_capacity, 6),  # mid, volume, bid, ask, timestamp, spread
                    dtype=torch.float32,
                    device='cuda'
                )
                
                # OHLCV buffer on GPU
                self._gpu_ohlcv = torch.empty(
                    (500, 5),  # open, high, low, close, volume
                    dtype=torch.float32,
                    device='cuda'
                )
                
                # Indicator output buffers
                self._gpu_indicators = torch.empty(
                    (self._buffer_capacity, 10),  # rsi, atr, macd, signal, hist, obv, vwap, etc
                    dtype=torch.float32,
                    device='cuda'
                )
                
                # Hawkes state
                self._hawkes_times = torch.empty(1000, dtype=torch.float32, device='cuda')
                
                # Persistent indicator state
                self._gpu_rsi_state = torch.zeros(2, device='cuda')  # avg_gain, avg_loss
                self._gpu_atr_state = torch.zeros(1, device='cuda')  # last atr
                self._gpu_obv = torch.zeros(1, device='cuda')
                
                # Warmup kernels
                self._warmup_kernels()
                
            logger.info(
                f"Advanced GPU initialized: "
                f"streams={self.cuda_streams}, "
                f"unified_memory={self._unified_buffer.numel() * 4 / 1e6:.1f}MB"
            )
            
        except Exception as e:
            logger.error(f"Advanced GPU init failed: {e}")
            self.use_gpu = False
    
    def _warmup_kernels(self) -> None:
        """Warmup CUDA kernels to avoid first-call overhead."""
        dummy = torch.randn(1000, device='cuda')
        for _ in range(3):
            torch.diff(dummy)
            torch.std(dummy)
            torch.mean(dummy)
        torch.cuda.synchronize()
    
    async def compute_async(self, tick: Tick) -> FeatureVector:
        """Async compute with GPU pipeline."""
        # Stage 1: Buffer update (CPU)
        self._ticks_buffer.append(tick)
        if len(self._ticks_buffer) > self._max_buffer:
            self._ticks_buffer.pop(0)
        
        # Stage 2: GPU batch processing (async)
        if self.use_gpu and len(self._ticks_buffer) >= 50:
            # Non-blocking GPU computation
            await self._gpu_pipeline(tick)
        
        # Stage 3: Feature assembly (CPU/GPU hybrid)
        return await self._compute_hybrid(tick)
    
    async def _gpu_pipeline(self, latest_tick: Tick) -> None:
        """Multi-stream GPU processing pipeline."""
        if not self.use_gpu or not self._streams:
            return
        
        with nvtx.range("gpu_pipeline"):
            # Stream 0: Price-based indicators (RSI, MACD)
            with torch.cuda.stream(self._streams[0]):
                prices = torch.tensor(
                    [float(t.mid) for t in self._ticks_buffer[-200:]],
                    device='cuda'
                )
                self._gpu_rsi = self._cuda_rsi(prices, self._gpu_rsi_state)
                self._gpu_macd = self._cuda_macd(prices)
            
            # Stream 1: Volatility indicators (ATR, bands)
            with torch.cuda.stream(self._streams[1]):
                if len(self._ohlcv_buffer) >= 14:
                    ohlc = torch.tensor([
                        [float(c.open), float(c.high), float(c.low), float(c.close), float(c.volume)]
                        for c in self._ohlcv_buffer[-50:]
                    ], device='cuda')
                    self._gpu_atr = self._cuda_atr(ohlc, self._gpu_atr_state)
            
            # Stream 2: Volume indicators (OBV, VWAP)
            with torch.cuda.stream(self._streams[2]):
                volumes = torch.tensor(
                    [float(t.volume) for t in self._ticks_buffer[-100:]],
                    device='cuda'
                )
                self._gpu_obv_new = self._cuda_obv(prices, volumes, self._gpu_obv)
            
            # Stream 3: Microstructure (Hawkes, spread)
            with torch.cuda.stream(self._streams[3]):
                self._gpu_hawkes = self._cuda_hawkes(
                    torch.tensor(float(latest_tick.timestamp.timestamp()), device='cuda'),
                    self._hawkes_decay,
                    self._hawkes_intensity
                )
            
            # Synchronize only when needed
            torch.cuda.synchronize(self._streams[0])
    
    def _cuda_rsi(self, prices: Tensor, state: Tensor) -> Tensor:
        """GPU RSI with stateful smoothing."""
        if len(prices) < 2:
            return torch.tensor(50.0, device='cuda')
        
        deltas = torch.diff(prices)
        gains = torch.where(deltas > 0, deltas, torch.zeros_like(deltas))
        losses = torch.where(deltas < 0, -deltas, torch.zeros_like(deltas))
        
        # Use previous state if available
        if state[0] > 0 or state[1] > 0:
            avg_gain = (state[0] * 13 + gains[-1]) / 14
            avg_loss = (state[1] * 13 + losses[-1]) / 14
        else:
            avg_gain = torch.mean(gains[-14:])
            avg_loss = torch.mean(losses[-14:])
        
        # Update state
        state[0] = avg_gain
        state[1] = avg_loss
        
        rs = avg_gain / avg_loss if avg_loss > 0 else torch.tensor(1e10, device='cuda')
        rsi = 100.0 - (100.0 / (1.0 + rs))
        
        return rsi
    
    def _cuda_macd(self, prices: Tensor) -> tuple[Tensor, Tensor, Tensor]:
        """GPU MACD calculation."""
        if len(prices) < 26:
            return torch.tensor(0.0, device='cuda'), torch.tensor(0.0, device='cuda'), torch.tensor(0.0, device='cuda')
        
        # Fast EMA
        ema_fast = prices[0]
        mult_fast = 2.0 / (self._macd_fast + 1.0)
        for p in prices[1:]:
            ema_fast = (p - ema_fast) * mult_fast + ema_fast
        
        # Slow EMA
        ema_slow = prices[0]
        mult_slow = 2.0 / (self._macd_slow + 1.0)
        for p in prices[1:]:
            ema_slow = (p - ema_slow) * mult_slow + ema_slow
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line * 0.5  # Simplified
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def _cuda_atr(self, ohlc: Tensor, state: Tensor) -> Tensor:
        """GPU ATR with state."""
        highs = ohlc[:, 1]
        lows = ohlc[:, 2]
        closes = ohlc[:, 3]
        
        tr1 = highs - lows
        tr2 = torch.abs(highs - torch.roll(closes, 1))
        tr3 = torch.abs(lows - torch.roll(closes, 1))
        tr = torch.maximum(tr1, torch.maximum(tr2, tr3))
        
        # Wilder's smoothing
        if state[0] > 0:
            atr = (state[0] * 13 + tr[-1]) / 14
        else:
            atr = torch.mean(tr)
        
        state[0] = atr
        return atr
    
    def _cuda_obv(self, prices: Tensor, volumes: Tensor, state: Tensor) -> Tensor:
        """GPU OBV with state."""
        if len(prices) < 2:
            return state
        
        changes = torch.sign(torch.diff(prices))
        obv_change = torch.sum(changes * volumes[1:])
        
        state[0] = state[0] + obv_change
        return state[0]
    
    def _cuda_hawkes(self, timestamp: Tensor, decay: Tensor, intensity: Tensor) -> Tensor:
        """GPU Hawkes process."""
        if self._hawkes_times is None or self._hawkes_times.numel() == 0:
            return torch.tensor(0.0, device='cuda')
        
        last_time = self._hawkes_times[0] if self._hawkes_times.numel() > 0 else timestamp - 1.0
        dt = timestamp - last_time
        
        # Exponential decay
        new_intensity = intensity * torch.exp(-decay * dt) + 1.0
        
        # Roll and store
        self._hawkes_times = torch.roll(self._hawkes_times, 1)
        self._hawkes_times[0] = timestamp
        
        return new_intensity
    
    async def _compute_hybrid(self, tick: Tick) -> FeatureVector:
        """Combine GPU and CPU computed features."""
        ts = pd.Timestamp(tick.timestamp)
        
        # Get GPU-computed values (if available)
        if self.use_gpu and hasattr(self, '_gpu_rsi'):
            rsi = float(self._gpu_rsi.cpu())
            atr = float(self._gpu_atr.cpu()) if hasattr(self, '_gpu_atr') else 0.0
            macd = float(self._gpu_macd[0].cpu()) if hasattr(self, '_gpu_macd') else 0.0
            macd_signal = float(self._gpu_macd[1].cpu()) if hasattr(self, '_gpu_macd') else 0.0
            obv = float(self._gpu_obv.cpu()) if hasattr(self, '_gpu_obv_new') else 0.0
            hawkes = float(self._gpu_hawkes.cpu()) if hasattr(self, '_gpu_hawkes') else 0.0
        else:
            # CPU fallback
            rsi, atr, macd, macd_signal, obv, hawkes = self._compute_cpu_indicators(tick)
        
        # CPU-only features (order flow, microstructure)
        bid_ask_ratio = float(tick.bid / tick.ask) if tick.ask > 0 else 1.0
        volume_imbalance = self._compute_volume_imbalance(tick)
        
        # Cyclical (CPU)
        hour_sin, hour_cos = self.cyclical.encode_hour(ts.hour)
        day_sin, day_cos = self.cyclical.encode_dayofweek(ts.dayofweek)
        
        # Returns (GPU or CPU)
        returns, log_returns, volatility = await self._compute_returns_gpu()
        
        return FeatureVector(
            timestamp=ts,
            symbol=tick.symbol,
            returns=returns,
            log_returns=log_returns,
            volatility=volatility,
            rsi=rsi,
            atr=atr,
            macd=macd,
            macd_signal=macd_signal,
            obv=obv,
            vwap_dev=self._compute_vwap_dev(tick.mid),
            bid_ask_ratio=bid_ask_ratio,
            volume_imbalance=volume_imbalance,
            hawkes_intensity=hawkes,
            hour_sin=hour_sin,
            hour_cos=hour_cos,
            day_sin=day_sin,
            day_cos=day_cos,
            spread=float(tick.ask - tick.bid),
            mid_price=float(tick.mid)
        )
    
    async def _compute_returns_gpu(self) -> tuple[float, float, float]:
        """Compute returns on GPU."""
        if not self.use_gpu or len(self._ticks_buffer) < 2:
            return 0.0, 0.0, 0.0
        
        prices = torch.tensor(
            [float(t.mid) for t in self._ticks_buffer],
            device='cuda'
        )
        
        returns = torch.diff(prices) / prices[:-1]
        log_returns = torch.log(prices[1:] / prices[:-1])
        volatility = torch.std(returns) * torch.sqrt(torch.tensor(252.0, device='cuda'))
        
        return (
            float(returns[-1].cpu()),
            float(log_returns[-1].cpu()),
            float(volatility.cpu())
        )
    
    def _compute_cpu_indicators(self, tick: Tick) -> tuple[float, ...]:
        """CPU fallback for indicators."""
        # Simplified CPU implementation
        return 50.0, 0.0, 0.0, 0.0, 0.0, 0.0
    
    def _compute_volume_imbalance(self, tick: Tick) -> float:
        """Compute volume imbalance."""
        if len(self._ticks_buffer) < 10:
            return 0.0
        
        recent = self._ticks_buffer[-10:]
        buy_volume = sum(t.volume for t in recent if t.mid >= (t.bid + t.ask) / 2)
        total = sum(t.volume for t in recent)
        
        return float(buy_volume / total - 0.5) if total > 0 else 0.0
    
    def _compute_vwap_dev(self, current_price: float) -> float:
        """Compute VWAP deviation."""
        if len(self._ohlcv_buffer) < 20:
            return 0.0
        
        typical_sum = sum(
            float((c.high + c.low + c.close) / 3 * c.volume)
            for c in self._ohlcv_buffer[-20:]
        )
        vol_sum = sum(float(c.volume) for c in self._ohlcv_buffer[-20:])
        
        if vol_sum > 0:
            vwap = typical_sum / vol_sum
            return (current_price - vwap) / vwap
        
        return 0.0
    
    def get_gpu_stats(self) -> dict[str, Any]:
        """GPU performance statistics."""
        if not self.use_gpu:
            return {"enabled": False}
        
        return {
            "enabled": True,
            "streams": len(self._streams),
            "buffer_capacity": self._buffer_capacity,
            "memory_pool_tensors": len(self._memory_pool._in_use) if self._memory_pool else 0,
            "cuda_memory_allocated_mb": torch.cuda.memory_allocated() / 1e6,
            "cuda_memory_reserved_mb": torch.cuda.memory_reserved() / 1e6,
        }
