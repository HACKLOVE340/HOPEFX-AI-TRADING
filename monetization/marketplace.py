"""
HOPEFX Marketplace Backend
Strategy listings, pricing engine, subscription management, license validation
"""

import json
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
import sqlite3
import stripe


class SubscriptionTier(Enum):
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class StrategyStatus(Enum):
    DRAFT = "draft"
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


@dataclass
class StrategyListing:
    """Strategy marketplace listing"""
    strategy_id: str
    creator_id: str
    name: str
    description: str
    price_monthly: float
    price_yearly: float
    tier: SubscriptionTier
    status: StrategyStatus
    category: str
    tags: List[str]
    performance_metrics: Dict[str, float]
    created_at: datetime
    updated_at: datetime
    rating: float = 0.0
    review_count: int = 0
    subscriber_count: int = 0
    total_revenue: float = 0.0
    is_featured: bool = False
    
    def to_dict(self) -> Dict:
        return {
            'strategy_id': self.strategy_id,
            'creator_id': self.creator_id,
            'name': self.name,
            'description': self.description,
            'price_monthly': self.price_monthly,
            'price_yearly': self.price_yearly,
            'tier': self.tier.value,
            'status': self.status.value,
            'category': self.category,
            'tags': self.tags,
            'performance_metrics': self.performance_metrics,
            'rating': self.rating,
            'review_count': self.review_count,
            'subscriber_count': self.subscriber_count,
            'total_revenue': self.total_revenue,
            'is_featured': self.is_featured,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


@dataclass
class Subscription:
    """User subscription to a strategy"""
    subscription_id: str
    user_id: str
    strategy_id: str
    tier: SubscriptionTier
    start_date: datetime
    end_date: datetime
    is_active: bool
    auto_renew: bool
    payment_method: str
    last_payment_date: Optional[datetime] = None
    next_payment_date: Optional[datetime] = None
    cancel_at_period_end: bool = False


@dataclass
class LicenseKey:
    """License key for strategy access"""
    license_id: str
    key: str
    user_id: str
    strategy_id: str
    subscription_id: str
    created_at: datetime
    expires_at: datetime
    is_active: bool
    max_activations: int
    current_activations: int = 0
    last_used: Optional[datetime] = None


class MarketplaceDatabase:
    """SQLite database for marketplace data"""
    
    def __init__(self, db_path: str = "monetization/marketplace.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Strategies table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                strategy_id TEXT PRIMARY KEY,
                creator_id TEXT,
                name TEXT,
                description TEXT,
                price_monthly REAL,
                price_yearly REAL,
                tier TEXT,
                status TEXT,
                category TEXT,
                tags TEXT,
                performance_metrics TEXT,
                rating REAL DEFAULT 0.0,
                review_count INTEGER DEFAULT 0,
                subscriber_count INTEGER DEFAULT 0,
                total_revenue REAL DEFAULT 0.0,
                is_featured INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        
        # Subscriptions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                subscription_id TEXT PRIMARY KEY,
                user_id TEXT,
                strategy_id TEXT,
                tier TEXT,
                start_date TEXT,
                end_date TEXT,
                is_active INTEGER,
                auto_renew INTEGER,
                payment_method TEXT,
                last_payment_date TEXT,
                next_payment_date TEXT,
                cancel_at_period_end INTEGER
            )
        """)
        
        # License keys table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                license_id TEXT PRIMARY KEY,
                license_key TEXT UNIQUE,
                user_id TEXT,
                strategy_id TEXT,
                subscription_id TEXT,
                created_at TEXT,
                expires_at TEXT,
                is_active INTEGER,
                max_activations INTEGER,
                current_activations INTEGER DEFAULT 0,
                last_used TEXT
            )
        """)
        
        # Reviews table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                review_id TEXT PRIMARY KEY,
                user_id TEXT,
                strategy_id TEXT,
                rating INTEGER,
                comment TEXT,
                created_at TEXT
            )
        """)
        
        # Transactions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                user_id TEXT,
                strategy_id TEXT,
                subscription_id TEXT,
                amount REAL,
                currency TEXT,
                status TEXT,
                payment_provider TEXT,
                payment_id TEXT,
                created_at TEXT
            )
        """)
        
        conn.commit()
        conn.close()
    
    def save_strategy(self, strategy: StrategyListing):
        """Save strategy to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO strategies 
            (strategy_id, creator_id, name, description, price_monthly, price_yearly,
             tier, status, category, tags, performance_metrics, rating, review_count,
             subscriber_count, total_revenue, is_featured, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            strategy.strategy_id, strategy.creator_id, strategy.name,
            strategy.description, strategy.price_monthly, strategy.price_yearly,
            strategy.tier.value, strategy.status.value, strategy.category,
            json.dumps(strategy.tags), json.dumps(strategy.performance_metrics),
            strategy.rating, strategy.review_count, strategy.subscriber_count,
            strategy.total_revenue, int(strategy.is_featured),
            strategy.created_at.isoformat(), strategy.updated_at.isoformat()
        ))
        conn.commit()
        conn.close()
    
    def get_strategy(self, strategy_id: str) -> Optional[StrategyListing]:
        """Get strategy by ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM strategies WHERE strategy_id = ?", (strategy_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return self._row_to_strategy(row)
        return None
    
    def _row_to_strategy(self, row) -> StrategyListing:
        """Convert database row to StrategyListing"""
        return StrategyListing(
            strategy_id=row[0],
            creator_id=row[1],
            name=row[2],
            description=row[3],
            price_monthly=row[4],
            price_yearly=row[5],
            tier=SubscriptionTier(row[6]),
            status=StrategyStatus(row[7]),
            category=row[8],
            tags=json.loads(row[9]),
            performance_metrics=json.loads(row[10]),
            rating=row[11],
            review_count=row[12],
            subscriber_count=row[13],
            total_revenue=row[14],
            is_featured=bool(row[15]),
            created_at=datetime.fromisoformat(row[16]),
            updated_at=datetime.fromisoformat(row[17])
        )
    
    def search_strategies(self, category: Optional[str] = None,
                         tier: Optional[SubscriptionTier] = None,
                         min_rating: float = 0.0,
                         sort_by: str = "rating") -> List[StrategyListing]:
        """Search strategies with filters"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = "SELECT * FROM strategies WHERE status = 'active' AND rating >= ?"
        params = [min_rating]
        
        if category:
            query += " AND category = ?"
            params.append(category)
        
        if tier:
            query += " AND tier = ?"
            params.append(tier.value)
        
        # Sorting
        sort_map = {
            "rating": "rating DESC",
            "price_asc": "price_monthly ASC",
            "price_desc": "price_monthly DESC",
            "popularity": "subscriber_count DESC",
            "newest": "created_at DESC"
        }
        query += f" ORDER BY {sort_map.get(sort_by, 'rating DESC')}"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_strategy(row) for row in rows]


class PricingEngine:
    """Dynamic pricing and discount engine"""
    
    def __init__(self):
        self.discounts: Dict[str, Any] = {}
    
    def calculate_price(self, base_price: float, tier: SubscriptionTier,
                       billing_cycle: str = "monthly",
                       user_id: Optional[str] = None,
                       coupon_code: Optional[str] = None) -> Dict[str, float]:
        """
        Calculate final price with discounts
        
        Returns:
            Dict with base_price, discount_amount, final_price
        """
        discount = 0.0
        
        # Yearly discount (2 months free)
        if billing_cycle == "yearly":
            discount += base_price * 0.1667  # 16.67% discount
        
        # Tier-based discount
        tier_discounts = {
            SubscriptionTier.FREE: 1.0,      # 100% off
            SubscriptionTier.BASIC: 0.0,
            SubscriptionTier.PRO: 0.1,       # 10% off
            SubscriptionTier.ENTERPRISE: 0.2  # 20% off
        }
        discount += base_price * tier_discounts.get(tier, 0.0)
        
        # Coupon discount
        if coupon_code and coupon_code in self.discounts:
            discount += base_price * self.discounts[coupon_code]
        
        final_price = max(0, base_price - discount)
        
        return {
            'base_price': base_price,
            'discount_amount': discount,
            'final_price': final_price,
            'savings_percentage': (discount / base_price * 100) if base_price > 0 else 0
        }
    
    def add_coupon(self, code: str, discount_percent: float, expires_at: Optional[datetime] = None):
        """Add coupon code"""
        self.discounts[code] = discount_percent / 100
    
    def get_recommended_tier(self, trading_volume: float, account_balance: float) -> SubscriptionTier:
        """Recommend subscription tier based on user profile"""
        if account_balance < 1000:
            return SubscriptionTier.FREE
        elif trading_volume < 100000:
            return SubscriptionTier.BASIC
        elif trading_volume < 1000000:
            return SubscriptionTier.PRO
        else:
            return SubscriptionTier.ENTERPRISE


class LicenseManager:
    """License key generation and validation"""
    
    def __init__(self, db: MarketplaceDatabase):
        self.db = db
    
    def generate_license_key(self, user_id: str, strategy_id: str,
                            subscription_id: str, expires_at: datetime,
                            max_activations: int = 1) -> LicenseKey:
        """Generate new license key"""
        license_id = secrets.token_hex(16)
        
        # Generate key in format: XXXX-XXXX-XXXX-XXXX
        key_parts = [secrets.token_hex(4).upper() for _ in range(4)]
        key = "-".join(key_parts)
        
        license_key = LicenseKey(
            license_id=license_id,
            key=key,
            user_id=user_id,
            strategy_id=strategy_id,
            subscription_id=subscription_id,
            created_at=datetime.now(),
            expires_at=expires_at,
            is_active=True,
            max_activations=max_activations
        )
        
        # Save to database
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO licenses 
            (license_id, license_key, user_id, strategy_id, subscription_id,
             created_at, expires_at, is_active, max_activations)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            license_key.license_id, license_key.key, license_key.user_id,
            license_key.strategy_id, license_key.subscription_id,
            license_key.created_at.isoformat(), license_key.expires_at.isoformat(),
            int(license_key.is_active), license_key.max_activations
        ))
        conn.commit()
        conn.close()
        
        return license_key
    
    def validate_license(self, key: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Validate license key
        
        Returns:
            Dict with valid (bool), message, and license data
        """
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM licenses WHERE license_key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return {'valid': False, 'message': 'Invalid license key'}
        
        license_data = {
            'license_id': row[0],
            'key': row[1],
            'user_id': row[2],
            'strategy_id': row[3],
            'is_active': bool(row[7]),
            'expires_at': datetime.fromisoformat(row[6]),
            'max_activations': row[8],
            'current_activations': row[9]
        }
        
        # Check if active
        if not license_data['is_active']:
            return {'valid': False, 'message': 'License is deactivated', 'license': license_data}
        
        # Check expiration
        if datetime.now() > license_data['expires_at']:
            return {'valid': False, 'message': 'License has expired', 'license': license_data}
        
        # Check user match if provided
        if user_id and user_id != license_data['user_id']:
            return {'valid': False, 'message': 'License not valid for this user', 'license': license_data}
        
        # Check activation limit
        if license_data['current_activations'] >= license_data['max_activations']:
            return {'valid': False, 'message': 'Maximum activations reached', 'license': license_data}
        
        return {
            'valid': True,
            'message': 'License valid',
            'license': license_data
        }
    
    def activate_license(self, key: str, device_id: str) -> bool:
        """Activate license on a device"""
        validation = self.validate_license(key)
        
        if not validation['valid']:
            return False
        
        license_id = validation['license']['license_id']
        
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE licenses 
            SET current_activations = current_activations + 1,
                last_used = ?
            WHERE license_id = ?
        """, (datetime.now().isoformat(), license_id))
        conn.commit()
        conn.close()
        
        return True
    
    def revoke_license(self, license_id: str) -> bool:
        """Revoke a license"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE licenses SET is_active = 0 WHERE license_id = ?
        """, (license_id,))
        conn.commit()
        conn.close()
        return True


class SubscriptionManager:
    """Manage user subscriptions"""
    
    def __init__(self, db: MarketplaceDatabase, stripe_key: Optional[str] = None):
        self.db = db
        self.pricing = PricingEngine()
        self.licenses = LicenseManager(db)
        
        if stripe_key:
            stripe.api_key = stripe_key
    
    def create_subscription(self, user_id: str, strategy_id: str,
                           tier: SubscriptionTier, billing_cycle: str = "monthly",
                           auto_renew: bool = True) -> Optional[Subscription]:
        """Create new subscription"""
        strategy = self.db.get_strategy(strategy_id)
        if not strategy:
            print(f"❌ Strategy {strategy_id} not found")
            return None
        
        # Calculate price
        base_price = strategy.price_monthly if billing_cycle == "monthly" else strategy.price_yearly
        price_info = self.pricing.calculate_price(base_price, tier, billing_cycle)
        
        # Create subscription
        subscription_id = secrets.token_hex(16)
        start_date = datetime.now()
        
        if billing_cycle == "monthly":
            end_date = start_date + timedelta(days=30)
        else:
            end_date = start_date + timedelta(days=365)
        
        subscription = Subscription(
            subscription_id=subscription_id,
            user_id=user_id,
            strategy_id=strategy_id,
            tier=tier,
            start_date=start_date,
            end_date=end_date,
            is_active=True,
            auto_renew=auto_renew,
            payment_method="stripe",
            next_payment_date=end_date if auto_renew else None
        )
        
        # Save to database
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscriptions 
            (subscription_id, user_id, strategy_id, tier, start_date, end_date,
             is_active, auto_renew, payment_method, next_payment_date, cancel_at_period_end)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            subscription.subscription_id, subscription.user_id, subscription.strategy_id,
            subscription.tier.value, subscription.start_date.isoformat(),
            subscription.end_date.isoformat(), int(subscription.is_active),
            int(subscription.auto_renew), subscription.payment_method,
            subscription.next_payment_date.isoformat() if subscription.next_payment_date else None,
            int(subscription.cancel_at_period_end)
        ))
        conn.commit()
        conn.close()
        
        # Generate license key
        license_key = self.licenses.generate_license_key(
            user_id, strategy_id, subscription_id, end_date
        )
        
        # Update strategy subscriber count
        strategy.subscriber_count += 1
        self.db.save_strategy(strategy)
        
        print(f"✅ Subscription created: {subscription_id}")
        print(f"   License key: {license_key.key}")
        
        return subscription
    
    def cancel_subscription(self, subscription_id: str, immediate: bool = False) -> bool:
        """Cancel subscription"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        if immediate:
            cursor.execute("""
                UPDATE subscriptions 
                SET is_active = 0, cancel_at_period_end = 0
                WHERE subscription_id = ?
            """, (subscription_id,))
        else:
            cursor.execute("""
                UPDATE subscriptions 
                SET cancel_at_period_end = 1
                WHERE subscription_id = ?
            """, (subscription_id,))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Subscription {subscription_id} cancelled")
        return True
    
    def check_access(self, user_id: str, strategy_id: str) -> bool:
        """Check if user has active access to strategy"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM subscriptions 
            WHERE user_id = ? AND strategy_id = ? AND is_active = 1
            AND end_date > ?
        """, (user_id, strategy_id, datetime.now().isoformat()))
        row = cursor.fetchone()
        conn.close()
        
        return row is not None


class MarketplaceAPI:
    """Main marketplace API"""
    
    def __init__(self, stripe_key: Optional[str] = None):
        self.db = MarketplaceDatabase()
        self.subscriptions = SubscriptionManager(self.db, stripe_key)
        self.pricing = PricingEngine()
    
    def list_strategy(self, creator_id: str, name: str, description: str,
                     price_monthly: float, price_yearly: float,
                     category: str, tags: List[str],
                     performance_metrics: Dict[str, float]) -> StrategyListing:
        """List new strategy on marketplace"""
        import uuid
        
        strategy_id = str(uuid.uuid4())
        
        strategy = StrategyListing(
            strategy_id=strategy_id,
            creator_id=creator_id,
            name=name,
            description=description,
            price_monthly=price_monthly,
            price_yearly=price_yearly,
            tier=SubscriptionTier.BASIC if price_monthly > 0 else SubscriptionTier.FREE,
            status=StrategyStatus.PENDING,
            category=category,
            tags=tags,
            performance_metrics=performance_metrics,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        self.db.save_strategy(strategy)
        print(f"✅ Strategy listed: {name} (ID: {strategy_id})")
        
        return strategy
    
    def approve_strategy(self, strategy_id: str) -> bool:
        """Approve strategy for marketplace"""
        strategy = self.db.get_strategy(strategy_id)
        if strategy:
            strategy.status = StrategyStatus.ACTIVE
            strategy.updated_at = datetime.now()
            self.db.save_strategy(strategy)
            print(f"✅ Strategy {strategy_id} approved")
            return True
        return False
    
    def get_featured_strategies(self, limit: int = 10) -> List[StrategyListing]:
        """Get featured strategies"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM strategies 
            WHERE is_featured = 1 AND status = 'active'
            ORDER BY rating DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        return [self.db._row_to_strategy(row) for row in rows]
    
    def get_creator_stats(self, creator_id: str) -> Dict:
        """Get creator statistics"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        # Get strategies
        cursor.execute("""
            SELECT COUNT(*), SUM(subscriber_count), SUM(total_revenue)
            FROM strategies WHERE creator_id = ?
        """, (creator_id,))
        row = cursor.fetchone()
        
        conn.close()
        
        return {
            'total_strategies': row[0] or 0,
            'total_subscribers': row[1] or 0,
            'total_revenue': row[2] or 0.0
        }


if __name__ == "__main__":
    print("HOPEFX Marketplace Backend")
    print("Features:")
    print("  ✅ Strategy listings with approval workflow")
    print("  ✅ Dynamic pricing engine with discounts")
    print("  ✅ Subscription management (monthly/yearly)")
    print("  ✅ License key generation and validation")
    print("  ✅ SQLite database for persistence")
    print("  ✅ Creator revenue tracking")
    print("  ✅ Strategy search and filtering")


# ── Compatibility aliases expected by monetization/__init__.py ────────────────
import enum as _enum

class StrategyCategory(_enum.Enum):
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    SCALPING = "scalping"
    ARBITRAGE = "arbitrage"
    ML_BASED = "ml_based"
    CUSTOM = "custom"

class StrategyLicenseType(_enum.Enum):
    FREE = "free"
    ONE_TIME = "one_time"
    SUBSCRIPTION = "subscription"
    REVENUE_SHARE = "revenue_share"

class PurchaseStatus(_enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"

# Dataclass-style aliases
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

@dataclass
class MarketplaceStrategy:
    id: str = ""
    name: str = ""
    description: str = ""
    category: StrategyCategory = StrategyCategory.CUSTOM
    license_type: StrategyLicenseType = StrategyLicenseType.FREE
    price: float = 0.0
    author_id: str = ""
    status: StrategyStatus = StrategyStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class StrategyPurchase:
    id: str = ""
    user_id: str = ""
    strategy_id: str = ""
    status: PurchaseStatus = PurchaseStatus.ACTIVE
    purchased_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class StrategyReview:
    id: str = ""
    user_id: str = ""
    strategy_id: str = ""
    rating: int = 5
    comment: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)

# StrategyMarketplace is an alias for MarketplaceAPI
StrategyMarketplace = MarketplaceAPI

# Module-level singleton
strategy_marketplace = MarketplaceAPI()


@dataclass
class StrategyPerformance:
    """Performance metrics for a marketplace strategy."""
    strategy_id: str
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    avg_trade_duration_hours: float = 0.0
    calmar_ratio: float = 0.0
    profit_factor: float = 0.0
    period_days: int = 90
    updated_at: datetime = field(default_factory=datetime.utcnow)
