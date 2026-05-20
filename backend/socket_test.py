import socket

print("测试 socket 连接...")

try:
    # 测试本地连接
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 5000))
    s.listen(1)
    print("成功绑定到 127.0.0.1:5000")
    s.close()
    print("socket 测试成功")
except Exception as e:
    print(f"socket 测试失败: {e}")
