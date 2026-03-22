import numpy as np
import pandas as pd

class RiskManager:
    def __init__(self, returns):
        self.returns = returns

    def calculate_var(self, confidence_level=0.95):
        """ Calculate Value at Risk (VaR) """
        return np.percentile(self.returns, 100 * (1 - confidence_level))

    def calculate_sharpe_ratio(self, risk_free_rate=0.01):
        """ Calculate Sharpe Ratio """
        excess_returns = self.returns.mean() - risk_free_rate
        return excess_returns / self.returns.std()

    def calculate_sortino_ratio(self, target_return=0):
        """ Calculate Sortino Ratio """
        downside_returns = self.returns[self.returns < target_return].std()
        return (self.returns.mean() - target_return) / downside_returns

    def calculate_position_size(self, account_balance, risk_percent, entry_price, stop_loss_price):
        """ Calculate position size """
        risk_per_trade = account_balance * risk_percent
        risk_per_share = entry_price - stop_loss_price
        return risk_per_trade / risk_per_share

    def calculate_kelly_criterion(self, win_probability, win_loss_ratio):
        """ Calculate Kelly Criterion """
        return (win_probability - (1 - win_probability)) / win_loss_ratio

    def portfolio_risk_check(self, weights, covariance_matrix):
        """ Calculate total portfolio risk """
        return np.sqrt(np.dot(weights.T, np.dot(covariance_matrix, weights)))
