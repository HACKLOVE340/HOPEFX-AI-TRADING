# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# Advanced Rate Limiting

from flask import Flask, request, jsonify
from collections import defaultdict
import time

app = Flask(__name__)

# Dictionary to store request counts and timestamps
rate_limits = defaultdict(lambda: defaultdict(list))

# Configuration
PER_USER_LIMIT = 5  # max requests per user
PER_USER_WINDOW = 60  # seconds
PER_ENDPOINT_LIMIT = 10  # max requests per endpoint
PER_ENDPOINT_WINDOW = 60  # seconds


# Helper function to clean up old requests
def cleanup_requests(user, endpoint):
    current_time = time.time()
    # Remove requests that are outside the window
    rate_limits[user][endpoint] = [
        timestamp
        for timestamp in rate_limits[user][endpoint]
        if current_time - timestamp < PER_ENDPOINT_WINDOW
    ]


@app.route("/api/some_endpoint", methods=["GET"])
def some_endpoint():
    user = request.args.get("user_id")  # Example of getting user ID from request
    endpoint = "/api/some_endpoint"

    cleanup_requests(user, endpoint)

    # Check per-user limit
    if len(rate_limits[user][endpoint]) >= PER_USER_LIMIT:
        return jsonify({"error": "User rate limit exceeded"}), 429

    # Check per-endpoint limit
    if len(rate_limits[endpoint]) >= PER_ENDPOINT_LIMIT:
        return jsonify({"error": "Endpoint rate limit exceeded"}), 429

    # Log the request
    rate_limits[user][endpoint].append(time.time())
    rate_limits[endpoint].append(time.time())

    return jsonify({"message": "Success"}), 200


if __name__ == "__main__":
    # debug=False — never run with debug=True in production (B201)
    app.run(debug=False)
