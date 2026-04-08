# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
import json
import time

import redis


import logging

logger = logging.getLogger(__name__)


class TestRedisConnection:
    def __init__(self, host="localhost", port=6379, db=0):
        self.client = redis.StrictRedis(host=host, port=port, db=db)

    def test_connectivity(self):
        try:
            self.client.ping()
            logger.info("Connection to Redis successful.")
            return True
        except redis.ConnectionError:
            logger.error("Failed to connect to Redis.")
            return False

    def store_tick_data(self, tick_data):
        try:
            self.client.set("tick_data", json.dumps(tick_data))
            logger.info("Sample tick data stored.")
        except Exception as e:
            logger.error(f"Error storing tick data: {e}")

    def retrieve_tick_data(self):
        try:
            data = self.client.get("tick_data")
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Error retrieving tick data: {e}")

    def hset_order(self, order_id, order_info):
        try:
            self.client.hset("orders", order_id, json.dumps(order_info))
            logger.info(f"Order {order_id} stored.")
        except Exception as e:
            logger.error(f"Error setting order: {e}")

    def hget_order(self, order_id):
        try:
            order = self.client.hget("orders", order_id)
            return json.loads(order) if order else None
        except Exception as e:
            logger.error(f"Error getting order: {e}")

    def test_list_operations(self):
        try:
            self.client.rpush("orders_list", "order_1")
            self.client.rpush("orders_list", "order_2")
            logger.info("Orders added to list.")
            first_order = self.client.lpop("orders_list")
            logger.info(f"Retrieved order from list: {first_order}")
        except Exception as e:
            logger.error(f"Error performing list operations: {e}")

    def measure_latency(self):
        start_time = time.time()
        self.client.ping()
        latency = time.time() - start_time
        logger.info(f"Latency: {latency * 1000:.2f} ms")


if __name__ == "__main__":
    test_redis = TestRedisConnection()
    if test_redis.test_connectivity():
        sample_ticks = {"tick": 12345, "timestamp": "2026-03-22 06:33:38"}
        test_redis.store_tick_data(sample_ticks)
        logger.info("Retrieved tick data:", test_redis.retrieve_tick_data())
        test_redis.hset_order("1", {"price": 100, "quantity": 10})
        logger.info("Order 1:", test_redis.hget_order("1"))
        test_redis.test_list_operations()
        test_redis.measure_latency()
