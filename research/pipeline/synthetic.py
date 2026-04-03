# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
research/pipeline/synthetic.py
================================
TimeGAN-inspired synthetic data augmentation for rare market regimes.

Why this matters
----------------
Crash regimes (2008, 2020 COVID, 2022 rate shock) and extreme vol spikes
appear in <5% of historical bars.  A model trained on imbalanced data learns
to predict "normal" almost always.  Generating synthetic rare-regime bars
that are statistically plausible — not just noise — lets us oversample those
regimes without repeating the same 50 real crash bars 20× (which causes
overfitting to specific historical events).

Architecture: Minimal TimeGAN
------------------------------
Full TimeGAN (Yoon et al. 2019) has 4 networks (embedder, recovery, generator,
discriminator) and is expensive to train.  This implementation uses a
simplified 3-network version:

  Embedder  E : real sequences → latent space
  Generator G : noise + condition → latent sequences
  Discriminator D : latent real vs latent fake

The condition vector encodes the target regime (one-hot), so G learns to
produce sequences that look like a specific regime.

Training is stable because:
- We operate in latent space (embedder pre-trained with reconstruction loss)
- Gradient penalty (WGAN-GP) replaces vanilla GAN loss
- Sequences are normalised per-feature before training

Usage
-----
    from research.pipeline.synthetic import RegimeSynthesizer

    synth = RegimeSynthesizer(seq_len=60, n_features=50)
    synth.fit(X_rare, regime_labels, epochs=500)
    X_aug = synth.generate(n_samples=200, regime=2)
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import torch
    from torch import nn, optim

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch unavailable — RegimeSynthesizer disabled")


# ─────────────────────────────────────────────────────────────────────────────
# Regime labeller (used before synthesiser to identify rare regimes)
# ─────────────────────────────────────────────────────────────────────────────


def label_regimes(
    df,
    vol_col: str = "realvol_20",
    ret_col: str = "ret_20",
    n_regimes: int = 3,
) -> np.ndarray:
    """
    Assign each bar to a volatility regime via quantile bucketing.

    Regime 0 = low vol / normal
    Regime 1 = medium vol / trending
    Regime 2 = high vol / crash/spike  ← the rare one we want to augment

    Parameters
    ----------
    df        : Feature DataFrame (must contain vol_col and ret_col)
    vol_col   : Realised volatility column name
    ret_col   : Return column name
    n_regimes : Number of regimes (default 3)

    Returns
    -------
    Integer array of regime labels, shape (n_samples,)
    """
    if vol_col not in df.columns:
        # Fallback: compute from close
        log_ret = np.log(df["close"] / df["close"].shift(1))
        vol = log_ret.rolling(20).std() * np.sqrt(252)
    else:
        vol = df[vol_col]

    labels = pd.qcut(vol.fillna(vol.median()), q=n_regimes, labels=False, duplicates="drop")
    return labels.fillna(0).astype(int).values


# ─────────────────────────────────────────────────────────────────────────────
# Network definitions
# ─────────────────────────────────────────────────────────────────────────────

if TORCH_AVAILABLE:
    class _Embedder(nn.Module):
        """Maps real sequences to a fixed-size latent space."""

        def __init__(self, n_features: int, hidden: int, latent: int, seq_len: int):
            super().__init__()
            self.rnn = nn.GRU(n_features, hidden, num_layers=2, batch_first=True, dropout=0.1)
            self.proj = nn.Linear(hidden, latent)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # x: (B, T, F)
            out, _ = self.rnn(x)
            return torch.tanh(self.proj(out))  # (B, T, latent)

    class _Recovery(nn.Module):
        """Reconstructs real sequences from latent space (autoencoder decoder)."""

        def __init__(self, latent: int, hidden: int, n_features: int):
            super().__init__()
            self.rnn = nn.GRU(latent, hidden, num_layers=2, batch_first=True, dropout=0.1)
            self.proj = nn.Linear(hidden, n_features)

        def forward(self, h: torch.Tensor) -> torch.Tensor:
            out, _ = self.rnn(h)
            return self.proj(out)

    class _Generator(nn.Module):
        """Generates latent sequences from noise + regime condition."""

        def __init__(self, noise_dim: int, n_conditions: int, hidden: int, latent: int):
            super().__init__()
            self.rnn = nn.GRU(
                noise_dim + n_conditions,
                hidden,
                num_layers=2,
                batch_first=True,
                dropout=0.1,
            )
            self.proj = nn.Linear(hidden, latent)

        def forward(self, z: torch.Tensor, c: torch.Tensor) -> torch.Tensor:
            # z: (B, T, noise_dim)  c: (B, n_conditions) → broadcast to (B, T, n_conditions)
            c_exp = c.unsqueeze(1).expand(-1, z.size(1), -1)
            inp = torch.cat([z, c_exp], dim=-1)
            out, _ = self.rnn(inp)
            return torch.tanh(self.proj(out))

    class _Discriminator(nn.Module):
        """Distinguishes real latent sequences from generated ones."""

        def __init__(self, latent: int, n_conditions: int, hidden: int):
            super().__init__()
            self.rnn = nn.GRU(
                latent + n_conditions,
                hidden,
                num_layers=2,
                batch_first=True,
                dropout=0.1,
            )
            self.head = nn.Linear(hidden, 1)

        def forward(self, h: torch.Tensor, c: torch.Tensor) -> torch.Tensor:
            c_exp = c.unsqueeze(1).expand(-1, h.size(1), -1)
            inp = torch.cat([h, c_exp], dim=-1)
            out, _ = self.rnn(inp)
            return self.head(out[:, -1, :]).squeeze(-1)  # (B,)


# ─────────────────────────────────────────────────────────────────────────────
# WGAN-GP gradient penalty
# ─────────────────────────────────────────────────────────────────────────────


def _gradient_penalty(D, real_h, fake_h, c, device, lam=10.0):
    B = real_h.size(0)
    alpha = torch.rand(B, 1, 1, device=device)
    interp = (alpha * real_h + (1 - alpha) * fake_h).requires_grad_(True)
    d_interp = D(interp, c)
    grads = torch.autograd.grad(
        outputs=d_interp,
        inputs=interp,
        grad_outputs=torch.ones_like(d_interp),
        create_graph=True,
        retain_graph=True,
    )[0]
    gp = ((grads.norm(2, dim=(1, 2)) - 1) ** 2).mean()
    return lam * gp


# ─────────────────────────────────────────────────────────────────────────────
# RegimeSynthesizer
# ─────────────────────────────────────────────────────────────────────────────


class RegimeSynthesizer:
    """
    Conditional TimeGAN for generating synthetic sequences of a target regime.

    Parameters
    ----------
    seq_len     : Length of each generated sequence (bars)
    n_features  : Number of features per bar
    n_regimes   : Number of distinct regime classes
    hidden      : RNN hidden size
    latent      : Latent space dimension
    noise_dim   : Generator noise input dimension
    device      : 'auto' | 'cuda' | 'cpu'
    """

    def __init__(
        self,
        seq_len: int = 60,
        n_features: int = 50,
        n_regimes: int = 3,
        hidden: int = 64,
        latent: int = 32,
        noise_dim: int = 16,
        device: str = "auto",
    ):
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch required for RegimeSynthesizer")

        self.seq_len = seq_len
        self.n_features = n_features
        self.n_regimes = n_regimes
        self.noise_dim = noise_dim

        if device == "auto":
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        self.E = _Embedder(n_features, hidden, latent, seq_len).to(self.device)  # pylint: disable=possibly-used-before-assignment
        self.R = _Recovery(latent, hidden, n_features).to(self.device)  # pylint: disable=possibly-used-before-assignment
        self.G = _Generator(noise_dim, n_regimes, hidden, latent).to(self.device)  # pylint: disable=possibly-used-before-assignment
        self.D = _Discriminator(latent, n_regimes, hidden).to(self.device)  # pylint: disable=possibly-used-before-assignment

        self._feature_mean: np.ndarray | None = None
        self._feature_std: np.ndarray | None = None
        self._fitted = False

    # ── Normalisation (min-max to [-1, 1] for GAN stability) ─────────────────

    def _normalise(self, X: np.ndarray) -> np.ndarray:
        return 2.0 * (X - self._feature_mean) / (self._feature_std + 1e-8) - 1.0

    def _denormalise(self, X: np.ndarray) -> np.ndarray:
        return (np.clip(X, -1.0, 1.0) + 1.0) / 2.0 * (self._feature_std + 1e-8) + self._feature_mean

    # ── Sequence builder ──────────────────────────────────────────────────────

    def _make_sequences(self, X: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Slide a window over X to produce (seq, label) pairs."""
        seqs, labs = [], []
        for i in range(len(X) - self.seq_len):
            seqs.append(X[i : i + self.seq_len])
            labs.append(labels[i + self.seq_len - 1])
        return np.array(seqs, dtype=np.float32), np.array(labs, dtype=np.int64)

    # ── Training ──────────────────────────────────────────────────────────────

    def fit(
        self,
        X: np.ndarray,
        regime_labels: np.ndarray,
        epochs: int = 500,
        batch_size: int = 32,
        lr: float = 1e-3,
        n_critic: int = 3,
        log_every: int = 50,
    ) -> RegimeSynthesizer:
        """
        Train the synthesiser on historical sequences.

        Parameters
        ----------
        X             : (n_samples, n_features) feature matrix
        regime_labels : (n_samples,) integer regime labels
        epochs        : Training epochs
        batch_size    : Mini-batch size
        lr            : Learning rate
        n_critic      : Discriminator updates per generator update (WGAN)
        """
        # Normalise using min/max so generated values stay in a bounded range.
        # _feature_mean stores the per-feature minimum.
        # _feature_std  stores the per-feature range (max - min).
        self._feature_mean = X.min(axis=0)
        self._feature_std = X.max(axis=0) - X.min(axis=0)
        X_norm = self._normalise(X)

        seqs, labs = self._make_sequences(X_norm, regime_labels)
        n = len(seqs)
        logger.info("TimeGAN training: %d sequences, %d regimes", n, self.n_regimes)

        # One-hot conditions
        conds = np.eye(self.n_regimes, dtype=np.float32)[labs]

        # ── Phase 1: Pre-train embedder / recovery (reconstruction) ──────────
        opt_er = optim.Adam(list(self.E.parameters()) + list(self.R.parameters()), lr=lr)
        for ep in range(min(epochs // 2, 200)):
            idx = np.random.choice(n, min(batch_size, n), replace=False)
            x_b = torch.tensor(seqs[idx]).to(self.device)
            h = self.E(x_b)
            x_hat = self.R(h)
            loss = nn.functional.mse_loss(x_hat, x_b)
            opt_er.zero_grad()
            loss.backward()
            opt_er.step()
            if ep % log_every == 0:
                logger.debug("Embedder pre-train ep=%d  recon_loss=%.4f", ep, loss.item())

        # ── Phase 2: Adversarial training ─────────────────────────────────────
        opt_g = optim.Adam(self.G.parameters(), lr=lr, betas=(0.5, 0.9))
        opt_d = optim.Adam(self.D.parameters(), lr=lr, betas=(0.5, 0.9))

        for ep in range(epochs):
            idx = np.random.choice(n, min(batch_size, n), replace=False)
            x_b = torch.tensor(seqs[idx]).to(self.device)
            c_b = torch.tensor(conds[idx]).to(self.device)

            # Embed real sequences
            with torch.no_grad():
                h_real = self.E(x_b)

            # ── Critic steps ──────────────────────────────────────────────────
            for _ in range(n_critic):
                z = torch.randn(len(idx), self.seq_len, self.noise_dim, device=self.device)
                h_fake = self.G(z, c_b).detach()
                d_real = self.D(h_real, c_b)
                d_fake = self.D(h_fake, c_b)
                gp = _gradient_penalty(self.D, h_real, h_fake, c_b, self.device)
                d_loss = d_fake.mean() - d_real.mean() + gp
                opt_d.zero_grad()
                d_loss.backward()
                opt_d.step()

            # ── Generator step ────────────────────────────────────────────────
            z = torch.randn(len(idx), self.seq_len, self.noise_dim, device=self.device)
            h_fake = self.G(z, c_b)
            g_loss = -self.D(h_fake, c_b).mean()
            opt_g.zero_grad()
            g_loss.backward()
            opt_g.step()

            if ep % log_every == 0:
                logger.info("TimeGAN ep=%d  D=%.3f  G=%.3f", ep, d_loss.item(), g_loss.item())

        self._fitted = True
        return self

    # ── Generation ────────────────────────────────────────────────────────────

    def generate(
        self,
        n_samples: int,
        regime: int,
        temperature: float = 1.0,
    ) -> np.ndarray:
        """
        Generate synthetic sequences for a target regime.

        Parameters
        ----------
        n_samples   : Number of sequences to generate
        regime      : Target regime index (0 = low vol, 2 = crash/spike)
        temperature : Noise scale — >1 increases diversity, <1 reduces it

        Returns
        -------
        (n_samples, seq_len, n_features) float32 array in original scale
        """
        if not self._fitted:
            raise RuntimeError("Call fit() before generate()")

        self.G.eval()
        self.R.eval()

        c = torch.zeros(n_samples, self.n_regimes, device=self.device)
        c[:, regime] = 1.0

        with torch.no_grad():
            z = torch.randn(n_samples, self.seq_len, self.noise_dim, device=self.device) * temperature
            h_fake = self.G(z, c)
            x_fake = self.R(h_fake).cpu().numpy()

        return self._denormalise(x_fake)

    # ── Augment helper ────────────────────────────────────────────────────────

    def augment_rare_regimes(
        self,
        X: np.ndarray,
        regime_labels: np.ndarray,
        target_regime: int,
        target_count: int | None = None,
        multiplier: float = 3.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Oversample a rare regime by generating synthetic sequences.

        Parameters
        ----------
        X              : Original (n_samples, n_features) array
        regime_labels  : (n_samples,) integer labels
        target_regime  : Regime index to augment
        target_count   : Desired total count for target regime; if None,
                         uses multiplier × current count
        multiplier     : How many times to multiply the rare regime

        Returns
        -------
        X_aug, labels_aug — concatenation of original + synthetic data
        """
        rare_mask = regime_labels == target_regime
        n_rare = rare_mask.sum()

        if n_rare == 0:
            logger.warning("No samples for regime %d — skipping augmentation", target_regime)
            return X, regime_labels

        n_generate = int(target_count - n_rare) if target_count else int(n_rare * (multiplier - 1))
        if n_generate <= 0:
            return X, regime_labels

        logger.info(
            "Augmenting regime %d: %d real → +%d synthetic",
            target_regime,
            n_rare,
            n_generate,
        )

        # Generate in batches of seq_len (take last bar of each sequence as a sample)
        synth_seqs = self.generate(n_generate, regime=target_regime)
        # Use the last bar of each sequence as a flat feature vector
        synth_flat = synth_seqs[:, -1, :]

        X_aug = np.vstack([X, synth_flat])
        labels_aug = np.concatenate([regime_labels, np.full(n_generate, target_regime, dtype=int)])
        return X_aug, labels_aug

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "E": self.E.state_dict(),
                "R": self.R.state_dict(),
                "G": self.G.state_dict(),
                "D": self.D.state_dict(),
                "feature_mean": self._feature_mean,
                "feature_std": self._feature_std,
                "seq_len": self.seq_len,
                "n_features": self.n_features,
                "n_regimes": self.n_regimes,
                "noise_dim": self.noise_dim,
            },
            path,
        )
        logger.info("RegimeSynthesizer saved → %s", path)

    @classmethod
    def load(cls, path: str | Path, device: str = "auto") -> RegimeSynthesizer:
        ckpt = torch.load(path, map_location="cpu", weights_only=False)  # nosec B614 — path confined to ml/saved_models
        obj = cls(
            seq_len=ckpt["seq_len"],
            n_features=ckpt["n_features"],
            n_regimes=ckpt["n_regimes"],
            noise_dim=ckpt["noise_dim"],
            device=device,
        )
        obj.E.load_state_dict(ckpt["E"])
        obj.R.load_state_dict(ckpt["R"])
        obj.G.load_state_dict(ckpt["G"])
        obj.D.load_state_dict(ckpt["D"])
        obj._feature_mean = ckpt["feature_mean"]
        obj._feature_std = ckpt["feature_std"]
        obj._fitted = True
        logger.info("RegimeSynthesizer loaded ← %s", path)
        return obj
