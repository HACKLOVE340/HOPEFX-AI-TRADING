# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
analytics/options.py
====================
Black-Scholes options pricing and full Greeks calculation.

All Greeks are computed analytically from the closed-form Black-Scholes
formulae — no finite-difference approximations.

Greeks implemented
------------------
delta  : dV/dS   — sensitivity of option price to underlying price
gamma  : d²V/dS² — rate of change of delta
theta  : dV/dt   — time decay (returned as daily decay, not annualised)
vega   : dV/dσ   — sensitivity to 1% change in implied volatility
rho    : dV/dr   — sensitivity to 1% change in risk-free rate

Formulae
--------
For a European call/put under GBM (no continuous dividends):

    d1 = [ln(S/K) + (r + σ²/2)·T] / (σ·√T)
    d2 = d1 - σ·√T

    Call price  = S·N(d1) - K·e^{-rT}·N(d2)
    Put price   = K·e^{-rT}·N(-d2) - S·N(-d1)

    Delta call  = N(d1)
    Delta put   = N(d1) - 1
    Gamma       = n(d1) / (S·σ·√T)          [same for call and put]
    Theta call  = [-S·n(d1)·σ/(2√T) - r·K·e^{-rT}·N(d2)] / 365
    Theta put   = [-S·n(d1)·σ/(2√T) + r·K·e^{-rT}·N(-d2)] / 365
    Vega        = S·n(d1)·√T / 100           [per 1% move in vol]
    Rho call    = K·T·e^{-rT}·N(d2) / 100   [per 1% move in rate]
    Rho put     = -K·T·e^{-rT}·N(-d2) / 100

where N(·) is the standard normal CDF and n(·) is the standard normal PDF.

Usage
-----
    from analytics.options import OptionsAnalyzer

    analyzer = OptionsAnalyzer()
    price = analyzer.price_option("call", 2350.0, 2400.0, 0.25, 0.18)
    greeks = analyzer.calculate_greeks("call", 2350.0, 2400.0, 0.25, 0.18)
    # greeks = {"delta": 0.42, "gamma": 0.0012, "theta": -1.83,
    #           "vega": 4.71, "rho": 2.18}
"""

import math


class OptionsAnalyzer:
    """Black-Scholes options pricing and Greeks."""

    # ── Public API ────────────────────────────────────────────────────────────

    def price_option(
        self,
        option_type: str,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = 0.05,
        model: str = "black_scholes",
    ) -> float:
        """
        Price a European option using Black-Scholes.

        Parameters
        ----------
        option_type    : "call" or "put"
        spot_price     : Current underlying price (S)
        strike_price   : Option strike price (K)
        time_to_expiry : Time to expiry in years (T)
        volatility     : Annualised implied volatility as a decimal (e.g. 0.18 = 18%)
        risk_free_rate : Annualised risk-free rate as a decimal (e.g. 0.05 = 5%)
        model          : Reserved for future models; only "black_scholes" supported.

        Returns
        -------
        float : Option price in the same currency as spot_price.
        """
        if time_to_expiry <= 0 or volatility <= 0 or spot_price <= 0 or strike_price <= 0:
            # Intrinsic value at expiry
            if option_type.lower() == "call":
                return max(spot_price - strike_price, 0.0)
            return max(strike_price - spot_price, 0.0)

        d1, d2 = self._d1_d2(spot_price, strike_price, time_to_expiry, volatility, risk_free_rate)
        discount = math.exp(-risk_free_rate * time_to_expiry)

        if option_type.lower() == "call":
            return spot_price * self._norm_cdf(d1) - strike_price * discount * self._norm_cdf(d2)
        # put
        return strike_price * discount * self._norm_cdf(-d2) - spot_price * self._norm_cdf(-d1)

    def calculate_greeks(
        self,
        option_type: str,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = 0.05,
    ) -> dict[str, float]:
        """
        Compute all first-order Black-Scholes Greeks analytically.

        Parameters
        ----------
        option_type    : "call" or "put"
        spot_price     : Current underlying price (S)
        strike_price   : Option strike price (K)
        time_to_expiry : Time to expiry in years (T)
        volatility     : Annualised implied volatility as a decimal
        risk_free_rate : Annualised risk-free rate as a decimal

        Returns
        -------
        dict with keys:
            delta  : dV/dS
            gamma  : d²V/dS²
            theta  : daily time decay (negative = option loses value each day)
            vega   : price change per 1% increase in implied volatility
            rho    : price change per 1% increase in risk-free rate
        """
        if time_to_expiry <= 0 or volatility <= 0 or spot_price <= 0 or strike_price <= 0:
            # At/past expiry: only delta has meaning (intrinsic)
            if option_type.lower() == "call":
                delta = 1.0 if spot_price > strike_price else 0.0
            else:
                delta = -1.0 if spot_price < strike_price else 0.0
            return {"delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

        d1, d2 = self._d1_d2(spot_price, strike_price, time_to_expiry, volatility, risk_free_rate)
        sqrt_t = math.sqrt(time_to_expiry)
        nd1 = self._norm_pdf(d1)  # standard normal PDF at d1
        discount = math.exp(-risk_free_rate * time_to_expiry)
        is_call = option_type.lower() == "call"

        # ── Delta ─────────────────────────────────────────────────────────────
        delta = self._norm_cdf(d1) if is_call else self._norm_cdf(d1) - 1.0

        # ── Gamma (identical for call and put) ────────────────────────────────
        gamma = nd1 / (spot_price * volatility * sqrt_t)

        # ── Theta (annualised → daily by dividing by 365) ─────────────────────
        common_theta = -(spot_price * nd1 * volatility) / (2.0 * sqrt_t)
        if is_call:
            theta = (common_theta - risk_free_rate * strike_price * discount * self._norm_cdf(d2)) / 365.0
        else:
            theta = (common_theta + risk_free_rate * strike_price * discount * self._norm_cdf(-d2)) / 365.0

        # ── Vega (per 1% change in vol) ───────────────────────────────────────
        vega = spot_price * nd1 * sqrt_t / 100.0

        # ── Rho (per 1% change in rate) ───────────────────────────────────────
        if is_call:
            rho = strike_price * time_to_expiry * discount * self._norm_cdf(d2) / 100.0
        else:
            rho = -strike_price * time_to_expiry * discount * self._norm_cdf(-d2) / 100.0

        return {
            "delta": round(delta, 6),
            "gamma": round(gamma, 6),
            "theta": round(theta, 6),
            "vega": round(vega, 6),
            "rho": round(rho, 6),
        }

    def implied_volatility(
        self,
        option_type: str,
        market_price: float,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,
        risk_free_rate: float = 0.05,
        tol: float = 1e-6,
        max_iter: int = 200,
    ) -> float | None:
        """
        Compute implied volatility via Newton-Raphson with bisection fallback.

        Returns the implied vol as a decimal (e.g. 0.18 = 18%), or None if
        the market price is outside the no-arbitrage bounds or convergence fails.
        """
        intrinsic = (
            max(spot_price - strike_price, 0.0)
            if option_type.lower() == "call"
            else max(strike_price - spot_price, 0.0)
        )
        if market_price < intrinsic or time_to_expiry <= 0:
            return None

        # Newton-Raphson: f(σ) = BS_price(σ) - market_price = 0
        sigma = 0.20  # initial guess
        for _ in range(max_iter):
            price = self.price_option(option_type, spot_price, strike_price, time_to_expiry, sigma, risk_free_rate)
            d1, _ = self._d1_d2(spot_price, strike_price, time_to_expiry, sigma, risk_free_rate)
            vega_ann = spot_price * self._norm_pdf(d1) * math.sqrt(time_to_expiry)
            if vega_ann < 1e-10:
                break
            diff = price - market_price
            if abs(diff) < tol:
                return round(sigma, 6)
            sigma -= diff / vega_ann
            if sigma <= 0:
                sigma = 1e-6

        # Bisection fallback
        lo, hi = 1e-6, 10.0
        for _ in range(100):
            mid = (lo + hi) / 2.0
            p = self.price_option(option_type, spot_price, strike_price, time_to_expiry, mid, risk_free_rate)
            if abs(p - market_price) < tol:
                return round(mid, 6)
            if p < market_price:
                lo = mid
            else:
                hi = mid
        return round((lo + hi) / 2.0, 6)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _d1_d2(
        self,
        S: float,
        K: float,
        T: float,
        sigma: float,
        r: float,
    ) -> tuple[float, float]:
        """Return (d1, d2) for Black-Scholes."""
        sqrt_t = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_t)
        d2 = d1 - sigma * sqrt_t
        return d1, d2

    def _norm_cdf(self, x: float) -> float:
        """Standard normal CDF via math.erf."""
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

    def _norm_pdf(self, x: float) -> float:
        """Standard normal PDF."""
        return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
