import requests
from bs4 import BeautifulSoup
import json
import re
import time

# 面试鸭网站URL
BASE_URL = "https://www.mianshiya.com"

# 类别映射
CATEGORY_MAP = {
    "前端": "前端开发",
    "后端": "后端开发",
    "产品": "产品经理",
    "UI": "UI设计",
    "Java": "后端开发",
    "Python": "后端开发",
    "Go": "后端开发",
    "C++": "后端开发",
    "计算机网络": "后端开发",
    "操作系统": "后端开发",
    "数据库": "后端开发",
    "算法": "后端开发",
    "数据结构": "后端开发"
}

# 获取所有分类链接
def get_category_links():
    """获取所有分类链接"""
    try:
        response = requests.get(BASE_URL)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 查找所有分类链接
        category_links = []
        # 查找所有a标签
        for a in soup.find_all('a'):
            href = a.get('href')
            text = a.text.strip()
            
            # 过滤出可能的分类链接
            if href and href.startswith('?current=') and 'pageSize=' in href:
                full_url = f"{BASE_URL}{href}"
                category_links.append((text, full_url))
        
        # 去重
        category_links = list(set(category_links))
        print(f"成功获取 {len(category_links)} 个分类链接")
        return category_links
    except Exception as e:
        print(f"获取分类链接失败: {str(e)}")
        return []

# 爬取单个页面的题目
def crawl_page(url, category):
    """爬取单个页面的题目"""
    questions = []
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 查找所有题目元素
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
                
                # 提取关键词
                keywords = extract_keywords(question_text)
                
                if question_text and answer_text:
                    questions.append({
                        "job_category": category,
                        "question": question_text,
                        "answer": answer_text,
                        "keywords": ",".join(keywords)
                    })
        
        print(f"成功爬取 {category} 分类 {len(questions)} 道题目")
    except Exception as e:
        print(f"爬取页面失败: {str(e)}")
    
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

# 爬取所有题目
def crawl_all_questions():
    """爬取所有题目"""
    questions = []
    
    # 获取所有分类链接
    category_links = get_category_links()
    
    # 如果没有获取到分类链接，使用默认链接
    if not category_links:
        # 默认分类链接
        default_categories = [
            ("前端开发", f"{BASE_URL}/?current=194&pageSize=20"),
            ("后端开发", f"{BASE_URL}/?current=1&pageSize=20"),
            ("产品经理", f"{BASE_URL}/?current=100&pageSize=20"),
            ("UI设计", f"{BASE_URL}/?current=200&pageSize=20")
        ]
        category_links = default_categories
    
    # 爬取每个分类
    for category_name, url in category_links:
        # 映射分类名称
        mapped_category = CATEGORY_MAP.get(category_name, "后端开发")
        
        # 爬取当前页面
        page_questions = crawl_page(url, mapped_category)
        questions.extend(page_questions)
        
        # 避免请求过快被封
        time.sleep(1)
    
    return questions

# 保存题目到文件
def save_questions(questions, filename="mianshiya_questions.json"):
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
    print("开始爬取面试鸭题库...")
    questions = crawl_all_questions()
    print(f"共爬取 {len(questions)} 道题目")
    
    # 保存到文件
    save_questions(questions)
    
    # 导入到系统
    import_questions_to_system(questions)
