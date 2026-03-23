import time
import random

class Order:
    def __init__(self, order_id, quantity, price, commission_rate):
        self.order_id = order_id
        self.quantity = quantity
        self.price = price
        self.executed_quantity = 0
        self.commission_rate = commission_rate
        self.commission_paid = 0.0
        self.is_filled = False

    def fill(self, filled_quantity):
        if filled_quantity > self.quantity:
            raise ValueError("Filled quantity cannot exceed order quantity.")
        self.executed_quantity += filled_quantity
        self.commission_paid += filled_quantity * self.commission_rate
        if self.executed_quantity >= self.quantity:
            self.is_filled = True

class OrderGateway:
    def __init__(self):
        self.orders = {}

    def create_order(self, order_id, quantity, price, commission_rate):
        order = Order(order_id, quantity, price, commission_rate)
        self.orders[order_id] = order
        return order

    def send_order(self, order):
        # Simulating order processing
        print(f'Sending order {order.order_id}...')
        time.sleep(random.uniform(0.1, 0.5)) # Simulate network delay

        # Simulating random slippage
        slippage = random.uniform(-0.05, 0.05) * order.price
        final_price = order.price + slippage

        # Simulating order fill
        filled_quantity = min(order.quantity, random.randint(0, order.quantity + 5))
        order.fill(filled_quantity)
        print(f'Order {order.order_id} filled with quantity {filled_quantity} at price {final_price:.2f} (slippage: {slippage:.2f})')

        if order.is_filled:
            print(f'Order {order.order_id} completely filled.')
        else:
            print(f'Order {order.order_id} partially filled.')

    def handle_rejection(self, order_id):
        print(f'Order {order_id} has been rejected.')

    def track_commissions(self):
        total_commissions = sum(order.commission_paid for order in self.orders.values())
        print(f'Total commissions paid: {total_commissions:.2f}')