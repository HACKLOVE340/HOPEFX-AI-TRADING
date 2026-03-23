import pandas as pd
import pandas_ta as ta
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import classification_report, confusion_matrix
import joblib

# Load historical XAUUSD data
# Make sure to change 'your_data.csv' to the path of your historical data
# Example: data = pd.read_csv('path/to/your/xauusd_data.csv')
data = pd.read_csv('your_data.csv')

# Feature generation using pandas_ta

def generate_features(data):
    data['EMA'] = ta.ema(data['Close'], length=14)
    data['RSI'] = ta.rsi(data['Close'], length=14)
    data['MACD'] = ta.macd(data['Close'])['macd_12_26']
    data['ATR'] = ta.atr(data['High'], data['Low'], data['Close'], length=14)
    bb = ta.bbands(data['Close'])
    data['BB_upper'] = bb['BB.upper']
    data['BB_middle'] = bb['BB.mavg']
    data['BB_lower'] = bb['BB.lower']
    return data

data = generate_features(data)

# Define your target variable (e.g., Buy=1, Sell=0)
# Make sure to change 'Target' to your actual target variable column
X = data[['EMA', 'RSI', 'MACD', 'ATR', 'BB_upper', 'BB_middle', 'BB_lower']]
y = data['Target']

# Split the data into training and testing sets
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Initialize the RandomForestClassifier
model = RandomForestClassifier(n_estimators=100, random_state=42)

# Train the model
model.fit(X_train, y_train)

# Cross-validation
cv_scores = cross_val_score(model, X, y, cv=5)
print(f'Cross-Validation Scores: {cv_scores}')
print(f'Average Score: {cv_scores.mean()}')

# Performance Metrics
predictions = model.predict(X_test)
print(confusion_matrix(y_test, predictions))
print(classification_report(y_test, predictions))

# Save the trained model
joblib.dump(model, 'ml/saved_models/ensemble_rf.pkl')
