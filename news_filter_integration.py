import requests
import redis
import time
from datetime import datetime, timedelta

class NewsFilterIntegration:
    def __init__(self, redis_host='localhost', redis_port=6379, event_cache_duration=300):
        self.redis_client = redis.StrictRedis(host=redis_host, port=redis_port, decode_responses=True)
        self.event_cache_duration = event_cache_duration

    def fetch_forex_events(self):
        url = "https://api.forexfactory.com/v1/events"
        try:
            response = requests.get(url)
            response.raise_for_status()  # Raise an exception for HTTP errors
            events = response.json()
            return events
        except requests.RequestException as e:
            print(f"API Error: {e}")
            return []

    def filter_events(self, events):
        now = datetime.utcnow()
        upcoming_events = []
        for event in events:
            event_time = datetime.strptime(event['date'], '%Y-%m-%d %H:%M:%S')
            if 0 <= (event_time - now).total_seconds() <= event['duration'] * 60:  # Check if event is upcoming
                upcoming_events.append(event)
                self.cache_event(event)
        return upcoming_events

    def cache_event(self, event):
        self.redis_client.set(event['id'], event, ex=self.event_cache_duration)

    def is_trading_paused(self):
        # Implement your logic to determine if trading should be paused
        return False  # Placeholder, should check with actual trading logic

    def pause_trading(self):
        # Implement your trading pause logic
        print("Trading is paused due to high-impact news events.")
        
    def run(self, check_interval=60):
        while True:
            events = self.fetch_forex_events()
            upcoming_events = self.filter_events(events)
            
            if upcoming_events:
                self.pause_trading()
            time.sleep(check_interval)

if __name__ == "__main__":
    nf_integration = NewsFilterIntegration()
    nf_integration.run()