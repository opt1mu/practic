from flask import Flask, jsonify, request
import time

app = Flask(__name__)

request_timestamps = []
RATE_LIMIT_RPS = 15


def is_rate_limited():
    now = time.time()
    global request_timestamps
    request_timestamps = [t for t in request_timestamps if now - t < 1.0]

    if len(request_timestamps) >= RATE_LIMIT_RPS:
        return True

    request_timestamps.append(now)
    return False


@app.route('/')
def index():
    if is_rate_limited():
        return "Too Many Requests", 429
    return "Main page", 200


@app.route('/api/v1/items')
def items():
    if is_rate_limited():
        return jsonify({"error": "Too Many Requests"}), 429
    return jsonify({"items": ["book", "pen"]}), 200


@app.route('/api/profile')
def profile():
    if is_rate_limited():
        return jsonify({"error": "Too Many Requests"}), 429
    return jsonify({"status": "profile_data"}), 200


@app.route('/api/v1/data', methods=['POST'])
def data():
    if is_rate_limited():
        return jsonify({"error": "Too Many Requests"}), 429
    return jsonify({"status": "created"}), 201


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080)