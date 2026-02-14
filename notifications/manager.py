# Import necessary libraries
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)

class NotificationManager:
    def __init__(self):
        self.notifications = []

    def add_notification(self, message):
        timestamp = datetime.utcnow().isoformat()
        self.notifications.append(f'{timestamp} - {message}')

    def show_notifications(self):
        for notification in self.notifications:
            print(notification)