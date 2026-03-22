from locust import User, task, between

class TradingUser(User):
    wait_time = between(1, 5)

    @task(1)
    def buy_stock(self):
        # Simulate buying stock operation
        print("Buying stock...")

    @task(2)
    def sell_stock(self):
        # Simulate selling stock operation
        print("Selling stock...")

    @task(3)
    def get_portfolio(self):
        # Simulate retrieving portfolio
        print("Getting portfolio...")

    @task(4)
    def check_stock_price(self):
        # Simulate checking stock prices
        print("Checking stock prices...")
