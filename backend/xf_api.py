import hashlib
import base64
import hmac
import json
import time
import os
from datetime import datetime
try:
    import requests
except Exception:
    requests = None


def _new_session():
    if requests is None:
        raise RuntimeError("Python package 'requests' is not installed")
    session = requests.Session()
    session.trust_env = False
    return session

class XunfeiAPIClient:
    """科大讯飞多模态AI API客户端"""
    
    def __init__(self, app_id, api_key, api_secret):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
    
    def _get_headers(self):
        """生成请求头"""
        url = "https://iat-api.xfyun.cn/v2/iat"
        now = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
        signature_origin = f"host: iat-api.xfyun.cn\ndate: {now}\nGET /v2/iat HTTP/1.1"
        signature_sha = hmac.new(self.api_secret.encode('utf-8'), 
                                 signature_origin.encode('utf-8'), 
                                 digestmod=hashlib.sha256).digest()
        signature = base64.b64encode(signature_sha).decode(encoding='utf-8')
        authorization_origin = f'api_key="{self.api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature}"'
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')
        return {
            "Authorization": authorization,
            "Date": now,
            "Host": "iat-api.xfyun.cn"
        }
    
    # ========== ASR 语音转文字 ==========
    def asr_audio_to_text(self, audio_data):
        """
        语音识别（ASR）- 使用科大讯飞WebSocket API
        输入：音频数据（PCM格式，16kHz采样率，16bit位深，单声道）
        输出：识别后的文本
        """
        try:
            import websocket
            import json
            import _thread as thread
            import ssl
            
            print(f"[ASR] 开始科大讯飞语音识别，音频大小: {len(audio_data)} 字节")
            
            # 科大讯飞WebSocket URL
            ws_url = "wss://iat-api.xfyun.cn/v2/iat"
            
            # 生成鉴权URL
            auth_url = self._get_auth_url()
            
            result_text = ""
            result_error = None
            
            def on_message(ws, message):
                nonlocal result_text
                try:
                    data = json.loads(message)
                    if data.get('code') != 0:
                        nonlocal result_error
                        result_error = data.get('message', '识别失败')
                        ws.close()
                        return
                    
                    # 解析识别结果
                    if 'data' in data and 'result' in data['data']:
                        ws_data = data['data']['result']
                        if 'ws' in ws_data:
                            for item in ws_data['ws']:
                                if 'cw' in item:
                                    for cw in item['cw']:
                                        result_text += cw['w']
                    
                    # 检查是否结束
                    if data.get('data', {}).get('status') == 2:
                        ws.close()
                except Exception as e:
                    print(f"[ASR] 解析消息失败: {e}")
            
            def on_error(ws, error):
                nonlocal result_error
                result_error = str(error)
                print(f"[ASR] WebSocket错误: {error}")
            
            def on_close(ws, close_status_code, close_msg):
                print(f"[ASR] WebSocket连接关闭")
            
            def on_open(ws):
                print("[ASR] WebSocket连接成功，开始发送音频数据")
                # 分帧发送音频数据
                frame_size = 8000  # 每帧大小
                for i in range(0, len(audio_data), frame_size):
                    frame = audio_data[i:i+frame_size]
                    # 第一帧
                    if i == 0:
                        data = {
                            "common": {"app_id": self.app_id},
                            "business": {
                                "language": "zh_cn",
                                "domain": "iat",
                                "accent": "mandarin",
                                "vinfo": 1,
                                "vad_eos": 3000
                            },
                            "data": {
                                "status": 0,
                                "format": "audio/L16;rate=16000",
                                "encoding": "raw",
                                "audio": base64.b64encode(frame).decode('utf-8')
                            }
                        }
                    # 中间帧
                    elif i + frame_size < len(audio_data):
                        data = {
                            "data": {
                                "status": 1,
                                "format": "audio/L16;rate=16000",
                                "encoding": "raw",
                                "audio": base64.b64encode(frame).decode('utf-8')
                            }
                        }
                    # 最后一帧
                    else:
                        data = {
                            "data": {
                                "status": 2,
                                "format": "audio/L16;rate=16000",
                                "encoding": "raw",
                                "audio": base64.b64encode(frame).decode('utf-8')
                            }
                        }
                    ws.send(json.dumps(data))
                    time.sleep(0.02)  # 控制发送速率
            
            # 建立WebSocket连接
            websocket.enableTrace(False)
            ws = websocket.WebSocketApp(
                auth_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            
            # 运行WebSocket（设置超时）
            ws.run_forever(
                sslopt={"cert_reqs": ssl.CERT_NONE},
                ping_timeout=30,
                http_proxy_host=None,
                http_proxy_port=None
            )
            
            if result_error:
                print(f"[ASR] 识别失败: {result_error}")
                return {"success": False, "error": result_error}
            
            if not result_text:
                print("[ASR] 未识别到文本")
                return {"success": False, "error": "未识别到有效语音"}
            
            print(f"[ASR] 识别成功: {result_text}")
            
            # 返回识别结果和分析
            analysis = self._analyze_speech_patterns(result_text)
            
            return {
                "success": True,
                "text": result_text,
                "confidence": 95,
                "analysis": analysis
            }
                
        except Exception as e:
            print(f"[ASR] 错误: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
    
    def _get_auth_url(self):
        """生成WebSocket鉴权URL"""
        from urllib.parse import urlencode
        import urllib.parse
        
        url = "wss://iat-api.xfyun.cn/v2/iat"
        now = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
        
        # 生成签名
        signature_origin = f"host: iat-api.xfyun.cn\ndate: {now}\nGET /v2/iat HTTP/1.1"
        signature_sha = hmac.new(
            self.api_secret.encode('utf-8'),
            signature_origin.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        signature = base64.b64encode(signature_sha).decode('utf-8')
        
        authorization_origin = f'api_key="{self.api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature}"'
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode('utf-8')
        
        # 构建URL参数
        params = {
            "authorization": authorization,
            "date": now,
            "host": "iat-api.xfyun.cn"
        }
        
        return f"{url}?{urlencode(params)}"
    
    # ========== 文本语义分析 ==========
    def analyze_text_content(self, text, question_info, job_category):
        """
        文本内容分析（用于面试回答评分）
        输入：识别出的文本、题目信息、岗位类别
        输出：内容评分和分析结果
        """
        try:
            print(f"[文本分析] 开始分析文本，长度: {len(text)} 字符")
            print(f"[文本分析] 岗位类别: {job_category}")
            
            # 这里可以调用科大讯飞的文本理解API
            # 目前使用本地分析
            analysis = {
                "word_count": len(text),
                "sentence_count": len([s for s in text.split('。') if s.strip()]),
                "has_keywords": self._check_keywords(text, question_info),
                "content_score": self._score_content_quality(text, question_info, job_category)
            }
            
            print(f"[文本分析] 分析结果: {analysis}")
            return analysis
            
        except Exception as e:
            print(f"[文本分析] 错误: {e}")
            return {"error": str(e)}
    
    def _check_keywords(self, text, question_info):
        """检查回答中是否包含关键词"""
        if not question_info or not isinstance(question_info, dict):
            return False
        
        keywords = question_info.get('keywords', '').split(',')
        found_keywords = [kw for kw in keywords if kw.strip() in text]
        return len(found_keywords) > 0
    
    def _score_content_quality(self, text, question_info, job_category):
        """评分内容质量"""
        score = 50  # 基础分
        
        # 长度评分
        if len(text) > 50:
            score += 10
        if len(text) > 100:
            score += 10
        if len(text) > 200:
            score += 10
        
        # 关键词匹配
        if question_info and isinstance(question_info, dict):
            keywords = question_info.get('keywords', '').split(',')
            found_count = sum(1 for kw in keywords if kw.strip() in text)
            score += min(20, found_count * 5)
        
        return min(100, score)
    
    def _analyze_speech_patterns(self, text):
        """分析语音模式（停顿、卡顿、语速等）"""
        import re
        
        patterns = {
            "filler_words": len(re.findall(r'(嗯|啊|呃|那个|这个|然后|就是)', text)),
            "repetitions": len(re.findall(r'(.{3,}?)\1+', text)),
            "hesitation_markers": len(re.findall(r'[...·—～]+', text)),
            "word_count": len(text),
            "sentence_count": len([s for s in re.split(r'[。！？]', text) if s.strip()])
        }
        
        avg_sentence_length = patterns["word_count"] / max(1, patterns["sentence_count"])
        
        fluency_score = 100
        fluency_score -= min(30, patterns["filler_words"] * 5)
        fluency_score -= min(20, patterns["repetitions"] * 10)
        fluency_score -= min(20, patterns["hesitation_markers"] * 5)
        
        if avg_sentence_length < 5:
            fluency_score -= 15
        elif avg_sentence_length > 50:
            fluency_score -= 5
        
        return {
            **patterns,
            "avg_sentence_length": round(avg_sentence_length, 1),
            "fluency_score": max(0, fluency_score),
            "speed_assessment": "过快" if avg_sentence_length > 40 else ("过慢" if avg_sentence_length < 8 else "正常")
        }
    
    # ========== 人脸检测与表情识别 ==========
    def detect_face_and_expression(self, image_base64):
        """
        面部检测 + 表情识别（基于讯飞开放平台）
        输入：Base64编码的图片
        输出：面部状态 + 情绪分析
        """
        try:
            url = "https://api.xfyun.cn/v1/service/v1/image_understanding"
            
            headers = {
                "Authorization": self.api_key,
                "Content-Type": "application/json"
            }
            
            data = {
                "header": {
                    "app_id": self.app_id,
                    "status": 3
                },
                "parameter": {
                    "image_understanding": {
                        "scene": "face_analysis"
                    }
                },
                "payload": {
                    "image": {
                        "encoding": "base64",
                        "image": image_base64.split(",")[-1] if "," in image_base64 else image_base64,
                        "status": 3
                    }
                }
            }
            
            response = _new_session().post(url, json=data, headers=headers, timeout=30)
            result = response.json()
            
            if result.get('code') == 0:
                content = result.get('data', {}).get('result', {}).get('content', '{}')
                face_info = json.loads(content) if isinstance(content, str) else content
                
                return {
                    "success": True,
                    "face_detected": True,
                    "face_info": face_info,
                    "expression_analysis": self._parse_expressions(face_info),
                    "compliance_check": self._check_face_compliance(face_info)
                }
            else:
                return {
                    "success": False,
                    "error": result.get('message', '人脸检测失败'),
                    "face_detected": False
                }
                
        except Exception as e:
            return {"success": False, "error": str(e), "face_detected": False}
    
    def _parse_expressions(self, face_info):
        """解析表情数据"""
        expressions = {
            "neutral": 0,
            "happy": 0,
            "sad": 0,
            "angry": 0,
            "surprised": 0,
            "fearful": 0,
            "disgusted": 0,
            "contempt": 0
        }
        
        if isinstance(face_info, dict) and 'faces' in face_info:
            faces = face_info['faces']
            if faces and len(faces) > 0:
                face = faces[0]
                attributes = face.get('attributes', {})
                emotion = attributes.get('emotion', {})
                
                expressions.update({
                    "confidence": emotion.get('confidence', 0),
                    "dominant_emotion": emotion.get('dominant_emotion', 'neutral'),
                    "attention": attributes.get('attention', {}).get('score', 70),
                    "eye_gaze": attributes.get('eye_gaze', {}),
                    "head_pose": attributes.get('head_pose', {})
                })
        
        return expressions
    
    def _check_face_compliance(self, face_info):
        """检查面部合规性"""
        compliance = {
            "is_compliant": True,
            "face_coverage": 60,
            "is_frontal": True,
            "has_occlusion": False,
            "lighting_ok": True,
            "deductions": []
        }
        
        if isinstance(face_info, dict) and 'faces' in face_info:
            faces = face_info['faces']
            if not faces or len(faces) == 0:
                compliance["is_compliant"] = False
                compliance["deductions"].append("未检测到人脸")
                return compliance
            
            face_rect = faces[0].get('rectangle', {})
            width = face_rect.get('width', 100)
            height = face_rect.get('height', 100)
            
            coverage = (width * height) / (640 * 480) * 100 if width and height else 30
            compliance["face_coverage"] = min(100, int(coverage))
            
            if compliance["face_coverage"] < 40:
                compliance["is_compliant"] = False
                compliance["deductions"].append(f"人脸占比过低({coverage:.0f}%)")
            
            pose = faces[0].get('attributes', {}).get('head_pose', {})
            yaw = abs(pose.get('yaw', 0))
            pitch = abs(pose.get('pitch', 0))
            
            if yaw > 25 or pitch > 20:
                compliance["is_frontal"] = False
                compliance["is_compliant"] = False
                compliance["deductions"].append("非正面朝向")
        
        return compliance


# ========== 多维度评分引擎 ==========
class MultimodalScoringEngine:
    """多模态AI面试评分引擎"""
    
    WEIGHTS = {
        "non_verbal": 0.40,      # 非语言表现（面部+表情+仪态）40%
        "verbal": 0.25,          # 语言表达（流畅度+清晰度+逻辑性）25%
        "content": 0.35          # 作答内容（专业匹配+逻辑深度+完整性）35%
    }
    
    NON_VERBAL_WEIGHTS = {
        "face_compliance": 0.25,     # 面部合规 10%
        "expression_emotion": 0.50,   # 表情与情绪 20%
        "posture_eye_contact": 0.25  # 仪态与眼神 10%
    }
    
    VERBAL_WEIGHTS = {
        "fluency": 0.40,             # 流畅度 10%
        "clarity": 0.30,             # 清晰度 7.5%
        "logic": 0.30                # 逻辑性 7.5%
    }
    
    CONTENT_WEIGHTS = {
        "professional_match": 0.35,  # 专业匹配 12.25%
        "logic_depth": 0.35,         # 逻辑深度 12.25%
        "completeness": 0.30         # 完整性 10.5%
    }
    
    @classmethod
    def calculate_overall_score(cls, multimodal_data):
        """
        计算综合得分
        multimodal_data: 包含面部数据、语音数据、文本数据的字典
        返回: 完整评分报告
        """
        if not isinstance(multimodal_data, dict):
            multimodal_data = {}

        non_verbal_score = cls._score_non_verbal(multimodal_data.get("face_data", {}))
        verbal_score = cls._score_verbal(multimodal_data.get("speech_data", {}))
        content_score = cls._score_content(
            multimodal_data.get("text_answer", ""),
            multimodal_data.get("question_info", {}),
            multimodal_data.get("job_category", "")
        )
        
        # 检查是否未作答
        text_answer = (multimodal_data.get("text_answer", "") or "").strip()
        if not text_answer or text_answer == "(未作答)":
            total_score = 15
        else:
            total_score = (
                non_verbal_score["subtotal"] * cls.WEIGHTS["non_verbal"] +
                verbal_score["subtotal"] * cls.WEIGHTS["verbal"] +
                content_score["subtotal"] * cls.WEIGHTS["content"]
            )
            # 对“不会/不知道”类回答做强惩罚，避免轻易拿到及格分
            if cls._detect_non_answer(text_answer):
                total_score = min(total_score, 28)
        
        grade = cls._determine_grade(total_score)
        
        return {
            "total_score": round(total_score, 1),
            "grade": grade,
            "dimensions": {
                "non_verbal": non_verbal_score,
                "verbal": verbal_score,
                "content": content_score
            },
            "recommendation": cls._generate_recommendation(grade, non_verbal_score, verbal_score, content_score)
        }
    
    @classmethod
    def _score_non_verbal(cls, face_data):
        """非语言表现评分（满分100）"""
        if not isinstance(face_data, dict):
            face_data = {}

        compliance = face_data.get("compliance_check", {})
        expression = face_data.get("expression_analysis", {})
        if not isinstance(compliance, dict):
            compliance = {}
        if not isinstance(expression, dict):
            expression = {}
        
        # 面部合规评分（满分100）
        face_score = 100
        if not compliance.get("is_compliant", True):
            face_score -= 20
        face_score -= min(15, (60 - compliance.get("face_coverage", 60)) // 4)
        if not compliance.get("is_frontal", True):
            face_score -= 15
        if compliance.get("has_occlusion", False):
            face_score -= 10
        face_score = max(0, face_score)
        
        # 表情与情绪评分（满分100）
        emotion_score = expression.get("confidence", 70)
        attention = expression.get("attention", 70)
        dominant = expression.get("dominant_emotion", "neutral")
        
        emotion_map = {
            "happy": 95, "neutral": 80, "surprised": 75,
            "sad": 55, "fearful": 45, "angry": 40,
            "disgusted": 35, "contempt": 30
        }
        emotion_base = emotion_map.get(dominant, 70)
        
        expr_score = (emotion_base * 0.5 + attention * 0.3 + emotion_score * 0.2)
        
        # 仪态与眼神评分（满分100）
        eye_gaze = expression.get("eye_gaze", {})
        posture_score = attention * 0.7 + (100 - abs(eye_gaze.get("direction_x", 0)) * 2) * 0.3
        posture_score = max(0, min(100, posture_score))
        
        subtotal = (
            face_score * cls.NON_VERBAL_WEIGHTS["face_compliance"] +
            expr_score * cls.NON_VERBAL_WEIGHTS["expression_emotion"] +
            posture_score * cls.NON_VERBAL_WEIGHTS["posture_eye_contact"]
        )
        
        return {
            "subtotal": subtotal,
            "breakdown": {
                "face_compliance": round(face_score, 1),
                "expression_emotion": round(expr_score, 1),
                "posture_eye_contact": round(posture_score, 1)
            },
            "details": {
                "face_coverage": compliance.get("face_coverage", 0),
                "is_frontal": compliance.get("is_frontal", True),
                "dominant_emotion": dominant,
                "confidence_level": emotion_score,
                "attention_level": attention
            }
        }

    @classmethod
    def _detect_non_answer(cls, answer_text):
        text = (answer_text or "").strip().lower()
        if not text:
            return True

        non_answer_patterns = [
            "不知道", "不太清楚", "不会", "没做过", "不了解", "想不起来",
            "随便", "无", "没有", "不清楚", "idk", "don't know"
        ]
        if any(p in text for p in non_answer_patterns):
            return True

        # 过短回答也视为无效回答
        pure = "".join(ch for ch in text if ch.strip())
        return len(pure) < 8
    
    @classmethod
    def _score_verbal(cls, speech_data):
        """语言表达评分（满分100）"""
        if not isinstance(speech_data, dict):
            speech_data = {}
        analysis = speech_data.get("analysis", {})
        if not isinstance(analysis, dict):
            analysis = {}

        word_count = int(analysis.get("word_count", 0) or 0)
        filler_words = int(analysis.get("filler_words", 0) or 0)
        hesitations = int(analysis.get("hesitation_markers", 0) or 0)
        repetitions = int(analysis.get("repetitions", 0) or 0)
        avg_sentence_length = float(analysis.get("avg_sentence_length", 12) or 12)

        fluency_raw = float(analysis.get("fluency_score", 45) or 45)
        short_penalty = max(0, 18 - word_count) * 2.2
        fluency = max(0, min(100, fluency_raw - short_penalty - repetitions * 6))

        clarity = max(0, min(100, 85 - filler_words * 8 - hesitations * 10 - repetitions * 6))
        logic = max(0, min(100, 35 + min(word_count, 120) * 0.45 - abs(avg_sentence_length - 18) * 2.2))
        if word_count < 12:
            logic = max(0, logic - 25)
            clarity = max(0, clarity - 15)
        
        subtotal = (
            fluency * cls.VERBAL_WEIGHTS["fluency"] +
            clarity * cls.VERBAL_WEIGHTS["clarity"] +
            logic * cls.VERBAL_WEIGHTS["logic"]
        )
        
        return {
            "subtotal": subtotal,
            "breakdown": {
                "fluency": round(fluency, 1),
                "clarity": round(clarity, 1),
                "logic": round(logic, 1)
            },
            "details": {
                "word_count": word_count,
                "filler_words": filler_words,
                "speed_assessment": analysis.get("speed_assessment", "正常"),
                "sentence_count": analysis.get("sentence_count", 0),
                "repetitions": repetitions
            }
        }
    
    @classmethod
    def _score_content(cls, answer, question_info, job_category):
        """作答内容评分（满分100）"""
        if not answer:
            return {"subtotal": 0, "breakdown": {"professional_match": 0, "logic_depth": 0, "completeness": 0}, "details": {}}
        
        if not isinstance(question_info, dict):
            question_info = {}

        if cls._detect_non_answer(answer):
            return {
                "subtotal": 8,
                "breakdown": {
                    "professional_match": 5,
                    "logic_depth": 8,
                    "completeness": 10
                },
                "details": {
                    "keyword_matches": 0,
                    "total_keywords": 0,
                    "matched_keywords_list": [],
                    "answer_length": len(answer),
                    "structure_indicators_found": 0,
                    "non_answer": True
                }
            }

        keywords = question_info.get("keywords", "").split(",") if question_info.get("keywords") else []
        correct_answer = question_info.get("answer", "")
        
        # 专业匹配度：不再给高基础分
        matched_keywords = sum(1 for kw in keywords if kw in answer)
        keyword_ratio = matched_keywords / max(1, len(keywords))
        professional_score = keyword_ratio * 100
        
        # 逻辑深度
        star_indicators = ["首先", "其次", "然后", "最后", "第一", "第二", "第三", "总之", "总结", "因为", "所以", "具体来说", "例如", "比如"]
        structure_hits = sum(1 for ind in star_indicators if ind in answer)
        logic_depth = min(100, structure_hits * 12 + max(0, (len(answer) - 20) * 0.35))
        
        # 完整性：按长度与参考答案比例计算，不再强行保底
        answer_len = len(answer)
        reference_len = len(correct_answer) if correct_answer else 140
        completeness = min(100, (answer_len / max(120, reference_len)) * 100)
        if answer_len < 15:
            completeness *= 0.4
        elif answer_len < 30:
            completeness *= 0.65
        
        subtotal = (
            professional_score * cls.CONTENT_WEIGHTS["professional_match"] +
            logic_depth * cls.CONTENT_WEIGHTS["logic_depth"] +
            completeness * cls.CONTENT_WEIGHTS["completeness"]
        )
        
        return {
            "subtotal": subtotal,
            "breakdown": {
                "professional_match": round(professional_score, 1),
                "logic_depth": round(logic_depth, 1),
                "completeness": round(completeness, 1)
            },
            "details": {
                "keyword_matches": matched_keywords,
                "total_keywords": len(keywords),
                "matched_keywords_list": [kw for kw in keywords if kw in answer],
                "answer_length": answer_len,
                "structure_indicators_found": sum(1 for ind in star_indicators if ind in answer)
            }
        }
    
    @classmethod
    def _determine_grade(cls, score):
        """确定等级 - 更加严苛"""
        if score >= 95: return "优秀"  # 提高优秀标准
        elif score >= 85: return "良好"  # 提高良好标准
        elif score >= 75: return "合格"  # 提高合格标准
        elif score >= 65: return "待改进"  # 提高待改进标准
        else: return "不合格"
    
    @classmethod
    def _generate_recommendation(cls, grade, nv, vb, ct):
        """生成录用建议"""
        if grade == "优秀":
            recommendation = "推荐录用"
            reason = "候选人表现优异，各方面能力突出"
        elif grade == "良好":
            recommendation = "推荐录用"
            reason = "候选人整体表现良好，具备岗位所需能力"
        elif grade == "合格":
            recommendation = "待定"
            reason = "候选人基本符合要求，建议进一步考察或提供培训机会"
        elif grade == "待改进":
            recommendation = "待定"
            reason = "候选人在某些方面存在不足，建议安排二次面试或针对性提升"
        else:
            recommendation = "不推荐"
            reason = "候选人与岗位要求存在较大差距"
        
        strengths = []
        weaknesses = []
        
        if nv["subtotal"] >= 80:
            strengths.append("仪表端庄，情绪稳定自信")
        elif nv["subtotal"] < 60:
            weaknesses.append("需加强面试礼仪和情绪管理")
        
        if vb["subtotal"] >= 80:
            strengths.append("表达流畅清晰，逻辑性强")
        elif vb["subtotal"] < 60:
            weaknesses.append("表达能力有待提升，建议多做练习")
        
        if ct["subtotal"] >= 80:
            strengths.append("专业基础扎实，回答完整深入")
        elif ct["subtotal"] < 60:
            weaknesses.append("专业知识需加强学习")
        
        return {
            "decision": recommendation,
            "reason": reason,
            "strengths": strengths if strengths else ["表现均衡"],
            "weaknesses": weaknesses if weaknesses else ["无明显短板"],
            "suggestions": [f"重点提升：{w}" for w in weaknesses] if weaknesses else ["保持现有水平，持续精进"]
        }


# 初始化讯飞客户端（从环境变量读取凭证）
XF_APP_ID = os.getenv("XF_APP_ID", "")
XF_API_KEY = os.getenv("XF_API_KEY", "")
XF_API_SECRET = os.getenv("XF_API_SECRET", "")

def get_xf_client():
    """获取讯飞API客户端实例"""
    print(f"尝试初始化讯飞客户端: APPID={XF_APP_ID}, API_KEY_SET={bool(XF_API_KEY)}, API_SECRET_SET={bool(XF_API_SECRET)}")
    if XF_APP_ID and XF_API_KEY and XF_API_SECRET and XF_API_KEY != "您的API密钥" and XF_API_SECRET != "您的API密钥":
        print("成功初始化讯飞客户端")
        return XunfeiAPIClient(XF_APP_ID, XF_API_KEY, XF_API_SECRET)
    else:
        print("讯飞客户端初始化失败: API密钥为空或无效")
        return None

def call_spark_api(prompt, max_tokens=1024):
    """
    调用科大讯飞星火大模型API（Spark）
    这会真正消耗token！
    """
    try:
        url = "https://spark-api-open.xf-yun.com/v2/chat/completions"
        
        # 生成请求头
        now = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
        signature_origin = f"host: spark-api-open.xf-yun.com\ndate: {now}\nPOST /v2/chat/completions HTTP/1.1"
        signature_sha = hmac.new(XF_API_SECRET.encode('utf-8'), 
                                 signature_origin.encode('utf-8'), 
                                 digestmod=hashlib.sha256).digest()
        signature = base64.b64encode(signature_sha).decode(encoding='utf-8')
        authorization_origin = f'api_key="{XF_API_KEY}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature}"'
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')
        
        headers = {
            "authorization": authorization,
            "date": now,
            "host": "spark-api-open.xf-yun.com",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "spark-x",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7
        }
        
        print(f"[Spark API] 正在调用星火大模型...")
        print(f"[Spark API] Prompt长度: {len(prompt)} 字符")
        
        response = _new_session().post(url, json=data, headers=headers, timeout=30)
        result = response.json()
        
        print(f"[Spark API] 响应状态码: {response.status_code}")
        print(f"[Spark API] 响应内容: {str(result)[:200]}...")
        
        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0]['message']['content']
            usage = result.get('usage', {})
            print(f"[Spark API] 调用成功，Token使用: {usage}")
            return {
                "success": True,
                "content": content,
                "usage": usage
            }
        else:
            error_msg = result.get('error', {}).get('message', '未知错误')
            print(f"[Spark API] 调用失败: {error_msg}")
            return {"success": False, "error": error_msg}
            
    except Exception as e:
        print(f"[Spark API] 异常: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}



def build_spark_ws_auth_url(base_url, api_key, api_secret):
    from urllib.parse import urlencode, urlparse
    from time import mktime
    from wsgiref.handlers import format_date_time

    parsed = urlparse(base_url)
    host = parsed.netloc
    path = parsed.path
    date = format_date_time(mktime(datetime.now().timetuple()))

    signature_origin = f"host: {host}\n"
    signature_origin += f"date: {date}\n"
    signature_origin += f"GET {path} HTTP/1.1"

    signature_sha = hmac.new(
        api_secret.encode('utf-8'),
        signature_origin.encode('utf-8'),
        digestmod=hashlib.sha256
    ).digest()
    signature = base64.b64encode(signature_sha).decode('utf-8')

    authorization_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"'
    )
    authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode('utf-8')
    return f"{base_url}?{urlencode({'authorization': authorization, 'date': date, 'host': host})}"


def call_spark_ws_api(prompt, max_tokens=1024):
    try:
        import json as _json
        import ssl
        import websocket

        ws_base_url = "wss://spark-api.xf-yun.com/v4.0/chat"
        ws_url = build_spark_ws_auth_url(ws_base_url, XF_API_KEY, XF_API_SECRET)
        print(f"[Spark WS] start, prompt length={len(prompt)}")

        result_parts = []
        usage = {}
        error_message = None

        def on_message(ws, message):
            nonlocal error_message, usage
            try:
                data = _json.loads(message)
                header = data.get("header", {})
                code = header.get("code", 0)
                if code != 0:
                    error_message = header.get("message") or data.get("message") or f"Spark????? {code}"
                    ws.close()
                    return

                payload = data.get("payload", {})
                choices = payload.get("choices", {})
                for item in choices.get("text", []):
                    content = item.get("content", "")
                    if content:
                        result_parts.append(content)

                if payload.get("usage"):
                    usage = payload.get("usage", {})

                if header.get("status") == 2 or choices.get("status") == 2:
                    ws.close()
            except Exception as exc:
                error_message = str(exc)
                ws.close()

        def on_error(ws, error):
            nonlocal error_message
            error_message = str(error)

        def on_close(ws, close_status_code, close_msg):
            print("[Spark WS] closed")

        def on_open(ws):
            request_data = {
                "header": {
                    "app_id": XF_APP_ID,
                    "uid": "ai-interview-system"
                },
                "parameter": {
                    "chat": {
                        "domain": "4.0Ultra",
                        "temperature": 0.2,
                        "max_tokens": max_tokens
                    }
                },
                "payload": {
                    "message": {
                        "text": [
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ]
                    }
                }
            }
            ws.send(_json.dumps(request_data))

        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        ws.run_forever(
            sslopt={"cert_reqs": ssl.CERT_NONE},
            ping_timeout=30,
            http_proxy_host=None,
            http_proxy_port=None
        )

        if error_message:
            print(f"[Spark WS] failed: {error_message}")
            return {"success": False, "error": error_message}

        content = "".join(result_parts).strip()
        if not content:
            return {"success": False, "error": "???????"}

        print(f"[Spark WS] success, content length={len(content)}")
        return {
            "success": True,
            "content": content,
            "usage": usage
        }
    except Exception as exc:
        print(f"[Spark WS] exception: {exc}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(exc)}


# ---------------- Strict runtime overrides ----------------
def _strict_score_non_verbal(cls, face_data):
    """Stricter non-verbal scoring to avoid unrealistically high scores."""
    if not isinstance(face_data, dict):
        face_data = {}

    face_detected = bool(face_data.get("face_detected", False))
    compliance = face_data.get("compliance_check", {})
    expression = face_data.get("expression_analysis", {})
    if not isinstance(compliance, dict):
        compliance = {}
    if not isinstance(expression, dict):
        expression = {}

    face_coverage = float(compliance.get("face_coverage", 0) or 0)
    is_compliant = bool(compliance.get("is_compliant", False))
    is_frontal = bool(compliance.get("is_frontal", False))
    has_occlusion = bool(compliance.get("has_occlusion", False))

    if (not face_detected) or face_coverage <= 0:
        face_score = 0.0
        expr_score = 20.0
        posture_score = 15.0
        dominant = "unknown"
        emotion_score = 20.0
        attention = 20.0
    else:
        face_score = min(100.0, max(0.0, face_coverage * 1.15))
        if not is_compliant:
            face_score -= 20.0
        if not is_frontal:
            face_score -= 18.0
        if has_occlusion:
            face_score -= 12.0
        if face_coverage < 45:
            face_score -= 15.0
        face_score = max(0.0, min(100.0, face_score))

        emotion_score = float(expression.get("confidence", 45) or 45)
        attention = float(expression.get("attention", 45) or 45)
        dominant = expression.get("dominant_emotion", "neutral")
        emotion_map = {
            "happy": 88, "neutral": 68, "surprised": 65,
            "sad": 45, "fearful": 35, "angry": 30,
            "disgusted": 25, "contempt": 20
        }
        emotion_base = float(emotion_map.get(dominant, 50))
        expr_score = max(0.0, min(100.0, emotion_base * 0.45 + attention * 0.35 + emotion_score * 0.20))

        eye_gaze = expression.get("eye_gaze", {})
        if not isinstance(eye_gaze, dict):
            eye_gaze = {}
        direction_x = float(eye_gaze.get("direction_x", 0) or 0)
        posture_score = max(0.0, min(100.0, attention * 0.65 + (100.0 - abs(direction_x) * 2.0) * 0.35))

    subtotal = (
        face_score * cls.NON_VERBAL_WEIGHTS["face_compliance"] +
        expr_score * cls.NON_VERBAL_WEIGHTS["expression_emotion"] +
        posture_score * cls.NON_VERBAL_WEIGHTS["posture_eye_contact"]
    )

    return {
        "subtotal": subtotal,
        "breakdown": {
            "face_compliance": round(face_score, 1),
            "expression_emotion": round(expr_score, 1),
            "posture_eye_contact": round(posture_score, 1)
        },
        "details": {
            "face_detected": face_detected,
            "face_coverage": round(face_coverage, 1),
            "is_frontal": is_frontal,
            "dominant_emotion": dominant,
            "confidence_level": round(float(emotion_score), 1),
            "attention_level": round(float(attention), 1)
        }
    }


try:
    MultimodalScoringEngine._score_non_verbal = classmethod(_strict_score_non_verbal)
except Exception:
    pass


def _detect_face_and_expression_observable(self, image_base64):
    """Xunfei face detect with endpoint/auth probing and explicit diagnostics."""
    try:
        image_raw = image_base64.split(",")[-1] if "," in str(image_base64) else str(image_base64)
        # User-provided private endpoint first; keep legacy as fallback probe.
        endpoints = [
            "https://api.xf-yun.com/v1/private/s67c9c78c",
        ]

        attempts = []

        def _parse_common_response(resp, endpoint, auth_mode):
            status = int(resp.status_code)
            ctype = resp.headers.get("Content-Type", "")
            text = (resp.text or "").strip()
            try:
                result = resp.json()
            except Exception:
                return None, {
                    "success": False,
                    "source": "xunfei",
                    "face_detected": False,
                    "error": "xunfei non-json response",
                    "details": {
                        "http_status": status,
                        "content_type": ctype,
                        "body_preview": text[:200],
                        "endpoint": endpoint,
                        "auth_mode": auth_mode
                    }
                }

            if result.get("code") == 0:
                content = result.get("data", {}).get("result", {}).get("content", "{}")
                try:
                    face_info = json.loads(content) if isinstance(content, str) else content
                except Exception:
                    face_info = {}
                return {
                    "success": True,
                    "source": "xunfei",
                    "face_detected": True,
                    "face_info": face_info,
                    "expression_analysis": self._parse_expressions(face_info),
                    "compliance_check": self._check_face_compliance(face_info),
                    "details": {
                        "http_status": status,
                        "content_type": ctype,
                        "endpoint": endpoint,
                        "auth_mode": auth_mode
                    }
                }, None

            return None, {
                "success": False,
                "source": "xunfei",
                "face_detected": False,
                "error": result.get("message", "xunfei detect failed"),
                "details": {
                    "http_status": status,
                    "content_type": ctype,
                    "xf_code": result.get("code"),
                    "xf_sid": result.get("sid"),
                    "endpoint": endpoint,
                    "auth_mode": auth_mode,
                    "body_preview": text[:200]
                }
            }

        for endpoint in endpoints:
            # Attempt C: HMAC(host/date/request-line) auth required by many xf private APIs.
            try:
                from urllib.parse import urlparse
                parsed = urlparse(endpoint)
                host = parsed.netloc
                path = parsed.path or "/"
                now = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
                signature_origin = f"host: {host}\ndate: {now}\nPOST {path} HTTP/1.1"
                signature_sha = hmac.new(
                    self.api_secret.encode("utf-8"),
                    signature_origin.encode("utf-8"),
                    digestmod=hashlib.sha256
                ).digest()
                signature = base64.b64encode(signature_sha).decode("utf-8")
                authorization_origin = (
                    f'api_key="{self.api_key}", algorithm="hmac-sha256", '
                    f'headers="host date request-line", signature="{signature}"'
                )
                authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")
                headers_c = {
                    "Authorization": authorization,
                    "Date": now,
                    "Host": host,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "AI-Interview/1.0"
                }
                body_c = {
                    "header": {"app_id": self.app_id, "status": 3},
                    "parameter": {"image_understanding": {"scene": "face_analysis"}},
                    "payload": {
                        "image": {"encoding": "base64", "image": image_raw, "status": 3}
                    }
                }
                resp_c = _new_session().post(endpoint, json=body_c, headers=headers_c, timeout=20)
                ok, fail = _parse_common_response(resp_c, endpoint, "hmac_host_date_request_line")
                if ok:
                    return ok
                attempts.append(fail)
            except Exception as e:
                attempts.append({
                    "success": False,
                    "source": "xunfei",
                    "face_detected": False,
                    "error": str(e),
                    "details": {"endpoint": endpoint, "auth_mode": "hmac_host_date_request_line"}
                })

            # Attempt A: JSON body + api_key header (legacy style).
            try:
                headers_a = {
                    "Authorization": self.api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "AI-Interview/1.0"
                }
                body_a = {
                    "header": {"app_id": self.app_id, "status": 3},
                    "parameter": {"image_understanding": {"scene": "face_analysis"}},
                    "payload": {
                        "image": {"encoding": "base64", "image": image_raw, "status": 3}
                    }
                }
                resp_a = _new_session().post(endpoint, json=body_a, headers=headers_a, timeout=20)
                ok, fail = _parse_common_response(resp_a, endpoint, "json_authorization_header")
                if ok:
                    return ok
                attempts.append(fail)
            except Exception as e:
                attempts.append({
                    "success": False,
                    "source": "xunfei",
                    "face_detected": False,
                    "error": str(e),
                    "details": {"endpoint": endpoint, "auth_mode": "json_authorization_header"}
                })

            # Attempt B: WebAPI checksum auth (X-Appid/X-Param/X-CurTime/X-CheckSum).
            try:
                cur_time = str(int(time.time()))
                param_obj = {
                    "scene": "face_analysis",
                    "image_type": "BASE64"
                }
                x_param = base64.b64encode(json.dumps(param_obj, ensure_ascii=False).encode("utf-8")).decode("utf-8")
                check_sum = hashlib.md5((self.api_key + cur_time + x_param + self.api_secret).encode("utf-8")).hexdigest()
                headers_b = {
                    "X-Appid": self.app_id,
                    "X-CurTime": cur_time,
                    "X-Param": x_param,
                    "X-CheckSum": check_sum,
                    "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                    "Accept": "application/json",
                    "User-Agent": "AI-Interview/1.0"
                }
                body_b = {"image": image_raw}
                resp_b = _new_session().post(endpoint, data=body_b, headers=headers_b, timeout=20)
                ok, fail = _parse_common_response(resp_b, endpoint, "webapi_checksum_headers")
                if ok:
                    return ok
                attempts.append(fail)
            except Exception as e:
                attempts.append({
                    "success": False,
                    "source": "xunfei",
                    "face_detected": False,
                    "error": str(e),
                    "details": {"endpoint": endpoint, "auth_mode": "webapi_checksum_headers"}
                })

        # All attempts failed.
        last = attempts[-1] if attempts else {"error": "xunfei detect failed"}
        return {
            "success": False,
            "source": "xunfei",
            "face_detected": False,
            "error": last.get("error", "xunfei detect failed"),
            "details": {
                "probe_attempts": attempts[-8:],  # keep payload compact but include private endpoint attempts
            }
        }
    except Exception as e:
        return {
            "success": False,
            "source": "xunfei",
            "face_detected": False,
            "error": str(e)
        }


try:
    XunfeiAPIClient.detect_face_and_expression = _detect_face_and_expression_observable
except Exception:
    pass
