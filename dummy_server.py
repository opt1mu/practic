from flask import Flask, jsonify, request

app = Flask(__name__)

@app.route('/')
def index():
    return "Main page", 200

@app.route('/api/v1/items')
def items():
    return jsonify({"items": ["book", "pen"]}), 200

@app.route('/api/profile')
def profile():
    return jsonify({"status": "profile_data"}), 200

@app.route('/api/v1/data', methods=['POST'])
def data():
    return jsonify({"status": "created"}), 201

if __name__ == '__main__':
    # Запускаем сервер на порту 8080
    app.run(host='127.0.0.1', port=8080)