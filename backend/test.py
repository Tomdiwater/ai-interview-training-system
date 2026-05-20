print("Python 环境正常")
import sys
print(f"Python 版本: {sys.version}")

try:
    from flask import Flask
    print("Flask 模块已安装")
except ImportError:
    print("Flask 模块未安装")
