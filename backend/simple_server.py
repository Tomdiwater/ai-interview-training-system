import http.server
import socketserver

PORT = 8000

handler = http.server.SimpleHTTPRequestHandler

with socketserver.TCPServer(("localhost", PORT), handler) as httpd:
    print(f"服务器运行在 http://localhost:{PORT}")
    httpd.serve_forever()
