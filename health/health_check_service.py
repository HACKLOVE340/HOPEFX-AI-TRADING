import requests
import psutil
import json

class HealthCheckService:
    def __init__(self):
        self.alerts = []

    def check_api(self, url):
        try:
            response = requests.get(url)
            return response.status_code == 200
        except Exception as e:
            self.alerts.append(f"API check failed: {str(e)}")
            return False

    def check_database(self, db_connection):
        # Dummy check for database connection
        try:
            db_connection.ping()
            return True
        except Exception as e:
            self.alerts.append(f"Database check failed: {str(e)}")
            return False

    def check_cache(self, cache_service):
        # Dummy check for cache service
        try:
            cache_service.ping()
            return True
        except Exception as e:
            self.alerts.append(f"Cache check failed: {str(e)}")
            return False

    def check_broker_connections(self, broker):
        # Check broker connection
        try:
            broker.check_connection()
            return True
        except Exception as e:
            self.alerts.append(f"Broker connection check failed: {str(e)}")
            return False

    def check_market_data_feed(self, market_data_url):
        return self.check_api(market_data_url)

    def monitor_system_resources(self):
        cpu = psutil.cpu_percent()
        memory = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        return {
            "cpu": cpu,
            "memory": memory,
            "disk": disk
        }

    def aggregate_health_status(self):
        # Connections are injected at runtime; use None as safe default
        status = {
            "api": self.check_api('http://localhost:8000'),
            "db": self.check_database(None),
            "cache": self.check_cache(None),
            "broker": self.check_broker_connections(None),
            "market_data": self.check_market_data_feed('http://localhost:8000'),
            "system_resources": self.monitor_system_resources(),
        }
        status['alerts'] = self.alerts
        return status

if __name__ == "__main__":
    service = HealthCheckService()
    health_status = service.aggregate_health_status()
    print(json.dumps(health_status, indent=4))