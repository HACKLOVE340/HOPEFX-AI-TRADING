"""
Tests for Invoice Generation System
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from monetization.invoices import (
    Invoice,
    InvoiceStatus,
    InvoiceGenerator
)
from monetization.pricing import SubscriptionTier


class TestInvoice:
    """Test Invoice model"""

    def test_invoice_creation(self):
        """Test creating an invoice"""
        invoice = Invoice(
            invoice_id="INV-001",
            invoice_number="2024-001",
            user_id="user-123",
            subscription_id="sub-456",
            tier=SubscriptionTier.PROFESSIONAL,
            amount=Decimal("99.00"),
            currency="USD",
            access_code="ABC123",
            status=InvoiceStatus.DRAFT
        )
        
        assert invoice.invoice_id == "INV-001"
        assert invoice.invoice_number == "2024-001"
        assert invoice.tier == SubscriptionTier.PROFESSIONAL
        assert invoice.amount == Decimal("99.00")
        assert invoice.status == InvoiceStatus.DRAFT

    def test_mark_invoice_paid(self):
        """Test marking invoice as paid"""
        invoice = Invoice(
            invoice_id="INV-001",
            invoice_number="2024-001",
            user_id="user-123",
            subscription_id="sub-456",
            tier=SubscriptionTier.STARTER,
            amount=Decimal("29.00")
        )
        
        invoice.mark_paid()
        assert invoice.status == InvoiceStatus.PAID
        assert invoice.paid_at is not None

    def test_mark_invoice_cancelled(self):
        """Test marking invoice as cancelled"""
        invoice = Invoice(
            invoice_id="INV-001",
            invoice_number="2024-001",
            user_id="user-123",
            subscription_id="sub-456",
            tier=SubscriptionTier.STARTER,
            amount=Decimal("29.00")
        )
        
        invoice.mark_cancelled()
        assert invoice.status == InvoiceStatus.CANCELLED

    def test_mark_invoice_refunded(self):
        """Test marking invoice as refunded"""
        invoice = Invoice(
            invoice_id="INV-001",
            invoice_number="2024-001",
            user_id="user-123",
            subscription_id="sub-456",
            tier=SubscriptionTier.STARTER,
            amount=Decimal("29.00")
        )
        
        invoice.mark_paid()
        invoice.mark_refunded()
        assert invoice.status == InvoiceStatus.REFUNDED

    def test_invoice_overdue(self):
        """Test overdue invoice detection"""
        invoice = Invoice(
            invoice_id="INV-001",
            invoice_number="2024-001",
            user_id="user-123",
            subscription_id="sub-456",
            tier=SubscriptionTier.STARTER,
            amount=Decimal("29.00")
        )
        
        # Set due date in the past
        invoice.due_date = datetime.utcnow() - timedelta(days=1)
        invoice.status = InvoiceStatus.PENDING
        
        assert invoice.is_overdue() is True

    def test_invoice_not_overdue(self):
        """Test non-overdue invoice"""
        invoice = Invoice(
            invoice_id="INV-001",
            invoice_number="2024-001",
            user_id="user-123",
            subscription_id="sub-456",
            tier=SubscriptionTier.STARTER,
            amount=Decimal("29.00")
        )
        
        # Set due date in the future
        invoice.due_date = datetime.utcnow() + timedelta(days=30)
        invoice.status = InvoiceStatus.PENDING
        
        assert invoice.is_overdue() is False

    def test_paid_invoice_not_overdue(self):
        """Test that paid invoices are never overdue"""
        invoice = Invoice(
            invoice_id="INV-001",
            invoice_number="2024-001",
            user_id="user-123",
            subscription_id="sub-456",
            tier=SubscriptionTier.STARTER,
            amount=Decimal("29.00")
        )
        
        invoice.due_date = datetime.utcnow() - timedelta(days=10)
        invoice.mark_paid()
        
        assert invoice.is_overdue() is False


class TestInvoiceGenerator:
    """Test InvoiceGenerator functionality"""

    def test_create_invoice(self):
        """Test creating an invoice"""
        generator = InvoiceGenerator()
        
        invoice = generator.create_invoice(
            user_id="user-123",
            subscription_id="sub-456",
            tier=SubscriptionTier.PROFESSIONAL,
            access_code="XYZ789",
            duration_months=1
        )
        
        assert invoice.user_id == "user-123"
        assert invoice.tier == SubscriptionTier.PROFESSIONAL
        assert invoice.access_code == "XYZ789"
        assert invoice.status == InvoiceStatus.PENDING

    def test_get_invoice(self):
        """Test retrieving an invoice"""
        generator = InvoiceGenerator()
        
        created_invoice = generator.create_invoice(
            user_id="user-123",
            subscription_id="sub-456",
            tier=SubscriptionTier.STARTER,
            duration_months=1
        )
        
        retrieved_invoice = generator.get_invoice(created_invoice.invoice_id)
        assert retrieved_invoice is not None
        assert retrieved_invoice.invoice_id == created_invoice.invoice_id

    def test_get_nonexistent_invoice(self):
        """Test retrieving a non-existent invoice"""
        generator = InvoiceGenerator()
        
        invoice = generator.get_invoice("NONEXISTENT")
        assert invoice is None

    def test_get_user_invoices(self):
        """Test retrieving all invoices for a user"""
        generator = InvoiceGenerator()
        
        # Create multiple invoices for same user
        for i in range(3):
            generator.create_invoice(
                user_id="user-123",
                subscription_id=f"sub-{i}",
                tier=SubscriptionTier.STARTER,
                duration_months=1
            )
        
        # Create invoice for different user
        generator.create_invoice(
            user_id="user-456",
            subscription_id="sub-999",
            tier=SubscriptionTier.STARTER,
            duration_months=1
        )
        
        user_invoices = generator.get_user_invoices("user-123")
        assert len(user_invoices) == 3

    def test_mark_invoice_paid(self):
        """Test marking invoice as paid via generator"""
        generator = InvoiceGenerator()
        
        invoice = generator.create_invoice(
            user_id="user-123",
            subscription_id="sub-456",
            tier=SubscriptionTier.STARTER,
            duration_months=1
        )
        
        result = generator.mark_invoice_paid(invoice.invoice_id)
        assert result is True
        
        updated_invoice = generator.get_invoice(invoice.invoice_id)
        assert updated_invoice.status == InvoiceStatus.PAID

    def test_cancel_invoice(self):
        """Test cancelling invoice via generator"""
        generator = InvoiceGenerator()
        
        invoice = generator.create_invoice(
            user_id="user-123",
            subscription_id="sub-456",
            tier=SubscriptionTier.STARTER,
            duration_months=1
        )
        
        result = generator.cancel_invoice(invoice.invoice_id)
        assert result is True
        
        updated_invoice = generator.get_invoice(invoice.invoice_id)
        assert updated_invoice.status == InvoiceStatus.CANCELLED

    def test_refund_invoice(self):
        """Test refunding invoice via generator"""
        generator = InvoiceGenerator()
        
        invoice = generator.create_invoice(
            user_id="user-123",
            subscription_id="sub-456",
            tier=SubscriptionTier.STARTER,
            duration_months=1
        )
        
        # First mark as paid
        generator.mark_invoice_paid(invoice.invoice_id)
        
        # Then refund
        result = generator.refund_invoice(invoice.invoice_id)
        assert result is True
        
        updated_invoice = generator.get_invoice(invoice.invoice_id)
        assert updated_invoice.status == InvoiceStatus.REFUNDED

    def test_get_invoice_stats(self):
        """Test getting invoice statistics"""
        generator = InvoiceGenerator()
        
        # Create various invoices
        inv1 = generator.create_invoice(
            user_id="user-123",
            subscription_id="sub-1",
            tier=SubscriptionTier.STARTER,
            duration_months=1
        )
        
        inv2 = generator.create_invoice(
            user_id="user-123",
            subscription_id="sub-2",
            tier=SubscriptionTier.PROFESSIONAL,
            duration_months=1
        )
        generator.mark_invoice_paid(inv2.invoice_id)
        
        stats = generator.get_invoice_stats(user_id="user-123")
        
        assert stats['total_invoices'] == 2
        assert stats['pending_invoices'] == 1
        assert stats['paid_invoices'] == 1
        # Amount will vary based on tier pricing, so just check it exists
        assert 'paid_amount' in stats

    def test_generate_pdf(self):
        """Test PDF generation"""
        generator = InvoiceGenerator()
        
        invoice = generator.create_invoice(
            user_id="user-123",
            subscription_id="sub-456",
            tier=SubscriptionTier.PROFESSIONAL,
            access_code="PDF123",
            duration_months=1
        )
        
        pdf_bytes = generator.generate_pdf(invoice.invoice_id)
        
        # Should return bytes (either real PDF or text fallback)
        assert pdf_bytes is not None
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 0

    def test_generate_pdf_nonexistent_invoice(self):
        """Test PDF generation for non-existent invoice"""
        generator = InvoiceGenerator()
        
        pdf_bytes = generator.generate_pdf("NONEXISTENT")
        assert pdf_bytes is None
