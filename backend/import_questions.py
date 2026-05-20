import json
import requests

# 读取JSON文件
def read_questions(filename="questions.json"):
    """读取题目数据"""
    with open(filename, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 检查数据格式
    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        return data.get('questions', [])
    else:
        return []

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
    print("开始导入题库...")
    questions = read_questions("questions_clean.json")
    print(f"共读取 {len(questions)} 道题目")
    
    # 导入到系统
    result = import_questions_to_system(questions)
    
    if result:
        print("导入成功！")
    else:
        print("导入失败，请检查系统状态。")
