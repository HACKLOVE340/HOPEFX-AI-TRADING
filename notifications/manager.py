"""
Notification Manager

Sends notifications via multiple channels (Discord, Telegram, Email, etc.)
"""

from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime
import logging
import requests

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
        """Send notification to Discord via webhook"""
        try:
            webhook_url = self.config.get('discord_webhook_url')
            if not webhook_url:
                logger.warning("Discord webhook URL not configured")
                return
            
            # Try to import requests
            try:
                import requests
                
                # Determine color based on level
                color_map = {
                    NotificationLevel.INFO: 0x3498db,  # Blue
                    NotificationLevel.WARNING: 0xf39c12,  # Orange
                    NotificationLevel.ERROR: 0xe74c3c,  # Red
                    NotificationLevel.CRITICAL: 0x8b0000,  # Dark red
                }
                
                # Create Discord embed
                embed = {
                    "title": f"{level.value} Notification",
                    "description": message,
                    "color": color_map.get(level, 0x95a5a6),
                    "timestamp": datetime.utcnow().isoformat(),
                    "footer": {
                        "text": "HOPEFX AI Trading"
                    }
                }
                
                # Add metadata as fields if present
                if metadata:
                    fields = []
                    for key, value in metadata.items():
                        if value is not None:
                            fields.append({
                                "name": key.replace('_', ' ').title(),
                                "value": str(value),
                                "inline": True
                            })
                    if fields:
                        embed["fields"] = fields
                
                payload = {"embeds": [embed]}
                
                response = requests.post(
                    webhook_url,
                    json=payload,
                    timeout=10
                )
                response.raise_for_status()
                logger.debug(f"Discord notification sent successfully")
                
            except (ImportError, AttributeError):
                # Fallback without requests library
                import urllib.request
                import json
                
                payload = {
                    "content": f"**{level.value}:** {message}"
                }
                if metadata:
                    metadata_str = "\n".join(f"{k}: {v}" for k, v in metadata.items() if v is not None)
                    payload["content"] += f"\n```{metadata_str}```"
                
                data = json.dumps(payload).encode('utf-8')
                # Validate URL scheme for security (only allow https for webhooks)
                if not webhook_url.startswith('https://'):
                    logger.error("Discord webhook URL must use HTTPS")
                    return
                    
                req = urllib.request.Request(
                    webhook_url,
                    data=data,
                    headers={'Content-Type': 'application/json'}
                )
                urllib.request.urlopen(req, timeout=10)  # nosec - URL scheme validated above
                logger.debug(f"Discord notification sent (urllib fallback)")
                
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")

    def _send_telegram(
        self,
        message: str,
        level: NotificationLevel,
        metadata: Optional[Dict[str, Any]]
    ):
        """Send notification to Telegram via Bot API"""
        try:
            bot_token = self.config.get('telegram_bot_token')
            chat_id = self.config.get('telegram_chat_id')
            
            if not bot_token or not chat_id:
                logger.warning("Telegram bot token or chat ID not configured")
                return
            
            # Try to import requests
            try:
                import requests
                
                # Format message with emoji based on level
                emoji_map = {
                    NotificationLevel.INFO: "ℹ️",
                    NotificationLevel.WARNING: "⚠️",
                    NotificationLevel.ERROR: "❌",
                    NotificationLevel.CRITICAL: "🚨",
                }
                emoji = emoji_map.get(level, "📢")
                
                # Build message text
                text = f"{emoji} **{level.value}**\n\n{message}"
                
                # Add metadata
                if metadata:
                    text += "\n\n📊 *Details:*"
                    for key, value in metadata.items():
                        if value is not None:
                            text += f"\n• {key.replace('_', ' ').title()}: `{value}`"
                
                # Send via Telegram Bot API
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown"
                }
                
                response = requests.post(url, json=payload, timeout=10)
                response.raise_for_status()
                logger.debug("Telegram notification sent successfully")
                
            except (ImportError, AttributeError):
                # Fallback without requests library
                import urllib.request
                import urllib.parse
                import json
                
                emoji_map = {
                    NotificationLevel.INFO: "INFO",
                    NotificationLevel.WARNING: "WARNING",
                    NotificationLevel.ERROR: "ERROR",
                    NotificationLevel.CRITICAL: "CRITICAL",
                }
                level_text = emoji_map.get(level, "NOTIFICATION")
                
                text = f"{level_text}: {message}"
                if metadata:
                    metadata_str = "\n".join(f"{k}: {v}" for k, v in metadata.items() if v is not None)
                    text += f"\n\n{metadata_str}"
                
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                # Validate URL scheme for security (only allow https for Telegram API)
                if not url.startswith('https://api.telegram.org/'):
                    logger.error("Telegram API URL must use HTTPS and be from api.telegram.org")
                    return
                    
                data = {
                    "chat_id": chat_id,
                    "text": text
                }
                data_encoded = urllib.parse.urlencode(data).encode('utf-8')
                req = urllib.request.Request(url, data=data_encoded)
                urllib.request.urlopen(req, timeout=10)  # nosec - URL scheme validated above
                logger.debug("Telegram notification sent (urllib fallback)")
                
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")

    def _send_email(
        self,
        message: str,
        level: NotificationLevel,
        metadata: Optional[Dict[str, Any]]
    ):
        """Send notification via SMTP email"""
        try:
            smtp_host = self.config.get('smtp_host', 'smtp.gmail.com')
            smtp_port = self.config.get('smtp_port', 587)
            smtp_username = self.config.get('smtp_username')
            smtp_password = self.config.get('smtp_password')
            smtp_from = self.config.get('smtp_from', smtp_username)
            smtp_to = self.config.get('smtp_to')
            
            if not smtp_username or not smtp_password or not smtp_to:
                logger.warning("SMTP credentials or recipient not configured")
                return
            
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[{level.value}] HOPEFX AI Trading Notification"
            msg['From'] = smtp_from
            msg['To'] = smtp_to if isinstance(smtp_to, str) else ', '.join(smtp_to)
            
            # Plain text version
            text_content = f"{level.value} Notification\n\n{message}"
            if metadata:
                text_content += "\n\nDetails:\n"
                for key, value in metadata.items():
                    if value is not None:
                        text_content += f"  {key.replace('_', ' ').title()}: {value}\n"
            
            # HTML version
            html_content = f"""
            <html>
              <head>
                <style>
                  body {{ font-family: Arial, sans-serif; }}
                  .header {{ background-color: #2c3e50; color: white; padding: 20px; }}
                  .content {{ padding: 20px; }}
                  .level-{level.value.lower()} {{ color: {self._get_level_color(level)}; }}
                  .metadata {{ background-color: #f5f5f5; padding: 10px; margin-top: 20px; }}
                  .metadata-item {{ margin: 5px 0; }}
                </style>
              </head>
              <body>
                <div class="header">
                  <h2>HOPEFX AI Trading Notification</h2>
                </div>
                <div class="content">
                  <h3 class="level-{level.value.lower()}">{level.value}</h3>
                  <p>{message}</p>
            """
            
            if metadata:
                html_content += '<div class="metadata"><h4>Details:</h4>'
                for key, value in metadata.items():
                    if value is not None:
                        html_content += f'<div class="metadata-item"><strong>{key.replace("_", " ").title()}:</strong> {value}</div>'
                html_content += '</div>'
            
            html_content += """
                </div>
              </body>
            </html>
            """
            
            # Attach parts
            part1 = MIMEText(text_content, 'plain')
            part2 = MIMEText(html_content, 'html')
            msg.attach(part1)
            msg.attach(part2)
            
            # Send email
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                server.starttls()
                server.login(smtp_username, smtp_password)
                recipients = [smtp_to] if isinstance(smtp_to, str) else smtp_to
                server.sendmail(smtp_from, recipients, msg.as_string())
            
            logger.debug(f"Email notification sent to {smtp_to}")
            
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
    
    def _get_level_color(self, level: NotificationLevel) -> str:
        """Get HTML color for notification level"""
        color_map = {
            NotificationLevel.INFO: '#3498db',
            NotificationLevel.WARNING: '#f39c12',
            NotificationLevel.ERROR: '#e74c3c',
            NotificationLevel.CRITICAL: '#8b0000',
        }
        return color_map.get(level, '#95a5a6')

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
