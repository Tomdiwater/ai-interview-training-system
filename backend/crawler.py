import requests
from bs4 import BeautifulSoup
import json
import re

# 面试鸭网站URL
BASE_URL = "https://www.mianshiya.com"

# 类别映射
CATEGORY_MAP = {
    "前端": "前端开发",
    "后端": "后端开发",
    "产品": "产品经理",
    "UI": "UI设计"
}

# 爬取题目
def crawl_questions():
    """爬取面试鸭网站的题目"""
    questions = []
    
    # 前端面试题
    frontend_url = f"{BASE_URL}/?current=194&pageSize=20"
    frontend_questions = crawl_category(frontend_url, "前端开发")
    questions.extend(frontend_questions)
    
    # 后端面试题
    backend_url = f"{BASE_URL}/?current=1&pageSize=20"
    backend_questions = crawl_category(backend_url, "后端开发")
    questions.extend(backend_questions)
    
    # 产品经理面试题
    product_url = f"{BASE_URL}/?current=100&pageSize=20"
    product_questions = crawl_category(product_url, "产品经理")
    questions.extend(product_questions)
    
    # UI设计面试题
    ui_url = f"{BASE_URL}/?current=200&pageSize=20"
    ui_questions = crawl_category(ui_url, "UI设计")
    questions.extend(ui_questions)
    
    return questions

# 爬取特定类别的题目
def crawl_category(url, category):
    """爬取特定类别的题目"""
    questions = []
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 查找题目列表
        question_elements = soup.find_all('div', class_='question-item')
        
        for element in question_elements:
            # 提取题目内容
            question_text = element.find('h3').text.strip() if element.find('h3') else ""
            
            # 提取答案内容
            answer_element = element.find('div', class_='answer-content')
            answer_text = answer_element.text.strip() if answer_element else ""
            
            # 提取关键词（简单处理，使用题目中的高频词）
            keywords = extract_keywords(question_text)
            
            if question_text and answer_text:
                questions.append({
                    "job_category": category,
                    "question": question_text,
                    "answer": answer_text,
                    "keywords": ",".join(keywords)
                })
        
        print(f"成功爬取 {category} 类别 {len(questions)} 道题目")
    except Exception as e:
        print(f"爬取 {category} 类别失败: {str(e)}")
    
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
        "算法", "数据结构", "网络", "操作系统", "数据库",
        "产品经理", "用户体验", "需求分析", "原型设计",
        "UI设计", "色彩", "排版", "设计系统"
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
def save_questions(questions, filename="questions.json"):
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
    except Exception as e:
        print(f"导入失败: {str(e)}")

if __name__ == "__main__":
    print("开始爬取面试鸭题库...")
    questions = crawl_questions()
    print(f"共爬取 {len(questions)} 道题目")
    
    # 保存到文件
    save_questions(questions)
    
    # 导入到系统
    import_questions_to_system(questions)
