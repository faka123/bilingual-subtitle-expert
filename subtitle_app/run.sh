#!/bin/bash
cd "$(dirname "$0")"
VENV_PYTHON="../venv/bin/python"

echo "🎬 启动双语字幕精确排版专家..."
echo ""

# 安装缺失依赖
$VENV_PYTHON -c "import streamlit" 2>/dev/null || {
    echo "⏳ 正在安装依赖..."
    $VENV_PYTHON -m pip install streamlit python-docx openai anthropic -q
    echo "✅ 完成"
}

echo "✅ 正在打开浏览器..."
echo "   Python: $($VENV_PYTHON --version)"
echo "   按 Ctrl+C 停止"
echo ""

$VENV_PYTHON -m streamlit run app.py --server.headless true
