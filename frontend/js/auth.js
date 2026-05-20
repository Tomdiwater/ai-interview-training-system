// API基础URL
const API_BASE_URL = 'http://127.0.0.1:5000';

// 表单切换函数
function switchForm(formType) {
    console.log('切换表单:', formType);
    const loginForm = document.getElementById('login-form');
    const registerForm = document.getElementById('register-form');
    
    if (!loginForm || !registerForm) {
        console.error('找不到表单元素');
        return;
    }
    
    if (formType === 'login') {
        loginForm.classList.remove('hidden');
        registerForm.classList.add('hidden');
        console.log('切换到登录表单');
    } else if (formType === 'register') {
        loginForm.classList.add('hidden');
        registerForm.classList.remove('hidden');
        console.log('切换到注册表单');
    }
}

// 显示消息
function showMessage(elementId, message, isError) {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    element.textContent = message;
    element.className = 'message ' + (isError ? 'error' : 'success');
    
    // 3秒后清除消息
    setTimeout(() => {
        element.textContent = '';
        element.className = '';
    }, 3000);
}

// 初始化表单事件监听
function initAuthForms() {
    // 登录表单提交
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const username = document.getElementById('login-username').value;
            const password = document.getElementById('login-password').value;
            
            if (!username || !password) {
                showMessage('login-message', '请输入用户名和密码', true);
                return;
            }
            
            try {
                const response = await fetch(`${API_BASE_URL}/api/login`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ username, password })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    // 保存用户信息到本地存储
                    localStorage.setItem('user_id', data.user_id.toString());
                    localStorage.setItem('username', data.username);
                    
                    showMessage('login-message', '登录成功，正在跳转...', false);
                    
                    // 延迟跳转，让用户看到成功消息
                    setTimeout(() => {
                        window.location.href = '/frontend/home.html';
                    }, 1000);
                } else {
                    showMessage('login-message', data.error || '登录失败', true);
                }
            } catch (error) {
                console.error('登录错误:', error);
                showMessage('login-message', '网络错误，请检查后端服务是否运行', true);
            }
        });
    }

    // 注册表单提交
    const registerForm = document.getElementById('registerForm');
    if (registerForm) {
        registerForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const username = document.getElementById('register-username').value;
            const password = document.getElementById('register-password').value;
            const email = document.getElementById('register-email').value;
            
            if (!username || !password || !email) {
                showMessage('register-message', '请填写所有字段', true);
                return;
            }
            
            // 简单的邮箱格式验证
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(email)) {
                showMessage('register-message', '请输入有效的邮箱地址', true);
                return;
            }
            
            try {
                const response = await fetch(`${API_BASE_URL}/api/register`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ username, password, email })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    showMessage('register-message', '注册成功！请登录', false);
                    
                    // 清空表单
                    document.getElementById('register-username').value = '';
                    document.getElementById('register-password').value = '';
                    document.getElementById('register-email').value = '';
                    
                    // 1.5秒后切换到登录表单
                    setTimeout(() => {
                        switchForm('login');
                    }, 1500);
                } else {
                    showMessage('register-message', data.error || '注册失败', true);
                }
            } catch (error) {
                console.error('注册错误:', error);
                showMessage('register-message', '网络错误，请检查后端服务是否运行', true);
            }
        });
    }
}

// 检查用户是否已登录
function checkLogin() {
    const user_id = localStorage.getItem('user_id');
    if (!user_id) {
        window.location.href = '/frontend/index.html';
    }
    return user_id;
}

// 页面加载完成后初始化
console.log('auth.js 已加载');
if (document.readyState === 'loading') {
    console.log('等待 DOM 加载...');
    document.addEventListener('DOMContentLoaded', () => {
        console.log('DOM 加载完成，初始化表单');
        initAuthForms();
    });
} else {
    console.log('DOM 已就绪，立即初始化表单');
    initAuthForms();
}