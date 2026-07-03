from http.server import BaseHTTPRequestHandler, HTTPServer

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(429)
        self.end_headers()
        self.wfile.write(b"Too Many Requests")

    def log_message(self, format, *args):
        pass # отключаем лишние логи в консоли сервера

if __name__ == "__main__":
    server = HTTPServer(('127.0.0.1', 8080), RequestHandler)
    print("[*] Mock-сервер запущен на http://127.0.0.1:8080 (всегда возвращает 429)")
    server.serve_forever()