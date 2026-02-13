"""
Random Forest Classifier for Trading Signals

Random Forest ensemble model for classification of trading signals
(BUY, SELL, HOLD) based on technical indicators and market features.
"""

from typing import Dict, Any, Optional, List
import numpy as np
import pandas as pd
import logging

from .base import BaseMLModel

logger = logging.getLogger(__name__)


class RandomForestTradingClassifier(BaseMLModel):
    """
    Random Forest classifier for trading signal prediction.
    
    Features:
    - Ensemble learning for robust predictions
    - Feature importance analysis
    - Class probability outputs
    - Handles imbalanced data
    """
    
    def __init__(self, name: str = "RF_Classifier", config: Optional[Dict] = None):
        """
        Initialize Random Forest classifier.
        
        Args:
            name: Model name
            config: Configuration dict with:
                - n_estimators: Number of trees (default: 100)
                - max_depth: Maximum tree depth (default: 10)
                - min_samples_split: Min samples to split (default: 5)
                - min_samples_leaf: Min samples per leaf (default: 2)
                - max_features: Max features per split (default: 'sqrt')
                - random_state: Random seed (default: 42)
                - class_weight: Handle imbalanced data (default: 'balanced')
        """
        super().__init__(name, config)
        
        # Model parameters
        self.n_estimators = self.config.get('n_estimators', 100)
        self.max_depth = self.config.get('max_depth', 10)
        self.min_samples_split = self.config.get('min_samples_split', 5)
        self.min_samples_leaf = self.config.get('min_samples_leaf', 2)
        self.max_features = self.config.get('max_features', 'sqrt')
        self.random_state = self.config.get('random_state', 42)
        self.class_weight = self.config.get('class_weight', 'balanced')
        
        # Feature names (for interpretation)
        self.feature_names: List[str] = []
        self.label_encoder = None
    
    def build(self) -> None:
        """Build Random Forest model."""
        try:
            from sklearn.ensemble import RandomForestClassifier
            
            self.model = RandomForestClassifier(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                min_samples_split=self.min_samples_split,
                min_samples_leaf=self.min_samples_leaf,
                max_features=self.max_features,
                random_state=self.random_state,
                class_weight=self.class_weight,
                n_jobs=-1  # Use all CPU cores
            )
            
            self.logger.info(
                f"Random Forest built with {self.n_estimators} trees, "
                f"max_depth={self.max_depth}"
            )
            
        except Exception as e:
            self.logger.error(f"Error building Random Forest: {e}")
            raise
    
    def train(self, X_train: np.ndarray, y_train: np.ndarray,
              X_val: Optional[np.ndarray] = None,
              y_val: Optional[np.ndarray] = None,
              feature_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Train Random Forest classifier.
        
        Args:
            X_train: Training features
            y_train: Training labels (0=SELL, 1=HOLD, 2=BUY or similar)
            X_val: Validation features (optional)
            y_val: Validation labels (optional)
            feature_names: Names of features for interpretation
            
        Returns:
            Training metrics
        """
        try:
            # Build model if not built
            if self.model is None:
                self.build()
            
            # Store feature names
            if feature_names:
                self.feature_names = feature_names
            elif hasattr(X_train, 'columns'):
                self.feature_names = list(X_train.columns)
            else:
                self.feature_names = [f"feature_{i}" for i in range(X_train.shape[1])]
            
            # Encode labels if they're strings
            if y_train.dtype == object:
                from sklearn.preprocessing import LabelEncoder
                self.label_encoder = LabelEncoder()
                y_train = self.label_encoder.fit_transform(y_train)
                if y_val is not None:
                    y_val = self.label_encoder.transform(y_val)
            
            # Train model
            self.model.fit(X_train, y_train)
            self.is_trained = True
            
            # Calculate training metrics
            train_pred = self.model.predict(X_train)
            train_accuracy = np.mean(train_pred == y_train)
            
            metrics = {
                'train_accuracy': float(train_accuracy),
                'train_samples': len(X_train),
                'n_features': X_train.shape[1],
                'n_classes': len(np.unique(y_train)),
            }
            
            # Validation metrics
            if X_val is not None and y_val is not None:
                val_pred = self.model.predict(X_val)
                val_accuracy = np.mean(val_pred == y_val)
                metrics['val_accuracy'] = float(val_accuracy)
                metrics['val_samples'] = len(X_val)
            
            # Feature importance
            feature_importance = self.get_feature_importance_dict()
            metrics['top_features'] = dict(
                sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)[:10]
            )
            
            # Store training history
            self.training_history.append({
                'timestamp': pd.Timestamp.now().isoformat(),
                'metrics': metrics,
            })
            
            self.logger.info(
                f"Random Forest training complete. "
                f"Train accuracy: {train_accuracy:.3f}"
            )
            
            return metrics
            
        except Exception as e:
            self.logger.error(f"Error training Random Forest: {e}")
            raise
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Predict trading signals.
        
        Args:
            X: Input features
            
        Returns:
            Predicted classes
        """
        if not self.is_trained:
            raise ValueError("Model not trained. Call train() first.")
        
        try:
            predictions = self.model.predict(X)
            
            # Decode labels if label encoder was used
            if self.label_encoder is not None:
                predictions = self.label_encoder.inverse_transform(predictions)
            
            return predictions
            
        except Exception as e:
            self.logger.error(f"Error making predictions: {e}")
            raise
    
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Predict class probabilities.
        
        Args:
            X: Input features
            
        Returns:
            Class probabilities [samples, classes]
        """
        if not self.is_trained:
            raise ValueError("Model not trained. Call train() first.")
        
        try:
            probabilities = self.model.predict_proba(X)
            return probabilities
            
        except Exception as e:
            self.logger.error(f"Error predicting probabilities: {e}")
            raise
    
    def predict_with_confidence(self, X: np.ndarray) -> tuple:
        """
        Predict with confidence scores.
        
        Args:
            X: Input features
            
        Returns:
            (predictions, confidence_scores)
        """
        predictions = self.predict(X)
        probabilities = self.predict_proba(X)
        
        # Confidence is the maximum probability for each prediction
        confidences = np.max(probabilities, axis=1)
        
        return predictions, confidences
    
    def get_feature_importance_dict(self) -> Dict[str, float]:
        """
        Get feature importance as dictionary.
        
        Returns:
            Dict mapping feature names to importance scores
        """
        if not self.is_trained:
            return {}
        
        importances = self.model.feature_importances_
        
        if self.feature_names:
            return dict(zip(self.feature_names, importances))
        else:
            return dict(enumerate(importances))
    
    def get_top_features(self, n: int = 10) -> List[tuple]:
        """
        Get top N most important features.
        
        Args:
            n: Number of top features to return
            
        Returns:
            List of (feature_name, importance) tuples
        """
        importance_dict = self.get_feature_importance_dict()
        sorted_features = sorted(
            importance_dict.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_features[:n]
    
    def evaluate_detailed(self, X_test: np.ndarray, y_test: np.ndarray) -> Dict[str, Any]:
        """
        Detailed evaluation with classification report.
        
        Args:
            X_test: Test features
            y_test: Test labels
            
        Returns:
            Detailed metrics including confusion matrix
        """
        from sklearn.metrics import (
            classification_report, confusion_matrix,
            accuracy_score, precision_recall_fscore_support
        )
        
        # Encode test labels if needed
        if self.label_encoder is not None and y_test.dtype == object:
            y_test_encoded = self.label_encoder.transform(y_test)
        else:
            y_test_encoded = y_test
        
        # Get predictions
        predictions = self.model.predict(X_test)
        
        # Calculate metrics
        accuracy = accuracy_score(y_test_encoded, predictions)
        precision, recall, f1, support = precision_recall_fscore_support(
            y_test_encoded, predictions, average='weighted'
        )
        
        # Confusion matrix
        cm = confusion_matrix(y_test_encoded, predictions)
        
        # Classification report
        if self.label_encoder is not None:
            target_names = self.label_encoder.classes_
        else:
            target_names = [str(i) for i in np.unique(y_test)]
        
        class_report = classification_report(
            y_test_encoded, predictions,
            target_names=target_names,
            output_dict=True
        )
        
        return {
            'accuracy': float(accuracy),
            'precision': float(precision),
            'recall': float(recall),
            'f1_score': float(f1),
            'confusion_matrix': cm.tolist(),
            'classification_report': class_report,
            'n_samples': len(X_test),
        }
    
    def optimize_hyperparameters(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        param_grid: Optional[Dict] = None,
        cv: int = 5
    ) -> Dict[str, Any]:
        """
        Optimize hyperparameters using GridSearchCV.
        
        Args:
            X_train: Training features
            y_train: Training labels
            param_grid: Parameter grid to search
            cv: Number of cross-validation folds
            
        Returns:
            Best parameters and scores
        """
        from sklearn.model_selection import GridSearchCV
        
        if param_grid is None:
            param_grid = {
                'n_estimators': [50, 100, 200],
                'max_depth': [5, 10, 15],
                'min_samples_split': [2, 5, 10],
                'min_samples_leaf': [1, 2, 4],
            }
        
        # Build base model
        self.build()
        
        # Grid search
        grid_search = GridSearchCV(
            self.model,
            param_grid,
            cv=cv,
            scoring='accuracy',
            n_jobs=-1,
            verbose=1
        )
        
        grid_search.fit(X_train, y_train)
        
        # Update model with best parameters
        self.model = grid_search.best_estimator_
        self.is_trained = True
        
        # Update config
        self.config.update(grid_search.best_params_)
        
        results = {
            'best_params': grid_search.best_params_,
            'best_score': float(grid_search.best_score_),
            'cv_results': {
                'mean_test_score': grid_search.cv_results_['mean_test_score'].tolist(),
                'std_test_score': grid_search.cv_results_['std_test_score'].tolist(),
            }
        }
        
        self.logger.info(f"Hyperparameter optimization complete. Best score: {results['best_score']:.3f}")
        
        return results
