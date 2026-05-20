// 测试登录功能
async function testLogin() {
    try {
        console.log('开始测试登录...');
        
        // 尝试直接连接后端
        const response = await fetch('http://127.0.0.1:5000/api/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username: 'testuser', password: 'test123' })
        });
        
        console.log('响应状态:', response.status);
        console.log('响应头:', response.headers);
        
        const data = await response.json();
        console.log('响应数据:', data);
        
        if (response.ok) {
            console.log('登录成功！');
        } else {
            console.log('登录失败:', data.error);
        }
    } catch (error) {
        console.error('错误:', error);
    }
}

// 测试getApiBaseUrl函数
function testGetApiBaseUrl() {
    const currentProtocol = window.location.protocol;
    const currentHost = window.location.hostname;
    const apiUrl = `${currentProtocol}//${currentHost}:5000`;
    console.log('API基础URL:', apiUrl);
}

// 运行测试
testGetApiBaseUrl();
testLogin();