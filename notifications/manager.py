
# Phase 7: Notifications Module - Discord, Telegram, Email, SMS

code = '''"""
HOPEFX Notifications Module
Multi-channel notifications with delivery tracking and webhooks
Supports: Discord, Telegram, Email, SMS
"""

import json
import logging
import smtplib
import requests
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path
from dataclasses import dataclass, field
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from enum import Enum
import sqlite3
import threading
import time


class NotificationChannel(Enum):
    DISCORD = "discord"
    TELEGRAM = "telegram"
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"


class NotificationPriority(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class NotificationMessage:
    """Standardized notification message"""
    message_id: str
    timestamp: datetime
    title: str
    content: str
    channel: NotificationChannel
    priority: NotificationPriority
    recipient: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.message_id:
            import uuid
            self.message_id = str(uuid.uuid4())


@dataclass
class DeliveryRecord:
    """Delivery tracking record"""
    record_id: str
    message_id: str
    channel: NotificationChannel
    recipient: str
    timestamp: datetime
    status: str  # PENDING, SENT, DELIVERED, FAILED, RETRY
    response_code: Optional[int] = None
    response_message: Optional[str] = None
    retry_count: int = 0
    delivered_at: Optional[datetime] = None


class NotificationDatabase:
    """SQLite database for notification tracking"""
    
    def __init__(self, db_path: str = "notifications/logs/notifications.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                timestamp TEXT,
                title TEXT,
                content TEXT,
                channel TEXT,
                priority TEXT,
                recipient TEXT,
                metadata TEXT
            )
        """)
        
        # Delivery records table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS delivery_records (
                record_id TEXT PRIMARY KEY,
                message_id TEXT,
                channel TEXT,
                recipient TEXT,
                timestamp TEXT,
                status TEXT,
                response_code INTEGER,
                response_message TEXT,
                retry_count INTEGER,
                delivered_at TEXT
            )
        """)
        
        # Webhook logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                webhook_url TEXT,
                payload TEXT,
                response_code INTEGER,
                response_body TEXT
            )
        """)
        
        conn.commit()
        conn.close()
    
    def save_message(self, message: NotificationMessage):
        """Save message to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO messages 
            (message_id, timestamp, title, content, channel, priority, recipient, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            message.message_id, message.timestamp.isoformat(), message.title,
            message.content, message.channel.value, message.priority.value,
            message.recipient, json.dumps(message.metadata)
        ))
        conn.commit()
        conn.close()
    
    def save_delivery_record(self, record: DeliveryRecord):
        """Save delivery record"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO delivery_records
            (record_id, message_id, channel, recipient, timestamp, status,
             response_code, response_message, retry_count, delivered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.record_id, record.message_id, record.channel.value, record.recipient,
            record.timestamp.isoformat(), record.status, record.response_code,
            record.response_message, record.retry_count,
            record.delivered_at.isoformat() if record.delivered_at else None
        ))
        conn.commit()
        conn.close()
    
    def log_webhook(self, webhook_url: str, payload: Dict, response_code: int, response_body: str):
        """Log webhook call"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO webhook_logs (timestamp, webhook_url, payload, response_code, response_body)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(), webhook_url, json.dumps(payload),
            response_code, response_body
        ))
        conn.commit()
        conn.close()
    
    def get_delivery_stats(self, channel: Optional[NotificationChannel] = None) -> Dict:
        """Get delivery statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if channel:
            cursor.execute("""
                SELECT status, COUNT(*) FROM delivery_records 
                WHERE channel = ?
                GROUP BY status
            """, (channel.value,))
        else:
            cursor.execute("""
                SELECT status, COUNT(*) FROM delivery_records 
                GROUP BY status
            """)
        
        results = cursor.fetchall()
        conn.close()
        
        stats = {'total': 0, 'sent': 0, 'delivered': 0, 'failed': 0, 'pending': 0}
        for status, count in results:
            stats[status.lower()] = count
            stats['total'] += count
        
        stats['success_rate'] = (stats['delivered'] + stats['sent']) / stats['total'] if stats['total'] > 0 else 0.0
        return stats


class BaseNotifier:
    """Base class for all notification channels"""
    
    def __init__(self, channel: NotificationChannel):
        self.channel = channel
        self.db = NotificationDatabase()
        self.enabled = True
    
    def send(self, message: NotificationMessage) -> DeliveryRecord:
        """Send notification - to be implemented by subclasses"""
        raise NotImplementedError
    
    def create_delivery_record(self, message: NotificationMessage, status: str,
                              response_code: Optional[int] = None,
                              response_message: Optional[str] = None) -> DeliveryRecord:
        """Create delivery record"""
        import uuid
        return DeliveryRecord(
            record_id=str(uuid.uuid4()),
            message_id=message.message_id,
            channel=self.channel,
            recipient=message.recipient,
            timestamp=datetime.now(),
            status=status,
            response_code=response_code,
            response_message=response_message
        )


class DiscordNotifier(BaseNotifier):
    """Discord webhook notifications"""
    
    def __init__(self, webhook_url: str):
        super().__init__(NotificationChannel.DISCORD)
        self.webhook_url = webhook_url
    
    def send(self, message: NotificationMessage) -> DeliveryRecord:
        """Send Discord webhook notification"""
        if not self.enabled:
            return self.create_delivery_record(message, "DISABLED")
        
        # Build Discord embed
        color_map = {
            NotificationPriority.LOW: 0x95a5a6,
            NotificationPriority.NORMAL: 0x3498db,
            NotificationPriority.HIGH: 0xf39c12,
            NotificationPriority.CRITICAL: 0xe74c3c
        }
        
        payload = {
            "embeds": [{
                "title": message.title,
                "description": message.content,
                "color": color_map.get(message.priority, 0x3498db),
                "timestamp": message.timestamp.isoformat(),
                "footer": {
                    "text": f"HOPEFX Trading | {message.priority.value.upper()}"
                },
                "fields": [
                    {
                        "name": "Channel",
                        "value": message.channel.value,
                        "inline": True
                    },
                    {
                        "name": "Message ID",
                        "value": message.message_id[:8],
                        "inline": True
                    }
                ]
            }]
        }
        
        # Add metadata fields
        for key, value in message.metadata.items():
            if len(payload["embeds"][0]["fields"]) < 25:  # Discord limit
                payload["embeds"][0]["fields"].append({
                    "name": key,
                    "value": str(value)[:1024],  # Discord field limit
                    "inline": True
                })
        
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=30,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code in [200, 204]:
                record = self.create_delivery_record(
                    message, "DELIVERED",
                    response_code=response.status_code,
                    response_message="Success"
                )
                record.delivered_at = datetime.now()
            else:
                record = self.create_delivery_record(
                    message, "FAILED",
                    response_code=response.status_code,
                    response_message=response.text[:500]
                )
            
            # Log webhook call
            self.db.log_webhook(self.webhook_url, payload, response.status_code, response.text[:500])
            
        except Exception as e:
            record = self.create_delivery_record(
                message, "FAILED",
                response_message=str(e)[:500]
            )
            self.db.log_webhook(self.webhook_url, payload, 0, str(e)[:500])
        
        # Save to database
        self.db.save_message(message)
        self.db.save_delivery_record(record)
        
        status_icon = "✅" if record.status == "DELIVERED" else "❌"
        print(f"{status_icon} Discord notification | {message.title} | {record.status}")
        
        return record


class TelegramNotifier(BaseNotifier):
    """Telegram bot notifications"""
    
    def __init__(self, bot_token: str, chat_id: str):
        super().__init__(NotificationChannel.TELEGRAM)
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
    
    def send(self, message: NotificationMessage) -> DeliveryRecord:
        """Send Telegram message"""
        if not self.enabled:
            return self.create_delivery_record(message, "DISABLED")
        
        # Format message
        priority_emoji = {
            NotificationPriority.LOW: "🔵",
            NotificationPriority.NORMAL: "🟢",
            NotificationPriority.HIGH: "🟠",
            NotificationPriority.CRITICAL: "🔴"
        }
        
        text = f"{priority_emoji.get(message.priority, '⚪')} *{message.title}*\n\n"
        text += f"{message.content}\n\n"
        text += f"_Priority: {message.priority.value}_\n"
        text += f"_Time: {message.timestamp.strftime('%Y-%m-%d %H:%M:%S')}_"
        
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        
        try:
            response = requests.post(
                f"{self.api_url}/sendMessage",
                json=payload,
                timeout=30
            )
            
            result = response.json()
            
            if response.status_code == 200 and result.get("ok"):
                record = self.create_delivery_record(
                    message, "DELIVERED",
                    response_code=response.status_code,
                    response_message="Message sent"
                )
                record.delivered_at = datetime.now()
            else:
                record = self.create_delivery_record(
                    message, "FAILED",
                    response_code=response.status_code,
                    response_message=result.get("description", "Unknown error")
                )
            
            self.db.log_webhook(f"{self.api_url}/sendMessage", payload, response.status_code, response.text[:500])
            
        except Exception as e:
            record = self.create_delivery_record(
                message, "FAILED",
                response_message=str(e)[:500]
            )
            self.db.log_webhook(f"{self.api_url}/sendMessage", payload, 0, str(e)[:500])
        
        self.db.save_message(message)
        self.db.save_delivery_record(record)
        
        status_icon = "✅" if record.status == "DELIVERED" else "❌"
        print(f"{status_icon} Telegram notification | {message.title} | {record.status}")
        
        return record


class EmailNotifier(BaseNotifier):
    """Email notifications via SMTP"""
    
    def __init__(self, smtp_host: str, smtp_port: int, username: str, password: str,
                 from_email: str, use_tls: bool = True):
        super().__init__(NotificationChannel.EMAIL)
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.use_tls = use_tls
    
    def send(self, message: NotificationMessage) -> DeliveryRecord:
        """Send email notification"""
        if not self.enabled:
            return self.create_delivery_record(message, "DISABLED")
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"[{message.priority.value.upper()}] {message.title}"
        msg['From'] = self.from_email
        msg['To'] = message.recipient
        
        # Plain text version
        text_body = f"""
{message.title}
{'=' * len(message.title)}

{message.content}

Priority: {message.priority.value}
Time: {message.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
Message ID: {message.message_id}

---
HOPEFX Trading Platform
        """
        
        # HTML version
        priority_color = {
            NotificationPriority.LOW: "#95a5a6",
            NotificationPriority.NORMAL: "#3498db",
            NotificationPriority.HIGH: "#f39c12",
            NotificationPriority.CRITICAL: "#e74c3c"
        }
        
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background-color: {priority_color.get(message.priority, '#3498db')}; 
                           color: white; padding: 15px; border-radius: 5px 5px 0 0;">
                    <h2 style="margin: 0;">{message.title}</h2>
                </div>
                <div style="background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd;">
                    <p>{message.content.replace(chr(10), '<br>')}</p>
                    
                    <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                    
                    <table style="width: 100%; font-size: 12px; color: #666;">
                        <tr>
                            <td><strong>Priority:</strong></td>
                            <td>{message.priority.value}</td>
                        </tr>
                        <tr>
                            <td><strong>Time:</strong></td>
                            <td>{message.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</td>
                        </tr>
                        <tr>
                            <td><strong>Message ID:</strong></td>
                            <td>{message.message_id}</td>
                        </tr>
                    </table>
                </div>
                <div style="text-align: center; padding: 15px; font-size: 12px; color: #999;">
                    HOPEFX Trading Platform
                </div>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        
        try:
            # Connect to SMTP server
            server = smtplib.SMTP(self.smtp_host, self.smtp_port)
            
            if self.use_tls:
                server.starttls()
            
            server.login(self.username, self.password)
            server.send_message(msg)
            server.quit()
            
            record = self.create_delivery_record(
                message, "DELIVERED",
                response_code=200,
                response_message="Email sent successfully"
            )
            record.delivered_at = datetime.now()
            
        except Exception as e:
            record = self.create_delivery_record(
                message, "FAILED",
                response_message=str(e)[:500]
            )
        
        self.db.save_message(message)
        self.db.save_delivery_record(record)
        
        status_icon = "✅" if record.status == "DELIVERED" else "❌"
        print(f"{status_icon} Email notification | {message.title} | {record.status}")
        
        return record


class SMSNotifier(BaseNotifier):
    """SMS notifications via Twilio"""
    
    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        super().__init__(NotificationChannel.SMS)
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.api_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    
    def send(self, message: NotificationMessage) -> DeliveryRecord:
        """Send SMS notification"""
        if not self.enabled:
            return self.create_delivery_record(message, "DISABLED")
        
        # Truncate content for SMS
        sms_content = f"{message.title}: {message.content}"
        if len(sms_content) > 160:
            sms_content = sms_content[:157] + "..."
        
        payload = {
            "To": message.recipient,
            "From": self.from_number,
            "Body": sms_content
        }
        
        try:
            response = requests.post(
                self.api_url,
                data=payload,
                auth=(self.account_sid, self.auth_token),
                timeout=30
            )
            
            result = response.json()
            
            if response.status_code == 201:
                record = self.create_delivery_record(
                    message, "DELIVERED",
                    response_code=response.status_code,
                    response_message=f"SID: {result.get('sid', 'N/A')}"
                )
                record.delivered_at = datetime.now()
            else:
                record = self.create_delivery_record(
                    message, "FAILED",
                    response_code=response.status_code,
                    response_message=result.get("message", "Unknown error")
                )
            
            self.db.log_webhook(self.api_url, payload, response.status_code, response.text[:500])
            
        except Exception as e:
            record = self.create_delivery_record(
                message, "FAILED",
                response_message=str(e)[:500]
            )
            self.db.log_webhook(self.api_url, payload, 0, str(e)[:500])
        
        self.db.save_message(message)
        self.db.save_delivery_record(record)
        
        status_icon = "✅" if record.status == "DELIVERED" else "❌"
        print(f"{status_icon} SMS notification | {message.title} | {record.status}")
        
        return record


class WebhookNotifier(BaseNotifier):
    """Generic webhook notifications"""
    
    def __init__(self, webhook_url: str, headers: Optional[Dict] = None):
        super().__init__(NotificationChannel.WEBHOOK)
        self.webhook_url = webhook_url
        self.headers = headers or {"Content-Type": "application/json"}
    
    def send(self, message: NotificationMessage) -> DeliveryRecord:
        """Send webhook notification"""
        if not self.enabled:
            return self.create_delivery_record(message, "DISABLED")
        
        payload = {
            "message_id": message.message_id,
            "timestamp": message.timestamp.isoformat(),
            "title": message.title,
            "content": message.content,
            "priority": message.priority.value,
            "channel": message.channel.value,
            "recipient": message.recipient,
            "metadata": message.metadata
        }
        
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code in [200, 201, 202, 204]:
                record = self.create_delivery_record(
                    message, "DELIVERED",
                    response_code=response.status_code,
                    response_message="Webhook delivered"
                )
                record.delivered_at = datetime.now()
            else:
                record = self.create_delivery_record(
                    message, "FAILED",
                    response_code=response.status_code,
                    response_message=response.text[:500]
                )
            
            self.db.log_webhook(self.webhook_url, payload, response.status_code, response.text[:500])
            
        except Exception as e:
            record = self.create_delivery_record(
                message, "FAILED",
                response_message=str(e)[:500]
            )
            self.db.log_webhook(self.webhook_url, payload, 0, str(e)[:500])
        
        self.db.save_message(message)
        self.db.save_delivery_record(record)
        
        status_icon = "✅" if record.status == "DELIVERED" else "❌"
        print(f"{status_icon} Webhook notification | {message.title} | {record.status}")
        
        return record


class NotificationManager:
    """Central manager for all notification channels"""
    
    def __init__(self):
        self.notifiers: Dict[NotificationChannel, BaseNotifier] = {}
        self.db = NotificationDatabase()
        self.default_recipients: Dict[NotificationChannel, str] = {}
    
    def register_notifier(self, channel: NotificationChannel, notifier: BaseNotifier):
        """Register a notification channel"""
        self.notifiers[channel] = notifier
    
    def set_default_recipient(self, channel: NotificationChannel, recipient: str):
        """Set default recipient for a channel"""
        self.default_recipients[channel] = recipient
    
    def send(self, title: str, content: str, channel: NotificationChannel,
             priority: NotificationPriority = NotificationPriority.NORMAL,
             recipient: Optional[str] = None, metadata: Optional[Dict] = None) -> List[DeliveryRecord]:
        """
        Send notification through specified channel
        
        Args:
            title: Notification title
            content: Notification content
            channel: Target channel
            priority: Priority level
            recipient: Override default recipient
            metadata: Additional data
        
        Returns:
            List of delivery records
        """
        import uuid
        
        # Use default recipient if not specified
        if recipient is None:
            recipient = self.default_recipients.get(channel, "default")
        
        # Create message
        message = NotificationMessage(
            message_id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            title=title,
            content=content,
            channel=channel,
            priority=priority,
            recipient=recipient,
            metadata=metadata or {}
        )
        
        # Send through appropriate notifier
        if channel in self.notifiers:
            record = self.notifiers[channel].send(message)
            return [record]
        else:
            print(f"❌ No notifier registered for channel: {channel.value}")
            return []
    
    def broadcast(self, title: str, content: str,
                 priority: NotificationPriority = NotificationPriority.NORMAL,
                 channels: Optional[List[NotificationChannel]] = None,
                 metadata: Optional[Dict] = None) -> List[DeliveryRecord]:
        """
        Broadcast notification to multiple channels
        
        Args:
            title: Notification title
            content: Notification content
            priority: Priority level
            channels: List of channels (None = all registered)
            metadata: Additional data
        
        Returns:
            List of delivery records
        """
        if channels is None:
            channels = list(self.notifiers.keys())
        
        records = []
        for channel in channels:
            if channel in self.notifiers:
                recipient = self.default_recipients.get(channel, "default")
                record = self.send(title, content, channel, priority, recipient, metadata)
                records.extend(record)
        
        return records
    
    def get_stats(self) -> Dict:
        """Get notification statistics"""
        stats = {}
        for channel in NotificationChannel:
            stats[channel.value] = self.db.get_delivery_stats(channel)
        stats['overall'] = self.db.get_delivery_stats()
        return stats
    
    def generate_report(self, output_dir: str = "notifications/logs") -> str:
        """Generate notification delivery report"""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_path = Path(output_dir) / f"notification_report_{timestamp}.json"
        
        stats = self.get_stats()
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'statistics': stats,
            'registered_channels': [c.value for c in self.notifiers.keys()],
            'default_recipients': {k.value: v for k, v in self.default_recipients.items()}
        }
        
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"Notification report generated: {report_path}")
        return str(report_path)


# Convenience functions for common notifications
def notify_trade_opened(symbol: str, direction: str, lot_size: float, entry_price: float,
                       manager: NotificationManager, channels: Optional[List[NotificationChannel]] = None):
    """Notify when trade is opened"""
    title = f"Trade Opened: {symbol}"
    content = f"{direction} {lot_size} lots @ {entry_price}"
    
    return manager.broadcast(title, content, NotificationPriority.NORMAL, channels,
                           metadata={'symbol': symbol, 'direction': direction,
                                    'lot_size': lot_size, 'entry_price': entry_price})


def notify_trade_closed(symbol: str, profit: float, manager: NotificationManager,
                       channels: Optional[List[NotificationChannel]] = None):
    """Notify when trade is closed"""
    title = f"Trade Closed: {symbol}"
    content = f"P&L: ${profit:.2f}"
    priority = NotificationPriority.HIGH if profit < 0 else NotificationPriority.NORMAL
    
    return manager.broadcast(title, content, priority, channels,
                           metadata={'symbol': symbol, 'profit': profit})


def notify_error(error_message: str, manager: NotificationManager,
                channels: Optional[List[NotificationChannel]] = None):
    """Notify on error"""
    return manager.broadcast("Error", error_message, NotificationPriority.CRITICAL, channels,
                           metadata={'error': True})


if __name__ == "__main__":
    print("HOPEFX Notifications Module")
    print("Features:")
    print("  ✅ Discord webhook integration")
    print("  ✅ Telegram bot integration")
    print("  ✅ Email SMTP integration")
    print("  ✅ SMS via Twilio")
    print("  ✅ Generic webhook support")
    print("  ✅ Delivery tracking with SQLite")
    print("  ✅ Priority levels")
    print("  ✅ Broadcast to multiple channels")
'''

# Save the file
with open('notifications/manager.py', 'w') as f:
    f.write(code)

print("✅ Created: notifications/manager.py")
print(f"   Lines: {len(code.splitlines())}")
print(f"   Size: {len(code)} bytes")
print("\n📊 Notifications Module Summary:")
print("   ✅ Discord webhook with rich embeds")
print("   ✅ Telegram bot with Markdown formatting")
print("   ✅ Email SMTP with HTML templates")
print("   ✅ SMS via Twilio API")
print("   ✅ Generic webhook support")
print("   ✅ SQLite delivery tracking database")
print("   ✅ Priority levels (Low, Normal, High, Critical)")
print("   ✅ Broadcast to multiple channels")
print("   ✅ Delivery statistics and reporting")
