"""
Notification Manager

Sends notifications via multiple channels (Discord, Telegram, Email, etc.)
"""

from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class NotificationLevel(Enum):
    """Notification severity levels"""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class NotificationChannel(Enum):
    """Notification channels"""
    CONSOLE = "CONSOLE"
    DISCORD = "DISCORD"
    TELEGRAM = "TELEGRAM"
    EMAIL = "EMAIL"
    SMS = "SMS"


class NotificationManager:
    """
    Manages notifications across multiple channels.
    
    Features:
    - Multiple notification channels
    - Priority-based filtering
    - Rate limiting
    - Template support
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize notification manager.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self.enabled_channels = self._get_enabled_channels()
        self.notification_history = []
        
        logger.info(
            f"Notification Manager initialized with channels: "
            f"{', '.join(c.value for c in self.enabled_channels)}"
        )
    
    def _get_enabled_channels(self) -> List[NotificationChannel]:
        """Get list of enabled notification channels"""
        channels = [NotificationChannel.CONSOLE]  # Always enabled
        
        # Add other channels based on config
        if self.config.get('discord_enabled'):
            channels.append(NotificationChannel.DISCORD)
        if self.config.get('telegram_enabled'):
            channels.append(NotificationChannel.TELEGRAM)
        if self.config.get('email_enabled'):
            channels.append(NotificationChannel.EMAIL)
        
        return channels
    
    def send(
        self,
        message: str,
        level: NotificationLevel = NotificationLevel.INFO,
        channels: Optional[List[NotificationChannel]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Send notification.
        
        Args:
            message: Notification message
            level: Severity level
            channels: Specific channels to use (None = all enabled)
            metadata: Additional metadata
        """
        # Use all enabled channels if not specified
        if channels is None:
            channels = self.enabled_channels
        
        # Filter to only enabled channels
        channels = [c for c in channels if c in self.enabled_channels]
        
        # Create notification record
        notification = {
            'message': message,
            'level': level.value,
            'channels': [c.value for c in channels],
            'timestamp': datetime.utcnow().isoformat(),
            'metadata': metadata or {},
        }
        
        # Store in history
        self.notification_history.append(notification)
        
        # Send to each channel
        for channel in channels:
            try:
                if channel == NotificationChannel.CONSOLE:
                    self._send_console(message, level)
                elif channel == NotificationChannel.DISCORD:
                    self._send_discord(message, level, metadata)
                elif channel == NotificationChannel.TELEGRAM:
                    self._send_telegram(message, level, metadata)
                elif channel == NotificationChannel.EMAIL:
                    self._send_email(message, level, metadata)
            except Exception as e:
                logger.error(f"Failed to send notification via {channel.value}: {e}")
    
    def _send_console(self, message: str, level: NotificationLevel):
        """Send notification to console/logs"""
        if level == NotificationLevel.INFO:
            logger.info(f"[NOTIFICATION] {message}")
        elif level == NotificationLevel.WARNING:
            logger.warning(f"[NOTIFICATION] {message}")
        elif level == NotificationLevel.ERROR:
            logger.error(f"[NOTIFICATION] {message}")
        elif level == NotificationLevel.CRITICAL:
            logger.critical(f"[NOTIFICATION] {message}")
    
    def _send_discord(
        self,
        message: str,
        level: NotificationLevel,
        metadata: Optional[Dict[str, Any]]
    ):
        """Send notification to Discord"""
        # Placeholder - would integrate with Discord webhook
        logger.debug(f"Discord notification: {message}")
        # TODO: Implement Discord webhook integration
    
    def _send_telegram(
        self,
        message: str,
        level: NotificationLevel,
        metadata: Optional[Dict[str, Any]]
    ):
        """Send notification to Telegram"""
        # Placeholder - would integrate with Telegram bot API
        logger.debug(f"Telegram notification: {message}")
        # TODO: Implement Telegram bot API integration
    
    def _send_email(
        self,
        message: str,
        level: NotificationLevel,
        metadata: Optional[Dict[str, Any]]
    ):
        """Send notification via email"""
        # Placeholder - would integrate with SMTP
        logger.debug(f"Email notification: {message}")
        # TODO: Implement SMTP email sending
    
    def notify_trade(
        self,
        action: str,
        symbol: str,
        quantity: float,
        price: float,
        pnl: Optional[float] = None
    ):
        """
        Send trade notification.
        
        Args:
            action: Trade action (e.g., "BUY", "SELL")
            symbol: Trading symbol
            quantity: Trade quantity
            price: Execution price
            pnl: Profit/Loss (if closing position)
        """
        message = f"Trade: {action} {quantity} {symbol} @ ${price:.2f}"
        
        if pnl is not None:
            message += f" | P&L: ${pnl:.2f}"
        
        self.send(
            message=message,
            level=NotificationLevel.INFO,
            metadata={
                'type': 'trade',
                'action': action,
                'symbol': symbol,
                'quantity': quantity,
                'price': price,
                'pnl': pnl,
            }
        )
    
    def notify_signal(
        self,
        strategy: str,
        signal_type: str,
        symbol: str,
        price: float,
        confidence: float
    ):
        """
        Send trading signal notification.
        
        Args:
            strategy: Strategy name
            signal_type: Signal type (BUY/SELL)
            symbol: Trading symbol
            price: Signal price
            confidence: Signal confidence
        """
        message = (
            f"Signal: {strategy} generated {signal_type} for {symbol} "
            f"@ ${price:.2f} (confidence: {confidence:.2%})"
        )
        
        self.send(
            message=message,
            level=NotificationLevel.INFO,
            metadata={
                'type': 'signal',
                'strategy': strategy,
                'signal_type': signal_type,
                'symbol': symbol,
                'price': price,
                'confidence': confidence,
            }
        )
    
    def notify_risk_alert(
        self,
        alert_type: str,
        message: str,
        severity: str = "WARNING"
    ):
        """
        Send risk management alert.
        
        Args:
            alert_type: Type of alert
            message: Alert message
            severity: Severity level
        """
        level = NotificationLevel[severity]
        
        self.send(
            message=f"RISK ALERT [{alert_type}]: {message}",
            level=level,
            metadata={
                'type': 'risk_alert',
                'alert_type': alert_type,
            }
        )
    
    def notify_error(self, error_type: str, message: str, details: Optional[str] = None):
        """
        Send error notification.
        
        Args:
            error_type: Type of error
            message: Error message
            details: Additional error details
        """
        full_message = f"ERROR [{error_type}]: {message}"
        if details:
            full_message += f"\nDetails: {details}"
        
        self.send(
            message=full_message,
            level=NotificationLevel.ERROR,
            metadata={
                'type': 'error',
                'error_type': error_type,
                'details': details,
            }
        )
    
    def get_recent_notifications(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recent notifications.
        
        Args:
            limit: Maximum number to return
            
        Returns:
            List of recent notifications
        """
        return self.notification_history[-limit:]
    
    def clear_history(self):
        """Clear notification history"""
        self.notification_history = []
        logger.info("Notification history cleared")
