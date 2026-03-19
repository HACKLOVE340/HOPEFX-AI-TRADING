# Trading Models

This module includes advanced ML models for trading, such as Random Forest, Gradient Boosting, and Ensemble methods.

## Random Forest

```python
from sklearn.ensemble import RandomForestClassifier

class RandomForestModel:
    def __init__(self, n_estimators=100):
        self.model = RandomForestClassifier(n_estimators=n_estimators)

    def train(self, X, y):
        self.model.fit(X, y)

    def predict(self, X):
        return self.model.predict(X)
        
from sklearn.ensemble import GradientBoostingClassifier

class GradientBoostingModel:
    def __init__(self, n_estimators=100):
        self.model = GradientBoostingClassifier(n_estimators=n_estimators)

    def train(self, X, y):
        self.model.fit(X, y)

    def predict(self, X):
        return self.model.predict(X)
        
from sklearn.ensemble import VotingClassifier

class EnsembleModel:
    def __init__(self, models):
        self.model = VotingClassifier(estimators=models)

    def train(self, X, y):
        self.model.fit(X, y)

    def predict(self, X):
        return self.model.predict(X)