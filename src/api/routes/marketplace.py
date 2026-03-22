"""
Marketplace API endpoints for copy trading and strategy licensing.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from src.marketplace.licensing import LicenseManager, LicenseType
from src.marketplace.replication import CopyTradingEngine, CopyTrader
from src.marketplace.payments import PaymentProcessor

router = APIRouter()

license_manager = LicenseManager()
copy_engine = CopyTradingEngine()
payment_processor = PaymentProcessor()


@router.post("/licenses")
async def purchase_license(
    strategy_id: str,
    license_type: LicenseType,
    user_id: str,
    payment_method: dict[str, Any]
):
    """Purchase strategy license."""
    # Create payment intent
    prices = {
        LicenseType.TRIAL: 0,
        LicenseType.BASIC: 99,
        LicenseType.PRO: 299,
        LicenseType.ENTERPRISE: 999
    }
    
    amount = prices.get(license_type, 0)
    
    if amount > 0:
        payment = await payment_processor.create_payment_intent(
            amount=amount,
            currency="USD",
            user_id=user_id,
            strategy_id=strategy_id
        )
        
        # In real implementation, wait for payment confirmation
        # For now, issue license immediately
        license = license_manager.issue_license(
            strategy_id=strategy_id,
            user_id=user_id,
            license_type=license_type
        )
        
        return {
            "license_id": license.license_id,
            "payment_intent": payment.payment_id,
            "status": "pending_payment"
        }
    
    # Free trial
    license = license_manager.issue_license(
        strategy_id=strategy_id,
        user_id=user_id,
        license_type=license_type,
        duration_days=7
    )
    
    return {
        "license_id": license.license_id,
        "expires_at": license.expires_at.isoformat(),
        "features": license.features
    }


@router.get("/licenses/{license_id}")
async def verify_license(license_id: str):
    """Verify license validity."""
    # In production, query database
    return {"license_id": license_id, "valid": True}


@router.post("/copy-trading")
async def start_copy_trading(config: dict[str, Any]):
    """Start copy trading."""
    copier = CopyTrader(
        trader_id=config["trader_id"],
        leader_id=config["leader_id"],
        copy_ratio=config.get("copy_ratio", 1.0),
        max_position_size=config.get("max_position_size", 100),
        risk_adjustment=config.get("risk_adjustment", "proportional"),
        stop_copy_if_drawdown=config.get("stop_copy_if_drawdown", 0.2)
    )
    
    await copy_engine.register_copier(copier)
    
    return {
        "copier_id": copier.trader_id,
        "leader_id": copier.leader_id,
        "status": "active"
    }


@router.get("/leaders")
async def list_leaders():
    """List top performing strategy leaders."""
    # In production, query from database with performance metrics
    return {
        "leaders": [
            {
                "leader_id": "leader_001",
                "strategy": "XAUUSD ML Ensemble",
                "total_return": 0.35,
                "sharpe_ratio": 1.8,
                "max_drawdown": 0.08,
                "followers": 150,
                "monthly_fee": 50
            }
        ]
    }


@router.post("/webhooks/stripe")
async def stripe_webhook(payload: bytes, signature: str):
    """Handle Stripe webhooks."""
    result = await payment_processor.handle_webhook(payload, signature)
    return result
