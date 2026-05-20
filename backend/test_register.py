import requests

# 测试注册接口
def test_register():
    url = 'http://127.0.0.1:5000/api/register'
    data = {
        'username': 'testuser',
        'password': 'test123',
        'email': 'testuser@example.com'
    }
    
    try:
        response = requests.post(url, json=data)
        print(f'响应状态码: {response.status_code}')
        print(f'响应内容: {response.json()}')
    except Exception as e:
        print(f'测试失败: {e}')

if __name__ == '__main__':
    test_register()
