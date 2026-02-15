# World Monitor Integration for HOPEFX AI Trading

## Overview

This document describes the integration of **World Monitor** (https://worldmonitor.app/) geopolitical intelligence into the HOPEFX AI Trading platform, specifically for enhancing XAU/USD (Gold) trading decisions.

## Four Ways to Use World Monitor

### 1. Use the Existing Integration (Built-in)

The simplest approach - use the pre-built integration:

```python
from news import get_gold_geopolitical_signal

# Get trading signal based on geopolitical events
signal = get_gold_geopolitical_signal()
print(f"Direction: {signal['direction']}")  # BUY, SELL, or NEUTRAL
print(f"Confidence: {signal['confidence']}")
print(f"Risk Score: {signal['risk_score']}")
```

### 2. Pull Data Directly from World Monitor API

Connect directly to World Monitor's REST API endpoints:

```python
from news import WorldMonitorAPIClient, get_api_client

# Initialize API client
client = get_api_client({
    'base_url': 'https://worldmonitor.app',
    'timeout': 30,
    'enabled_layers': ['conflicts', 'country_intel', 'news', 'outages']
})

# Get specific data
conflicts = client.get_conflicts(region='Middle East')
country_risk = client.get_country_intel(country='RU')
news = client.get_news_intel(topic='sanctions', hours=24)
outages = client.get_outages()

# Or get all enabled layers at once
all_data = client.get_all_layers()

# Calculate gold risk score from live data
risk_score = client.calculate_gold_risk_score()
print(f"Global Risk: {risk_score['global_risk_score']}")
print(f"Gold Outlook: {risk_score['gold_outlook']}")
```

#### Available API Endpoints

| Endpoint | Description | Method |
|----------|-------------|--------|
| `/api/acled` | Armed conflict events | `get_conflicts()` |
| `/api/country-intel` | Country risk & sanctions | `get_country_intel()` |
| `/api/firms-fires` | Satellite fire detection | `get_satellite_fires()` |
| `/api/opensky` | Military flight tracking | `get_military_flights()` |
| `/api/theater-posture` | Military force posture | `get_military_theater()` |
| `/api/gdelt-doc` | Global news intelligence | `get_news_intel()` |
| `/api/cloudflare-outages` | Internet outages | `get_outages()` |

### 3. Self-Host World Monitor

Run your own World Monitor instance for full control:

```python
from news import create_self_hosted_setup, WorldMonitorSelfHostConfig

# Generate setup script
setup_script = create_self_hosted_setup()
with open('setup_worldmonitor.sh', 'w') as f:
    f.write(setup_script)

# Run: bash setup_worldmonitor.sh

# Generate HOPEFX config for self-hosted instance
config = WorldMonitorSelfHostConfig.generate_hopefx_config(
    self_hosted_url='http://localhost:5173'
)

# Use with API client
from news import get_api_client
client = get_api_client(config)
```

#### Self-Hosting Requirements

- Node.js 18+
- Git
- Optional: Redis (Upstash) for caching
- Optional: API keys for enhanced data

#### Docker Deployment

```yaml
version: '3.8'
services:
  worldmonitor:
    image: node:18-alpine
    working_dir: /app
    ports:
      - "5173:5173"
    environment:
      - GROQ_API_KEY=${GROQ_API_KEY:-}
      - NASA_FIRMS_API_KEY=${NASA_FIRMS_API_KEY:-}
    volumes:
      - ./worldmonitor:/app
    command: sh -c "npm install && npm run dev"
```

### 4. Customize Data Layers

Configure exactly which data layers to monitor and their weights:

```python
from news import get_custom_layer_config, CustomDataLayerConfig

# Get gold-optimized configuration
config = get_custom_layer_config(gold_optimized=True)
print(f"Enabled: {config.get_enabled_layers()}")
print(f"Weights: {config.get_layer_weights()}")

# Or create custom configuration
custom = CustomDataLayerConfig({
    'conflicts': {'enabled': True, 'weight': 1.0},
    'sanctions': {'enabled': True, 'weight': 0.9},
    'military': {'enabled': True, 'weight': 0.8},
    'nuclear': {'enabled': True, 'weight': 0.8},
    'hotspots': {'enabled': True, 'weight': 0.7},
    'pipelines': {'enabled': True, 'weight': 0.6},
    'outages': {'enabled': True, 'weight': 0.5},
    'weather': {'enabled': False, 'weight': 0.3},  # Disabled
    'protests': {'enabled': False, 'weight': 0.4},  # Disabled
})

# Enable/disable layers dynamically
custom.enable_layer('weather', weight=0.4)
custom.disable_layer('protests')
custom.set_weight('conflicts', 1.0)
custom.set_alert_threshold('conflicts', 5)

# Convert to provider config
provider_config = custom.to_provider_config()
```

#### Layer Weight Reference

| Layer | Default Weight | Gold Correlation |
|-------|---------------|------------------|
| conflicts | 1.0 | Strong Positive |
| sanctions | 0.9 | Positive |
| military | 0.8 | Strong Positive |
| nuclear | 0.8 | Strong Positive |
| hotspots | 0.7 | Positive |
| pipelines | 0.6 | Positive |
| outages | 0.5 | Moderate Positive |
| natural | 0.5 | Moderate Positive |
| weather | 0.3 | Weak Positive |
| protests | 0.4 | Moderate Positive |

## What is World Monitor?

World Monitor is a **real-time global intelligence dashboard** that provides:

- **Active Conflict Monitoring**: Wars, military operations, escalation tracking
- **Sanctions Tracking**: Economic sanctions, trade restrictions, embargoes
- **Intelligence Hotspots**: Areas of heightened geopolitical activity
- **Natural Disasters**: Weather alerts, earthquakes, environmental events
- **Infrastructure Outages**: Internet outages, pipeline disruptions, cable damage
- **Country Instability Index**: Real-time stability scores for 20+ nations

### Why It's Valuable for XAU/USD Trading

Gold is the ultimate **safe-haven asset**. When geopolitical risks increase, investors flee to gold, driving prices up. World Monitor provides real-time data on exactly these risk factors:

| Geopolitical Event | Gold Impact | Why |
|-------------------|-------------|-----|
| Military Conflict | **BULLISH** | Flight to safety, currency uncertainty |
| Sanctions | **BULLISH** | Trade disruption, economic instability |
| Natural Disasters | **BULLISH** (if severe) | Supply chain disruption, reconstruction costs |
| Political Unrest | **BULLISH** | Currency weakness, economic uncertainty |
| Infrastructure Outages | **BULLISH** | Systemic risk concerns |

## URL Structure Analysis

The provided World Monitor URL:
```
https://worldmonitor.app/?lat=46.4000&lon=-163.8957&zoom=2.50&view=mena&timeRange=7d&layers=conflicts,hotspots,sanctions,weather,outages,natural
```

### Parameters Explained:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `lat` | 46.4000 | Latitude for map center |
| `lon` | -163.8957 | Longitude for map center |
| `zoom` | 2.50 | Map zoom level |
| `view` | mena | Regional preset (Middle East & North Africa) |
| `timeRange` | 7d | Show events from last 7 days |
| `layers` | conflicts,hotspots,sanctions,weather,outages,natural | Active data layers |

### Available Data Layers:

1. **conflicts** - Active conflict zones with escalation tracking
2. **hotspots** - Intelligence hotspots with news correlation
3. **sanctions** - Economic sanctions regimes
4. **weather** - Severe weather alerts
5. **outages** - Internet/infrastructure outages
6. **natural** - Natural disasters (earthquakes, fires, floods)
7. **military** - Military bases, flight tracking, naval vessels
8. **protests** - Social unrest events
9. **nuclear** - Nuclear facilities
10. **pipelines** - Oil & gas infrastructure
11. **cables** - Undersea communication cables
12. **datacenters** - Major data center clusters

## Implementation

### Files Added/Modified

1. **`news/geopolitical_risk.py`** (NEW)
   - `GeopoliticalRiskProvider`: Main provider class for geopolitical data
   - `GeopoliticalEvent`: Data class for individual events
   - `GeopoliticalRiskAssessment`: Comprehensive risk assessment
   - `WorldMonitorIntegration`: Helper for building World Monitor URLs
   - `get_gold_geopolitical_signal()`: Convenience function for trading signals

2. **`news/__init__.py`** (UPDATED)
   - Added exports for new geopolitical risk classes
   - Updated version to 1.1.0

3. **`news/impact_predictor.py`** (UPDATED)
   - Extended geopolitical keywords for better event categorization

### Usage Examples

```python
from news.geopolitical_risk import (
    get_geopolitical_provider,
    get_gold_geopolitical_signal,
    WorldMonitorIntegration
)

# Get geopolitical risk provider
provider = get_geopolitical_provider()

# Get current geopolitical events
events = provider.get_current_events()

# Get comprehensive risk assessment
assessment = provider.get_risk_assessment()
print(f"Global Risk Score: {assessment.global_risk_score}")
print(f"Gold Outlook: {assessment.gold_outlook.value}")
print(f"Active Conflicts: {assessment.active_conflicts}")

# Get trading signal for gold
signal = get_gold_geopolitical_signal()
print(f"Direction: {signal['direction']}")
print(f"Confidence: {signal['confidence']}")
print(f"Recommendations: {signal['recommendations']}")

# Build World Monitor URLs for gold-relevant regions
integration = WorldMonitorIntegration()
urls = integration.get_gold_relevant_views()
print(f"Middle East Monitor: {urls['middle_east']}")
print(f"Eastern Europe Monitor: {urls['eastern_europe']}")
```

### Configuration Options

Add to your `.env` or config:

```python
# Geopolitical Risk Configuration
GEOPOLITICAL_CONFIG = {
    'time_range': '7d',       # Event time window
    'cache_ttl': 300,         # Cache TTL in seconds
    'data_layers': [          # Layers to monitor
        'conflicts',
        'hotspots', 
        'sanctions',
        'weather',
        'outages',
        'natural'
    ]
}
```

## Gold-Sensitive Regions

The system monitors these regions with extra weight for gold trading:

### Middle East (MENA)
- Iran, Iraq, Syria, Israel, Saudi Arabia, Yemen, Lebanon, Qatar, UAE
- **Impact**: Oil flows, regional stability, US dollar strength

### Eastern Europe
- Russia, Ukraine, Belarus, Poland
- **Impact**: Energy supplies, sanctions, safe-haven demand

### Asia-Pacific
- China, Taiwan, North Korea, South Korea, Japan
- **Impact**: Trade flows, currency stability, regional tensions

### Major Economies
- United States, China, Germany, Japan, UK, France, Italy
- **Impact**: Global economic health, policy decisions

## Event Types and Trading Impact

| Event Type | Severity Impact | Gold Correlation |
|------------|----------------|------------------|
| Conflict | +15 risk score | Strong Bullish |
| Military Activity | +15 risk score | Strong Bullish |
| Sanctions | +10 risk score | Bullish |
| Natural Disaster | +5 risk score | Moderate Bullish |
| Infrastructure Outage | +5 risk score | Moderate Bullish |
| Political Unrest | +10 risk score | Bullish |
| Cyber Attack | +5 risk score | Moderate Bullish |
| Economic Crisis | +15 risk score | Strong Bullish |

## Risk Score Calculation

The global risk score (0-100) is calculated as:

1. **Base Score**: Sum of individual event risk scores
2. **Event Type Weight**: Conflicts and military +15, sanctions +10, etc.
3. **Severity Weight**: Critical +80, High +60, Medium +40, Low +20
4. **Region Weight**: +10 for gold-sensitive regions
5. **Confidence Adjustment**: Score × event confidence

## Trading Recommendations Logic

Based on risk assessment:

| Global Risk | Gold Outlook | Trading Recommendation |
|-------------|--------------|----------------------|
| ≥70 | Strongly Bullish | Increase gold allocation, long XAU/USD |
| 50-69 | Bullish | Favor gold on dips, moderate exposure |
| 30-49 | Neutral | Maintain balanced position |
| <30 | Bearish | Reduce gold exposure, risk-on favored |

## Data Sources

World Monitor aggregates data from:

- **GDELT**: Global Database of Events, Language, and Tone
- **ACLED**: Armed Conflict Location & Event Data
- **OpenSky**: Real-time aircraft tracking (military flights)
- **AIS**: Automatic Identification System (naval vessels)
- **NASA FIRMS**: Fire Information for Resource Management
- **Cloudflare Radar**: Internet outage detection
- **USGS**: Earthquake monitoring
- **100+ RSS Feeds**: Global news sources

## Open Source

World Monitor is **open source** and free to use:

- **Live App**: https://worldmonitor.app/
- **GitHub**: https://github.com/koala73/worldmonitor
- **Documentation**: https://github.com/koala73/worldmonitor/blob/main/docs/DOCUMENTATION.md

## Future Enhancements

1. **Real-time WebSocket Integration**: Direct feed from World Monitor
2. **Historical Analysis**: Correlation between past events and gold moves
3. **Alert System**: Push notifications for critical geopolitical events
4. **Machine Learning**: Predictive models for event-to-price correlation
5. **Multi-Asset Support**: Extend to oil, currencies, and other safe-havens

## Related Files

- `news/providers.py` - News data providers
- `news/sentiment.py` - Sentiment analysis
- `news/impact_predictor.py` - Market impact prediction
- `news/economic_calendar.py` - Economic events
- `risk/manager.py` - Risk management
- `analysis/market_analysis.py` - Market regime detection
