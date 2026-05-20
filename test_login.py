import requests
import json

# 测试登录接口
url = 'http://127.0.0.1:5000/api/login'
data = {
    'username': 'testuser',
    'password': 'test123'
}

headers = {
    'Content-Type': 'application/json'
}

try:
    response = requests.post(url, json=data, headers=headers)
    print('状态码:', response.status_code)
    print('响应内容:', response.json())
except Exception as e:
    print('错误:', str(e))

# 测试注册接口
print('\n测试注册接口:')
register_url = 'http://127.0.0.1:5000/api/register'
register_data = {
    'username': 'newuser',
    'password': 'newpass123',
    'email': 'newuser@example.com'
}

try:
    response = requests.post(register_url, json=register_data, headers=headers)
    print('状态码:', response.status_code)
    print('响应内容:', response.json())
except Exception as e:
    print('错误:', str(e))