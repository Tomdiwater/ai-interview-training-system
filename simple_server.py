from flask import Flask, send_from_directory
import os

app = Flask(__name__)

# 配置静态文件服务
@app.route('/')
def index():
    return send_from_directory('frontend', 'index.html')

@app.route('/frontend/<path:filename>')
def serve_frontend(filename):
    return send_from_directory('frontend', filename)

if __name__ == '__main__':
    # 使用127.0.0.1作为主机地址，避免网络配置问题
    app.run(debug=True, host='127.0.0.1', port=5000)