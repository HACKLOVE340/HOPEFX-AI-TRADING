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
