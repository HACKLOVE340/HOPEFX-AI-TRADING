# HOPEFX Mobile Development Guide

> Building mobile-first trading experiences

---

## 📱 Mobile Overview

HOPEFX provides mobile trading through:
1. **Progressive Web App (PWA)** - Works on any device
2. **Mobile-Optimized API** - REST and WebSocket
3. **Push Notifications** - Real-time alerts
4. **Native App Templates** - Flutter/React Native ready

---

## 🌐 Progressive Web App (PWA)

### Features

The HOPEFX PWA provides a native-like experience:

- ✅ Works offline
- ✅ Installable on home screen
- ✅ Push notifications
- ✅ Fast loading
- ✅ Responsive design
- ✅ Touch-optimized

### Installation

**For Users:**

1. Navigate to `https://your-hopefx-domain/`
2. Click "Add to Home Screen" (iOS) or install prompt (Android)
3. Launch from home screen like a native app

**For Developers:**

The PWA is configured in `mobile/pwa/manifest.json`:

```json
{
  "name": "HOPEFX AI Trading",
  "short_name": "HOPEFX",
  "description": "AI-Powered Trading Platform",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#131722",
  "theme_color": "#26a69a",
  "icons": [
    {
      "src": "/icons/icon-192.png",
      "sizes": "192x192",
      "type": "image/png"
    },
    {
      "src": "/icons/icon-512.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
```

### Service Worker

The service worker enables offline functionality:

```javascript
// mobile/pwa/service-worker.js
const CACHE_NAME = 'hopefx-v1';
const urlsToCache = [
  '/',
  '/static/css/main.css',
  '/static/js/main.js',
  '/manifest.json'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => response || fetch(event.request))
  );
});
```

---

## 📲 Native App Development

### Flutter Template

Build native iOS and Android apps with Flutter:

```dart
// lib/main.dart
import 'package:flutter/material.dart';
import 'package:hopefx_mobile/api/client.dart';
import 'package:hopefx_mobile/screens/dashboard.dart';

void main() {
  runApp(HopeFXApp());
}

class HopeFXApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'HOPEFX Trading',
      theme: ThemeData(
        brightness: Brightness.dark,
        primaryColor: Color(0xFF26a69a),
        scaffoldBackgroundColor: Color(0xFF131722),
      ),
      home: DashboardScreen(),
    );
  }
}
```

#### API Client

```dart
// lib/api/client.dart
import 'package:dio/dio.dart';

class HopeFXClient {
  final Dio _dio;
  final String baseUrl;
  
  HopeFXClient({required this.baseUrl, required String apiKey}) 
    : _dio = Dio(BaseOptions(
        baseUrl: baseUrl,
        headers: {'Authorization': 'Bearer $apiKey'},
      ));
  
  Future<Map<String, dynamic>> getPortfolio() async {
    final response = await _dio.get('/api/v1/portfolio');
    return response.data;
  }
  
  Future<Map<String, dynamic>> placeOrder({
    required String symbol,
    required String side,
    required double quantity,
  }) async {
    final response = await _dio.post('/api/v1/orders', data: {
      'symbol': symbol,
      'side': side,
      'type': 'market',
      'quantity': quantity,
    });
    return response.data;
  }
  
  Stream<Map<String, dynamic>> priceStream(String symbol) {
    // WebSocket implementation
    return Stream.empty();
  }
}
```

#### Dashboard Screen

```dart
// lib/screens/dashboard.dart
import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';

class DashboardScreen extends StatefulWidget {
  @override
  _DashboardScreenState createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('HOPEFX Trading'),
        actions: [
          IconButton(
            icon: Icon(Icons.notifications),
            onPressed: () => Navigator.pushNamed(context, '/notifications'),
          ),
        ],
      ),
      body: Column(
        children: [
          // Portfolio Summary Card
          PortfolioCard(),
          // Price Chart
          Expanded(child: PriceChart()),
          // Quick Trade Buttons
          TradeButtons(),
        ],
      ),
      bottomNavigationBar: BottomNavigationBar(
        items: [
          BottomNavigationBarItem(icon: Icon(Icons.dashboard), label: 'Dashboard'),
          BottomNavigationBarItem(icon: Icon(Icons.show_chart), label: 'Charts'),
          BottomNavigationBarItem(icon: Icon(Icons.history), label: 'History'),
          BottomNavigationBarItem(icon: Icon(Icons.settings), label: 'Settings'),
        ],
      ),
    );
  }
}
```

### React Native Template

For React Native development:

```jsx
// App.js
import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Provider } from 'react-redux';
import { store } from './store';

import DashboardScreen from './screens/Dashboard';
import ChartsScreen from './screens/Charts';
import HistoryScreen from './screens/History';
import SettingsScreen from './screens/Settings';

const Tab = createBottomTabNavigator();

export default function App() {
  return (
    <Provider store={store}>
      <NavigationContainer>
        <Tab.Navigator
          screenOptions={{
            tabBarStyle: { backgroundColor: '#131722' },
            tabBarActiveTintColor: '#26a69a',
          }}
        >
          <Tab.Screen name="Dashboard" component={DashboardScreen} />
          <Tab.Screen name="Charts" component={ChartsScreen} />
          <Tab.Screen name="History" component={HistoryScreen} />
          <Tab.Screen name="Settings" component={SettingsScreen} />
        </Tab.Navigator>
      </NavigationContainer>
    </Provider>
  );
}
```

#### API Service

```javascript
// services/api.js
import axios from 'axios';

const API_BASE = 'https://api.hopefx.com/v1';

class HopeFXAPI {
  constructor(apiKey) {
    this.client = axios.create({
      baseURL: API_BASE,
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
    });
  }

  async getPortfolio() {
    const response = await this.client.get('/portfolio');
    return response.data;
  }

  async getPositions() {
    const response = await this.client.get('/positions');
    return response.data;
  }

  async placeOrder(order) {
    const response = await this.client.post('/orders', order);
    return response.data;
  }

  async closePosition(positionId) {
    const response = await this.client.delete(`/positions/${positionId}`);
    return response.data;
  }
}

export default HopeFXAPI;
```

---

## 🔔 Push Notifications

### Setup

```python
# mobile/push_notifications.py
from firebase_admin import messaging
import firebase_admin
from firebase_admin import credentials

class PushNotificationManager:
    """
    Push notification manager for mobile apps
    """
    
    def __init__(self, credentials_path: str = None):
        if credentials_path:
            cred = credentials.Certificate(credentials_path)
            firebase_admin.initialize_app(cred)
    
    def send_trade_alert(self, token: str, signal: dict):
        """Send trade signal notification"""
        message = messaging.Message(
            notification=messaging.Notification(
                title=f"Trade Signal: {signal['action'].upper()}",
                body=f"{signal['symbol']} - {signal['reason']}"
            ),
            data={
                'type': 'trade_signal',
                'symbol': signal['symbol'],
                'action': signal['action'],
                'strength': str(signal.get('strength', 0.5))
            },
            token=token,
        )
        
        response = messaging.send(message)
        return response
    
    def send_price_alert(self, token: str, symbol: str, price: float, threshold: float):
        """Send price alert notification"""
        direction = "above" if price >= threshold else "below"
        
        message = messaging.Message(
            notification=messaging.Notification(
                title=f"Price Alert: {symbol}",
                body=f"{symbol} is now {direction} {threshold:.2f}"
            ),
            data={
                'type': 'price_alert',
                'symbol': symbol,
                'price': str(price),
                'threshold': str(threshold)
            },
            token=token,
        )
        
        return messaging.send(message)
    
    def send_position_update(self, token: str, position: dict):
        """Send position update notification"""
        pnl = position.get('unrealized_pnl', 0)
        pnl_emoji = "📈" if pnl > 0 else "📉" if pnl < 0 else "➡️"
        
        message = messaging.Message(
            notification=messaging.Notification(
                title=f"{pnl_emoji} Position Update",
                body=f"{position['symbol']}: {pnl:+.2f}"
            ),
            data={
                'type': 'position_update',
                'position_id': position['id'],
                'pnl': str(pnl)
            },
            token=token,
        )
        
        return messaging.send(message)
```

### Client-Side Integration

**React Native:**

```javascript
// services/notifications.js
import messaging from '@react-native-firebase/messaging';
import AsyncStorage from '@react-native-async-storage/async-storage';

export async function requestNotificationPermission() {
  const authStatus = await messaging().requestPermission();
  const enabled = 
    authStatus === messaging.AuthorizationStatus.AUTHORIZED ||
    authStatus === messaging.AuthorizationStatus.PROVISIONAL;

  if (enabled) {
    const token = await messaging().getToken();
    await registerDeviceToken(token);
  }
  
  return enabled;
}

export async function registerDeviceToken(token) {
  await AsyncStorage.setItem('pushToken', token);
  // Send to backend
  await api.post('/notifications/register', { token });
}

export function setupNotificationHandlers() {
  // Foreground messages
  messaging().onMessage(async remoteMessage => {
    console.log('Notification received:', remoteMessage);
    // Show in-app notification
  });

  // Background messages
  messaging().setBackgroundMessageHandler(async remoteMessage => {
    console.log('Background message:', remoteMessage);
  });
}
```

**Flutter:**

```dart
// lib/services/notifications.dart
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

class NotificationService {
  final FirebaseMessaging _messaging = FirebaseMessaging.instance;
  final FlutterLocalNotificationsPlugin _localNotifications = 
    FlutterLocalNotificationsPlugin();

  Future<void> initialize() async {
    // Request permission
    await _messaging.requestPermission();
    
    // Get token
    final token = await _messaging.getToken();
    await _registerToken(token!);
    
    // Handle messages
    FirebaseMessaging.onMessage.listen(_handleForegroundMessage);
    FirebaseMessaging.onBackgroundMessage(_handleBackgroundMessage);
  }

  void _handleForegroundMessage(RemoteMessage message) {
    // Show local notification
    _localNotifications.show(
      message.hashCode,
      message.notification?.title,
      message.notification?.body,
      NotificationDetails(
        android: AndroidNotificationDetails(
          'hopefx_trading',
          'Trading Alerts',
          importance: Importance.high,
        ),
      ),
    );
  }
}
```

---

## 📡 Mobile API

### Optimized Endpoints

The mobile API provides optimized endpoints for mobile clients:

```python
# mobile/api.py
from fastapi import APIRouter, Depends
from typing import Optional

router = APIRouter(prefix="/mobile", tags=["Mobile"])

@router.get("/dashboard")
async def get_dashboard():
    """
    Get all dashboard data in a single request
    Optimized for mobile to reduce API calls
    """
    return {
        "portfolio": await get_portfolio_summary(),
        "positions": await get_open_positions(),
        "recent_signals": await get_recent_signals(limit=5),
        "price": await get_current_price("XAUUSD"),
        "alerts": await get_unread_alerts()
    }

@router.get("/chart/{symbol}")
async def get_chart_data(
    symbol: str,
    timeframe: str = "1H",
    limit: int = 100
):
    """
    Get chart data optimized for mobile display
    """
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": await get_ohlcv(symbol, timeframe, limit),
        "indicators": {
            "sma_20": await calculate_sma(symbol, 20),
            "ema_50": await calculate_ema(symbol, 50)
        }
    }

@router.post("/quick-trade")
async def quick_trade(
    symbol: str,
    side: str,
    risk_percent: float = 0.02
):
    """
    One-tap trading with automatic position sizing
    """
    position_size = calculate_position_size(risk_percent)
    return await place_order(symbol, side, position_size)
```

### WebSocket for Real-Time Data

```python
# mobile/websocket.py
from fastapi import WebSocket

@router.websocket("/ws/mobile")
async def mobile_websocket(websocket: WebSocket):
    await websocket.accept()
    
    try:
        while True:
            # Send combined updates
            data = {
                "type": "update",
                "portfolio": await get_portfolio_summary(),
                "prices": await get_watched_prices(),
                "positions": await get_position_updates()
            }
            await websocket.send_json(data)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
```

---

## 📊 Mobile UI Components

### Chart Component

```jsx
// components/TradingChart.jsx
import React from 'react';
import { View, Dimensions } from 'react-native';
import { LineChart, CandlestickChart } from 'react-native-wagmi-charts';

export function TradingChart({ data, type = 'candlestick' }) {
  const { width } = Dimensions.get('window');
  
  if (type === 'candlestick') {
    return (
      <CandlestickChart.Provider data={data}>
        <CandlestickChart width={width} height={300}>
          <CandlestickChart.Candles />
          <CandlestickChart.Crosshair>
            <CandlestickChart.Tooltip />
          </CandlestickChart.Crosshair>
        </CandlestickChart>
      </CandlestickChart.Provider>
    );
  }
  
  return (
    <LineChart.Provider data={data}>
      <LineChart width={width} height={300}>
        <LineChart.Path color="#26a69a" />
        <LineChart.CursorLine />
        <LineChart.CursorCrosshair />
      </LineChart>
    </LineChart.Provider>
  );
}
```

### Trade Panel

```jsx
// components/TradePanel.jsx
import React, { useState } from 'react';
import { View, TouchableOpacity, Text, StyleSheet } from 'react-native';

export function TradePanel({ symbol, currentPrice, onTrade }) {
  const [quantity, setQuantity] = useState(0.1);
  
  return (
    <View style={styles.container}>
      <View style={styles.priceDisplay}>
        <Text style={styles.symbol}>{symbol}</Text>
        <Text style={styles.price}>${currentPrice.toFixed(2)}</Text>
      </View>
      
      <View style={styles.quantitySelector}>
        <TouchableOpacity onPress={() => setQuantity(q => Math.max(0.01, q - 0.01))}>
          <Text style={styles.button}>-</Text>
        </TouchableOpacity>
        <Text style={styles.quantity}>{quantity.toFixed(2)}</Text>
        <TouchableOpacity onPress={() => setQuantity(q => q + 0.01)}>
          <Text style={styles.button}>+</Text>
        </TouchableOpacity>
      </View>
      
      <View style={styles.tradeButtons}>
        <TouchableOpacity 
          style={[styles.tradeButton, styles.buyButton]}
          onPress={() => onTrade('buy', quantity)}
        >
          <Text style={styles.buttonText}>BUY</Text>
        </TouchableOpacity>
        <TouchableOpacity 
          style={[styles.tradeButton, styles.sellButton]}
          onPress={() => onTrade('sell', quantity)}
        >
          <Text style={styles.buttonText}>SELL</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#1e222d',
    padding: 16,
    borderRadius: 8,
  },
  buyButton: {
    backgroundColor: '#26a69a',
  },
  sellButton: {
    backgroundColor: '#ef5350',
  },
  // ... more styles
});
```

---

## 🔐 Security Considerations

### Secure Storage

```javascript
// Store sensitive data securely
import * as SecureStore from 'expo-secure-store';

export async function saveApiKey(apiKey) {
  await SecureStore.setItemAsync('apiKey', apiKey);
}

export async function getApiKey() {
  return await SecureStore.getItemAsync('apiKey');
}
```

### Biometric Authentication

```javascript
// Enable biometric login
import * as LocalAuthentication from 'expo-local-authentication';

export async function authenticateWithBiometrics() {
  const hasHardware = await LocalAuthentication.hasHardwareAsync();
  const isEnrolled = await LocalAuthentication.isEnrolledAsync();
  
  if (hasHardware && isEnrolled) {
    const result = await LocalAuthentication.authenticateAsync({
      promptMessage: 'Authenticate to access HOPEFX',
    });
    return result.success;
  }
  
  return false;
}
```

---

## 📦 Deployment

### iOS App Store

1. Configure signing in Xcode
2. Build release version
3. Upload to App Store Connect
4. Submit for review

### Google Play Store

1. Generate signed APK/AAB
2. Create Play Console listing
3. Upload bundle
4. Submit for review

### PWA Deployment

Ensure your server has:
- HTTPS enabled
- Valid SSL certificate
- Proper CORS headers
- Service worker registered

---

## 🆘 Support

- **Documentation:** [docs/API_GUIDE.md](./API_GUIDE.md)
- **Discord:** `#mobile-development`
- **GitHub:** Issue tracker

---

*Build amazing mobile trading experiences with HOPEFX!*
