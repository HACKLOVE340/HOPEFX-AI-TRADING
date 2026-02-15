"""
Geopolitical Risk Intelligence Module

Integrates World Monitor data for geopolitical risk assessment in trading:
- Conflict zone monitoring (wars, military activities)
- Sanctions tracking (trade restrictions, economic warfare)
- Country instability index (political risk scores)
- Infrastructure disruptions (outages, natural disasters)
- Weather/natural hazard alerts

World Monitor Source: https://worldmonitor.app/
GitHub: https://github.com/koala73/worldmonitor

This module is particularly valuable for XAU/USD (Gold) trading since:
- Gold is a safe-haven asset that rises during geopolitical crises
- Sanctions affect global gold supply chains
- Conflicts drive flight-to-safety demand
- Currency instability increases gold appeal

Author: HOPEFX Development Team
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta, timezone
import requests
import json

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class GeopoliticalEventType(Enum):
    """Types of geopolitical events"""
    CONFLICT = "conflict"
    SANCTIONS = "sanctions"
    HOTSPOT = "hotspot"
    NATURAL_DISASTER = "natural_disaster"
    INFRASTRUCTURE_OUTAGE = "infrastructure_outage"
    MILITARY_ACTIVITY = "military_activity"
    POLITICAL_UNREST = "political_unrest"
    CYBER_ATTACK = "cyber_attack"
    ECONOMIC_CRISIS = "economic_crisis"
    TERRORISM = "terrorism"


class RiskSeverity(Enum):
    """Risk severity levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class GoldImpact(Enum):
    """Potential impact on gold prices"""
    STRONGLY_BULLISH = "strongly_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    STRONGLY_BEARISH = "strongly_bearish"


@dataclass
class GeopoliticalEvent:
    """Represents a geopolitical event that may impact markets"""
    event_type: GeopoliticalEventType
    severity: RiskSeverity
    title: str
    description: str
    region: str
    countries: List[str]
    coordinates: Optional[Tuple[float, float]] = None  # (lat, lon)
    timestamp: datetime = field(default_factory=_utc_now)
    source: str = "worldmonitor"
    confidence: float = 0.8
    
    # Trading impact assessment
    gold_impact: Optional[GoldImpact] = None
    affected_currencies: List[str] = field(default_factory=list)
    risk_score: float = 0.0  # 0-100
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'event_type': self.event_type.value,
            'severity': self.severity.value,
            'title': self.title,
            'description': self.description,
            'region': self.region,
            'countries': self.countries,
            'coordinates': self.coordinates,
            'timestamp': self.timestamp.isoformat(),
            'source': self.source,
            'confidence': self.confidence,
            'gold_impact': self.gold_impact.value if self.gold_impact else None,
            'affected_currencies': self.affected_currencies,
            'risk_score': self.risk_score
        }


@dataclass
class CountryRisk:
    """Country instability index data"""
    country_code: str
    country_name: str
    instability_index: float  # 0-100 (higher = more unstable)
    trend: str  # 'increasing', 'stable', 'decreasing'
    risk_factors: List[str]
    last_updated: datetime = field(default_factory=_utc_now)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'country_code': self.country_code,
            'country_name': self.country_name,
            'instability_index': self.instability_index,
            'trend': self.trend,
            'risk_factors': self.risk_factors,
            'last_updated': self.last_updated.isoformat()
        }


@dataclass
class GeopoliticalRiskAssessment:
    """Overall geopolitical risk assessment"""
    global_risk_score: float  # 0-100
    gold_outlook: GoldImpact
    active_conflicts: int
    sanctions_count: int
    hotspots: int
    high_risk_regions: List[str]
    key_events: List[GeopoliticalEvent]
    country_risks: Dict[str, CountryRisk]
    trading_recommendations: List[str]
    timestamp: datetime = field(default_factory=_utc_now)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'global_risk_score': self.global_risk_score,
            'gold_outlook': self.gold_outlook.value,
            'active_conflicts': self.active_conflicts,
            'sanctions_count': self.sanctions_count,
            'hotspots': self.hotspots,
            'high_risk_regions': self.high_risk_regions,
            'key_events': [e.to_dict() for e in self.key_events],
            'country_risks': {k: v.to_dict() for k, v in self.country_risks.items()},
            'trading_recommendations': self.trading_recommendations,
            'timestamp': self.timestamp.isoformat()
        }


class GeopoliticalRiskProvider:
    """
    Provides geopolitical risk intelligence from World Monitor.
    
    World Monitor is a real-time global intelligence dashboard that tracks:
    - Active conflicts and military activity
    - Sanctions regimes
    - Natural disasters and weather events
    - Infrastructure outages
    - Country instability indices
    
    This data is crucial for XAU/USD trading since gold prices are
    highly sensitive to geopolitical risks (safe-haven demand).
    """
    
    # World Monitor layer mapping to event types
    LAYER_MAPPING = {
        'conflicts': GeopoliticalEventType.CONFLICT,
        'hotspots': GeopoliticalEventType.HOTSPOT,
        'sanctions': GeopoliticalEventType.SANCTIONS,
        'weather': GeopoliticalEventType.NATURAL_DISASTER,
        'outages': GeopoliticalEventType.INFRASTRUCTURE_OUTAGE,
        'natural': GeopoliticalEventType.NATURAL_DISASTER,
        'military': GeopoliticalEventType.MILITARY_ACTIVITY,
        'protests': GeopoliticalEventType.POLITICAL_UNREST,
    }
    
    # Regions that significantly impact gold prices
    GOLD_SENSITIVE_REGIONS = {
        'middle_east': ['Iran', 'Iraq', 'Syria', 'Israel', 'Saudi Arabia', 
                        'Yemen', 'Lebanon', 'Qatar', 'UAE'],
        'eastern_europe': ['Russia', 'Ukraine', 'Belarus', 'Poland'],
        'asia_pacific': ['China', 'Taiwan', 'North Korea', 'South Korea', 'Japan'],
        'major_economies': ['United States', 'China', 'Germany', 'Japan', 
                           'United Kingdom', 'France', 'Italy'],
    }
    
    # Keywords that indicate high-impact events for gold
    HIGH_IMPACT_KEYWORDS = {
        'conflict': ['war', 'invasion', 'military strike', 'bombing', 'attack',
                    'escalation', 'nuclear', 'missile', 'troops', 'deployed'],
        'sanctions': ['sanctions', 'embargo', 'trade ban', 'asset freeze',
                     'financial restrictions', 'export controls'],
        'economic': ['default', 'currency crisis', 'inflation surge',
                    'bank collapse', 'recession', 'debt crisis'],
        'political': ['coup', 'assassination', 'revolution', 'civil unrest',
                     'election crisis', 'government collapse'],
    }
    
    # Currency exposure by country
    COUNTRY_CURRENCIES = {
        'United States': 'USD',
        'European Union': 'EUR',
        'United Kingdom': 'GBP',
        'Japan': 'JPY',
        'Switzerland': 'CHF',
        'Australia': 'AUD',
        'Canada': 'CAD',
        'China': 'CNY',
        'Russia': 'RUB',
    }
    
    # ISO 3166-1 alpha-2 country codes for proper code generation
    COUNTRY_ISO_CODES = {
        'United States': 'US',
        'United Kingdom': 'GB',
        'European Union': 'EU',
        'Russia': 'RU',
        'Ukraine': 'UA',
        'Belarus': 'BY',
        'Poland': 'PL',
        'China': 'CN',
        'Taiwan': 'TW',
        'Japan': 'JP',
        'North Korea': 'KP',
        'South Korea': 'KR',
        'Iran': 'IR',
        'Iraq': 'IQ',
        'Syria': 'SY',
        'Israel': 'IL',
        'Saudi Arabia': 'SA',
        'Yemen': 'YE',
        'Lebanon': 'LB',
        'Qatar': 'QA',
        'UAE': 'AE',
        'Germany': 'DE',
        'France': 'FR',
        'Italy': 'IT',
        'Switzerland': 'CH',
        'Australia': 'AU',
        'Canada': 'CA',
    }
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize geopolitical risk provider.
        
        Args:
            config: Configuration dictionary with optional settings:
                - api_endpoint: World Monitor API endpoint (if using API)
                - data_layers: List of layers to monitor
                - time_range: Time range for events (e.g., '7d')
                - cache_ttl: Cache time-to-live in seconds
        """
        self.config = config or {}
        
        # Default configuration
        self.base_url = self.config.get('api_endpoint', 'https://worldmonitor.app')
        self.time_range = self.config.get('time_range', '7d')
        self.cache_ttl = self.config.get('cache_ttl', 300)  # 5 minutes
        
        # Layers to monitor (from the URL provided)
        self.data_layers = self.config.get('data_layers', [
            'conflicts', 'hotspots', 'sanctions', 'weather', 'outages', 'natural'
        ])
        
        # Cache for events
        self._cache = {}
        self._cache_timestamp = None
        
        # Historical events for trend analysis
        self.event_history = []
        
        logger.info(f"GeopoliticalRiskProvider initialized with layers: {self.data_layers}")
    
    def get_current_events(self, force_refresh: bool = False) -> List[GeopoliticalEvent]:
        """
        Get current geopolitical events.
        
        Args:
            force_refresh: Force refresh from source, ignoring cache
            
        Returns:
            List of GeopoliticalEvent objects
        """
        # Check cache validity
        if not force_refresh and self._is_cache_valid():
            return self._cache.get('events', [])
        
        events = []
        
        try:
            # Simulate fetching from World Monitor
            # In production, this would make actual API calls
            events = self._fetch_events_from_source()
            
            # Assess gold impact for each event
            for event in events:
                event.gold_impact = self._assess_gold_impact(event)
                event.risk_score = self._calculate_risk_score(event)
                event.affected_currencies = self._get_affected_currencies(event)
            
            # Update cache
            self._cache['events'] = events
            self._cache_timestamp = datetime.now(timezone.utc)
            
            # Store in history
            self.event_history.extend(events)
            # Keep only last 7 days
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            self.event_history = [e for e in self.event_history if e.timestamp > cutoff]
            
        except Exception as e:
            logger.error(f"Error fetching geopolitical events: {e}")
            # Return cached data if available
            events = self._cache.get('events', [])
        
        return events
    
    def get_risk_assessment(self) -> GeopoliticalRiskAssessment:
        """
        Get comprehensive geopolitical risk assessment.
        
        Returns:
            GeopoliticalRiskAssessment with all risk metrics
        """
        events = self.get_current_events()
        
        # Count event types
        conflicts = [e for e in events if e.event_type == GeopoliticalEventType.CONFLICT]
        sanctions = [e for e in events if e.event_type == GeopoliticalEventType.SANCTIONS]
        hotspots = [e for e in events if e.event_type == GeopoliticalEventType.HOTSPOT]
        
        # Calculate global risk score
        global_risk = self._calculate_global_risk(events)
        
        # Determine gold outlook
        gold_outlook = self._determine_gold_outlook(events, global_risk)
        
        # Get high-risk regions
        high_risk_regions = self._identify_high_risk_regions(events)
        
        # Get country risks
        country_risks = self._get_country_risks(events)
        
        # Generate trading recommendations
        recommendations = self._generate_trading_recommendations(
            events, global_risk, gold_outlook
        )
        
        return GeopoliticalRiskAssessment(
            global_risk_score=global_risk,
            gold_outlook=gold_outlook,
            active_conflicts=len(conflicts),
            sanctions_count=len(sanctions),
            hotspots=len(hotspots),
            high_risk_regions=high_risk_regions,
            key_events=events[:10],  # Top 10 events
            country_risks=country_risks,
            trading_recommendations=recommendations
        )
    
    def get_gold_trading_signal(self) -> Dict[str, Any]:
        """
        Get geopolitical-based gold trading signal.
        
        Returns:
            Trading signal with direction and confidence
        """
        assessment = self.get_risk_assessment()
        
        # Map gold outlook to signal
        signal_map = {
            GoldImpact.STRONGLY_BULLISH: {'direction': 'BUY', 'strength': 1.0},
            GoldImpact.BULLISH: {'direction': 'BUY', 'strength': 0.7},
            GoldImpact.NEUTRAL: {'direction': 'NEUTRAL', 'strength': 0.5},
            GoldImpact.BEARISH: {'direction': 'SELL', 'strength': 0.7},
            GoldImpact.STRONGLY_BEARISH: {'direction': 'SELL', 'strength': 1.0},
        }
        
        signal_info = signal_map.get(
            assessment.gold_outlook,
            {'direction': 'NEUTRAL', 'strength': 0.5}
        )
        
        # Calculate confidence based on data quality
        confidence = self._calculate_signal_confidence(assessment)
        
        return {
            'symbol': 'XAUUSD',
            'direction': signal_info['direction'],
            'strength': signal_info['strength'],
            'confidence': confidence,
            'risk_score': assessment.global_risk_score,
            'gold_outlook': assessment.gold_outlook.value,
            'active_conflicts': assessment.active_conflicts,
            'key_regions': assessment.high_risk_regions[:3],
            'recommendations': assessment.trading_recommendations,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    def _fetch_events_from_source(self) -> List[GeopoliticalEvent]:
        """
        Fetch events from World Monitor or similar sources.
        
        In production, this would make API calls to World Monitor.
        For now, we create representative events based on typical global situations.
        
        World Monitor data layers from URL:
        - conflicts: Active conflict zones
        - hotspots: Intelligence hotspots with news correlation
        - sanctions: Economic sanctions regimes
        - weather: Severe weather alerts
        - outages: Infrastructure outages
        - natural: Natural disasters
        """
        events = []
        
        # Example: Create events that would typically come from World Monitor
        # In production, replace with actual API integration
        
        # These are placeholder events that demonstrate the data structure
        # World Monitor's open-source nature means you can integrate directly
        # See: https://github.com/koala73/worldmonitor
        
        sample_events = [
            {
                'type': GeopoliticalEventType.CONFLICT,
                'severity': RiskSeverity.HIGH,
                'title': 'Active Conflict Zone - Eastern Europe',
                'description': 'Ongoing military operations affecting regional stability',
                'region': 'Eastern Europe',
                'countries': ['Ukraine', 'Russia'],
                'coordinates': (48.3794, 31.1656),
            },
            {
                'type': GeopoliticalEventType.HOTSPOT,
                'severity': RiskSeverity.HIGH,
                'title': 'Middle East Tensions - Gulf Region',
                'description': 'Elevated military activity and shipping disruptions',
                'region': 'Middle East',
                'countries': ['Iran', 'Israel', 'Yemen'],
                'coordinates': (27.5142, 53.3573),
            },
            {
                'type': GeopoliticalEventType.SANCTIONS,
                'severity': RiskSeverity.MEDIUM,
                'title': 'Economic Sanctions Update',
                'description': 'New trade restrictions affecting global commodities',
                'region': 'Global',
                'countries': ['Russia', 'Iran'],
                'coordinates': None,
            },
        ]
        
        for event_data in sample_events:
            event = GeopoliticalEvent(
                event_type=event_data['type'],
                severity=event_data['severity'],
                title=event_data['title'],
                description=event_data['description'],
                region=event_data['region'],
                countries=event_data['countries'],
                coordinates=event_data.get('coordinates'),
                timestamp=datetime.now(timezone.utc),
                source='worldmonitor',
                confidence=0.85
            )
            events.append(event)
        
        logger.info(f"Fetched {len(events)} geopolitical events")
        return events
    
    def _assess_gold_impact(self, event: GeopoliticalEvent) -> GoldImpact:
        """
        Assess potential impact on gold prices.
        
        Gold typically rises during:
        - Military conflicts (safe-haven demand)
        - Economic sanctions (trade disruption)
        - Political instability (currency weakness)
        - Natural disasters affecting major economies
        """
        # Start with neutral
        impact_score = 0
        
        # Event type impact
        type_impact = {
            GeopoliticalEventType.CONFLICT: 2,
            GeopoliticalEventType.HOTSPOT: 1,
            GeopoliticalEventType.SANCTIONS: 1,
            GeopoliticalEventType.NATURAL_DISASTER: 1,
            GeopoliticalEventType.INFRASTRUCTURE_OUTAGE: 1,
            GeopoliticalEventType.MILITARY_ACTIVITY: 2,
            GeopoliticalEventType.POLITICAL_UNREST: 1,
            GeopoliticalEventType.CYBER_ATTACK: 1,
            GeopoliticalEventType.ECONOMIC_CRISIS: 2,
            GeopoliticalEventType.TERRORISM: 2,
        }
        impact_score += type_impact.get(event.event_type, 0)
        
        # Severity impact
        severity_impact = {
            RiskSeverity.CRITICAL: 3,
            RiskSeverity.HIGH: 2,
            RiskSeverity.MEDIUM: 1,
            RiskSeverity.LOW: 0,
            RiskSeverity.INFO: 0,
        }
        impact_score += severity_impact.get(event.severity, 0)
        
        # Region impact (gold-sensitive regions)
        for region_key, countries in self.GOLD_SENSITIVE_REGIONS.items():
            if any(country in countries for country in event.countries):
                impact_score += 1
                break
        
        # Check for high-impact keywords
        text = f"{event.title} {event.description}".lower()
        for category, keywords in self.HIGH_IMPACT_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                impact_score += 1
                break
        
        # Map score to gold impact
        if impact_score >= 6:
            return GoldImpact.STRONGLY_BULLISH
        elif impact_score >= 4:
            return GoldImpact.BULLISH
        elif impact_score >= 2:
            return GoldImpact.NEUTRAL
        elif impact_score >= 1:
            return GoldImpact.BEARISH
        else:
            return GoldImpact.NEUTRAL
    
    def _calculate_risk_score(self, event: GeopoliticalEvent) -> float:
        """Calculate risk score for an event (0-100)"""
        score = 0.0
        
        # Base score by severity
        severity_scores = {
            RiskSeverity.CRITICAL: 80,
            RiskSeverity.HIGH: 60,
            RiskSeverity.MEDIUM: 40,
            RiskSeverity.LOW: 20,
            RiskSeverity.INFO: 10,
        }
        score = severity_scores.get(event.severity, 30)
        
        # Adjust by event type
        if event.event_type in [GeopoliticalEventType.CONFLICT, 
                                GeopoliticalEventType.MILITARY_ACTIVITY]:
            score += 15
        
        # Adjust by region significance
        for region_key, countries in self.GOLD_SENSITIVE_REGIONS.items():
            if any(country in countries for country in event.countries):
                score += 10
                break
        
        # Apply confidence
        score *= event.confidence
        
        return min(100, score)
    
    def _get_affected_currencies(self, event: GeopoliticalEvent) -> List[str]:
        """Determine currencies affected by an event"""
        currencies = []
        
        for country in event.countries:
            if country in self.COUNTRY_CURRENCIES:
                currencies.append(self.COUNTRY_CURRENCIES[country])
        
        # Major events affect global reserve currencies
        if event.severity in [RiskSeverity.CRITICAL, RiskSeverity.HIGH]:
            if 'USD' not in currencies:
                currencies.append('USD')
            if 'CHF' not in currencies:
                currencies.append('CHF')  # Swiss franc safe haven
        
        return list(set(currencies))
    
    def _calculate_global_risk(self, events: List[GeopoliticalEvent]) -> float:
        """Calculate overall global risk score"""
        if not events:
            return 20.0  # Base risk level
        
        # Sum weighted risk scores
        total_risk = sum(e.risk_score for e in events)
        
        # Normalize by number of events using power of 0.7 for diminishing returns.
        # This ensures that 10 low-risk events don't outweigh 2 high-risk events.
        # The 0.7 exponent provides sub-linear scaling: more events increase risk
        # but at a decreasing rate, preventing score inflation from noise events.
        DIMINISHING_RETURNS_EXPONENT = 0.7
        avg_risk = total_risk / (len(events) ** DIMINISHING_RETURNS_EXPONENT) if events else 0
        
        # Count critical/high severity events
        critical_count = sum(1 for e in events 
                           if e.severity in [RiskSeverity.CRITICAL, RiskSeverity.HIGH])
        
        # Boost for multiple high-risk events
        risk_boost = min(critical_count * 5, 25)
        
        return min(100, avg_risk + risk_boost)
    
    def _determine_gold_outlook(
        self,
        events: List[GeopoliticalEvent],
        global_risk: float
    ) -> GoldImpact:
        """Determine overall gold outlook based on events"""
        if not events:
            return GoldImpact.NEUTRAL
        
        # Count bullish vs bearish events for gold
        bullish_count = sum(1 for e in events 
                          if e.gold_impact in [GoldImpact.BULLISH, GoldImpact.STRONGLY_BULLISH])
        bearish_count = sum(1 for e in events 
                          if e.gold_impact in [GoldImpact.BEARISH, GoldImpact.STRONGLY_BEARISH])
        
        # Consider global risk level
        if global_risk >= 70:
            return GoldImpact.STRONGLY_BULLISH
        elif global_risk >= 50:
            if bullish_count > bearish_count:
                return GoldImpact.BULLISH
        
        # Default based on event balance
        if bullish_count > bearish_count * 2:
            return GoldImpact.STRONGLY_BULLISH
        elif bullish_count > bearish_count:
            return GoldImpact.BULLISH
        elif bearish_count > bullish_count:
            return GoldImpact.BEARISH
        else:
            return GoldImpact.NEUTRAL
    
    def _identify_high_risk_regions(self, events: List[GeopoliticalEvent]) -> List[str]:
        """Identify regions with highest risk"""
        region_scores = {}
        
        for event in events:
            if event.region not in region_scores:
                region_scores[event.region] = 0
            region_scores[event.region] += event.risk_score
        
        # Sort by risk score
        sorted_regions = sorted(region_scores.items(), key=lambda x: -x[1])
        
        # Return top 5 high-risk regions
        return [region for region, score in sorted_regions[:5] if score >= 30]
    
    def _get_country_risks(
        self,
        events: List[GeopoliticalEvent]
    ) -> Dict[str, CountryRisk]:
        """Calculate risk for individual countries"""
        country_risks = {}
        
        for event in events:
            for country in event.countries:
                if country not in country_risks:
                    country_risks[country] = {
                        'risk_scores': [],
                        'factors': []
                    }
                
                country_risks[country]['risk_scores'].append(event.risk_score)
                country_risks[country]['factors'].append(event.event_type.value)
        
        # Create CountryRisk objects
        result = {}
        for country, data in country_risks.items():
            avg_risk = sum(data['risk_scores']) / len(data['risk_scores'])
            
            # Use ISO country code mapping, fall back to first 2 chars if unknown
            country_code = self.COUNTRY_ISO_CODES.get(country, country[:2].upper())
            
            result[country] = CountryRisk(
                country_code=country_code,
                country_name=country,
                instability_index=avg_risk,
                trend='stable',  # Would need historical data
                risk_factors=list(set(data['factors']))
            )
        
        return result
    
    def _generate_trading_recommendations(
        self,
        events: List[GeopoliticalEvent],
        global_risk: float,
        gold_outlook: GoldImpact
    ) -> List[str]:
        """Generate trading recommendations based on geopolitical situation"""
        recommendations = []
        
        # Risk-based recommendations
        if global_risk >= 70:
            recommendations.append(
                "HIGH ALERT: Elevated geopolitical risk - Consider increasing gold allocation"
            )
            recommendations.append(
                "Reduce exposure to risk assets during heightened uncertainty"
            )
        elif global_risk >= 50:
            recommendations.append(
                "MODERATE RISK: Monitor developing situations - Gold as portfolio hedge"
            )
        else:
            recommendations.append(
                "LOW RISK: Geopolitical environment relatively stable"
            )
        
        # Gold-specific recommendations
        if gold_outlook == GoldImpact.STRONGLY_BULLISH:
            recommendations.append(
                "GOLD BULLISH: Strong safe-haven demand expected - Consider long XAU/USD"
            )
        elif gold_outlook == GoldImpact.BULLISH:
            recommendations.append(
                "GOLD POSITIVE: Moderate safe-haven flows - Favor gold on dips"
            )
        elif gold_outlook == GoldImpact.BEARISH:
            recommendations.append(
                "GOLD CAUTIOUS: Risk-on sentiment may pressure gold - Reduce long exposure"
            )
        
        # Region-specific recommendations
        conflict_events = [e for e in events 
                         if e.event_type == GeopoliticalEventType.CONFLICT]
        if conflict_events:
            regions = set(e.region for e in conflict_events)
            recommendations.append(
                f"Active conflicts in {', '.join(regions)} - Monitor for escalation"
            )
        
        # Sanctions recommendations
        sanctions_events = [e for e in events 
                          if e.event_type == GeopoliticalEventType.SANCTIONS]
        if sanctions_events:
            countries = set()
            for e in sanctions_events:
                countries.update(e.countries)
            recommendations.append(
                f"Sanctions affecting {', '.join(list(countries)[:3])} - Watch commodity flows"
            )
        
        return recommendations
    
    def _calculate_signal_confidence(
        self,
        assessment: GeopoliticalRiskAssessment
    ) -> float:
        """Calculate confidence in the trading signal"""
        confidence = 0.5  # Base confidence
        
        # More events = more data = higher confidence
        event_count = len(assessment.key_events)
        if event_count >= 5:
            confidence += 0.2
        elif event_count >= 3:
            confidence += 0.1
        
        # Clear direction = higher confidence
        if assessment.gold_outlook in [GoldImpact.STRONGLY_BULLISH, 
                                       GoldImpact.STRONGLY_BEARISH]:
            confidence += 0.2
        elif assessment.gold_outlook in [GoldImpact.BULLISH, GoldImpact.BEARISH]:
            confidence += 0.1
        
        # High risk = higher confidence in bullish gold
        if assessment.global_risk_score >= 60:
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid"""
        if self._cache_timestamp is None:
            return False
        
        age = (datetime.now(timezone.utc) - self._cache_timestamp).total_seconds()
        return age < self.cache_ttl


class WorldMonitorIntegration:
    """
    Integration layer for World Monitor dashboard.
    
    World Monitor URL structure (from user's link):
    https://worldmonitor.app/?lat=46.4000&lon=-163.8957&zoom=2.50&view=mena&timeRange=7d&layers=conflicts,hotspots,sanctions,weather,outages,natural
    
    Parameters:
    - lat/lon: Map center coordinates
    - zoom: Map zoom level
    - view: Regional view preset (global, americas, europe, mena, asia, etc.)
    - timeRange: Event time window (1h, 6h, 24h, 48h, 7d)
    - layers: Active data layers (conflicts, hotspots, sanctions, weather, outages, natural)
    """
    
    # Regional view presets with coordinates
    REGIONAL_VIEWS = {
        'global': {'lat': 20.0, 'lon': 0.0, 'zoom': 2.0},
        'americas': {'lat': 20.0, 'lon': -100.0, 'zoom': 3.0},
        'europe': {'lat': 50.0, 'lon': 10.0, 'zoom': 4.0},
        'mena': {'lat': 30.0, 'lon': 45.0, 'zoom': 4.0},  # Middle East & North Africa
        'asia': {'lat': 35.0, 'lon': 105.0, 'zoom': 3.5},
        'africa': {'lat': 0.0, 'lon': 20.0, 'zoom': 3.5},
        'oceania': {'lat': -25.0, 'lon': 135.0, 'zoom': 4.0},
    }
    
    # Available data layers
    DATA_LAYERS = [
        'conflicts',      # Active conflict zones
        'hotspots',       # Intelligence hotspots
        'sanctions',      # Economic sanctions
        'weather',        # Weather alerts
        'outages',        # Infrastructure outages
        'natural',        # Natural disasters
        'military',       # Military activity (bases, flights)
        'protests',       # Social unrest
        'nuclear',        # Nuclear facilities
        'pipelines',      # Energy infrastructure
        'cables',         # Undersea cables
        'datacenters',    # Major data centers
    ]
    
    def __init__(self, config: Optional[Dict] = None):
        """Initialize World Monitor integration"""
        self.config = config or {}
        self.base_url = 'https://worldmonitor.app'
        
        logger.info("WorldMonitorIntegration initialized")
    
    def build_monitor_url(
        self,
        view: str = 'global',
        time_range: str = '7d',
        layers: Optional[List[str]] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        zoom: Optional[float] = None
    ) -> str:
        """
        Build World Monitor dashboard URL.
        
        Args:
            view: Regional view preset
            time_range: Time range (1h, 6h, 24h, 48h, 7d)
            layers: Data layers to enable
            lat: Custom latitude
            lon: Custom longitude
            zoom: Custom zoom level
            
        Returns:
            Complete World Monitor URL
        """
        # Get view coordinates
        view_config = self.REGIONAL_VIEWS.get(view, self.REGIONAL_VIEWS['global'])
        
        # Use custom coordinates if provided
        lat = lat if lat is not None else view_config['lat']
        lon = lon if lon is not None else view_config['lon']
        zoom = zoom if zoom is not None else view_config['zoom']
        
        # Default layers
        if layers is None:
            layers = ['conflicts', 'hotspots', 'sanctions', 'weather', 'outages', 'natural']
        
        # Build URL
        url = f"{self.base_url}/"
        url += f"?lat={lat:.4f}"
        url += f"&lon={lon:.4f}"
        url += f"&zoom={zoom:.2f}"
        url += f"&view={view}"
        url += f"&timeRange={time_range}"
        url += f"&layers={','.join(layers)}"
        
        return url
    
    def get_gold_relevant_views(self) -> Dict[str, str]:
        """
        Get World Monitor URLs for regions most relevant to gold trading.
        
        Returns:
            Dictionary of region names to URLs
        """
        gold_regions = {
            'middle_east': {
                'view': 'mena',
                'layers': ['conflicts', 'hotspots', 'sanctions', 'military']
            },
            'eastern_europe': {
                'view': 'europe',
                'layers': ['conflicts', 'hotspots', 'sanctions', 'military'],
                'lat': 50.0,
                'lon': 30.0,
                'zoom': 4.5
            },
            'asia_pacific': {
                'view': 'asia',
                'layers': ['conflicts', 'hotspots', 'sanctions', 'military']
            },
            'global_overview': {
                'view': 'global',
                'layers': ['conflicts', 'hotspots', 'sanctions', 'weather', 'outages']
            }
        }
        
        urls = {}
        for region, config in gold_regions.items():
            urls[region] = self.build_monitor_url(
                view=config.get('view', 'global'),
                layers=config.get('layers'),
                lat=config.get('lat'),
                lon=config.get('lon'),
                zoom=config.get('zoom'),
                time_range='7d'
            )
        
        return urls


# Global provider instance
_geopolitical_provider = None


def get_geopolitical_provider(config: Optional[Dict] = None) -> GeopoliticalRiskProvider:
    """Get or create global geopolitical risk provider"""
    global _geopolitical_provider
    if _geopolitical_provider is None:
        _geopolitical_provider = GeopoliticalRiskProvider(config)
    return _geopolitical_provider


def get_gold_geopolitical_signal() -> Dict[str, Any]:
    """
    Convenience function to get geopolitical-based gold trading signal.
    
    Returns:
        Trading signal dictionary
    """
    provider = get_geopolitical_provider()
    return provider.get_gold_trading_signal()
