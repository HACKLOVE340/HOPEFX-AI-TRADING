"""
HOPEFX Machine Learning Pipeline
LSTM, XGBoost, Random Forest with model saving/loading, hyperparameter tuning, evaluation
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Union
from pathlib import Path
import json
import pickle
import joblib
import warnings
warnings.filterwarnings('ignore')

# sklearn imports
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV, TimeSeriesSplit
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    mean_squared_error, mean_absolute_error, r2_score,
    classification_report, confusion_matrix
)

# XGBoost
try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

# TensorFlow/Keras
try:
    import tensorflow as tf
    from tensorflow.keras.models import Sequential, load_model, save_model
    from tensorflow.keras.layers import LSTM, Dense, Dropout, GRU, Bidirectional
    from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint, ReduceLROnPlateau
    from tensorflow.keras.optimizers import Adam
    TENSORFLOW_AVAILABLE = True
except ImportError:
    TENSORFLOW_AVAILABLE = False


class FeatureEngineer:
    """Create features for ML models from OHLCV data"""
    
    def __init__(self, include_indicators: bool = True, include_lags: bool = True):
        self.include_indicators = include_indicators
        self.include_lags = include_lags
        self.scaler = StandardScaler()
        self.feature_names: List[str] = []
    
    def create_features(
        self,
        df: pd.DataFrame,
        target_col: str = 'close',
        prediction_horizon: int = 1,
        lookback_window: int = 20
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Create feature matrix and target vector
        
        Returns:
            X: Feature DataFrame
            y: Target Series (returns direction for classification, returns for regression)
        """
        data = df.copy()
        
        # Price-based features
        data['returns'] = data[target_col].pct_change()
        data['log_returns'] = np.log(data[target_col] / data[target_col].shift(1))
        
        # Lag features
        if self.include_lags:
            for lag in range(1, lookback_window + 1):
                data[f'{target_col}_lag_{lag}'] = data[target_col].shift(lag)
                data[f'returns_lag_{lag}'] = data['returns'].shift(lag)
        
        # Technical indicators
        if self.include_indicators:
            # Moving averages
            for window in [5, 10, 20, 50]:
                data[f'sma_{window}'] = data[target_col].rolling(window=window).mean()
                data[f'ema_{window}'] = data[target_col].ewm(span=window, adjust=False).mean()
                data[f'dist_sma_{window}'] = (data[target_col] - data[f'sma_{window}']) / data[f'sma_{window}']
            
            # Volatility
            data['atr_14'] = self._calculate_atr(data, 14)
            data['volatility_20'] = data['returns'].rolling(window=20).std()
            
            # RSI
            data['rsi_14'] = self._calculate_rsi(data[target_col], 14)
            
            # MACD
            ema_fast = data[target_col].ewm(span=12, adjust=False).mean()
            ema_slow = data[target_col].ewm(span=26, adjust=False).mean()
            data['macd'] = ema_fast - ema_slow
            data['macd_signal'] = data['macd'].ewm(span=9, adjust=False).mean()
            data['macd_hist'] = data['macd'] - data['macd_signal']
            
            # Bollinger Bands
            sma_20 = data[target_col].rolling(window=20).mean()
            std_20 = data[target_col].rolling(window=20).std()
            data['bb_upper'] = sma_20 + (std_20 * 2)
            data['bb_lower'] = sma_20 - (std_20 * 2)
            data['bb_position'] = (data[target_col] - data['bb_lower']) / (data['bb_upper'] - data['bb_lower'])
            
            # Volume features
            if 'volume' in data.columns:
                data['volume_sma_20'] = data['volume'].rolling(window=20).mean()
                data['volume_ratio'] = data['volume'] / data['volume_sma_20']
                data['obv'] = self._calculate_obv(data)
        
        # Target variable - future returns
        future_returns = data[target_col].pct_change(prediction_horizon).shift(-prediction_horizon)
        
        # Classification target: 1 if price goes up, 0 if down
        data['target_class'] = (future_returns > 0).astype(int)
        
        # Regression target: actual returns
        data['target_reg'] = future_returns
        
        # Drop NaN values
        data = data.dropna()
        
        # Select feature columns (exclude target and non-feature columns)
        exclude_cols = ['target_class', 'target_reg', 'open', 'high', 'low', 'close', 'volume']
        feature_cols = [col for col in data.columns if col not in exclude_cols]
        
        self.feature_names = feature_cols
        
        X = data[feature_cols]
        y_class = data['target_class']
        y_reg = data['target_reg']
        
        return X, y_class, y_reg, data
    
    def scale_features(self, X_train: pd.DataFrame, X_test: Optional[pd.DataFrame] = None) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Scale features using StandardScaler"""
        X_train_scaled = self.scaler.fit_transform(X_train)
        
        if X_test is not None:
            X_test_scaled = self.scaler.transform(X_test)
            return X_train_scaled, X_test_scaled
        
        return X_train_scaled, None
    
    def save_scaler(self, filepath: str):
        """Save fitted scaler"""
        joblib.dump(self.scaler, filepath)
    
    def load_scaler(self, filepath: str):
        """Load fitted scaler"""
        self.scaler = joblib.load(filepath)
    
    @staticmethod
    def _calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    @staticmethod
    def _calculate_atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range"""
        high = data['high']
        low = data['low']
        close = data['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/period, adjust=False).mean()
        return atr
    
    @staticmethod
    def _calculate_obv(data: pd.DataFrame) -> pd.Series:
        """Calculate On Balance Volume"""
        obv = pd.Series(index=data.index, dtype=float)
        obv.iloc[0] = data['volume'].iloc[0]
        
        for i in range(1, len(data)):
            if data['close'].iloc[i] > data['close'].iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] + data['volume'].iloc[i]
            elif data['close'].iloc[i] < data['close'].iloc[i-1]:
                obv.iloc[i] = obv.iloc[i-1] - data['volume'].iloc[i]
            else:
                obv.iloc[i] = obv.iloc[i-1]
        
        return obv


class LSTMModel:
    """LSTM model for time series prediction"""
    
    def __init__(
        self,
        sequence_length: int = 60,
        n_features: int = 10,
        lstm_units: List[int] = [64, 32],
        dropout_rate: float = 0.2,
        learning_rate: float = 0.001,
        model_name: str = "lstm_model"
    ):
        if not TENSORFLOW_AVAILABLE:
            raise ImportError("TensorFlow not installed. Run: pip install tensorflow")
        
        self.sequence_length = sequence_length
        self.n_features = n_features
        self.lstm_units = lstm_units
        self.dropout_rate = dropout_rate
        self.learning_rate = learning_rate
        self.model_name = model_name
        
        self.model: Optional[Any] = None  # tf.keras.Model when TF available
        self.history: Optional[Any] = None
        self.scaler = MinMaxScaler(feature_range=(0, 1))
    
    def build_model(self) -> Any:
        """Build LSTM architecture"""
        model = Sequential()
        
        # First LSTM layer
        model.add(LSTM(
            self.lstm_units[0],
            return_sequences=len(self.lstm_units) > 1,
            input_shape=(self.sequence_length, self.n_features)
        ))
        model.add(Dropout(self.dropout_rate))
        
        # Additional LSTM layers
        for i, units in enumerate(self.lstm_units[1:], 1):
            return_sequences = i < len(self.lstm_units) - 1
            model.add(LSTM(units, return_sequences=return_sequences))
            model.add(Dropout(self.dropout_rate))
        
        # Output layer
        model.add(Dense(16, activation='relu'))
        model.add(Dense(1))
        
        # Compile
        optimizer = Adam(learning_rate=self.learning_rate)
        model.compile(optimizer=optimizer, loss='mean_squared_error', metrics=['mae'])
        
        self.model = model
        return model
    
    def prepare_sequences(
        self,
        data: np.ndarray,
        target: Optional[np.ndarray] = None
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Create sequences for LSTM input"""
        X, y = [], []
        
        for i in range(len(data) - self.sequence_length):
            X.append(data[i:(i + self.sequence_length)])
            if target is not None:
                y.append(target[i + self.sequence_length])
        
        X = np.array(X)
        y = np.array(y) if target is not None else None
        
        return X, y
    
    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        epochs: int = 100,
        batch_size: int = 32,
        patience: int = 15,
        model_dir: str = "ml/checkpoints"
    ) -> Dict:
        """Train LSTM model"""
        
        if self.model is None:
            self.n_features = X_train.shape[2]
            self.build_model()
        
        # Callbacks
        Path(model_dir).mkdir(parents=True, exist_ok=True)
        checkpoint_path = f"{model_dir}/{self.model_name}_best.h5"
        
        callbacks = [
            EarlyStopping(
                monitor='val_loss' if X_val is not None else 'loss',
                patience=patience,
                restore_best_weights=True,
                verbose=1
            ),
            ModelCheckpoint(
                checkpoint_path,
                monitor='val_loss' if X_val is not None else 'loss',
                save_best_only=True,
                verbose=1
            ),
            ReduceLROnPlateau(
                monitor='val_loss' if X_val is not None else 'loss',
                factor=0.5,
                patience=patience // 2,
                verbose=1
            )
        ]
        
        # Train
        validation_data = (X_val, y_val) if X_val is not None else None
        
        self.history = self.model.fit(
            X_train, y_train,
            epochs=epochs,
            batch_size=batch_size,
            validation_data=validation_data,
            callbacks=callbacks,
            verbose=1
        )
        
        return {
            'epochs_trained': len(self.history.history['loss']),
            'final_loss': self.history.history['loss'][-1],
            'final_val_loss': self.history.history.get('val_loss', [None])[-1],
            'checkpoint_path': checkpoint_path
        }
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make predictions"""
        if self.model is None:
            raise ValueError("Model not trained. Call fit() or load_model() first.")
        return self.model.predict(X, verbose=0)
    
    def save(self, filepath: str):
        """Save model to disk"""
        if self.model is None:
            raise ValueError("No model to save")
        
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        # Save Keras model
        if filepath.endswith('.h5') or filepath.endswith('.keras'):
            self.model.save(filepath)
        else:
            self.model.save(filepath + '.h5')
            filepath = filepath + '.h5'
        
        # Save config
        config = {
            'sequence_length': self.sequence_length,
            'n_features': self.n_features,
            'lstm_units': self.lstm_units,
            'dropout_rate': self.dropout_rate,
            'learning_rate': self.learning_rate,
            'model_name': self.model_name
        }
        
        config_path = filepath.replace('.h5', '_config.json').replace('.keras', '_config.json')
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"LSTM model saved: {filepath}")
        return filepath
    
    def load(self, filepath: str):
        """Load model from disk"""
        self.model = load_model(filepath)
        
        # Load config if exists
        config_path = filepath.replace('.h5', '_config.json').replace('.keras', '_config.json')
        if Path(config_path).exists():
            with open(config_path, 'r') as f:
                config = json.load(f)
                self.sequence_length = config.get('sequence_length', self.sequence_length)
                self.n_features = config.get('n_features', self.n_features)
                self.lstm_units = config.get('lstm_units', self.lstm_units)
        
        print(f"LSTM model loaded: {filepath}")
    
    def evaluate(self, X_test: np.ndarray, y_test: np.ndarray) -> Dict[str, float]:
        """Evaluate model performance"""
        predictions = self.predict(X_test)
        
        mse = mean_squared_error(y_test, predictions)
        rmse = np.sqrt(mse)
        mae = mean_absolute_error(y_test, predictions)
        r2 = r2_score(y_test, predictions)
        
        return {
            'mse': mse,
            'rmse': rmse,
            'mae': mae,
            'r2': r2,
            'mape': np.mean(np.abs((y_test - predictions.flatten()) / y_test)) * 100
        }


class XGBoostModel:
    """XGBoost model for trading signal prediction"""
    
    def __init__(
        self,
        model_type: str = 'classifier',  # 'classifier' or 'regressor'
        params: Optional[Dict] = None,
        model_name: str = "xgboost_model"
    ):
        if not XGBOOST_AVAILABLE:
            raise ImportError("XGBoost not installed. Run: pip install xgboost")
        
        self.model_type = model_type
        self.model_name = model_name
        self.params = params or self._default_params()
        self.model: Optional[Any] = None
        self.feature_importance: Optional[pd.DataFrame] = None
    
    def _default_params(self) -> Dict:
        """Default XGBoost parameters"""
        if self.model_type == 'classifier':
            return {
                'objective': 'binary:logistic',
                'eval_metric': ['logloss', 'auc'],
                'max_depth': 6,
                'learning_rate': 0.1,
                'n_estimators': 100,
                'subsample': 0.8,
                'colsample_bytree': 0.8,
                'random_state': 42,
                'use_label_encoder': False
            }
        else:
            return {
                'objective': 'reg:squarederror',
                'eval_metric': 'rmse',
                'max_depth': 6,
                'learning_rate': 0.1,
                'n_estimators': 100,
                'subsample': 0.8,
                'colsample_bytree': 0.8,
                'random_state': 42
            }
    
    def build_model(self):
        """Build XGBoost model"""
        if self.model_type == 'classifier':
            self.model = xgb.XGBClassifier(**self.params)
        else:
            self.model = xgb.XGBRegressor(**self.params)
        return self.model
    
    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        early_stopping_rounds: int = 10
    ) -> Dict:
        """Train XGBoost model"""
        
        if self.model is None:
            self.build_model()
        
        eval_set = [(X_train, y_train)]
        if X_val is not None and y_val is not None:
            eval_set.append((X_val, y_val))
        
        self.model.fit(
            X_train, y_train,
            eval_set=eval_set,
            early_stopping_rounds=early_stopping_rounds if len(eval_set) > 1 else None,
            verbose=False
        )
        
        # Feature importance
        if hasattr(self.model, 'feature_importances_'):
            self.feature_importance = pd.DataFrame({
                'feature': range(len(self.model.feature_importances_)),
                'importance': self.model.feature_importances_
            }).sort_values('importance', ascending=False)
        
        return {
            'best_iteration': self.model.best_iteration if hasattr(self.model, 'best_iteration') else self.params['n_estimators'],
            'best_score': self.model.best_score if hasattr(self.model, 'best_score') else None
        }
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make predictions"""
        if self.model is None:
            raise ValueError("Model not trained. Call fit() or load_model() first.")
        return self.model.predict(X)
    
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Make probability predictions (classification only)"""
        if self.model is None:
            raise ValueError("Model not trained")
        if self.model_type != 'classifier':
            raise ValueError("predict_proba only available for classifiers")
        return self.model.predict_proba(X)
    
    def save(self, filepath: str):
        """Save model to disk"""
        if self.model is None:
            raise ValueError("No model to save")
        
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        # Save model
        if filepath.endswith('.json'):
            self.model.save_model(filepath)
        elif filepath.endswith('.pkl'):
            joblib.dump(self.model, filepath)
        else:
            filepath = filepath + '.json'
            self.model.save_model(filepath)
        
        # Save config
        config = {
            'model_type': self.model_type,
            'params': self.params,
            'model_name': self.model_name
        }
        
        config_path = filepath.replace('.json', '_config.json').replace('.pkl', '_config.json')
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        # Save feature importance if available
        if self.feature_importance is not None:
            importance_path = filepath.replace('.json', '_importance.csv').replace('.pkl', '_importance.csv')
            self.feature_importance.to_csv(importance_path, index=False)
        
        print(f"XGBoost model saved: {filepath}")
        return filepath
    
    def load(self, filepath: str):
        """Load model from disk"""
        if filepath.endswith('.json'):
            if self.model is None:
                self.build_model()
            self.model.load_model(filepath)
        else:
            self.model = joblib.load(filepath)
        
        print(f"XGBoost model loaded: {filepath}")
    
    def evaluate(self, X_test: np.ndarray, y_test: np.ndarray) -> Dict[str, float]:
        """Evaluate model performance"""
        predictions = self.predict(X_test)
        
        if self.model_type == 'classifier':
            # Classification metrics
            accuracy = accuracy_score(y_test, predictions)
            precision = precision_score(y_test, predictions, zero_division=0)
            recall = recall_score(y_test, predictions, zero_division=0)
            f1 = f1_score(y_test, predictions, zero_division=0)
            
            # Confusion matrix
            cm = confusion_matrix(y_test, predictions)
            
            return {
                'accuracy': accuracy,
                'precision': precision,
                'recall': recall,
                'f1': f1,
                'confusion_matrix': cm.tolist()
            }
        else:
            # Regression metrics
            mse = mean_squared_error(y_test, predictions)
            rmse = np.sqrt(mse)
            mae = mean_absolute_error(y_test, predictions)
            r2 = r2_score(y_test, predictions)
            
            return {
                'mse': mse,
                'rmse': rmse,
                'mae': mae,
                'r2': r2
            }


class RandomForestModel:
    """Random Forest model for trading signal prediction"""
    
    def __init__(
        self,
        model_type: str = 'classifier',
        n_estimators: int = 100,
        max_depth: Optional[int] = None,
        min_samples_split: int = 2,
        random_state: int = 42,
        model_name: str = "random_forest_model"
    ):
        self.model_type = model_type
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_split = min_samples_split
        self.random_state = random_state
        self.model_name = model_name
        
        self.model: Optional[Any] = None
        self.feature_importance: Optional[pd.DataFrame] = None
    
    def build_model(self):
        """Build Random Forest model"""
        if self.model_type == 'classifier':
            self.model = RandomForestClassifier(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                min_samples_split=self.min_samples_split,
                random_state=self.random_state,
                n_jobs=-1
            )
        else:
            self.model = RandomForestRegressor(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                min_samples_split=self.min_samples_split,
                random_state=self.random_state,
                n_jobs=-1
            )
        return self.model
    
    def fit(self, X_train: np.ndarray, y_train: np.ndarray) -> Dict:
        """Train Random Forest model"""
        
        if self.model is None:
            self.build_model()
        
        self.model.fit(X_train, y_train)
        
        # Feature importance
        if hasattr(self.model, 'feature_importances_'):
            self.feature_importance = pd.DataFrame({
                'feature': range(len(self.model.feature_importances_)),
                'importance': self.model.feature_importances_
            }).sort_values('importance', ascending=False)
        
        return {
            'n_estimators': self.n_estimators,
            'feature_importances': self.model.feature_importances_.tolist()
        }
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make predictions"""
        if self.model is None:
            raise ValueError("Model not trained. Call fit() or load_model() first.")
        return self.model.predict(X)
    
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Make probability predictions (classification only)"""
        if self.model is None:
            raise ValueError("Model not trained")
        if self.model_type != 'classifier':
            raise ValueError("predict_proba only available for classifiers")
        return self.model.predict_proba(X)
    
    def save(self, filepath: str):
        """Save model to disk"""
        if self.model is None:
            raise ValueError("No model to save")
        
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        # Save model using joblib
        if not filepath.endswith('.pkl'):
            filepath = filepath + '.pkl'
        
        joblib.dump(self.model, filepath)
        
        # Save config
        config = {
            'model_type': self.model_type,
            'n_estimators': self.n_estimators,
            'max_depth': self.max_depth,
            'min_samples_split': self.min_samples_split,
            'model_name': self.model_name
        }
        
        config_path = filepath.replace('.pkl', '_config.json')
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        # Save feature importance
        if self.feature_importance is not None:
            importance_path = filepath.replace('.pkl', '_importance.csv')
            self.feature_importance.to_csv(importance_path, index=False)
        
        print(f"Random Forest model saved: {filepath}")
        return filepath
    
    def load(self, filepath: str):
        """Load model from disk"""
        self.model = joblib.load(filepath)
        
        print(f"Random Forest model loaded: {filepath}")
    
    def evaluate(self, X_test: np.ndarray, y_test: np.ndarray) -> Dict[str, float]:
        """Evaluate model performance"""
        predictions = self.predict(X_test)
        
        if self.model_type == 'classifier':
            accuracy = accuracy_score(y_test, predictions)
            precision = precision_score(y_test, predictions, zero_division=0)
            recall = recall_score(y_test, predictions, zero_division=0)
            f1 = f1_score(y_test, predictions, zero_division=0)
            
            cm = confusion_matrix(y_test, predictions)
            
            return {
                'accuracy': accuracy,
                'precision': precision,
                'recall': recall,
                'f1': f1,
                'confusion_matrix': cm.tolist()
            }
        else:
            mse = mean_squared_error(y_test, predictions)
            rmse = np.sqrt(mse)
            mae = mean_absolute_error(y_test, predictions)
            r2 = r2_score(y_test, predictions)
            
            return {
                'mse': mse,
                'rmse': rmse,
                'mae': mae,
                'r2': r2
            }


class EnsembleModel:
    """Ensemble of LSTM, XGBoost, and Random Forest"""
    
    def __init__(
        self,
        models: Optional[Dict[str, Any]] = None,
        weights: Optional[List[float]] = None,
        voting: str = 'soft'  # 'soft' or 'hard'
    ):
        self.models = models or {}
        self.weights = weights or [1/3, 1/3, 1/3]
        self.voting = voting
    
    def add_model(self, name: str, model: Any):
        """Add a model to ensemble"""
        self.models[name] = model
    
    def predict(self, X_dict: Dict[str, np.ndarray]) -> np.ndarray:
        """
        Make ensemble predictions
        
        Args:
            X_dict: Dictionary with model inputs {'lstm': X_lstm, 'xgboost': X_xgb, 'rf': X_rf}
        """
        predictions = []
        
        for name, model in self.models.items():
            if name in X_dict:
                pred = model.predict(X_dict[name])
                predictions.append(pred)
        
        # Weighted average
        if len(predictions) > 0:
            # Normalize weights
            weights = np.array(self.weights[:len(predictions)])
            weights = weights / weights.sum()
            
            # Weighted prediction
            ensemble_pred = np.average(predictions, axis=0, weights=weights)
            return ensemble_pred
        
        return np.array([])
    
    def save(self, base_dir: str = "ml/models"):
        """Save all ensemble models"""
        Path(base_dir).mkdir(parents=True, exist_ok=True)
        
        saved_paths = {}
        for name, model in self.models.items():
            filepath = f"{base_dir}/ensemble_{name}"
            if hasattr(model, 'save'):
                saved_path = model.save(filepath)
                saved_paths[name] = saved_path
        
        # Save ensemble config
        config = {
            'weights': self.weights,
            'voting': self.voting,
            'models': list(self.models.keys())
        }
        
        with open(f"{base_dir}/ensemble_config.json", 'w') as f:
            json.dump(config, f, indent=2)
        
        return saved_paths


class HyperparameterTuner:
    """Hyperparameter tuning for ML models"""
    
    def __init__(self, model_type: str = 'xgboost'):
        self.model_type = model_type
        self.best_params: Optional[Dict] = None
        self.cv_results: Optional[pd.DataFrame] = None
    
    def tune_xgboost(
        self,
        X: np.ndarray,
        y: np.ndarray,
        param_grid: Optional[Dict] = None,
        cv: int = 3,
        scoring: str = 'f1'
    ) -> Dict:
        """Grid search for XGBoost"""
        
        if not XGBOOST_AVAILABLE:
            raise ImportError("XGBoost not installed")
        
        if param_grid is None:
            param_grid = {
                'max_depth': [3, 5, 7],
                'learning_rate': [0.01, 0.1, 0.3],
                'n_estimators': [50, 100, 200],
                'subsample': [0.8, 1.0],
                'colsample_bytree': [0.8, 1.0]
            }
        
        # Time series cross-validation
        tscv = TimeSeriesSplit(n_splits=cv)
        
        model = xgb.XGBClassifier(
            objective='binary:logistic',
            eval_metric='logloss',
            use_label_encoder=False,
            random_state=42
        )
        
        grid_search = GridSearchCV(
            model,
            param_grid,
            cv=tscv,
            scoring=scoring,
            n_jobs=-1,
            verbose=1
        )
        
        grid_search.fit(X, y)
        
        self.best_params = grid_search.best_params_
        self.cv_results = pd.DataFrame(grid_search.cv_results_)
        
        return {
            'best_params': grid_search.best_params_,
            'best_score': grid_search.best_score_,
            'cv_results': self.cv_results
        }
    
    def tune_random_forest(
        self,
        X: np.ndarray,
        y: np.ndarray,
        param_grid: Optional[Dict] = None,
        cv: int = 3,
        scoring: str = 'f1',
        n_iter: int = 20
    ) -> Dict:
        """Random search for Random Forest"""
        
        if param_grid is None:
            param_grid = {
                'n_estimators': [50, 100, 200, 500],
                'max_depth': [5, 10, 20, None],
                'min_samples_split': [2, 5, 10],
                'min_samples_leaf': [1, 2, 4]
            }
        
        tscv = TimeSeriesSplit(n_splits=cv)
        
        model = RandomForestClassifier(random_state=42)
        
        random_search = RandomizedSearchCV(
            model,
            param_grid,
            n_iter=n_iter,
            cv=tscv,
            scoring=scoring,
            n_jobs=-1,
            verbose=1,
            random_state=42
        )
        
        random_search.fit(X, y)
        
        self.best_params = random_search.best_params_
        self.cv_results = pd.DataFrame(random_search.cv_results_)
        
        return {
            'best_params': random_search.best_params_,
            'best_score': random_search.best_score_,
            'cv_results': self.cv_results
        }
    
    def save_results(self, output_dir: str = "ml/training"):
        """Save tuning results"""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Save best params
        with open(f"{output_dir}/best_params_{self.model_type}.json", 'w') as f:
            json.dump(self.best_params, f, indent=2)
        
        # Save CV results
        if self.cv_results is not None:
            self.cv_results.to_csv(f"{output_dir}/cv_results_{self.model_type}.csv", index=False)
        
        print(f"Tuning results saved to {output_dir}/")


class MLEvaluationReport:
    """Generate evaluation reports for ML models"""
    
    def __init__(self, output_dir: str = "ml/evaluation"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_report(
        self,
        model_name: str,
        metrics: Dict[str, Any],
        y_true: np.ndarray,
        y_pred: np.ndarray,
        feature_importance: Optional[pd.DataFrame] = None
    ) -> str:
        """Generate comprehensive evaluation report"""
        
        report_time = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_path = self.output_dir / f"{model_name}_evaluation_{report_time}.json"
        
        report = {
            'model_name': model_name,
            'timestamp': datetime.now().isoformat(),
            'metrics': metrics,
            'predictions_sample': {
                'y_true': y_true[:20].tolist(),
                'y_pred': y_pred[:20].tolist()
            }
        }
        
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        # Save feature importance
        if feature_importance is not None:
            importance_path = self.output_dir / f"{model_name}_feature_importance_{report_time}.csv"
            feature_importance.to_csv(importance_path, index=False)
        
        # Save predictions
        pred_df = pd.DataFrame({
            'y_true': y_true,
            'y_pred': y_pred
        })
        pred_path = self.output_dir / f"{model_name}_predictions_{report_time}.csv"
        pred_df.to_csv(pred_path, index=False)
        
        print(f"Evaluation report saved: {report_path}")
        return str(report_path)
    
    def plot_confusion_matrix(self, cm: np.ndarray, model_name: str, save: bool = True):
        """Plot confusion matrix"""
        import matplotlib.pyplot as plt
        import seaborn as sns
        
        plt.figure(figsize=(8, 6))
        sns.heatmap(cm, annot=True, fmt='d', cmap='Blues')
        plt.title(f'Confusion Matrix - {model_name}')
        plt.ylabel('True Label')
        plt.xlabel('Predicted Label')
        
        if save:
            plot_path = self.output_dir / f"{model_name}_confusion_matrix.png"
            plt.savefig(plot_path, dpi=300, bbox_inches='tight')
            print(f"Confusion matrix saved: {plot_path}")
        
        plt.show()
    
    def plot_feature_importance(self, importance_df: pd.DataFrame, model_name: str, top_n: int = 20, save: bool = True):
        """Plot feature importance"""
        import matplotlib.pyplot as plt
        
        plt.figure(figsize=(10, 8))
        top_features = importance_df.head(top_n)
        plt.barh(range(len(top_features)), top_features['importance'])
        plt.yticks(range(len(top_features)), [f'Feature {i}' for i in top_features['feature']])
        plt.xlabel('Importance')
        plt.title(f'Top {top_n} Feature Importance - {model_name}')
        plt.gca().invert_yaxis()
        
        if save:
            plot_path = self.output_dir / f"{model_name}_feature_importance.png"
            plt.savefig(plot_path, dpi=300, bbox_inches='tight')
            print(f"Feature importance plot saved: {plot_path}")
        
        plt.show()


# Convenience function for full ML pipeline
def train_ml_pipeline(
    df: pd.DataFrame,
    model_types: List[str] = ['lstm', 'xgboost', 'random_forest'],
    prediction_horizon: int = 1,
    test_size: float = 0.2,
    model_dir: str = "ml/models"
) -> Dict[str, Any]:
    """
    Complete ML training pipeline
    
    Args:
        df: DataFrame with OHLCV data
        model_types: List of models to train
        prediction_horizon: Days ahead to predict
        test_size: Fraction of data for testing
        model_dir: Directory to save models
    
    Returns:
        Dictionary with trained models and evaluation metrics
    """
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    
    results = {}
    
    # Feature engineering
    print("Creating features...")
    fe = FeatureEngineer()
    X, y_class, y_reg, full_data = fe.create_features(df, prediction_horizon=prediction_horizon)
    
    # Train/test split (time series aware)
    split_idx = int(len(X) * (1 - test_size))
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train_class, y_test_class = y_class.iloc[:split_idx], y_class.iloc[split_idx:]
    y_train_reg, y_test_reg = y_reg.iloc[:split_idx], y_reg.iloc[split_idx:]
    
    # Scale features
    X_train_scaled, X_test_scaled = fe.scale_features(X_train, X_test)
    
    evaluator = MLEvaluationReport()
    
    # Train LSTM
    if 'lstm' in model_types and TENSORFLOW_AVAILABLE:
        print("\nTraining LSTM...")
        
        # Prepare sequences
        lstm_model = LSTMModel(sequence_length=60, n_features=X_train_scaled.shape[1])
        X_lstm_train, y_lstm_train = lstm_model.prepare_sequences(X_train_scaled, y_train_reg.values)
        X_lstm_test, y_lstm_test = lstm_model.prepare_sequences(X_test_scaled, y_test_reg.values)
        
        # Build and train
        lstm_model.build_model()
        train_info = lstm_model.fit(
            X_lstm_train, y_lstm_train,
            X_lstm_test, y_lstm_test,
            epochs=50,
            model_dir=model_dir
        )
        
        # Evaluate
        metrics = lstm_model.evaluate(X_lstm_test, y_lstm_test)
        predictions = lstm_model.predict(X_lstm_test)
        
        # Save
        model_path = lstm_model.save(f"{model_dir}/lstm_model.h5")
        
        # Report
        report_path = evaluator.generate_report('LSTM', metrics, y_lstm_test, predictions.flatten())
        
        results['lstm'] = {
            'model': lstm_model,
            'metrics': metrics,
            'model_path': model_path,
            'report_path': report_path
        }
        
        print(f"LSTM RMSE: {metrics['rmse']:.4f}")
    
    # Train XGBoost
    if 'xgboost' in model_types and XGBOOST_AVAILABLE:
        print("\nTraining XGBoost...")
        
        xgb_model = XGBoostModel(model_type='classifier')
        train_info = xgb_model.fit(X_train_scaled, y_train_class.values, X_test_scaled, y_test_class.values)
        
        # Evaluate
        metrics = xgb_model.evaluate(X_test_scaled, y_test_class.values)
        predictions = xgb_model.predict(X_test_scaled)
        
        # Save
        model_path = xgb_model.save(f"{model_dir}/xgboost_model.json")
        
        # Report
        report_path = evaluator.generate_report(
            'XGBoost', metrics, y_test_class.values, predictions,
            feature_importance=xgb_model.feature_importance
        )
        
        if xgb_model.feature_importance is not None:
            evaluator.plot_feature_importance(xgb_model.feature_importance, 'XGBoost')
        
        results['xgboost'] = {
            'model': xgb_model,
            'metrics': metrics,
            'model_path': model_path,
            'report_path': report_path
        }
        
        print(f"XGBoost Accuracy: {metrics['accuracy']:.4f}, F1: {metrics['f1']:.4f}")
    
    # Train Random Forest
    if 'random_forest' in model_types:
        print("\nTraining Random Forest...")
        
        rf_model = RandomForestModel(model_type='classifier', n_estimators=100)
        train_info = rf_model.fit(X_train_scaled, y_train_class.values)
        
        # Evaluate
        metrics = rf_model.evaluate(X_test_scaled, y_test_class.values)
        predictions = rf_model.predict(X_test_scaled)
        
        # Save
        model_path = rf_model.save(f"{model_dir}/random_forest_model.pkl")
        
        # Report
        report_path = evaluator.generate_report(
            'RandomForest', metrics, y_test_class.values, predictions,
            feature_importance=rf_model.feature_importance
        )
        
        if rf_model.feature_importance is not None:
            evaluator.plot_feature_importance(rf_model.feature_importance, 'RandomForest')
        
        results['random_forest'] = {
            'model': rf_model,
            'metrics': metrics,
            'model_path': model_path,
            'report_path': report_path
        }
        
        print(f"Random Forest Accuracy: {metrics['accuracy']:.4f}, F1: {metrics['f1']:.4f}")
    
    # Save feature engineer
    fe.save_scaler(f"{model_dir}/feature_scaler.pkl")
    
    print(f"\nPipeline complete. Models saved to {model_dir}/")
    return results


if __name__ == "__main__":
    print("HOPEFX Machine Learning Pipeline")
    print("Models: LSTM, XGBoost, Random Forest")
    print("Features: Feature engineering, hyperparameter tuning, evaluation reports")
    print("\nUsage:")
    print("  from ml.training import train_ml_pipeline")
    print("  results = train_ml_pipeline(df, model_types=['lstm', 'xgboost', 'random_f'])")
