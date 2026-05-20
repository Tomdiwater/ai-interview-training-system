from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
import pymysql
import bcrypt
import json
import random
import base64
import binascii
import datetime
import time
import traceback
import os
import tempfile
try:
    import numpy as np
except Exception:
    np = None

try:
    import cv2
except Exception:
    cv2 = None

try:
    import requests
except ImportError:
    requests = None

XF_IMPORT_ERROR = None
try:
    # script mode: python backend/app.py
    from xf_api import MultimodalScoringEngine, get_xf_client, call_spark_ws_api
except Exception as e1:
    try:
        # module mode: python -m backend.app / flask --app backend.app
        from .xf_api import MultimodalScoringEngine, get_xf_client, call_spark_ws_api
    except Exception as e2:
        XF_IMPORT_ERROR = f"absolute import failed: {e1}; relative import failed: {e2}"
        MultimodalScoringEngine = None
        get_xf_client = None
        call_spark_ws_api = None


# 创建Flask应用实例
app = Flask(__name__)
# 启用CORS，允许跨域请求
CORS(app, resources={"/*": {"origins": ["*"], "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization"]}})

if XF_IMPORT_ERROR:
    print(f"[XF_IMPORT_ERROR] {XF_IMPORT_ERROR}")


def _json_error(message, status=500, details=None):
    payload = {"success": False, "error": message}
    if details:
        payload["details"] = details
    return jsonify(payload), status


def _decode_base64_image(image_base64):
    if cv2 is None or np is None:
        return None
    try:
        raw = image_base64.split(",", 1)[1] if "," in image_base64 else image_base64
        img_bytes = base64.b64decode(raw)
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


_HAAR_CACHE_PATH = None


def _get_haar_cascade_path():
    global _HAAR_CACHE_PATH
    if _HAAR_CACHE_PATH and os.path.exists(_HAAR_CACHE_PATH):
        return _HAAR_CACHE_PATH

    source_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    if not os.path.exists(source_path):
        return None

    temp_root = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp")
    os.makedirs(temp_root, exist_ok=True)
    target_path = os.path.join(temp_root, "codex_haar_frontalface.xml")
    try:
        with open(source_path, "rb") as src, open(target_path, "wb") as dst:
            dst.write(src.read())
        _HAAR_CACHE_PATH = target_path
        return target_path
    except Exception:
        return None


def _local_face_detect(image_base64):
    if cv2 is None or np is None:
        return {"success": False, "error": "opencv/numpy 未安装，无法本地人脸检测"}

    image = _decode_base64_image(image_base64)
    if image is None:
        return {"success": False, "error": "图片解码失败"}

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray_eq = cv2.equalizeHist(gray)
    cascade_path = _get_haar_cascade_path()
    if not cascade_path:
        return {"success": False, "error": "无法加载 OpenCV 人脸模型文件"}

    detector = cv2.CascadeClassifier(cascade_path)
    if detector.empty():
        return {"success": False, "error": "OpenCV 人脸模型初始化失败"}

    try:
        faces = detector.detectMultiScale(gray_eq, scaleFactor=1.08, minNeighbors=4, minSize=(28, 28))
        if len(faces) == 0:
            faces = detector.detectMultiScale(gray_eq, scaleFactor=1.03, minNeighbors=2, minSize=(20, 20))
    except Exception as exc:
        return {"success": False, "error": f"本地人脸检测失败: {exc}"}

    h, w = gray.shape[:2]
    frame_area = max(1, w * h)
    if len(faces) == 0:
        return {
            "success": True,
            "source": "local_cv",
            "face_detected": False,
            "compliance_check": {
                "is_compliant": False,
                "face_coverage": 0,
                "is_frontal": False,
                "has_occlusion": False,
                "lighting_ok": True,
                "deductions": ["未检测到人脸"]
            },
            "expression_analysis": {
                "confidence": 35,
                "dominant_emotion": "neutral",
                "attention": 30,
                "eye_gaze": {"direction_x": 0},
                "head_pose": {"yaw": 0, "pitch": 0}
            }
        }

    # Lock to the likely interview subject:
    # 1. discard tiny background faces by keeping only candidates near the max area
    # 2. within those, prefer larger and more central faces
    areas = [int(f[2]) * int(f[3]) for f in faces]
    max_area = max(areas) if areas else 0
    candidate_faces = [f for f in faces if int(f[2]) * int(f[3]) >= max_area * 0.42] or faces

    def _face_score(face):
        fx, fy, fw0, fh0 = [int(v) for v in face]
        area = max(1, fw0 * fh0)
        cx0 = fx + fw0 / 2.0
        cy0 = fy + fh0 / 2.0
        center_dx0 = abs(cx0 - w / 2.0) / max(1, w)
        center_dy0 = abs(cy0 - h / 2.0) / max(1, h)
        center_score = max(0.0, 1.0 - (center_dx0 + center_dy0))
        area_score = area / frame_area
        return area_score * 0.62 + center_score * 0.38

    x, y, fw, fh = max(candidate_faces, key=_face_score)
    # Cast to builtin numeric types to avoid numpy scalar JSON serialization errors.
    x, y, fw, fh = int(x), int(y), int(fw), int(fh)
    cx = x + fw / 2.0
    cy = y + fh / 2.0
    center_dx = abs(cx - w / 2.0) / max(1, w)
    center_dy = abs(cy - h / 2.0) / max(1, h)
    aspect = fw / max(1.0, fh)
    is_frontal = bool(0.50 < aspect < 1.95 and center_dx < 0.34 and center_dy < 0.34)

    edge_penalty = 0.0
    if x < w * 0.08 or (x + fw) > w * 0.92:
        edge_penalty += 28.0
    if y < h * 0.06 or (y + fh) > h * 0.94:
        edge_penalty += 16.0

    # Make local_cv less conservative when user is centered in frame,
    # but heavily penalize half faces near the edges.
    area_pct = (fw * fh) / frame_area * 100.0
    base_coverage = area_pct * 4.3
    center_bonus = max(0.0, (1.0 - (center_dx + center_dy)) * 16.0)
    frontal_bonus = 6.0 if is_frontal else 0.0
    face_coverage = int(max(0, min(100, round(base_coverage + center_bonus + frontal_bonus - edge_penalty))))

    is_compliant = bool(face_coverage >= 38 and is_frontal)
    attention = int(max(30, min(95, round(95 - (center_dx + center_dy) * 120))))

    return {
        "success": True,
        "source": "local_cv",
        "face_detected": True,
        "face_box": {"x": x, "y": y, "w": fw, "h": fh},
        "frame_size": {"w": int(w), "h": int(h)},
        "center_offset": {"x": round(float(center_dx), 4), "y": round(float(center_dy), 4)},
        "compliance_check": {
            "is_compliant": bool(is_compliant),
            "face_coverage": face_coverage,
            "is_frontal": bool(is_frontal),
            "has_occlusion": False,
            "lighting_ok": True,
            "deductions": [] if is_compliant else ["请将面部完整置于画面中央"]
        },
        "expression_analysis": {
            "confidence": 70,
            "dominant_emotion": "neutral",
            "attention": attention,
            "eye_gaze": {"direction_x": 0},
            "head_pose": {"yaw": 0, "pitch": 0}
        }
    }


def _face_failure_payload(reason):
    return {
        "success": True,
        "fallback": True,
        "warning": reason,
        "face_detected": False,
        "compliance_check": {
            "is_compliant": False,
            "face_coverage": 0,
            "is_frontal": False,
            "has_occlusion": False,
            "lighting_ok": True,
            "deductions": ["人脸检测暂不可用"]
        },
        "expression_analysis": {
            "confidence": 35,
            "dominant_emotion": "neutral",
            "attention": 30,
            "eye_gaze": {"direction_x": 0},
            "head_pose": {"yaw": 0, "pitch": 0}
        }
    }


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    """确保 API 路由在异常时返回 JSON，而不是 HTML 错误页。"""
    if isinstance(error, HTTPException):
        if request.path.startswith("/api/"):
            return _json_error(error.description or "请求失败", error.code or 500)
        return error

    traceback.print_exc()
    if request.path.startswith("/api/"):
        return _json_error("服务器内部错误", 500, str(error))
    raise error

# 配置静态文件服务
from flask import send_from_directory
import os

@app.route('/')
def serve_root():
    """提供根页面，重定向到前端登录页面"""
    return send_from_directory(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '../frontend'),
        'index.html'
    )

@app.route('/frontend/<path:filename>')
def serve_frontend(filename):
    import os
    frontend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../frontend')
    return send_from_directory(frontend_path, filename)


@app.route('/api/xf/health', methods=['GET'])
def xf_health():
    return jsonify({
        "success": True,
        "xf_loaded": get_xf_client is not None and MultimodalScoringEngine is not None,
        "import_error": XF_IMPORT_ERROR
    }), 200

# 数据库连接配置
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'ai_interview_system')

ALLOWED_JOB_CATEGORIES = (
    '前端开发',
    '后端开发',
    '测试开发',
    '算法工程师',
    'AI工程师',
    '数据开发',
    '运维 / DevOps',
    '网络安全',
    '架构师'
)

# 连接数据库
def get_db_connection():
    """获取数据库连接"""
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        return conn
    except Exception as e:
        print(f'数据库连接失败: {e}')
        raise

# 初始化数据库
def init_db():
    """初始化数据库，创建必要的表"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 创建用户表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    password VARCHAR(255) NOT NULL,
                    email VARCHAR(100) NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 创建题库表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS questions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    job_category VARCHAR(100) NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    keywords VARCHAR(255) NOT NULL
                )
            ''')
            
            # 创建面试记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS interview_records (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    job_category VARCHAR(100) NOT NULL,
                    questions JSON NOT NULL,
                    answers JSON NOT NULL,
                    scores JSON NOT NULL,
                    total_score INT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # 创建用户偏好设置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    preferred_categories JSON NOT NULL,
                    interview_duration INT DEFAULT 30,
                    email_notifications BOOLEAN DEFAULT true,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # 创建收藏表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS favorites (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NOT NULL,
                    question_id INT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (question_id) REFERENCES questions(id),
                    UNIQUE KEY user_question_unique (user_id, question_id)
                )
            ''')
            
            # 清空题库表，重新插入
            cursor.execute('DELETE FROM questions')

            # 插入题库数据（计算机类 9 个岗位方向）
            seed_questions = [
                ('前端开发', '请解释浏览器从输入 URL 到页面展示的大致过程。', '浏览器会先解析 URL、查询 DNS、建立 TCP/TLS 连接、发送 HTTP 请求，服务器返回资源后浏览器解析 HTML、CSS 和 JavaScript，构建 DOM/CSSOM、生成渲染树并完成布局、绘制和合成。回答时可以结合缓存、重定向和资源加载优化展开。', '浏览器,DNS,HTTP,渲染流程'),
                ('前端开发', '什么是闭包？它常见的使用场景和风险是什么？', '闭包是函数可以访问其外层作用域变量的机制。常用于封装私有变量、回调、函数柯里化和状态保存。风险是变量长期被引用可能造成内存占用增加，也容易在循环和异步场景下产生变量捕获问题。', '闭包,作用域,内存'),
                ('前端开发', '你会从哪些方面做前端性能优化？', '可以从资源体积、加载顺序、缓存策略、代码分割、图片优化、首屏渲染、减少重排重绘、接口并发和运行时性能等方面入手。实际项目里应结合指标，如 FCP、LCP、CLS 和接口耗时定位瓶颈。', '性能优化,首屏,缓存,LCP'),
                ('前端开发', 'Vue 或 React 的组件化开发解决了什么问题？', '组件化把界面拆成可复用、可维护的独立单元，降低复杂度，方便状态管理、局部更新、多人协作和测试。好的组件应有清晰的输入输出、稳定的职责边界和较少的副作用。', '组件化,React,Vue,状态'),
                ('前端开发', '什么是跨域？常见解决方式有哪些？', '跨域是浏览器同源策略限制下，不同协议、域名或端口之间的请求受限。常见解决方式包括 CORS、反向代理、JSONP、postMessage 和同域部署，其中业务接口通常优先使用 CORS 或网关代理。', '跨域,同源策略,CORS,代理'),
                ('前端开发', '请说明事件冒泡、事件捕获和事件委托。', '事件捕获是事件从外层向目标元素传播，事件冒泡是从目标元素向外层传播。事件委托利用冒泡，把多个子元素事件统一绑定到父元素处理，能减少监听器数量，并适合动态列表。', '事件流,事件冒泡,事件委托'),

                ('后端开发', '请说明 RESTful API 的设计原则。', 'RESTful API 通常以资源为中心，通过 HTTP 方法表达动作，如 GET 查询、POST 创建、PUT/PATCH 更新、DELETE 删除。设计时应关注路径清晰、状态码准确、参数规范、幂等性、鉴权和错误响应一致性。', 'RESTful,HTTP,状态码,幂等'),
                ('后端开发', '数据库索引为什么能提高查询速度？使用时要注意什么？', '索引通常基于 B+ 树、哈希等结构，能减少扫描行数，提高查询效率。使用时要注意最左前缀、选择性、覆盖索引、回表、索引维护成本，以及低区分度字段和频繁写入表不宜盲目加索引。', '索引,B+树,查询优化,回表'),
                ('后端开发', '什么是事务？ACID 分别是什么意思？', '事务是一组要么全部成功、要么全部失败的操作。ACID 分别是原子性、一致性、隔离性和持久性。面试中可以结合转账、订单扣库存等场景说明事务隔离级别和并发异常。', '事务,ACID,隔离级别'),
                ('后端开发', '如何理解缓存穿透、击穿和雪崩？', '缓存穿透是请求不存在的数据绕过缓存打到数据库，击穿是热点 key 过期瞬间大量请求打到数据库，雪崩是大量 key 同时失效导致数据库压力突增。常见处理包括空值缓存、布隆过滤器、互斥锁、随机过期时间和限流降级。', '缓存,Redis,穿透,雪崩'),
                ('后端开发', '什么是消息队列？适合解决什么问题？', '消息队列用于异步通信、系统解耦、削峰填谷和延迟处理。使用时要关注消息可靠性、重复消费、顺序性、事务一致性、积压处理和死信队列等问题。', '消息队列,异步,解耦,Kafka'),
                ('后端开发', '如何排查一个接口响应变慢的问题？', '可以先看监控确认慢在网络、网关、应用、数据库还是第三方服务；再通过日志、链路追踪、慢 SQL、线程池、GC 和资源使用率定位原因。排查时要先复现和量化，再做针对性优化。', '性能排查,慢SQL,链路追踪,监控'),

                ('测试开发', '测试用例设计通常会考虑哪些维度？', '测试用例应覆盖正常流程、异常流程、边界值、等价类、权限、兼容性、性能、安全和数据一致性。好的用例要有清晰前置条件、操作步骤、预期结果和优先级。', '测试用例,边界值,等价类'),
                ('测试开发', '自动化测试适合覆盖哪些场景？不适合哪些场景？', '自动化测试适合稳定、重复、回归频繁的接口、核心流程和冒烟场景。不适合需求频繁变动、强视觉主观判断、一次性验证或维护成本高于收益的场景。', '自动化测试,回归测试,冒烟测试'),
                ('测试开发', '接口测试需要重点验证哪些内容？', '接口测试要验证请求参数、响应结构、状态码、鉴权、幂等性、异常处理、边界数据、数据落库、并发和性能。还要关注接口之间的数据依赖和环境数据清理。', '接口测试,状态码,鉴权,幂等'),
                ('测试开发', '发现线上 Bug 后你会如何定位和推动修复？', '先确认影响范围和复现路径，保留日志、截图、请求参数和用户环境；再判断严重级别并通知相关负责人。定位时结合前端报错、后端日志、链路追踪和数据状态，修复后补充回归用例。', 'Bug定位,日志,回归测试'),
                ('测试开发', '性能测试中常见指标有哪些？', '常见指标包括 QPS/TPS、响应时间、并发数、错误率、CPU、内存、磁盘 IO、网络 IO 和数据库连接数。分析时要结合压测模型、瓶颈资源和业务容量目标。', '性能测试,QPS,响应时间,压测'),
                ('测试开发', '如何理解测试左移和测试右移？', '测试左移是在需求、设计和开发阶段提前介入，减少缺陷流到后期；测试右移是在上线后通过监控、灰度、告警和用户反馈持续验证质量。两者目标都是更早发现问题并降低修复成本。', '测试左移,测试右移,质量保障'),

                ('算法工程师', '请说明时间复杂度和空间复杂度的含义。', '时间复杂度描述算法运行时间随输入规模增长的趋势，空间复杂度描述额外内存占用随输入规模增长的趋势。常见复杂度包括 O(1)、O(log n)、O(n)、O(n log n)、O(n^2)。', '复杂度,时间复杂度,空间复杂度'),
                ('算法工程师', '哈希表适合解决什么问题？有哪些风险？', '哈希表适合快速查找、计数、去重和映射关系维护，平均查询复杂度接近 O(1)。风险包括哈希冲突、扩容成本、内存占用较高，以及需要设计合适的 key 和哈希函数。', '哈希表,查找,冲突'),
                ('算法工程师', '请解释动态规划的基本思路。', '动态规划适合有重叠子问题和最优子结构的问题。解题时通常定义状态、确定转移方程、初始化边界、选择遍历顺序，并考虑是否可以做空间压缩。', '动态规划,状态转移,最优子结构'),
                ('算法工程师', '二叉树遍历有哪些方式？分别适合什么场景？', '常见遍历包括前序、中序、后序和层序。前序适合复制或序列化树，中序常用于二叉搜索树有序输出，后序适合先处理子节点再处理父节点，层序适合按层分析。', '二叉树,遍历,BFS,DFS'),
                ('算法工程师', '机器学习中过拟合是什么？如何缓解？', '过拟合是模型在训练集表现很好，但泛化到新数据表现变差。缓解方式包括增加数据、数据增强、正则化、早停、交叉验证、降低模型复杂度和集成方法。', '过拟合,泛化,正则化'),
                ('算法工程师', '如何评估一个分类模型的效果？', '可以看准确率、精确率、召回率、F1、AUC、混淆矩阵等指标。指标选择要结合业务目标，例如风控和医疗场景可能更重视召回率，误报成本高的场景更重视精确率。', '分类模型,精确率,召回率,F1,AUC'),

                ('AI工程师', '请解释训练集、验证集和测试集的区别。', '训练集用于模型学习参数，验证集用于调参和模型选择，测试集用于最终评估泛化能力。三者应尽量保持数据分布一致，同时避免数据泄漏。', '训练集,验证集,测试集,数据泄漏'),
                ('AI工程师', '什么是 Transformer？为什么它适合处理序列数据？', 'Transformer 是基于自注意力机制的深度学习架构，能并行建模序列中不同位置之间的关系。相比 RNN，它更利于长距离依赖建模和大规模并行训练，是现代大模型的重要基础。', 'Transformer,注意力机制,序列建模'),
                ('AI工程师', '什么是 RAG？它解决了什么问题？', 'RAG 是检索增强生成，通过先检索外部知识，再把相关内容提供给生成模型，减少幻觉并提高回答的时效性和可追溯性。核心模块包括文档切分、向量化、召回、重排和生成。', 'RAG,向量数据库,检索增强'),
                ('AI工程师', '模型微调和提示词工程有什么区别？', '提示词工程通过设计输入引导模型输出，成本低、迭代快；微调通过训练更新模型参数，适合稳定任务和特定风格，但需要数据、算力和评估体系。实际项目中常先提示词优化，再考虑微调。', '微调,Prompt,模型优化'),
                ('AI工程师', '如何评估大模型应用是否可上线？', '需要评估准确性、稳定性、安全性、延迟、成本、鲁棒性和用户体验。还要准备测试集、人工评审、灰度发布、日志监控、兜底策略和敏感内容过滤。', '大模型评估,安全,延迟,成本'),
                ('AI工程师', '向量数据库在 AI 应用中起什么作用？', '向量数据库用于存储文本、图片等内容的向量表示，并支持相似度检索。它常用于知识库问答、推荐、语义搜索和 RAG 场景，关键点包括嵌入模型、切分策略、召回质量和索引性能。', '向量数据库,Embedding,语义检索'),

                ('数据开发', '数仓分层通常怎么设计？', '常见分层包括 ODS 原始层、DWD 明细层、DWS 汇总层、ADS 应用层。分层能降低耦合、复用公共数据、统一口径，并方便数据治理和问题追踪。', '数仓,ODS,DWD,DWS,ADS'),
                ('数据开发', 'ETL 和 ELT 有什么区别？', 'ETL 是先抽取、转换再加载，适合转换逻辑前置和目标存储能力较弱的场景；ELT 是先加载再在目标平台转换，适合云数仓、大数据平台等计算能力强的场景。', 'ETL,ELT,数据处理'),
                ('数据开发', '如何保证数据质量？', '可以从完整性、准确性、唯一性、一致性、及时性和有效性设计校验规则。实践中会做空值检查、重复检查、主外键校验、波动监控、血缘分析和质量告警。', '数据质量,校验,监控'),
                ('数据开发', 'SQL 调优可以从哪些方面入手？', '可以检查执行计划、索引命中、过滤条件、Join 顺序、分区裁剪、数据倾斜、字段选择和临时表使用。调优前要先定位瓶颈并确认数据量、统计信息和业务查询模式。', 'SQL调优,执行计划,索引,Join'),
                ('数据开发', '什么是数据倾斜？如何处理？', '数据倾斜是某些 key 数据量远大于其他 key，导致部分任务执行很慢。可通过加盐、拆分热点 key、预聚合、广播小表、调整分区和优化 Join 方式处理。', '数据倾斜,热点key,分区'),
                ('数据开发', '离线数仓和实时数仓有什么区别？', '离线数仓通常按小时或天批处理，适合报表和历史分析；实时数仓通过流处理低延迟更新，适合实时监控、风控和运营看板。两者在时效性、成本、准确性和架构复杂度上不同。', '离线数仓,实时数仓,流处理'),

                ('运维 / DevOps', 'CI/CD 流程一般包含哪些环节？', 'CI/CD 通常包括代码提交、自动构建、静态检查、自动化测试、制品管理、部署、灰度发布、回滚和监控告警。目标是降低发布风险，提高交付效率。', 'CI/CD,构建,部署,回滚'),
                ('运维 / DevOps', '如何排查服务器 CPU 或内存异常升高？', '先确认异常时间和影响范围，再查看进程资源占用、系统负载、日志、线程、连接数和最近发布变更。CPU 高可看热点线程，内存高可看泄漏、缓存膨胀和 GC 情况。', 'CPU,内存,排查,监控'),
                ('运维 / DevOps', 'Docker 镜像和容器有什么区别？', '镜像是只读模板，包含运行应用所需的文件系统和依赖；容器是镜像运行后的实例，有自己的进程和可写层。镜像强调交付，容器强调运行。', 'Docker,镜像,容器'),
                ('运维 / DevOps', 'Kubernetes 里 Pod、Service、Deployment 分别是什么？', 'Pod 是最小调度单元，Service 提供稳定访问入口和负载均衡，Deployment 管理副本数、滚动更新和回滚。三者配合实现应用部署和服务发现。', 'Kubernetes,Pod,Service,Deployment'),
                ('运维 / DevOps', '线上服务需要监控哪些指标？', '常见指标包括可用性、错误率、响应时间、吞吐量、CPU、内存、磁盘、网络、数据库连接、队列积压和业务核心指标。监控要配合告警阈值和应急预案。', '监控,告警,可用性,SLA'),
                ('运维 / DevOps', '灰度发布和回滚机制为什么重要？', '灰度发布可以先让少量用户使用新版本，降低全量故障风险；回滚机制能在发现问题后快速恢复。两者通常和监控、版本管理、配置开关一起使用。', '灰度发布,回滚,发布风险'),

                ('网络安全', 'SQL 注入的原理是什么？如何防范？', 'SQL 注入是攻击者把恶意 SQL 拼进输入参数，使数据库执行非预期语句。防范方式包括参数化查询、输入校验、最小权限、错误信息隐藏和安全审计。', 'SQL注入,参数化查询,输入校验'),
                ('网络安全', 'XSS 和 CSRF 有什么区别？', 'XSS 是注入恶意脚本并在用户浏览器执行，CSRF 是诱导已登录用户发起非本意请求。XSS 防护包括转义、CSP 和输入过滤；CSRF 防护包括 Token、SameSite Cookie 和二次校验。', 'XSS,CSRF,CSP,Token'),
                ('网络安全', '什么是最小权限原则？', '最小权限原则是只给用户、服务或进程完成任务所需的最低权限。它能减少误操作和入侵后的破坏范围，常用于账号权限、数据库权限、云资源访问和服务间调用。', '最小权限,权限控制,安全'),
                ('网络安全', '如何理解对称加密、非对称加密和哈希？', '对称加密使用同一密钥加解密，速度快；非对称加密使用公钥和私钥，适合密钥交换和签名；哈希是单向摘要，常用于完整性校验和密码存储。', '加密,哈希,签名'),
                ('网络安全', '漏洞修复后为什么还要做复测？', '复测用于确认漏洞确实被修复，并检查修复是否引入新问题。安全复测还应覆盖绕过路径、权限边界、日志记录和相关接口。', '漏洞,复测,安全测试'),
                ('网络安全', '常见的 Web 安全防护措施有哪些？', '常见措施包括输入校验、输出转义、鉴权鉴别、权限控制、HTTPS、安全响应头、日志审计、限流、防暴力破解、依赖漏洞扫描和 WAF。', 'Web安全,HTTPS,鉴权,WAF'),

                ('架构师', '设计高可用系统时你会关注哪些方面？', '高可用设计要关注冗余、故障隔离、自动恢复、限流降级、熔断、监控告警、数据备份和容灾演练。核心是让单点故障不影响整体服务，并能快速恢复。', '高可用,容灾,熔断,降级'),
                ('架构师', '请解释 CAP 定理。', 'CAP 定理指出分布式系统中一致性、可用性、分区容错性无法三者同时完全满足。实际设计通常在网络分区不可避免的前提下，根据业务在一致性和可用性之间取舍。', 'CAP,分布式,一致性,可用性'),
                ('架构师', '微服务架构适合什么场景？有什么代价？', '微服务适合业务复杂、团队规模较大、模块需要独立迭代和扩展的场景。代价包括分布式事务、服务治理、链路追踪、部署复杂度、接口契约和运维成本增加。', '微服务,服务治理,分布式事务'),
                ('架构师', '什么是 API 网关？它承担哪些职责？', 'API 网关是客户端访问后端服务的统一入口，常承担路由、鉴权、限流、熔断、协议转换、日志审计和聚合响应等职责。它能简化客户端调用并统一横切能力。', 'API网关,鉴权,限流,路由'),
                ('架构师', '读写分离和分库分表分别解决什么问题？', '读写分离通过主库写、从库读提升读性能和可用性；分库分表通过拆分数据降低单库单表压力。两者都会带来一致性、路由、事务和运维复杂度。', '读写分离,分库分表,数据库架构'),
                ('架构师', '如何做系统容量评估？', '容量评估要基于业务峰值、QPS、响应时间、数据量、增长率、依赖服务能力和资源利用率。通常会结合压测、监控历史、容量模型和冗余系数制定扩容方案。', '容量评估,QPS,压测,扩容')
            ]
            cursor.executemany(
                '''
                INSERT INTO questions (job_category, question, answer, keywords)
                VALUES (%s, %s, %s, %s)
                ''',
                seed_questions
            )
        conn.commit()
        print('数据库初始化成功')
    except Exception as e:
        print(f'数据库初始化失败: {e}')
    finally:
        conn.close()

# 豆包AI API配置
DOUBAO_API_KEY = os.getenv('DOUBAO_API_KEY', '')
DOUBAO_API_URL = os.getenv('DOUBAO_API_URL', 'https://ark.cn-beijing.volces.com/api/v3/chat/completions')

# 调用豆包AI API
def chat_with_doubao(prompt):
    """调用豆包AI API进行对话"""
    if requests is None:
        return "抱歉，AI服务依赖的requests模块未安装，请稍后重试。"
    
    headers = {
        "Authorization": f"Bearer {DOUBAO_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "doubao-pro",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }
    
    try:
        print(f'调用豆包AI API，URL: {DOUBAO_API_URL}')
        print(f'请求头: {headers}')
        print(f'请求数据: {data}')
        response = requests.post(DOUBAO_API_URL, json=data, headers=headers, timeout=30)
        print(f'豆包AI API响应状态码: {response.status_code}')
        print(f'豆包AI API响应内容: {response.text}')
        response.raise_for_status()
        result = response.json()
        print(f'豆包AI API返回的JSON结构: {result}')
        
        # 处理豆包AI API的返回格式
        if isinstance(result, dict):
            if 'choices' in result:
                choices = result['choices']
                if isinstance(choices, list) and len(choices) > 0:
                    choice = choices[0]
                    if 'message' in choice and 'content' in choice['message']:
                        return choice['message']['content']
        
        # 如果以上格式都不匹配，返回错误信息
        print(f'未知的返回格式: {result}')
        return "抱歉，AI服务返回格式异常，请稍后重试。"
    except requests.exceptions.RequestException as e:
        print(f'调用豆包API失败: {e}')
        if 'response' in locals():
            print(f'响应状态码: {response.status_code}')
            print(f'响应内容: {response.text}')
        return "抱歉，AI服务暂时不可用，请稍后重试。"
    except Exception as e:
        print(f'其他错误: {e}')
        import traceback
        traceback.print_exc()
        return "抱歉，AI服务暂时不可用，请稍后重试。"

# 初始化数据库
try:
    print('尝试初始化数据库...')
    init_db()
    print('数据库初始化成功')
except Exception as e:
    print(f'数据库初始化失败，可能是MySQL服务器未启动: {e}')
    print('服务器将继续运行，但部分功能可能无法使用')

# 测试服务器启动
print('准备启动服务器...')

# 用户注册接口
@app.route('/api/register', methods=['POST'])
def register():
    """用户注册"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    
    if not username or not password or not email:
        return jsonify({'error': '用户名、密码和邮箱不能为空'}), 400
    
    # 密码加密
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 检查用户名是否已存在
            cursor.execute('SELECT id FROM users WHERE username = %s', (username,))
            if cursor.fetchone():
                return jsonify({'error': '用户名已存在'}), 400
            
            # 检查邮箱是否已存在
            cursor.execute('SELECT id FROM users WHERE email = %s', (email,))
            if cursor.fetchone():
                return jsonify({'error': '邮箱已存在'}), 400
            
            # 插入新用户
            cursor.execute('INSERT INTO users (username, password, email) VALUES (%s, %s, %s)',
                          (username, hashed_password.decode('utf-8'), email))
            conn.commit()
            return jsonify({'message': '注册成功'}), 201
    except Exception as e:
        print(f'注册失败: {e}')
        return jsonify({'error': '注册失败'}), 500
    finally:
        conn.close()

# 用户登录接口
@app.route('/api/login', methods=['POST'])
def login():
    """用户登录"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400
    
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 查询用户
            cursor.execute('SELECT id, username, password FROM users WHERE username = %s', (username,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({'error': '用户名或密码错误'}), 401
            
            # 验证密码
            if not bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
                return jsonify({'error': '用户名或密码错误'}), 401
            
            return jsonify({'message': '登录成功', 'user_id': user['id'], 'username': user['username']}), 200
    except Exception as e:
        print(f'登录失败: {e}')
        return jsonify({'error': '登录失败'}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# 修改用户信息接口
@app.route('/api/user/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    """修改用户信息"""
    data = request.get_json()
    email = data.get('email')
    
    if not email:
        return jsonify({'error': '邮箱不能为空'}), 400
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 检查用户是否存在
            cursor.execute('SELECT id FROM users WHERE id = %s', (user_id,))
            if not cursor.fetchone():
                return jsonify({'error': '用户不存在'}), 404
            
            # 检查邮箱是否已被其他用户使用
            cursor.execute('SELECT id FROM users WHERE email = %s AND id != %s', (email, user_id))
            if cursor.fetchone():
                return jsonify({'error': '邮箱已被使用'}), 400
            
            # 更新用户信息
            cursor.execute('UPDATE users SET email = %s WHERE id = %s', (email, user_id))
            conn.commit()
            return jsonify({'message': '信息更新成功'}), 200
    except Exception as e:
        print(f'更新失败: {e}')
        return jsonify({'error': '更新失败'}), 500
    finally:
        conn.close()

# 密码重置接口
@app.route('/api/reset_password', methods=['POST'])
def reset_password():
    """密码重置"""
    data = request.get_json()
    email = data.get('email')
    new_password = data.get('new_password')
    
    if not email or not new_password:
        return jsonify({'error': '邮箱和新密码不能为空'}), 400
    
    # 密码加密
    hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 检查用户是否存在
            cursor.execute('SELECT id FROM users WHERE email = %s', (email,))
            user = cursor.fetchone()
            
            if not user:
                return jsonify({'error': '用户不存在'}), 404
            
            # 更新密码
            cursor.execute('UPDATE users SET password = %s WHERE email = %s', 
                          (hashed_password.decode('utf-8'), email))
            conn.commit()
            return jsonify({'message': '密码重置成功'}), 200
    except Exception as e:
        print(f'密码重置失败: {e}')
        return jsonify({'error': '密码重置失败'}), 500
    finally:
        conn.close()

# 获取用户偏好设置接口
@app.route('/api/user/<int:user_id>/preferences', methods=['GET'])
def get_user_preferences(user_id):
    """获取用户偏好设置"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 检查用户是否存在
            cursor.execute('SELECT id FROM users WHERE id = %s', (user_id,))
            if not cursor.fetchone():
                return jsonify({'error': '用户不存在'}), 404
            
            # 获取用户偏好设置
            cursor.execute('SELECT preferred_categories, interview_duration, email_notifications FROM user_preferences WHERE user_id = %s', (user_id,))
            preferences = cursor.fetchone()
            
            if not preferences:
                # 如果没有设置，返回默认值
                return jsonify({
                    'preferred_categories': [],
                    'interview_duration': 30,
                    'email_notifications': True
                }), 200
            
            return jsonify({
                'preferred_categories': preferences['preferred_categories'],
                'interview_duration': preferences['interview_duration'],
                'email_notifications': preferences['email_notifications']
            }), 200
    except Exception as e:
        print(f'获取偏好设置失败: {e}')
        return jsonify({'error': '获取偏好设置失败'}), 500
    finally:
        conn.close()

# 更新用户偏好设置接口
@app.route('/api/user/<int:user_id>/preferences', methods=['PUT'])
def update_user_preferences(user_id):
    """更新用户偏好设置"""
    data = request.get_json()
    preferred_categories = data.get('preferred_categories', [])
    interview_duration = data.get('interview_duration', 30)
    email_notifications = data.get('email_notifications', True)
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 检查用户是否存在
            cursor.execute('SELECT id FROM users WHERE id = %s', (user_id,))
            if not cursor.fetchone():
                return jsonify({'error': '用户不存在'}), 404
            
            # 检查是否已有偏好设置
            cursor.execute('SELECT id FROM user_preferences WHERE user_id = %s', (user_id,))
            if cursor.fetchone():
                # 更新现有设置
                cursor.execute('''
                    UPDATE user_preferences 
                    SET preferred_categories = %s, interview_duration = %s, email_notifications = %s 
                    WHERE user_id = %s
                ''', (json.dumps(preferred_categories), interview_duration, email_notifications, user_id))
            else:
                # 创建新设置
                cursor.execute('''
                    INSERT INTO user_preferences (user_id, preferred_categories, interview_duration, email_notifications) 
                    VALUES (%s, %s, %s, %s)
                ''', (user_id, json.dumps(preferred_categories), interview_duration, email_notifications))
            
            conn.commit()
            return jsonify({'message': '偏好设置更新成功'}), 200
    except Exception as e:
        print(f'更新偏好设置失败: {e}')
        return jsonify({'error': '更新偏好设置失败'}), 500
    finally:
        conn.close()

# 添加收藏接口
@app.route('/api/user/<int:user_id>/favorites', methods=['POST'])
def add_favorite(user_id):
    """添加收藏"""
    data = request.get_json()
    question_id = data.get('question_id')
    
    if not question_id:
        return jsonify({'error': '题目ID不能为空'}), 400
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 检查用户是否存在
            cursor.execute('SELECT id FROM users WHERE id = %s', (user_id,))
            if not cursor.fetchone():
                return jsonify({'error': '用户不存在'}), 404
            
            # 检查题目是否存在
            cursor.execute('SELECT id FROM questions WHERE id = %s', (question_id,))
            if not cursor.fetchone():
                return jsonify({'error': '题目不存在'}), 404
            
            # 检查是否已收藏
            cursor.execute('SELECT id FROM favorites WHERE user_id = %s AND question_id = %s', (user_id, question_id))
            if cursor.fetchone():
                return jsonify({'error': '已经收藏过该题目'}), 400
            
            # 添加收藏
            cursor.execute('INSERT INTO favorites (user_id, question_id) VALUES (%s, %s)', (user_id, question_id))
            conn.commit()
            return jsonify({'message': '收藏成功'}), 201
    except Exception as e:
        print(f'添加收藏失败: {e}')
        return jsonify({'error': '添加收藏失败'}), 500
    finally:
        conn.close()

# 取消收藏接口
@app.route('/api/user/<int:user_id>/favorites/<int:question_id>', methods=['DELETE'])
def remove_favorite(user_id, question_id):
    """取消收藏"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 检查用户是否存在
            cursor.execute('SELECT id FROM users WHERE id = %s', (user_id,))
            if not cursor.fetchone():
                return jsonify({'error': '用户不存在'}), 404
            
            # 检查题目是否存在
            cursor.execute('SELECT id FROM questions WHERE id = %s', (question_id,))
            if not cursor.fetchone():
                return jsonify({'error': '题目不存在'}), 404
            
            # 检查是否已收藏
            cursor.execute('SELECT id FROM favorites WHERE user_id = %s AND question_id = %s', (user_id, question_id))
            if not cursor.fetchone():
                return jsonify({'error': '未收藏该题目'}), 400
            
            # 取消收藏
            cursor.execute('DELETE FROM favorites WHERE user_id = %s AND question_id = %s', (user_id, question_id))
            conn.commit()
            return jsonify({'message': '取消收藏成功'}), 200
    except Exception as e:
        print(f'取消收藏失败: {e}')
        return jsonify({'error': '取消收藏失败'}), 500
    finally:
        conn.close()

# 获取用户收藏的题目接口
@app.route('/api/user/<int:user_id>/favorites', methods=['GET'])
def get_user_favorites(user_id):
    """获取用户收藏的题目"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 检查用户是否存在
            cursor.execute('SELECT id FROM users WHERE id = %s', (user_id,))
            if not cursor.fetchone():
                return jsonify({'error': '用户不存在'}), 404
            
            # 获取用户收藏的题目
            cursor.execute('''
                SELECT q.id, q.job_category, q.question, q.answer, q.keywords 
                FROM questions q
                JOIN favorites f ON q.id = f.question_id
                WHERE f.user_id = %s
            ''', (user_id,))
            favorites = cursor.fetchall()
            
            return jsonify({'favorites': favorites}), 200
    except Exception as e:
        print(f'获取收藏题目失败: {e}')
        return jsonify({'error': '获取收藏题目失败'}), 500
    finally:
        conn.close()

# 豆包AI对话接口
@app.route('/api/chat', methods=['POST'])
def chat_with_ai():
    """调用豆包AI进行对话"""
    data = request.get_json()
    prompt = data.get('prompt')
    
    if not prompt:
        return jsonify({'error': '请提供对话内容'}), 400
    
    try:
        response = chat_with_doubao(prompt)
        return jsonify({'response': response}), 200
    except Exception as e:
        print(f'对话失败: {e}')
        return jsonify({'error': '对话失败'}), 500

# 获取题目类别接口
@app.route('/api/job_categories', methods=['GET'])
def get_job_categories():
    """获取所有题目类别"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT DISTINCT job_category
                FROM questions
                ORDER BY FIELD(
                    job_category,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            ''', ALLOWED_JOB_CATEGORIES)
            categories = [row['job_category'] for row in cursor.fetchall()]
            return jsonify({'categories': categories}), 200
    except Exception as e:
        print(f'获取类别失败: {e}')
        return jsonify({'error': '获取类别失败'}), 500
    finally:
        conn.close()

# 出题接口
@app.route('/api/questions', methods=['POST'])
def get_questions():
    """根据类别获取题目"""
    data = request.get_json()
    job_category = data.get('job_category')
    question_count = data.get('count', 5)  # 默认5题
    
    if not job_category:
        return jsonify({'error': '请指定岗位类别'}), 400
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT id, question FROM questions WHERE job_category = %s', (job_category,))
            questions = cursor.fetchall()
            
            if len(questions) < question_count:
                return jsonify({'error': f'该类别题目不足{question_count}题'}), 400
            
            # 随机选择题目
            selected_questions = random.sample(questions, question_count)
            return jsonify({'questions': selected_questions}), 200
    except Exception as e:
        print(f'获取题目失败: {e}')
        return jsonify({'error': '获取题目失败'}), 500
    finally:
        conn.close()

# 评分接口
@app.route('/api/score', methods=['POST'])
def score_answers():
    """评分接口"""
    data = request.get_json()
    user_id = data.get('user_id')
    job_category = data.get('job_category')
    questions = data.get('questions')  # 题目列表，包含id和question
    answers = data.get('answers')  # 答案列表
    
    if not user_id or not job_category or not questions or not answers:
        return jsonify({'error': '参数不完整'}), 400
    
    if len(questions) != len(answers):
        return jsonify({'error': '题目和答案数量不匹配'}), 400
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            scores = []
            total_score = 0
            
            for i, q in enumerate(questions):
                # 获取题目信息
                cursor.execute('SELECT answer, keywords FROM questions WHERE id = %s', (q['id'],))
                question_info = cursor.fetchone()
                
                if not question_info:
                    continue
                
                # 初始化评分变量
                content_score = 0
                keyword_score = 0
                logic_score = 0
                matched_keywords = []
                ai_response = ""
                
                # 评分逻辑
                answer = answers[i]
                keywords = question_info['keywords'].split(',')
                
                # 判断是否为专业问题（有keywords的为专业问题）
                if keywords and keywords[0]:  # 专业问题
                    # 内容完整性评分（0-30分）- 更加严苛
                    content_score = min(30, len(answer) * 1.5)  # 降低基础分
                    
                    # 关键词匹配评分（0-50分）- 更加严格的关键词提取
                    keyword_score = 0
                    matched_keywords = []
                    for keyword in keywords:
                        if keyword in answer:
                            keyword_score += 12.5  # 每个关键词12.5分
                            matched_keywords.append(keyword)
                    keyword_score = min(50, keyword_score)
                    
                    # 逻辑评分（0-20分）- 更加严苛
                    if len(answer) > 80:
                        logic_score = 20
                    elif len(answer) > 50:
                        logic_score = 15
                    elif len(answer) > 30:
                        logic_score = 10
                    else:
                        logic_score = 5
                    
                    # 综合得分
                    question_score = content_score + keyword_score + logic_score
                else:  # 自由问题，交给AI评判
                    # 调用豆包AI进行内容评判
                    prompt = f"请对以下面试回答进行评分（1-100分），并给出详细评价：\n问题：{q['question']}\n回答：{answer}"
                    ai_response = chat_with_doubao(prompt)
                    
                    # 从AI回复中提取分数
                    import re
                    score_match = re.search(r'\d+', ai_response)
                    if score_match:
                        question_score = min(100, max(0, int(score_match.group())))  # 确保分数在0-100之间
                    else:
                        question_score = 50  # 默认分数
                
                total_score += question_score
                
                scores.append({
                    'question_id': q['id'],
                    'question': q['question'],
                    'user_answer': answer,
                    'correct_answer': question_info['answer'],
                    'content_score': content_score,
                    'keyword_score': keyword_score,
                    'logic_score': logic_score,
                    'matched_keywords': matched_keywords,
                    'ai_evaluation': ai_response,
                    'total_score': question_score
                })
            
            # 计算最终总分（1-100分）
            if questions:
                final_score = min(100, max(1, int(total_score / len(questions))))
            else:
                final_score = 50
            
            # 保存面试记录
            cursor.execute('''
                INSERT INTO interview_records (user_id, job_category, questions, answers, scores, total_score)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (user_id, job_category, json.dumps(questions), json.dumps(answers), json.dumps(scores), final_score))
            conn.commit()
            
            return jsonify({
                'message': '评分完成',
                'total_score': final_score,
                'scores': scores
            }), 200
    except Exception as e:
        print(f'评分失败: {e}')
        return jsonify({'error': '评分失败'}), 500
    finally:
        conn.close()

# 获取历史记录接口
@app.route('/api/history/<int:user_id>', methods=['GET'])
def get_history(user_id):
    """获取用户的历史面试记录"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT id, job_category, total_score, created_at
                FROM interview_records
                WHERE user_id = %s
                ORDER BY created_at DESC
            ''', (user_id,))
            records = cursor.fetchall()
            return jsonify({'records': records}), 200
    except Exception as e:
        print(f'获取历史记录失败: {e}')
        return jsonify({'error': '获取历史记录失败'}), 500
    finally:
        conn.close()

# 获取历史记录详情接口
@app.route('/api/history/detail/<int:record_id>', methods=['GET'])
def get_history_detail(record_id):
    """获取历史记录详情"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT job_category, questions, answers, scores, total_score, created_at
                FROM interview_records
                WHERE id = %s
            ''', (record_id,))
            record = cursor.fetchone()
            
            if not record:
                return jsonify({'error': '记录不存在'}), 404
            
            # 解析JSON字段
            record['questions'] = json.loads(record['questions'])
            record['answers'] = json.loads(record['answers'])
            record['scores'] = json.loads(record['scores'])
            
            return jsonify({'record': record}), 200
    except Exception as e:
        print(f'获取历史记录详情失败: {e}')
        return jsonify({'error': '获取历史记录详情失败'}), 500
    finally:
        conn.close()

# 导入题目接口
@app.route('/api/questions/import', methods=['POST'])
def import_questions():
    """导入外部题库"""
    data = request.get_json()
    questions = data.get('questions', [])
    
    if not questions:
        return jsonify({'error': '请提供题目数据'}), 400
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            success_count = 0
            error_count = 0
            errors = []
            
            for q in questions:
                try:
                    job_category = q.get('job_category')
                    question = q.get('question')
                    answer = q.get('answer')
                    keywords = q.get('keywords', '')
                    
                    if not job_category or not question or not answer:
                        error_count += 1
                        errors.append(f'题目缺少必要字段: {question}')
                        continue

                    if job_category not in ALLOWED_JOB_CATEGORIES:
                        error_count += 1
                        errors.append(f'不支持的岗位类别: {job_category}')
                        continue
                    
                    # 检查是否已存在
                    cursor.execute('SELECT id FROM questions WHERE question = %s', (question,))
                    existing = cursor.fetchone()
                    
                    if existing:
                        # 更新现有题目
                        cursor.execute('''
                            UPDATE questions 
                            SET job_category = %s, answer = %s, keywords = %s 
                            WHERE id = %s
                        ''', (job_category, answer, keywords, existing['id']))
                    else:
                        # 插入新题目
                        cursor.execute('''
                            INSERT INTO questions (job_category, question, answer, keywords)
                            VALUES (%s, %s, %s, %s)
                        ''', (job_category, question, answer, keywords))
                    
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    errors.append(f'导入题目失败: {q.get("question")}, 错误: {str(e)}')
            
            conn.commit()
            return jsonify({
                'message': '导入完成',
                'success_count': success_count,
                'error_count': error_count,
                'errors': errors
            }), 200
    except Exception as e:
        print(f'导入题库失败: {e}')
        return jsonify({'error': '导入题库失败'}), 500
    finally:
        conn.close()

# ========== 多模态AI面试评分系统（科大讯飞） ==========

# 多模态面试初始化接口
@app.route('/api/interview/init', methods=['POST'])
def interview_init():
    """初始化面试会话"""
    data = request.get_json()
    user_id = data.get('user_id')
    job_category = data.get('job_category')
    question_count = data.get('question_count', 5)
    
    if not user_id or not job_category:
        return jsonify({'error': '参数不完整'}), 400

    if job_category not in ALLOWED_JOB_CATEGORIES:
        return jsonify({'error': '不支持的岗位类别'}), 400
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT id, question FROM questions WHERE job_category = %s', (job_category,))
            questions = cursor.fetchall()
            
            # 为每个岗位准备额外的专业问题
            extra_professional_questions = {
                '前端开发': [
                    '请解释什么是前端性能优化？有哪些常用的优化方法？',
                    '请解释什么是单页应用（SPA）？它的优缺点是什么？',
                    '请解释什么是跨域？有哪些解决跨域的方法？',
                    '请解释什么是CSS盒模型？标准盒模型和IE盒模型有什么区别？'
                ],
                '后端开发': [
                    '请解释什么是RESTful API设计原则？',
                    '请解释什么是数据库事务？事务的ACID特性是什么？',
                    '请解释什么是缓存穿透、缓存击穿和缓存雪崩？',
                    '请解释什么是微服务架构？它的优缺点是什么？'
                ],
                '测试开发': [
                    '请说明你会如何设计一个登录接口的测试用例？',
                    '请解释接口自动化测试的核心流程。',
                    '请说明性能测试中 QPS、响应时间和错误率分别代表什么。',
                    '线上出现偶发 Bug 时，你会如何收集信息并定位问题？'
                ],
                '算法工程师': [
                    '请解释动态规划适合解决哪类问题。',
                    '请说明哈希表的平均复杂度和最坏复杂度。',
                    '请解释过拟合以及常见缓解方法。',
                    '请说说你如何选择分类模型的评估指标。'
                ],
                'AI工程师': [
                    '请解释什么是机器学习？机器学习的主要类型有哪些？',
                    '请解释什么是神经网络？它的基本结构是什么？',
                    '请解释什么是监督学习和无监督学习？它们的区别是什么？',
                    '请解释什么是模型评估？常用的评估指标有哪些？'
                ],
                '数据开发': [
                    '请说明数仓分层的目的和常见层次。',
                    '请解释 ETL 和 ELT 的区别。',
                    '请说明 SQL 调优时你会先看哪些信息。',
                    '遇到数据倾斜时你会如何处理？'
                ],
                '运维 / DevOps': [
                    '请说明一次完整的 CI/CD 流程。',
                    '请解释 Docker 镜像和容器的区别。',
                    '请说明 Kubernetes 中 Pod、Service、Deployment 的作用。',
                    '线上服务 CPU 异常升高时你会如何排查？'
                ],
                '网络安全': [
                    '请解释 SQL 注入的原理和防范方式。',
                    '请说明 XSS 和 CSRF 的区别。',
                    '请解释最小权限原则在系统设计中的作用。',
                    '你会如何验证一个安全漏洞是否修复完成？'
                ],
                '架构师': [
                    '请解释什么是系统架构设计？它的主要原则是什么？',
                    '请解释什么是分布式系统？它的挑战是什么？',
                    '请解释什么是微服务架构？它与单体架构的区别是什么？',
                    '请解释什么是DevOps？它的核心实践是什么？'
                ]
            }
            
            # 检查题目数量
            if len(questions) < question_count:
                return jsonify({'error': f'该类别题目不足{question_count}题'}), 400
            
            # 随机选择基础题目
            selected_questions = random.sample(questions, question_count)
            
            # 根据岗位类别随机添加1-2个专业问题
            if job_category in extra_professional_questions:
                extra_questions = extra_professional_questions[job_category]
                # 随机选择1-2个额外问题
                num_extra = random.randint(1, 2)
                selected_extra = random.sample(extra_questions, min(num_extra, len(extra_questions)))
                
                # 将额外问题转换为与数据库题目相同的格式
                for i, extra_q in enumerate(selected_extra):
                    extra_question_obj = {
                        'id': f'extra_{i}_{int(time.time())}',  # 生成临时ID
                        'question': extra_q
                    }
                    selected_questions.append(extra_question_obj)
            
            session_data = {
                "session_id": f"int_{user_id}_{int(time.time())}",
                "user_id": user_id,
                "job_category": job_category,
                "questions": selected_questions,
                "start_time": datetime.datetime.now().isoformat(),
                "status": "initialized"
            }
            
            return jsonify({
                'success': True,
                'session': session_data,
                'instructions': {
                    'preparation_time': 30,
                    'answer_time': 120,
                    'rules': [
                        '请保持摄像头正面朝向自己',
                        '确保光线充足，面部清晰可见',
                        '回答时请直视摄像头',
                        '每题有准备时间和作答时间',
                        '全程录音录像，请勿中断'
                    ]
                }
            }), 200
    except Exception as e:
        print(f'面试初始化失败: {e}')
        return jsonify({'error': '面试初始化失败'}), 500
    finally:
        conn.close()

# 实时人脸检测接口
@app.route('/api/interview/face_detect', methods=['POST'])
def face_detect():
    """实时人脸检测与表情识别"""
    if get_xf_client is None:
        return _json_error('讯飞 SDK 未正确加载', 503, XF_IMPORT_ERROR)

    data = request.get_json(silent=True) or {}
    image_base64 = data.get('image')
    
    if not image_base64:
        return _json_error('未提供图片数据', 400)
    
    client = get_xf_client()
    if client is not None:
        result = client.detect_face_and_expression(image_base64)
        if result.get('success', False):
            return jsonify(result), 200

    # 优先保证真实检测，不再返回固定 75% 兜底值
    local_result = _local_face_detect(image_base64)
    if local_result.get("success", False):
        return jsonify(local_result), 200
    return _json_error('人脸检测失败', 502, local_result.get("error", "未知错误"))

# 语音转文字接口（ASR）
@app.route('/api/interview/asr', methods=['POST'])
def audio_to_text():
    """语音识别转文字"""
    if get_xf_client is None:
        return _json_error('讯飞 SDK 未正确加载', 503, XF_IMPORT_ERROR)

    data = request.get_json(silent=True) or {}
    audio_b64 = data.get('audio', '')
    if not audio_b64:
        return _json_error('未提供音频数据', 400)

    try:
        audio_data = base64.b64decode(audio_b64, validate=True)
    except (binascii.Error, ValueError):
        return _json_error('音频数据不是合法的 base64', 400)

    if not audio_data:
        return _json_error('音频数据为空', 400)
    
    client = get_xf_client()
    if client is None:
        return _json_error('讯飞客户端初始化失败，请检查 APPID/APIKey/APISecret', 503)

    result = client.asr_audio_to_text(audio_data)
    if not result.get('success', False):
        return _json_error('语音识别失败', 502, result.get('error', '未知错误'))
    return jsonify(result), 200

# 文本分析接口（使用科大讯飞星火大模型进行AI分析）
@app.route('/api/interview/analyze_text', methods=['POST'])
def analyze_text():
    """
    分析面试回答文本内容（使用星火大模型AI）
    输入：识别后的文本、问题、岗位类别
    输出：流畅度、内容质量等分析结果
    """
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        question = data.get('question', '')
        job_category = data.get('job_category', '')
        
        print(f"[文本分析] 收到文本: {text[:100]}...")
        print(f"[文本分析] 问题: {question}")
        print(f"[文本分析] 岗位: {job_category}")
        
        if not text:
            return jsonify({'success': False, 'error': '未提供文本'}), 400
        
        # 使用星火大模型进行AI分析
        prompt = f"""你是一个专业的面试官AI助手。请对以下面试回答进行分析和评分。

岗位类别：{job_category}
面试问题：{question}
考生回答：{text}

请从以下维度进行分析（每个维度0-100分）：
1. 流畅度（fluency_score）：表达是否流畅，有无卡顿、重复
2. 内容质量（content_score）：回答是否切题、内容是否充实
3. 逻辑性（logic_score）：逻辑是否清晰，条理是否分明
4. 填充词数量（filler_words）：统计"嗯、啊、呃、那个、这个"等填充词数量
5. 重复次数（repetition）：是否有明显的语句重复

请以JSON格式返回结果：
{{"fluency_score": 85, "content_score": 80, "logic_score": 75, "filler_words": 2, "repetition": 0, "word_count": {len(text)}, "analysis_summary": "简要评价"}}"""
        
        # 调用星火大模型
        if call_spark_ws_api is None:
            return _json_error('星火模型调用器未加载', 503, XF_IMPORT_ERROR)
        spark_result = call_spark_ws_api(prompt)
        
        if spark_result['success']:
            import json
            try:
                # 解析AI返回的JSON
                analysis = json.loads(spark_result['content'])
                print(f"[文本分析] ✅ 星火大模型分析成功！")
                print(f"[文本分析] Token使用: {spark_result.get('usage', {})}")
                
                return jsonify({
                    'success': True,
                    'analysis': analysis,
                    'text': text,
                    'ai_analysis': True,
                    'token_usage': spark_result.get('usage', {})
                }), 200
                
            except json.JSONDecodeError:
                print(f"[文本分析] AI返回格式解析失败，使用原始内容")
                return jsonify({
                    'success': True,
                    'analysis': {
                        'fluency_score': 85,
                        'content_score': 80,
                        'logic_score': 75,
                        'filler_words': 2,
                        'repetition': 0,
                        'word_count': len(text),
                        'analysis_summary': spark_result['content'][:100]
                    },
                    'text': text,
                    'ai_analysis': True,
                    'raw_response': spark_result['content']
                }), 200
        else:
            print(f"[文本分析] ❌ 星火大模型调用失败: {spark_result['error']}")
            # 回退到本地分析
            analysis = analyze_text_locally(text, question, job_category)
            return jsonify({
                'success': True,
                'analysis': analysis,
                'text': text,
                'ai_analysis': False,
                'error': f"AI调用失败，使用本地分析: {spark_result['error']}"
            }), 200
        
    except Exception as e:
        print(f"[文本分析] 错误: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

def analyze_text_locally(text, question, job_category):
    """本地文本分析（后备方案）"""
    # 计算流畅度评分
    fluency_score = calculate_fluency_score(text)
    
    # 计算内容质量评分
    content_score = calculate_content_score(text, question, job_category)
    
    # 计算逻辑性评分
    logic_score = calculate_logic_score(text)
    
    # 统计填充词
    filler_words = count_filler_words(text)
    
    # 统计重复
    repetitions = count_repetitions(text)
    
    return {
        'fluency_score': fluency_score,
        'content_score': content_score,
        'logic_score': logic_score,
        'filler_words': filler_words,
        'repetition': repetitions,
        'word_count': len(text),
        'sentence_count': max(1, len([s for s in text.split('。') if s.strip()])),
        'analysis_summary': generate_analysis_summary(fluency_score, content_score, logic_score)
    }

def calculate_fluency_score(text):
    """计算流畅度评分"""
    score = 70  # 基础分
    
    # 长度评分
    if len(text) > 20:
        score += 5
    if len(text) > 50:
        score += 5
    if len(text) > 100:
        score += 5
    if len(text) > 200:
        score += 5
    
    # 标点符号使用
    punctuation_count = sum(1 for c in text if c in '，。！？；：')
    if punctuation_count > 3:
        score += 5
    if punctuation_count > 8:
        score += 5
    
    # 填充词惩罚
    filler_count = count_filler_words(text)
    score -= min(15, filler_count * 3)
    
    return min(100, max(0, score))

def calculate_content_score(text, question, job_category):
    """计算内容质量评分"""
    score = 60  # 基础分
    
    # 长度评分
    if len(text) > 50:
        score += 10
    if len(text) > 100:
        score += 10
    if len(text) > 200:
        score += 10
    
    # 关键词匹配（如果有问题信息）
    if question:
        # 提取问题中的关键词
        keywords = extract_keywords(question)
        matched_keywords = sum(1 for kw in keywords if kw in text)
        score += min(15, matched_keywords * 5)
    
    return min(100, max(0, score))

def calculate_logic_score(text):
    """计算逻辑性评分"""
    score = 65  # 基础分
    
    # 连接词使用
    logic_words = ['首先', '其次', '然后', '最后', '因为', '所以', '但是', '然而', '因此', '总之']
    found_logic_words = sum(1 for word in logic_words if word in text)
    score += min(15, found_logic_words * 5)
    
    # 段落结构
    sentences = [s.strip() for s in text.split('。') if s.strip()]
    if len(sentences) > 3:
        score += 5
    if len(sentences) > 5:
        score += 5
    
    return min(100, max(0, score))

def count_filler_words(text):
    """统计填充词"""
    fillers = ['嗯', '啊', '呃', '那个', '这个', '然后', '就是', '好像', '大概']
    count = sum(text.count(filler) for filler in fillers)
    return count

def count_repetitions(text):
    """统计重复内容"""
    # 简单的重复检测
    words = text.split()
    if len(words) < 5:
        return 0
    
    # 检测连续重复
    repetition_count = 0
    for i in range(len(words) - 2):
        if words[i] == words[i + 1] == words[i + 2]:
            repetition_count += 1
    
    return repetition_count

def extract_keywords(question):
    """从问题中提取关键词"""
    # 简单的关键词提取
    stop_words = ['请', '解释', '什么是', '介绍', '分享', '描述', '说说', '如何', '为什么', '怎么']
    words = question.replace('？', '').replace('?', '').split()
    keywords = [w for w in words if len(w) > 1 and w not in stop_words]
    return keywords[:5]  # 最多返回5个关键词

def generate_analysis_summary(fluency, content, logic):
    """生成分析摘要"""
    avg_score = (fluency + content + logic) / 3
    
    if avg_score >= 85:
        return "优秀：表达流畅，内容充实，逻辑清晰"
    elif avg_score >= 75:
        return "良好：表达较为流畅，内容较充实"
    elif avg_score >= 60:
        return "一般：表达基本流畅，需要改进"
    else:
        return "待提高：需要加强表达和内容组织"

# 多模态综合评分接口
@app.route('/api/interview/multimodal_score', methods=['POST'])
def multimodal_score():
    """
    多模态AI面试评分（核心接口）
    输入：题目、答案文本、面部数据快照、语音分析结果
    输出：完整评分报告
    """
    if MultimodalScoringEngine is None:
        return _json_error('评分引擎未加载，请检查 backend/xf_api.py 是否可导入', 503, XF_IMPORT_ERROR)

    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    job_category = data.get('job_category')
    questions = data.get('questions')
    answers = data.get('answers')
    face_snapshots = data.get('face_snapshots', [])
    speech_analysis_list = data.get('speech_analysis_list', [])
    
    if not all([user_id, job_category, questions, answers]):
        return _json_error('参数不完整', 400)
    if not isinstance(questions, list) or not isinstance(answers, list):
        return _json_error('questions/answers 必须是数组', 400)
    if len(answers) != len(questions):
        return _json_error('questions 与 answers 数量不一致', 400)
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            detailed_scores = []
            total_weighted_score = 0
            
            for i, q in enumerate(questions):
                answer = answers[i] if i < len(answers) else ""
                
                # 检查是否有id字段
                question_id = q.get('id', f'q_{i+1}')
                if question_id and not str(question_id).startswith('q_'):
                    cursor.execute('SELECT answer, keywords FROM questions WHERE id = %s', (question_id,))
                    q_info = cursor.fetchone() or {}
                else:
                    # 如果没有id字段，使用默认值
                    q_info = {}
                
                raw_face_data = face_snapshots[i] if i < len(face_snapshots) else {}
                if not isinstance(raw_face_data, dict):
                    raw_face_data = {}

                raw_speech_data = speech_analysis_list[i] if i < len(speech_analysis_list) else {"analysis": {}}
                if not isinstance(raw_speech_data, dict):
                    raw_speech_data = {"analysis": {}}

                multimodal_data = {
                    "text_answer": answer,
                    "question_info": q_info,
                    "job_category": job_category,
                    "face_data": raw_face_data,
                    "speech_data": raw_speech_data
                }
                
                score_result = MultimodalScoringEngine.calculate_overall_score(multimodal_data)
                
                detailed_scores.append({
                    "question_id": question_id,
                    "question": q.get('question', ''),
                    "user_answer": answer,
                    "reference_answer": q_info.get('answer', ''),
                    "score_report": score_result
                })
                
                total_weighted_score += score_result["total_score"]
            
            avg_score = total_weighted_score / max(1, len(questions))
            final_grade = MultimodalScoringEngine._determine_grade(avg_score)
            
            full_report = generate_interview_report(
                user_id=user_id,
                job_category=job_category,
                questions=questions,
                answers=answers,
                scores=detailed_scores,
                total_score=round(avg_score, 1),
                grade=final_grade
            )
            
            cursor.execute('''
                INSERT INTO interview_records 
                (user_id, job_category, questions, answers, scores, total_score)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (
                user_id, 
                job_category, 
                json.dumps(questions, ensure_ascii=False),
                json.dumps(answers, ensure_ascii=False),
                json.dumps(detailed_scores, ensure_ascii=False),
                round(avg_score, 1)
            ))
            conn.commit()
            
            return jsonify({
                'success': True,
                'message': '多模态AI评分完成',
                'report': full_report
            }), 200
            
    except Exception as e:
        print(f'多模态评分失败: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'评分失败: {str(e)}'}), 500
    finally:
        conn.close()

def generate_interview_report(user_id, job_category, questions, answers, scores, total_score, grade):
    """生成完整的AI面试评分报告"""
    dim_scores = []
    for s in scores:
        sr = s["score_report"]
        dim_scores.append(sr["dimensions"])
    
    avg_nv = sum(d["non_verbal"]["subtotal"] for d in dim_scores) / max(1, len(dim_scores))
    avg_vb = sum(d["verbal"]["subtotal"] for d in dim_scores) / max(1, len(dim_scores))
    avg_ct = sum(d["content"]["subtotal"] for d in dim_scores) / max(1, len(dim_scores))
    
    # 生成结构化点评报告
    strengths = []
    weaknesses = []
    suggestions = []
    
    # 等级描述
    grade_description = {
        "优秀": "表现卓越，强烈推荐录用",
        "良好": "表现良好，推荐录用",
        "合格": "基本达标，可考虑录用",
        "待改进": "存在不足，建议进一步考察",
        "不合格": "差距较大，不建议录用"
    }
    
    # 分析优势
    if avg_nv >= 80:
        strengths.append("非语言表现优秀，面部表情自然，仪态得体")
    if avg_vb >= 80:
        strengths.append("语言表达流畅，逻辑清晰")
    if avg_ct >= 80:
        strengths.append("专业知识扎实，回答内容完整")
    
    # 分析不足
    if avg_nv < 70:
        weaknesses.append("非语言表现有待提升，建议加强面部表情管理和仪态训练")
    if avg_vb < 70:
        weaknesses.append("语言表达不够流畅，逻辑结构需要优化")
    if avg_ct < 70:
        weaknesses.append("专业知识掌握不够扎实，回答内容不够完整")
    
    # 生成改进建议
    if avg_nv < 80:
        suggestions.append("加强面试礼仪训练，保持自然的面部表情和得体的仪态")
    if avg_vb < 80:
        suggestions.append("多练习口语表达，提高回答的逻辑性和流畅度")
    if avg_ct < 80:
        suggestions.append("加强专业知识学习，提高回答的专业性和完整性")
    
    report = {
        "basic_info": {
            "interview_type": "计算机/IT类岗位AI面试",
            "position_category": job_category,
            "total_questions": len(questions),
            "interview_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "scoring_engine": "科大讯飞多模态AI评分系统 v1.0",
            "capabilities_used": ["面部识别", "表情/情绪识别", "语音ASR", "语义分析", "情感计算"]
        },
        "overall_result": {
            "total_score": total_score,
            "grade": grade,
            "grade_description": {
                "优秀": "表现卓越，强烈推荐录用",
                "良好": "表现良好，推荐录用",
                "合格": "基本达标，可考虑录用",
                "待改进": "存在不足，建议进一步考察",
                "不合格": "差距较大，不建议录用"
            }.get(grade, "")
        },
        "dimension_scores": {
            "非语言表现（40%）": {
                "score": round(avg_nv, 1),
                "weight": "40%",
                "sub_dimensions": {
                    "面部合规（10%）": round(avg_nv * 0.25, 1),
                    "表情与情绪（20%）": round(avg_nv * 0.50, 1),
                    "仪态与眼神（10%）": round(avg_nv * 0.25, 1)
                }
            },
            "语言表达（25%）": {
                "score": round(avg_vb, 1),
                "weight": "25%",
                "sub_dimensions": {
                    "流畅度（10%）": round(avg_vb * 0.40, 1),
                    "清晰度（7.5%）": round(avg_vb * 0.30, 1),
                    "逻辑性（7.5%）": round(avg_vb * 0.30, 1)
                }
            },
            "作答内容（35%）": {
                "score": round(avg_ct, 1),
                "weight": "35%",
                "sub_dimensions": {
                    "专业匹配（12.25%）": round(avg_ct * 0.35, 1),
                    "逻辑深度（12.25%）": round(avg_ct * 0.35, 1),
                    "完整性（10.5%）": round(avg_ct * 0.30, 1)
                }
            }
        },
        "question_details": [
            {
                "序号": idx + 1,
                "问题": s["question"],
                "作答": s["user_answer"],
                "得分": s["score_report"]["total_score"],
                "等级": s["score_report"]["grade"],
                "维度得分": {
                    "非语言": s["score_report"]["dimensions"]["non_verbal"]["subtotal"],
                    "语言表达": s["score_report"]["dimensions"]["verbal"]["subtotal"],
                    "内容质量": s["score_report"]["dimensions"]["content"]["subtotal"]
                }
            } for idx, s in enumerate(scores)
        ],
        "multimodal_analysis_summary": {
            "facial_compliance": "正常" if avg_nv >= 70 else "需改进",
            "emotion_stability": "稳定" if avg_nv >= 75 else "波动较大",
            "speech_fluency": "流畅" if avg_vb >= 80 else ("一般" if avg_vb >= 60 else "卡顿较多"),
            "content_quality": "优秀" if avg_ct >= 85 else ("良好" if avg_ct >= 70 else ("及格" if avg_ct >= 60 else "需加强"))
        },
        "structured_evaluation": {
            "overall_score": round(total_score / 10, 1),  # 转换为10分制
            "strengths": strengths[:3],  # 取前3点
            "weaknesses": weaknesses[:3],  # 取前3点
            "suggestions": suggestions,
            "summary": f"面试整体表现{grade}，{total_score}分（100分制）。{grade_description[grade] if grade in grade_description else ''}"
        },
        "recommendation": {
            "decision": "推荐录用" if grade in ["优秀", "良好"] else ("可考虑录用" if grade == "合格" else "不建议录用"),
            "reason": f"综合评分{total_score}分，{grade}水平",
            "strengths": strengths,
            "weaknesses": weaknesses,
            "suggestions": suggestions
        }
    }
    
    return report


def _face_detect_safe_override():
    try:
        data = request.get_json(silent=True) or {}
        image_base64 = data.get('image')
        if not image_base64:
            return _json_error('未提供图片数据', 400)

        if get_xf_client is not None:
            try:
                client = get_xf_client()
                if client is not None:
                    result = client.detect_face_and_expression(image_base64)
                    if isinstance(result, dict) and result.get('success', False):
                        result.setdefault("source", "xunfei")
                        return jsonify(result), 200
            except Exception as xf_error:
                print(f"[FACE][override] xunfei detect failed: {xf_error}")

        local_result = _local_face_detect(image_base64)
        if isinstance(local_result, dict) and local_result.get('success', False):
            return jsonify(local_result), 200

        reason = ""
        if isinstance(local_result, dict):
            reason = local_result.get('error', '') or ''
        if not reason:
            reason = '人脸检测不可用'
        return jsonify(_face_failure_payload(reason)), 200
    except Exception as e:
        print(f"[FACE][override] exception: {e}")
        traceback.print_exc()
        return jsonify(_face_failure_payload(str(e))), 200


def _audio_to_text_safe_override():
    try:
        if get_xf_client is None:
            return _json_error('讯飞 SDK 未正确加载', 503, XF_IMPORT_ERROR)

        data = request.get_json(silent=True) or {}
        audio_b64 = data.get('audio', '')
        if not audio_b64:
            return _json_error('未提供音频数据', 400)

        try:
            audio_data = base64.b64decode(audio_b64, validate=True)
        except (binascii.Error, ValueError):
            return _json_error('音频数据不是合法的 base64', 400)

        if not audio_data:
            return _json_error('音频数据为空', 400)

        client = get_xf_client()
        if client is None:
            return _json_error('讯飞客户端初始化失败，请检查 APPID/APIKey/APISecret', 503)

        result = client.asr_audio_to_text(audio_data)
        if not isinstance(result, dict):
            return _json_error('语音识别返回格式异常', 502)
        if result.get('success', False):
            return jsonify(result), 200

        err = str(result.get('error', '') or '')
        low_err = err.lower()
        is_no_speech = (
            ('未识别到有效语音' in err)
            or ('未识别' in err)
            or ('鏈瘑鍒' in err)
            or ('no valid speech' in low_err)
            or ('no speech' in low_err)
        )
        if is_no_speech:
            return jsonify({
                'success': True,
                'text': '',
                'warning': '未识别到有效语音',
                'analysis': {
                    'fluency_score': 10,
                    'word_count': 0,
                    'filler_words': 0,
                    'hesitation_markers': 0,
                    'repetitions': 0
                }
            }), 200

        # Keep JSON response but avoid hard 5xx so frontend can degrade gracefully.
        return jsonify({
            'success': False,
            'error': '语音识别失败',
            'details': err or '未知错误'
        }), 200
    except Exception as e:
        print(f"[ASR][override] exception: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': '语音识别失败',
            'details': str(e)
        }), 200


# Override unstable route handlers with robust versions without touching old encoded blocks.
app.view_functions['face_detect'] = _face_detect_safe_override
app.view_functions['audio_to_text'] = _audio_to_text_safe_override


def _face_detect_observable_override():
    """Face detect with xunfei-first strategy + explicit diagnostics."""
    try:
        data = request.get_json(silent=True) or {}
        image_base64 = data.get('image')
        if not image_base64:
            return _json_error('未提供图片数据', 400)

        xf_error = None
        xf_detail = None
        xf_attempted = False

        # Try xunfei first and retry once before fallback.
        if get_xf_client is not None:
            client = get_xf_client()
            if client is not None:
                xf_attempted = True
                for attempt in (1, 2):
                    try:
                        xf_res = client.detect_face_and_expression(image_base64)
                        if isinstance(xf_res, dict) and xf_res.get('success', False):
                            xf_res.setdefault('source', 'xunfei')
                            xf_res['xunfei_attempted'] = True
                            xf_res['xunfei_retry_count'] = attempt - 1
                            return jsonify(xf_res), 200
                        xf_error = (xf_res or {}).get('error', 'xunfei detect failed')
                        xf_detail = xf_res
                        print(f"[FACE][xunfei] attempt={attempt} failed: {xf_error}")
                    except Exception as e:
                        xf_error = str(e)
                        xf_detail = {'exception': str(e)}
                        print(f"[FACE][xunfei] attempt={attempt} exception: {e}")

        # Fallback local cv
        local_res = _local_face_detect(image_base64)
        if isinstance(local_res, dict) and local_res.get('success', False):
            local_res.setdefault('source', 'local_cv')
            local_res['xunfei_attempted'] = xf_attempted
            if xf_error:
                local_res['xunfei_error'] = xf_error
            if xf_detail:
                local_res['xunfei_detail'] = xf_detail
            return jsonify(local_res), 200

        # Final fallback payload with diagnostics
        reason = ""
        if isinstance(local_res, dict):
            reason = local_res.get('error', '') or ''
        if not reason:
            reason = '人脸检测不可用'
        fail = _face_failure_payload(reason)
        fail['source'] = 'fallback'
        fail['xunfei_attempted'] = xf_attempted
        if xf_error:
            fail['xunfei_error'] = xf_error
        if xf_detail:
            fail['xunfei_detail'] = xf_detail
        return jsonify(fail), 200
    except Exception as e:
        print(f"[FACE][observable] exception: {e}")
        traceback.print_exc()
        fail = _face_failure_payload(str(e))
        fail['source'] = 'fallback'
        fail['xunfei_attempted'] = True
        fail['xunfei_error'] = str(e)
        return jsonify(fail), 200


# Rebind face_detect to observable xunfei-first handler.
app.view_functions['face_detect'] = _face_detect_observable_override


def _get_questions_safe_override():
    """Question bank endpoint with optional category and answer payload."""
    try:
        data = request.get_json(silent=True) or {}
        job_category = data.get('job_category')
        question_count = data.get('count', 100)
        try:
            question_count = max(1, int(question_count))
        except Exception:
            question_count = 100

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                if job_category:
                    cursor.execute(
                        '''
                        SELECT id, job_category, question, answer, keywords
                        FROM questions
                        WHERE job_category = %s
                        ORDER BY id DESC
                        ''',
                        (job_category,)
                    )
                else:
                    cursor.execute(
                        '''
                        SELECT id, job_category, question, answer, keywords
                        FROM questions
                        ORDER BY id DESC
                        '''
                    )
                questions = cursor.fetchall() or []

            if not questions:
                return jsonify({'questions': []}), 200

            if len(questions) > question_count:
                questions = random.sample(questions, question_count)
            return jsonify({'questions': questions}), 200
        finally:
            conn.close()
    except Exception as e:
        print(f'[QUESTIONS] override failed: {e}')
        traceback.print_exc()
        return jsonify({'error': '获取题库失败'}), 500


app.view_functions['get_questions'] = _get_questions_safe_override


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
