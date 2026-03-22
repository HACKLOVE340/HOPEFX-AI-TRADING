import websocket
import json
import threading
import time

class MT5LiveFeed:
    def __init__(self, url):
        self.url = url
        self.connected = False
        self.latency = []
        self.smoothed_ticks = []
        self.tick_buffer = []
        self.reconnect_interval = 5  # seconds
        self.ws = None

    def connect(self):
        def on_open(ws):
            self.connected = True
            print("WebSocket connection opened.")

        def on_message(ws, message):
            self.handle_message(message)

        def on_close(ws):
            self.connected = False
            print("WebSocket connection closed.")
            self.reconnect()

        self.ws = websocket.WebSocketApp(self.url,
                                          on_open=on_open,
                                          on_message=on_message,
                                          on_close=on_close)
        self.ws.run_forever()

    def reconnect(self):
        while not self.connected:
            print(f"Attempting to reconnect in {self.reconnect_interval} seconds...")
            time.sleep(self.reconnect_interval)
            self.connect()

    def handle_message(self, message):
        tick_data = json.loads(message)
        self.track_latency(tick_data)
        self.smooth_ticks(tick_data)

    def track_latency(self, tick_data):
        timestamp = tick_data.get('timestamp')
        latency = time.time() - timestamp
        self.latency.append(latency)
        if len(self.latency) > 100:
            self.latency.pop(0)  # Keep the last 100 latency measurements

    def smooth_ticks(self, tick_data):
        self.tick_buffer.append(tick_data)
        if len(self.tick_buffer) > 10:  # Smoothing over the last 10 ticks
            self.tick_buffer.pop(0)
        smoothed_tick = self.calculate_smoothed_tick()
        self.smoothed_ticks.append(smoothed_tick)

    def calculate_smoothed_tick(self):
        # Implement your smoothing algorithm here
        # Placeholder for simplicity
        return sum(tick['price'] for tick in self.tick_buffer) / len(self.tick_buffer)

    def start(self):
        threading.Thread(target=self.connect).start()

if __name__ == '__main__':
    live_feed = MT5LiveFeed('wss://your.websocket.url')
    live_feed.start()
