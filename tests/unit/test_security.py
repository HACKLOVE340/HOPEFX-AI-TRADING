"""
Tests for Security Utilities

Tests for all security modules including:
- Log sanitization
- Security auditing
- Credential rotation tracking
- Security configuration validation
"""

import pytest
import os
from datetime import datetime, timedelta
from unittest.mock import patch

from utils.security import (
    LogSanitizer,
    SecurityAuditor,
    CredentialRotationTracker,
    SecurityConfigValidator,
    AuditEventType,
    SecurityLevel,
    generate_secure_key,
    generate_secure_salt,
    check_security_setup
)


class TestLogSanitizer:
    """Test log sanitization functionality"""

    def test_sanitize_api_key(self):
        """Test API key redaction"""
        sanitizer = LogSanitizer()
        
        message = 'api_key="sk_live_abc123xyz456def789"'
        result = sanitizer.sanitize(message)
        
        assert "abc123xyz456def789" not in result
        assert "[REDACTED]" in result

    def test_sanitize_password(self):
        """Test password redaction"""
        sanitizer = LogSanitizer()
        
        message = 'password = "supersecret123"'
        result = sanitizer.sanitize(message)
        
        assert "supersecret123" not in result
        assert "[REDACTED]" in result

    def test_sanitize_bearer_token(self):
        """Test bearer token redaction"""
        sanitizer = LogSanitizer()
        
        message = 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9'
        result = sanitizer.sanitize(message)
        
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert "[REDACTED]" in result

    def test_sanitize_credit_card(self):
        """Test credit card number redaction"""
        sanitizer = LogSanitizer()
        
        message = 'Card: 4111-1111-1111-1111'
        result = sanitizer.sanitize(message)
        
        assert "4111-1111-1111-1111" not in result
        assert "[REDACTED]" in result

    def test_sanitize_private_key(self):
        """Test private key detection"""
        sanitizer = LogSanitizer()
        
        message = '-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg...'
        result = sanitizer.sanitize(message)
        
        assert "-----BEGIN PRIVATE KEY-----" not in result

    def test_sanitize_dict(self):
        """Test dictionary sanitization"""
        sanitizer = LogSanitizer()
        
        data = {
            'username': 'john',
            'password': 'secret123',
            'api_key': 'sk_test_123456',
            'message': 'Hello world'
        }
        
        result = sanitizer.sanitize_dict(data)
        
        assert result['username'] == 'john'
        assert 'secret123' not in result['password']
        assert 'sk_test_123456' not in str(result['api_key'])
        assert result['message'] == 'Hello world'

    def test_sanitize_nested_dict(self):
        """Test nested dictionary sanitization"""
        sanitizer = LogSanitizer()
        
        data = {
            'credentials': {
                'api_secret': 'verysecret',
                'token': 'mytoken123'
            }
        }
        
        result = sanitizer.sanitize_dict(data)
        
        assert 'verysecret' not in str(result)
        assert 'mytoken123' not in str(result)

    def test_sanitizer_disabled(self):
        """Test that disabled sanitizer passes through"""
        sanitizer = LogSanitizer(enabled=False)
        
        message = 'password = "secret"'
        result = sanitizer.sanitize(message)
        
        assert result == message

    def test_custom_redaction_text(self):
        """Test custom redaction text"""
        sanitizer = LogSanitizer(redaction_text="***HIDDEN***")
        
        message = 'password = "secret123"'
        result = sanitizer.sanitize(message)
        
        assert "***HIDDEN***" in result


class TestSecurityAuditor:
    """Test security auditing functionality"""

    def test_log_event(self):
        """Test logging a security event"""
        auditor = SecurityAuditor(enabled=True, log_to_file=False)
        
        event = auditor.log_event(
            event_type=AuditEventType.LOGIN_SUCCESS,
            resource="user_session",
            action="create",
            user_id="user123",
            success=True
        )
        
        assert event is not None
        assert event.event_type == AuditEventType.LOGIN_SUCCESS
        assert event.success is True
        assert event.user_id == "user123"

    def test_log_event_with_details(self):
        """Test logging event with details"""
        auditor = SecurityAuditor(enabled=True, log_to_file=False)
        
        event = auditor.log_event(
            event_type=AuditEventType.API_ACCESS,
            resource="trading_api",
            action="execute_trade",
            details={'symbol': 'XAUUSD', 'amount': 1000}
        )
        
        assert event.details['symbol'] == 'XAUUSD'

    def test_log_sensitive_details_sanitized(self):
        """Test that sensitive details are sanitized"""
        auditor = SecurityAuditor(enabled=True, log_to_file=False)
        
        event = auditor.log_event(
            event_type=AuditEventType.CREDENTIAL_ACCESS,
            resource="api_key",
            action="read",
            details={'password': 'supersecret', 'api_key': 'sk_test_123'}
        )
        
        # Details should be sanitized
        assert 'supersecret' not in str(event.details['password']) or '[REDACTED]' in str(event.details['password'])

    def test_get_events_filtered(self):
        """Test filtering audit events"""
        auditor = SecurityAuditor(enabled=True, log_to_file=False)
        
        auditor.log_event(AuditEventType.LOGIN_SUCCESS, "session", "create")
        auditor.log_event(AuditEventType.LOGIN_FAILURE, "session", "create")
        auditor.log_event(AuditEventType.API_ACCESS, "api", "call")
        
        login_events = auditor.get_events(event_type=AuditEventType.LOGIN_SUCCESS)
        
        assert len(login_events) == 1
        assert login_events[0].event_type == AuditEventType.LOGIN_SUCCESS

    def test_auditor_disabled(self):
        """Test that disabled auditor returns None"""
        auditor = SecurityAuditor(enabled=False)
        
        event = auditor.log_event(
            event_type=AuditEventType.LOGIN_SUCCESS,
            resource="session",
            action="create"
        )
        
        assert event is None


class TestCredentialRotationTracker:
    """Test credential rotation tracking"""

    def test_register_credential(self):
        """Test registering a credential"""
        tracker = CredentialRotationTracker(rotation_days=90)
        
        tracker.register_credential("api_key")
        
        age = tracker.get_credential_age("api_key")
        assert age is not None
        assert age.days == 0

    def test_needs_rotation_fresh(self):
        """Test that fresh credential doesn't need rotation"""
        tracker = CredentialRotationTracker(rotation_days=90)
        
        tracker.register_credential("fresh_key")
        
        assert tracker.needs_rotation("fresh_key") is False

    def test_needs_rotation_expired(self):
        """Test that expired credential needs rotation"""
        tracker = CredentialRotationTracker(rotation_days=90)
        
        # Register with past date
        past_date = datetime.utcnow() - timedelta(days=100)
        tracker.register_credential("old_key", created_at=past_date)
        
        assert tracker.needs_rotation("old_key") is True

    def test_get_rotation_status(self):
        """Test getting rotation status for all credentials"""
        tracker = CredentialRotationTracker(rotation_days=30)
        
        tracker.register_credential("key1")
        past_date = datetime.utcnow() - timedelta(days=35)
        tracker.register_credential("key2", created_at=past_date)
        
        status = tracker.get_rotation_status()
        
        assert len(status) == 2
        assert status['key1']['needs_rotation'] is False
        assert status['key2']['needs_rotation'] is True

    def test_get_credentials_needing_rotation(self):
        """Test getting list of credentials needing rotation"""
        tracker = CredentialRotationTracker(rotation_days=30)
        
        tracker.register_credential("good_key")
        past_date = datetime.utcnow() - timedelta(days=40)
        tracker.register_credential("expired_key", created_at=past_date)
        
        needing_rotation = tracker.get_credentials_needing_rotation()
        
        assert "expired_key" in needing_rotation
        assert "good_key" not in needing_rotation


class TestSecurityConfigValidator:
    """Test security configuration validation"""

    def test_validate_missing_encryption_key(self):
        """Test validation fails without encryption key"""
        with patch.dict(os.environ, {}, clear=True):
            validator = SecurityConfigValidator()
            is_valid = validator.validate()
            
            # Should fail without CONFIG_ENCRYPTION_KEY
            assert is_valid is False
            assert any('CONFIG_ENCRYPTION_KEY' in issue['variable'] 
                      for issue in validator.issues)

    def test_validate_short_encryption_key(self):
        """Test validation fails with short encryption key"""
        with patch.dict(os.environ, {'CONFIG_ENCRYPTION_KEY': 'shortkey'}, clear=True):
            validator = SecurityConfigValidator()
            is_valid = validator.validate()
            
            assert is_valid is False
            assert any('32 characters' in issue['message'] 
                      for issue in validator.issues)

    def test_validate_valid_config(self):
        """Test validation passes with valid config"""
        env = {
            'CONFIG_ENCRYPTION_KEY': 'a' * 64,  # 64 hex chars = 32 bytes
            'CONFIG_SALT': 'b' * 32,
            'APP_ENV': 'development'
        }
        
        with patch.dict(os.environ, env, clear=True):
            validator = SecurityConfigValidator()
            is_valid = validator.validate()
            
            assert is_valid is True

    def test_validate_production_debug_enabled(self):
        """Test validation fails when debug enabled in production"""
        env = {
            'CONFIG_ENCRYPTION_KEY': 'a' * 64,
            'APP_ENV': 'production',
            'DEBUG': 'true'
        }
        
        with patch.dict(os.environ, env, clear=True):
            validator = SecurityConfigValidator()
            is_valid = validator.validate()
            
            assert is_valid is False
            assert any('DEBUG' in issue['variable'] 
                      for issue in validator.issues)

    def test_get_security_report(self):
        """Test security report generation"""
        env = {
            'CONFIG_ENCRYPTION_KEY': 'a' * 64,
            'CONFIG_SALT': 'b' * 32,
            'APP_ENV': 'development'
        }
        
        with patch.dict(os.environ, env, clear=True):
            validator = SecurityConfigValidator()
            report = validator.get_security_report()
            
            assert 'valid' in report
            assert 'checklist' in report
            assert 'environment' in report
            assert report['checklist']['CONFIG_ENCRYPTION_KEY'] is True


class TestSecurityHelpers:
    """Test security helper functions"""

    def test_generate_secure_key(self):
        """Test secure key generation"""
        key = generate_secure_key(32)
        
        assert len(key) == 64  # 32 bytes = 64 hex characters
        assert all(c in '0123456789abcdef' for c in key)

    def test_generate_secure_key_unique(self):
        """Test that generated keys are unique"""
        keys = [generate_secure_key(16) for _ in range(100)]
        
        assert len(set(keys)) == 100  # All unique

    def test_generate_secure_salt(self):
        """Test secure salt generation"""
        salt = generate_secure_salt(16)
        
        assert len(salt) == 32  # 16 bytes = 32 hex characters

    def test_check_security_setup(self):
        """Test comprehensive security check"""
        env = {
            'CONFIG_ENCRYPTION_KEY': 'a' * 64,
            'CONFIG_SALT': 'b' * 32,
            'APP_ENV': 'development'
        }
        
        with patch.dict(os.environ, env, clear=True):
            report = check_security_setup()
            
            assert 'valid' in report
            assert 'checklist' in report

    def test_check_security_setup_missing_key(self):
        """Test security check with missing key provides commands"""
        with patch.dict(os.environ, {}, clear=True):
            report = check_security_setup()
            
            assert report['valid'] is False
            if 'setup_commands' in report:
                assert 'CONFIG_ENCRYPTION_KEY' in report['setup_commands']
