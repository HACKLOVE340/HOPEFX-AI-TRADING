# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
analytics/simulations.py
========================
Simulation engine — delegates to analytics.monte_carlo for bootstrap MC
and provides a genetic algorithm optimiser (scipy differential_evolution
with random-search fallback).

The MonteCarloEngine in analytics/monte_carlo.py is the canonical
implementation. This module re-exports it for backward compatibility
and adds the SimulationEngine wrapper used by the dashboard.
"""

from __future__ import annotations


import numpy as np

from analytics.monte_carlo import BootstrapResult, run_bootstrap


class SimulationEngine:
    """
    Simulation engine used by the dashboard and backtesting pipeline.

    monte_carlo_simulation() delegates to the bootstrap engine in
    analytics.monte_carlo (block or i.i.d. resampling of actual trade P&Ls).
    genetic_algorithm_optimization() uses scipy differential_evolution
    with a random-search fallback when scipy is unavailable.
    """

    def monte_carlo_simulation(
        self,
        trade_pnls: list[float],
        initial_capital: float = 100_000.0,
        n_paths: int = 5000,
        confidence_levels: list[float] | None = None,
        method: str = "iid",
    ) -> dict:
        """
        Bootstrap Monte Carlo over actual trade P&L sequence.

        Parameters
        ----------
        trade_pnls      : Per-trade net P&L values in USD.
        initial_capital : Starting equity.
        n_paths         : Number of bootstrap paths.
        confidence_levels: Ignored (kept for API compatibility).
        method          : "iid" or "block".

        Returns
        -------
        Dict with all bootstrap metrics + confidence intervals.
        """
        result: BootstrapResult = run_bootstrap(
            trade_pnls=trade_pnls,
            initial_capital=initial_capital,
            n_paths=n_paths,
            method=method,
        )
        summary = result.summary()
        # Add legacy keys for backward compatibility
        summary["mean_return"] = result.original_cagr
        summary["std_dev"] = (
            float(np.std(result.final_equity_distribution)) if result.final_equity_distribution else 0.0
        )
        summary["var_95"] = result.final_equity_ci_95[0]
        summary["var_99"] = result.sharpe_ci_99[0]
        summary["max_drawdown"] = result.original_max_dd
        summary["best_case"] = result.final_equity_ci_95[1]
        summary["paths"] = result.final_equity_distribution[:100]  # truncate for API
        return summary

    def genetic_algorithm_optimization(
        self,
        parameters: dict,
        fitness_function,
        population_size: int = 100,
        generations: int = 50,
    ) -> dict:
        """
        Genetic algorithm parameter optimisation.

        Uses differential evolution via scipy when available;
        falls back to random search otherwise.
        """
        try:
            from scipy.optimize import differential_evolution

            param_keys = list(parameters.keys())
            bounds = []
            for k in param_keys:
                v = parameters[k]
                if isinstance(v, int | float):
                    bounds.append((v * 0.5, v * 2.0))
                else:
                    bounds.append((0.0, 1.0))

            def _objective(x):
                params = dict(zip(param_keys, x, strict=False))
                score = fitness_function(params)
                return -score  # minimise negative fitness

            result = differential_evolution(
                _objective,
                bounds,
                maxiter=generations,
                popsize=max(5, population_size // 10),
                seed=42,
                tol=1e-6,
            )
            best_params = dict(zip(param_keys, result.x, strict=False))
            return {
                "best_parameters": best_params,
                "fitness_score": -result.fun,
                "generations": generations,
                "converged": result.success,
            }
        except ImportError:
            # Fallback: random search
            best_params = parameters
            best_fitness = 0.0
            rng = np.random.default_rng(42)
            for _ in range(population_size * generations):
                candidate = {
                    k: v * rng.uniform(0.5, 2.0) if isinstance(v, int | float) else v for k, v in parameters.items()
                }
                fitness = fitness_function(candidate)
                if fitness > best_fitness:
                    best_fitness = fitness
                    best_params = candidate
            return {
                "best_parameters": best_params,
                "fitness_score": best_fitness,
                "generations": generations,
                "converged": False,
            }
