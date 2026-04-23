# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Invoice Generation System

This module handles invoice creation, management, and PDF generation.
Invoices include access codes and are sent to users upon payment confirmation.
"""

import logging
from datetime import datetime, timezone

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # Python 3.10 compat
        pass


UTC = timezone.utc
from decimal import Decimal

from .pricing import SubscriptionTier, pricing_manager
from .subscription import subscription_manager

logger = logging.getLogger(__name__)


class InvoiceStatus(StrEnum):
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
        access_code: str | None = None,
        status: InvoiceStatus = InvoiceStatus.DRAFT,
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
        self.created_at = datetime.now(UTC)
        self.due_date = datetime.now(UTC)
        self.paid_at: datetime | None = None
        self.cancelled_at: datetime | None = None
        self.items: list[dict] = []
        self.notes: str = ""

    def add_item(self, description: str, amount: Decimal, quantity: int = 1) -> None:
        """Add line item to invoice"""
        self.items.append(
            {
                "description": description,
                "amount": float(amount),
                "quantity": quantity,
                "total": float(amount * quantity),
            }
        )

    def mark_paid(self) -> None:
        """Mark invoice as paid"""
        self.status = InvoiceStatus.PAID
        self.paid_at = datetime.now(UTC)
        logger.info("Invoice %s marked as paid", self.invoice_number)

    def mark_cancelled(self) -> None:
        """Mark invoice as cancelled"""
        self.status = InvoiceStatus.CANCELLED
        self.cancelled_at = datetime.now(UTC)
        logger.info("Invoice %s cancelled", self.invoice_number)

    def mark_refunded(self) -> None:
        """Mark invoice as refunded"""
        self.status = InvoiceStatus.REFUNDED
        logger.info("Invoice %s refunded", self.invoice_number)

    def is_overdue(self) -> bool:
        """Check if invoice is overdue"""
        if self.status == InvoiceStatus.PAID:
            return False
        return datetime.now(UTC) > self.due_date

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "invoice_id": self.invoice_id,
            "invoice_number": self.invoice_number,
            "user_id": self.user_id,
            "subscription_id": self.subscription_id,
            "tier": self.tier.value,
            "amount": float(self.amount),
            "currency": self.currency,
            "access_code": self.access_code,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "due_date": self.due_date.isoformat(),
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "items": self.items,
            "notes": self.notes,
            "is_overdue": self.is_overdue(),
        }


class InvoiceGenerator:
    """Generate and manage invoices"""

    def __init__(self):
        self._invoices: dict[str, Invoice] = {}
        self._invoice_counter = 1

    def _generate_invoice_number(self) -> str:
        """Generate unique invoice number"""
        now = datetime.now(UTC)
        number = f"INV-{now.year}-{self._invoice_counter:06d}"
        self._invoice_counter += 1
        return number

    def create_invoice(
        self,
        user_id: str,
        subscription_id: str,
        tier: SubscriptionTier,
        access_code: str | None = None,
        duration_months: int = 1,
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
            status=InvoiceStatus.PENDING,
        )

        # Add subscription as line item
        tier_name = pricing_manager.get_tier(tier).name if pricing_manager.get_tier(tier) else tier.value
        invoice.add_item(
            description=f"{tier_name} Subscription ({duration_months} month{'s' if duration_months > 1 else ''})",
            amount=tier_price,
            quantity=duration_months,
        )

        # Add access code to notes
        if access_code:
            invoice.notes = f"Access Code: {access_code}\nValid for {30 * duration_months} days"

        self._invoices[invoice_id] = invoice

        logger.info("Created invoice %s for $%s (%s)", invoice_number, amount, tier.value)

        return invoice

    def create_commission_invoice(self, user_id: str, commission_amount: Decimal, period: str = "Monthly") -> Invoice:
        """Create invoice for commissions"""
        import uuid

        invoice_id = f"INV-{uuid.uuid4().hex[:12].upper()}"
        invoice_number = self._generate_invoice_number()

        sub = subscription_manager.get_user_subscription(user_id)
        user_tier = sub.tier if sub else SubscriptionTier.FREE

        invoice = Invoice(
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            user_id=user_id,
            subscription_id=sub.subscription_id if sub else "COMMISSION",
            tier=user_tier,
            amount=commission_amount,
            currency="USD",
            status=InvoiceStatus.PENDING,
        )

        invoice.add_item(
            description=f"{period} Trading Commissions",
            amount=commission_amount,
            quantity=1,
        )

        self._invoices[invoice_id] = invoice

        logger.info("Created commission invoice %s for $%s", invoice_number, commission_amount)

        return invoice

    def get_invoice(self, invoice_id: str) -> Invoice | None:
        """Get invoice by ID"""
        return self._invoices.get(invoice_id)

    def get_invoice_by_number(self, invoice_number: str) -> Invoice | None:
        """Get invoice by number"""
        for invoice in self._invoices.values():
            if invoice.invoice_number == invoice_number:
                return invoice
        return None

    def get_user_invoices(self, user_id: str) -> list[Invoice]:
        """Get all invoices for a user"""
        return [inv for inv in self._invoices.values() if inv.user_id == user_id]

    def get_pending_invoices(self, user_id: str | None = None) -> list[Invoice]:
        """Get pending invoices"""
        invoices = self._invoices.values()
        if user_id:
            invoices = [inv for inv in invoices if inv.user_id == user_id]
        return [inv for inv in invoices if inv.status == InvoiceStatus.PENDING]

    def get_paid_invoices(self, user_id: str | None = None) -> list[Invoice]:
        """Get paid invoices"""
        invoices = self._invoices.values()
        if user_id:
            invoices = [inv for inv in invoices if inv.user_id == user_id]
        return [inv for inv in invoices if inv.status == InvoiceStatus.PAID]

    def get_overdue_invoices(self, user_id: str | None = None) -> list[Invoice]:
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

    def get_invoice_stats(self, user_id: str | None = None) -> dict:
        """Get invoice statistics"""
        invoices = self.get_user_invoices(user_id) if user_id else list(self._invoices.values())

        total = len(invoices)
        pending = len([inv for inv in invoices if inv.status == InvoiceStatus.PENDING])
        paid = len([inv for inv in invoices if inv.status == InvoiceStatus.PAID])
        overdue = len([inv for inv in invoices if inv.is_overdue()])

        total_amount = sum(inv.amount for inv in invoices)
        paid_amount = sum(inv.amount for inv in invoices if inv.status == InvoiceStatus.PAID)
        pending_amount = sum(inv.amount for inv in invoices if inv.status == InvoiceStatus.PENDING)

        return {
            "total_invoices": total,
            "pending_invoices": pending,
            "paid_invoices": paid,
            "overdue_invoices": overdue,
            "total_amount": float(total_amount),
            "paid_amount": float(paid_amount),
            "pending_amount": float(pending_amount),
        }

    def generate_pdf(self, invoice_id: str) -> bytes | None:
        """
        Generate PDF for invoice.

        Returns:
            PDF bytes or None if invoice not found
        """
        invoice = self.get_invoice(invoice_id)
        if not invoice:
            return None

        try:
            # Try to import reportlab if available
            try:
                from io import BytesIO

                from reportlab.lib import colors
                from reportlab.lib.pagesizes import letter
                from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
                from reportlab.lib.units import inch
                from reportlab.platypus import (
                    Paragraph,
                    SimpleDocTemplate,
                    Spacer,
                    Table,
                    TableStyle,
                )

                # Create PDF buffer
                buffer = BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=letter)

                # Container for elements
                elements = []
                styles = getSampleStyleSheet()

                # Custom title style
                title_style = ParagraphStyle(
                    "CustomTitle",
                    parent=styles["Heading1"],
                    fontSize=24,
                    textColor=colors.HexColor("#2C3E50"),
                    spaceAfter=30,
                    alignment=1,  # Center
                )

                # Add title
                elements.append(Paragraph("INVOICE", title_style))
                elements.append(Spacer(1, 0.2 * inch))

                # Invoice header info
                header_data = [
                    ["Invoice Number:", invoice.invoice_number],
                    ["Invoice ID:", invoice.invoice_id],
                    ["Date:", invoice.created_at.strftime("%Y-%m-%d %H:%M:%S")],
                    ["Status:", invoice.status.value.upper()],
                ]

                if invoice.paid_at:
                    header_data.append(["Paid At:", invoice.paid_at.strftime("%Y-%m-%d %H:%M:%S")])

                header_table = Table(header_data, colWidths=[2 * inch, 4 * inch])
                header_table.setStyle(
                    TableStyle(
                        [
                            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                            ("FONTSIZE", (0, 0), (-1, -1), 10),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ]
                    )
                )
                elements.append(header_table)
                elements.append(Spacer(1, 0.3 * inch))

                # Invoice details
                details_data = [
                    ["Description", "Amount"],
                    [
                        f"{invoice.tier.value.upper()} Subscription",
                        f"${invoice.amount:.2f}",
                    ],
                ]

                if invoice.access_code:
                    details_data.append(["Access Code", invoice.access_code])

                details_table = Table(details_data, colWidths=[4 * inch, 2 * inch])
                details_table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495E")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, 0), 11),
                            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                            ("GRID", (0, 0), (-1, -1), 1, colors.black),
                            ("TOPPADDING", (0, 1), (-1, -1), 8),
                            ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
                        ]
                    )
                )
                elements.append(details_table)
                elements.append(Spacer(1, 0.3 * inch))

                # Total
                total_data = [
                    ["TOTAL:", f"${invoice.amount:.2f} {invoice.currency}"],
                ]
                total_table = Table(total_data, colWidths=[4 * inch, 2 * inch])
                total_table.setStyle(
                    TableStyle(
                        [
                            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                            ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, -1), 14),
                            ("TOPPADDING", (0, 0), (-1, -1), 12),
                        ]
                    )
                )
                elements.append(total_table)

                # Footer
                elements.append(Spacer(1, 0.5 * inch))
                footer_text = "Thank you for your business!"
                elements.append(Paragraph(footer_text, styles["Normal"]))

                # Build PDF
                doc.build(elements)
                pdf_bytes = buffer.getvalue()
                buffer.close()

                logger.info("Generated PDF for invoice %s (%s bytes)", invoice.invoice_number, len(pdf_bytes))

                return pdf_bytes

            except ImportError:
                # Fallback: Generate simple text-based PDF without reportlab
                logger.warning("reportlab not available, generating simple text PDF")

                pdf_content = f"""
INVOICE

Invoice Number: {invoice.invoice_number}
Invoice ID: {invoice.invoice_id}
Date: {invoice.created_at.strftime("%Y-%m-%d %H:%M:%S")}
Status: {invoice.status.value.upper()}
"""
                if invoice.paid_at:
                    pdf_content += f"Paid At: {invoice.paid_at.strftime('%Y-%m-%d %H:%M:%S')}\n"

                pdf_content += f"""
Description: {invoice.tier.value.upper()} Subscription
Amount: ${invoice.amount:.2f} {invoice.currency}
"""
                if invoice.access_code:
                    pdf_content += f"Access Code: {invoice.access_code}\n"

                pdf_content += f"\nTOTAL: ${invoice.amount:.2f} {invoice.currency}\n"
                pdf_content += "\nThank you for your business!"

                return pdf_content.encode("utf-8")

        except Exception as e:
            logger.error("Error generating PDF for invoice %s: %s", invoice.invoice_number, e)

            return None


# Global invoice generator instance
invoice_generator = InvoiceGenerator()
