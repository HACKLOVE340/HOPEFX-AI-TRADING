# ml/online_learner.py
"""
HOPEFX Online Learning Pipeline
Continuously adapts to market regime changes without catastrophic forgetting
"""

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
import numpy as np
from typing import List, Dict, Tuple, Optional
from collections import deque
import copy


class EWCRegularizer:
    """
    Elastic Weight Consolidation (Kirkpatrick et al. 2017)
    Prevents catastrophic forgetting in neural networks.
    """
    
    def __init__(self, model: nn.Module, lambda_ewc: float = 1000):
        self.model = model
        self.lambda_ewc = lambda_ewc
        self.fisher_dict: Dict[str, torch.Tensor] = {}
        self.optimal_params: Dict[str, torch.Tensor] = {}
        self.ewc_loss = 0
    
    def update_fisher(self, dataloader: DataLoader):
        """Compute Fisher Information Matrix"""
        self.model.eval()
        fisher = {}
        
        # Initialize
        for name, param in self.model.named_parameters():
            fisher[name] = torch.zeros_like(param)
        
        # Accumulate gradients
        for batch_x, batch_y in dataloader:
            self.model.zero_grad()
            output = self.model(batch_x)
            loss = nn.functional.binary_cross_entropy(output, batch_y)
            loss.backward()
            
            for name, param in self.model.named_parameters():
                if param.grad is not None:
                    fisher[name] += param.grad.data ** 2
        
        # Average
        n = len(dataloader)
        for name in fisher:
            self.fisher_dict[name] = fisher[name] / n
        
        # Store optimal params
        for name, param in self.model.named_parameters():
            self.optimal_params[name] = param.data.clone()
    
    def compute_loss(self, model: nn.Module) -> torch.Tensor:
        """Compute EWC regularization loss"""
        if not self.fisher_dict:
            return torch.tensor(0.0)
        
        loss = 0
        for name, param in model.named_parameters():
            if name in self.fisher_dict:
                loss += (self.fisher_dict[name] * (param - self.optimal_params[name]) ** 2).sum()
        
        return self.lambda_ewc * loss


class OnlineLearner:
    """
    Continual learning for market prediction.
    Adapts to new data while preserving knowledge of past regimes.
    """
    
    def __init__(self, model: nn.Module, learning_rate: float = 1e-4):
        self.model = model
        self.optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=0.01)
        self.ewc = EWCRegularizer(model)
        
        # Experience replay buffer
        self.replay_buffer: deque = deque(maxlen=10000)
        self.batch_size = 32
        
        # Learning rate scheduler
        self.scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer, mode='max', factor=0.5, patience=10
        )
        
        # Metrics
        self.train_losses = []
        self.validation_accuracies = []
    
    def train_step(self, 
                   new_data: Tuple[np.ndarray, np.ndarray],
                   validation_data: Optional[Tuple[np.ndarray, np.ndarray]] = None) -> float:
        """
        Single online training step with EWC and replay.
        
        Args:
            new_data: (features, labels) from latest batch
            validation_data: Optional validation set for EWC update
        """
        # Add to replay buffer
        X_new, y_new = new_data
        for i in range(len(X_new)):
            self.replay_buffer.append((X_new[i], y_new[i]))
        
        # Sample from replay buffer (experience replay)
        if len(self.replay_buffer) >= self.batch_size:
            indices = np.random.choice(len(self.replay_buffer), self.batch_size, replace=False)
            batch = [self.replay_buffer[i] for i in indices]
            
            X_batch = torch.FloatTensor(np.stack([x for x, y in batch]))
            y_batch = torch.FloatTensor(np.stack([y for x, y in batch]))
        else:
            X_batch = torch.FloatTensor(X_new)
            y_batch = torch.FloatTensor(y_new)
        
        # Training
        self.model.train()
        self.optimizer.zero_grad()
        
        # Forward
        predictions = self.model(X_batch)
        
        # Task loss
        task_loss = nn.functional.binary_cross_entropy(predictions, y_batch)
        
        # EWC regularization (prevent forgetting)
        ewc_loss = self.ewc.compute_loss(self.model)
        
        # Total loss
        total_loss = task_loss + ewc_loss
        
        # Backward
        total_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
        self.optimizer.step()
        
        # Update EWC periodically
        if validation_data and len(self.train_losses) % 100 == 0:
            val_loader = DataLoader(
                TensorDataset(
                    torch.FloatTensor(validation_data[0]),
                    torch.FloatTensor(validation_data[1])
                ),
                batch_size=self.batch_size
            )
            self.ewc.update_fisher(val_loader)
        
        self.train_losses.append(total_loss.item())
        
        return total_loss.item()
    
    def adapt_to_regime(self, regime: str, regime_data: Dict[str, np.ndarray]):
        """
        Fast adaptation to detected market regime.
        Uses regime-specific learning rate and EWC weight.
        """
        # Adjust learning rate based on regime volatility
        if regime == 'volatile':
            for param_group in self.optimizer.param_groups:
                param_group['lr'] *= 1.5  # Faster adaptation
            self.ewc.lambda_ewc = 500  # Less regularization (more plasticity)
        elif regime == 'ranging':
            for param_group in self.optimizer.param_groups:
                param_group['lr'] *= 0.8  # Slower, more stable
            self.ewc.lambda_ewc = 2000  # More regularization
    
    def get_learning_diagnostics(self) -> Dict:
        """Get diagnostics about learning process"""
        return {
            'train_loss_trend': np.polyfit(range(len(self.train_losses)), self.train_losses, 1)[0] if len(self.train_losses) > 10 else 0,
            'buffer_size': len(self.replay_buffer),
            'ewc_lambda': self.ewc.lambda_ewc,
            'current_lr': self.optimizer.param_groups[0]['lr']
        }


class EnsemblePredictor:
    """
    Ensemble of models with different architectures.
    Provides robust predictions via model diversity.
    """
    
    def __init__(self, models: List[nn.Module], weights: Optional[List[float]] = None):
        self.models = models
        self.weights = weights or [1.0 / len(models)] * len(models)
        self.performance_history: Dict[int, List[float]] = {i: [] for i in range(len(models))}
    
    def predict(self, X: np.ndarray) -> Tuple[float, float]:
        """
        Ensemble prediction with uncertainty estimation.
        
        Returns:
            (mean_prediction, uncertainty)
        """
        X_tensor = torch.FloatTensor(X)
        
        predictions = []
        with torch.no_grad():
            for model in self.models:
                model.eval()
                pred = model(X_tensor)
                predictions.append(pred.numpy())
        
        # Weighted average
        predictions = np.array(predictions)
        weighted_pred = np.average(predictions, axis=0, weights=self.weights)
        
        # Uncertainty = variance across models
        uncertainty = np.var(predictions, axis=0)
        
        return float(weighted_pred.mean()), float(uncertainty.mean())
    
    def update_weights(self, recent_performance: Dict[int, float]):
        """
        Update ensemble weights based on recent performance.
        Poor performers get reduced weight.
        """
        # Softmax weighting based on performance
        exp_perf = np.exp([recent_performance.get(i, 0) for i in range(len(self.models))])
        self.weights = (exp_perf / exp_perf.sum()).tolist()
    
    def add_model(self, model: nn.Module, initial_weight: float = 0.1):
        """Add new model to ensemble (for continual expansion)"""
        self.models.append(model)
        # Redistribute weights
        total = sum(self.weights) + initial_weight
        self.weights = [w * (1 - initial_weight / total) for w in self.weights] + [initial_weight / total]
