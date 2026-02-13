"""
Invoice Generation System

This module handles invoice creation, management, and PDF generation.
Invoices include access codes and are sent to users upon payment confirmation.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, List
from decimal import Decimal
from enum import Enum

from .pricing import SubscriptionTier, pricing_manager


logger = logging.getLogger(__name__)


class InvoiceStatus(str, Enum):
    """Invoice status enumeration"""
    DRAFT = "draft"
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    OVERDUE = "overdue"


class Invoice:
    """Invoice model"""

    def __init__(
        self,
        invoice_id: str,
        invoice_number: str,
        user_id: str,
        subscription_id: str,
        tier: SubscriptionTier,
        amount: Decimal,
        currency: str = "USD",
        access_code: Optional[str] = None,
        status: InvoiceStatus = InvoiceStatus.DRAFT
    ):
        self.invoice_id = invoice_id
        self.invoice_number = invoice_number
        self.user_id = user_id
        self.subscription_id = subscription_id
        self.tier = tier
        self.amount = amount
        self.currency = currency
        self.access_code = access_code
        self.status = status
        self.created_at = datetime.utcnow()
        self.due_date = datetime.utcnow()
        self.paid_at: Optional[datetime] = None
        self.cancelled_at: Optional[datetime] = None
        self.items: List[Dict] = []
        self.notes: str = ""

    def add_item(
        self,
        description: str,
        amount: Decimal,
        quantity: int = 1
    ) -> None:
        """Add line item to invoice"""
        self.items.append({
            'description': description,
            'amount': float(amount),
            'quantity': quantity,
            'total': float(amount * quantity)
        })

    def mark_paid(self) -> None:
        """Mark invoice as paid"""
        self.status = InvoiceStatus.PAID
        self.paid_at = datetime.utcnow()
        logger.info(f"Invoice {self.invoice_number} marked as paid")

    def mark_cancelled(self) -> None:
        """Mark invoice as cancelled"""
        self.status = InvoiceStatus.CANCELLED
        self.cancelled_at = datetime.utcnow()
        logger.info(f"Invoice {self.invoice_number} cancelled")

    def mark_refunded(self) -> None:
        """Mark invoice as refunded"""
        self.status = InvoiceStatus.REFUNDED
        logger.info(f"Invoice {self.invoice_number} refunded")

    def is_overdue(self) -> bool:
        """Check if invoice is overdue"""
        if self.status == InvoiceStatus.PAID:
            return False
        return datetime.utcnow() > self.due_date

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'invoice_id': self.invoice_id,
            'invoice_number': self.invoice_number,
            'user_id': self.user_id,
            'subscription_id': self.subscription_id,
            'tier': self.tier.value,
            'amount': float(self.amount),
            'currency': self.currency,
            'access_code': self.access_code,
            'status': self.status.value,
            'created_at': self.created_at.isoformat(),
            'due_date': self.due_date.isoformat(),
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'items': self.items,
            'notes': self.notes,
            'is_overdue': self.is_overdue()
        }


class InvoiceGenerator:
    """Generate and manage invoices"""

    def __init__(self):
        self._invoices: Dict[str, Invoice] = {}
        self._invoice_counter = 1

    def _generate_invoice_number(self) -> str:
        """Generate unique invoice number"""
        now = datetime.utcnow()
        number = f"INV-{now.year}-{self._invoice_counter:06d}"
        self._invoice_counter += 1
        return number

    def create_invoice(
        self,
        user_id: str,
        subscription_id: str,
        tier: SubscriptionTier,
        access_code: Optional[str] = None,
        duration_months: int = 1
    ) -> Invoice:
        """Create a new invoice for subscription"""
        import uuid

        invoice_id = f"INV-{uuid.uuid4().hex[:12].upper()}"
        invoice_number = self._generate_invoice_number()

        # Get tier pricing
        tier_price = pricing_manager.get_tier_price(tier)
        amount = tier_price * duration_months

        invoice = Invoice(
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            user_id=user_id,
            subscription_id=subscription_id,
            tier=tier,
            amount=amount,
            currency="USD",
            access_code=access_code,
            status=InvoiceStatus.PENDING
        )

        # Add subscription as line item
        tier_name = pricing_manager.get_tier(tier).name if pricing_manager.get_tier(tier) else tier.value
        invoice.add_item(
            description=f"{tier_name} Subscription ({duration_months} month{'s' if duration_months > 1 else ''})",
            amount=tier_price,
            quantity=duration_months
        )

        # Add access code to notes
        if access_code:
            invoice.notes = f"Access Code: {access_code}\nValid for {30 * duration_months} days"

        self._invoices[invoice_id] = invoice

        logger.info(f"Created invoice {invoice_number} for ${amount} ({tier.value})")
        return invoice

    def create_commission_invoice(
        self,
        user_id: str,
        commission_amount: Decimal,
        period: str = "Monthly"
    ) -> Invoice:
        """Create invoice for commissions"""
        import uuid

        invoice_id = f"INV-{uuid.uuid4().hex[:12].upper()}"
        invoice_number = self._generate_invoice_number()

        invoice = Invoice(
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            user_id=user_id,
            subscription_id="COMMISSION",
            tier=SubscriptionTier.PROFESSIONAL,  # Default tier
            amount=commission_amount,
            currency="USD",
            status=InvoiceStatus.PENDING
        )

        invoice.add_item(
            description=f"{period} Trading Commissions",
            amount=commission_amount,
            quantity=1
        )

        self._invoices[invoice_id] = invoice

        logger.info(f"Created commission invoice {invoice_number} for ${commission_amount}")
        return invoice

    def get_invoice(self, invoice_id: str) -> Optional[Invoice]:
        """Get invoice by ID"""
        return self._invoices.get(invoice_id)

    def get_invoice_by_number(self, invoice_number: str) -> Optional[Invoice]:
        """Get invoice by number"""
        for invoice in self._invoices.values():
            if invoice.invoice_number == invoice_number:
                return invoice
        return None

    def get_user_invoices(self, user_id: str) -> List[Invoice]:
        """Get all invoices for a user"""
        return [inv for inv in self._invoices.values() if inv.user_id == user_id]

    def get_pending_invoices(self, user_id: Optional[str] = None) -> List[Invoice]:
        """Get pending invoices"""
        invoices = self._invoices.values()
        if user_id:
            invoices = [inv for inv in invoices if inv.user_id == user_id]
        return [inv for inv in invoices if inv.status == InvoiceStatus.PENDING]

    def get_paid_invoices(self, user_id: Optional[str] = None) -> List[Invoice]:
        """Get paid invoices"""
        invoices = self._invoices.values()
        if user_id:
            invoices = [inv for inv in invoices if inv.user_id == user_id]
        return [inv for inv in invoices if inv.status == InvoiceStatus.PAID]

    def get_overdue_invoices(self, user_id: Optional[str] = None) -> List[Invoice]:
        """Get overdue invoices"""
        invoices = self._invoices.values()
        if user_id:
            invoices = [inv for inv in invoices if inv.user_id == user_id]
        return [inv for inv in invoices if inv.is_overdue()]

    def mark_invoice_paid(self, invoice_id: str) -> bool:
        """Mark invoice as paid"""
        invoice = self.get_invoice(invoice_id)
        if not invoice:
            return False

        invoice.mark_paid()
        return True

    def cancel_invoice(self, invoice_id: str) -> bool:
        """Cancel invoice"""
        invoice = self.get_invoice(invoice_id)
        if not invoice:
            return False

        invoice.mark_cancelled()
        return True

    def refund_invoice(self, invoice_id: str) -> bool:
        """Refund invoice"""
        invoice = self.get_invoice(invoice_id)
        if not invoice:
            return False

        invoice.mark_refunded()
        return True

    def get_invoice_stats(self, user_id: Optional[str] = None) -> Dict:
        """Get invoice statistics"""
        if user_id:
            invoices = self.get_user_invoices(user_id)
        else:
            invoices = list(self._invoices.values())

        total = len(invoices)
        pending = len([inv for inv in invoices if inv.status == InvoiceStatus.PENDING])
        paid = len([inv for inv in invoices if inv.status == InvoiceStatus.PAID])
        overdue = len([inv for inv in invoices if inv.is_overdue()])

        total_amount = sum(inv.amount for inv in invoices)
        paid_amount = sum(inv.amount for inv in invoices if inv.status == InvoiceStatus.PAID)
        pending_amount = sum(inv.amount for inv in invoices if inv.status == InvoiceStatus.PENDING)

        return {
            'total_invoices': total,
            'pending_invoices': pending,
            'paid_invoices': paid,
            'overdue_invoices': overdue,
            'total_amount': float(total_amount),
            'paid_amount': float(paid_amount),
            'pending_amount': float(pending_amount)
        }

    def generate_pdf(self, invoice_id: str) -> Optional[bytes]:
        """Generate PDF for invoice (placeholder)"""
        invoice = self.get_invoice(invoice_id)
        if not invoice:
            return None

        # TODO: Implement PDF generation using reportlab or similar
        # For now, return placeholder
        logger.info(f"PDF generation requested for invoice {invoice.invoice_number}")
        return b"PDF placeholder"


# Global invoice generator instance
invoice_generator = InvoiceGenerator()
