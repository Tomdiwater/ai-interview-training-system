import socket
import threading
import os

class SimpleHTTPServer:
    def __init__(self, host='127.0.0.1', port=8000):
        self.host = host
        self.port = port
        self.server_socket = None
    
    def start(self):
        # 创建服务器套接字
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            print(f"服务器启动成功，监听地址: {self.host}:{self.port}")
            print(f"请在浏览器中访问: http://{self.host}:{self.port}/frontend/index.html")
            
            while True:
                client_socket, client_address = self.server_socket.accept()
                threading.Thread(target=self.handle_client, args=(client_socket, client_address)).start()
                
        except Exception as e:
            print(f"服务器启动失败: {e}")
        finally:
            if self.server_socket:
                self.server_socket.close()
    
    def handle_client(self, client_socket, client_address):
        try:
            # 接收客户端请求
            request = client_socket.recv(1024).decode('utf-8')
            print(f"收到请求 from {client_address}: {request.split('\n')[0]}")
            
            # 解析请求路径
            if request:
                path = request.split(' ')[1]
                if path == '/':
                    path = '/frontend/index.html'
                
                # 构建文件路径
                file_path = os.path.join(os.getcwd(), path.lstrip('/'))
                
                # 处理文件请求
                if os.path.exists(file_path) and os.path.isfile(file_path):
                    # 读取文件
                    with open(file_path, 'rb') as f:
                        content = f.read()
                    
                    # 根据文件扩展名设置Content-Type
                    content_type = self.get_content_type(file_path)
                    
                    # 发送响应
                    response = f"HTTP/1.1 200 OK\r\n"
                    response += f"Content-Type: {content_type}\r\n"
                    response += f"Content-Length: {len(content)}\r\n"
                    response += "Connection: close\r\n"
                    response += "\r\n"
                    
                    client_socket.sendall(response.encode('utf-8') + content)
                else:
                    # 文件不存在，返回404
                    response = "HTTP/1.1 404 Not Found\r\n"
                    response += "Content-Type: text/html\r\n"
                    response += "Connection: close\r\n"
                    response += "\r\n"
                    response += "<h1>404 Not Found</h1>"
                    client_socket.sendall(response.encode('utf-8'))
        
        except Exception as e:
            print(f"处理请求时出错: {e}")
        finally:
            client_socket.close()
    
    def get_content_type(self, file_path):
        """根据文件扩展名返回Content-Type"""
        ext = os.path.splitext(file_path)[1].lower()
        
        content_types = {
            '.html': 'text/html',
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif'
        }
        
        return content_types.get(ext, 'application/octet-stream')

if __name__ == '__main__':
    server = SimpleHTTPServer(port=8080)
    server.start()