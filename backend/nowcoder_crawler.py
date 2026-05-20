import requests
from bs4 import BeautifulSoup
import json
import re
import time

# 牛客网面试题页面URL
BASE_URL = "https://www.nowcoder.com/intelligentTest"

# 类别映射
CATEGORY_MAP = {
    "前端开发": "前端开发",
    "后端开发": "后端开发",
    "产品经理": "产品经理",
    "UI设计": "UI设计",
    "算法": "后端开发",
    "数据结构": "后端开发",
    "计算机网络": "后端开发",
    "操作系统": "后端开发",
    "数据库": "后端开发"
}

# 爬取牛客网面试题
def crawl_nowcoder_questions():
    """爬取牛客网面试题"""
    questions = []
    
    try:
        # 模拟浏览器请求
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        # 发送请求
        response = requests.get(BASE_URL, headers=headers)
        response.raise_for_status()
        
        print(f"成功获取页面，状态码: {response.status_code}")
        
        # 解析页面
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 查找题目元素
        # 这里需要根据实际页面结构调整选择器
        question_elements = soup.find_all('div', class_='question-item')
        
        if not question_elements:
            # 尝试其他可能的选择器
            question_elements = soup.find_all('div', class_='question')
        
        if not question_elements:
            # 尝试查找所有h3标签，可能是题目
            h3_elements = soup.find_all('h3')
            for h3 in h3_elements:
                question_text = h3.text.strip()
                # 查找答案
                answer_element = h3.find_next('div')
                answer_text = answer_element.text.strip() if answer_element else ""
                
                if question_text and answer_text:
                    # 简单分类
                    category = "后端开发"
                    if "前端" in question_text or "JS" in question_text or "React" in question_text or "Vue" in question_text:
                        category = "前端开发"
                    elif "产品" in question_text:
                        category = "产品经理"
                    elif "UI" in question_text or "设计" in question_text:
                        category = "UI设计"
                    
                    keywords = extract_keywords(question_text)
                    questions.append({
                        "job_category": category,
                        "question": question_text,
                        "answer": answer_text,
                        "keywords": ",".join(keywords)
                    })
        else:
            for element in question_elements:
                # 提取题目内容
                question_text = element.find('h3').text.strip() if element.find('h3') else ""
                
                # 提取答案内容
                answer_element = element.find('div', class_='answer-content')
                if not answer_element:
                    answer_element = element.find('div', class_='answer')
                answer_text = answer_element.text.strip() if answer_element else ""
                
                # 简单分类
                category = "后端开发"
                if "前端" in question_text or "JS" in question_text or "React" in question_text or "Vue" in question_text:
                    category = "前端开发"
                elif "产品" in question_text:
                    category = "产品经理"
                elif "UI" in question_text or "设计" in question_text:
                    category = "UI设计"
                
                # 提取关键词
                keywords = extract_keywords(question_text)
                
                if question_text and answer_text:
                    questions.append({
                        "job_category": category,
                        "question": question_text,
                        "answer": answer_text,
                        "keywords": ",".join(keywords)
                    })
        
        print(f"成功爬取 {len(questions)} 道题目")
    except Exception as e:
        print(f"爬取失败: {str(e)}")
    
    return questions

# 提取关键词
def extract_keywords(text):
    """从题目中提取关键词"""
    # 简单的关键词提取逻辑
    # 移除标点符号
    text = re.sub(r'[\s\.,，。！？!?:;；]', ' ', text)
    
    # 常见技术关键词
    tech_keywords = [
        "JavaScript", "React", "Vue", "CSS", "HTML", "Node.js",
        "Java", "Spring", "MySQL", "Redis", "Python", "Django",
        "Go", "C++", "算法", "数据结构", "网络", "操作系统",
        "数据库", "产品经理", "用户体验", "需求分析", "原型设计",
        "UI设计", "色彩", "排版", "设计系统", "前端", "后端"
    ]
    
    keywords = []
    for keyword in tech_keywords:
        if keyword in text:
            keywords.append(keyword)
    
    # 如果没有提取到关键词，返回默认关键词
    if not keywords:
        keywords = ["面试", "技术"]
    
    return keywords[:5]  # 最多返回5个关键词

# 保存题目到文件
def save_questions(questions, filename="nowcoder_questions.json"):
    """保存题目到JSON文件"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
    print(f"成功保存 {len(questions)} 道题目到 {filename}")

# 导入题目到系统
def import_questions_to_system(questions):
    """通过API导入题目到系统"""
    import_url = "http://127.0.0.1:12345/api/questions/import"
    
    try:
        response = requests.post(
            import_url,
            json={"questions": questions},
            headers={"Content-Type": "application/json"}
        )
        
        response.raise_for_status()
        result = response.json()
        print(f"导入结果: {result}")
        return result
    except Exception as e:
        print(f"导入失败: {str(e)}")
        return None

if __name__ == "__main__":
    print("开始爬取牛客网面试题...")
    questions = crawl_nowcoder_questions()
    print(f"共爬取 {len(questions)} 道题目")
    
    # 保存到文件
    save_questions(questions)
    
    # 导入到系统
    import_questions_to_system(questions)
