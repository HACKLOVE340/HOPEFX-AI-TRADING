# World Monitor Integration for HOPEFX AI Trading

## Overview

This document describes the integration of **World Monitor** (https://worldmonitor.app/) geopolitical intelligence into the HOPEFX AI Trading platform, specifically for enhancing XAU/USD (Gold) trading decisions.

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
