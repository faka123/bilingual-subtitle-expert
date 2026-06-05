"""Streamlit Cloud 入口文件

此文件位于仓库根目录，供 Streamlit Cloud 自动检测并启动应用。
实际主程序位于 subtitle_app/app.py

Streamlit Cloud 会执行: streamlit run streamlit_app.py
"""

import runpy
from pathlib import Path

# 运行 subtitle_app 中的主应用
runpy.run_path(str(Path(__file__).parent / "subtitle_app" / "app.py"))
