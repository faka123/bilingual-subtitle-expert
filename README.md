# 双语字幕精确排版专家

将校对好的中英对照文档与带时间轴的中文 SRT 字幕智能匹配，生成专业双语字幕文件。

## 功能

- 📄 支持 .docx / .txt 校对文档 + .srt 时间轴文档
- 🔍 自动识别并过滤双语 SRT 中的英文条目
- 🎯 difflib 相似度匹配 + 中文虚词清洗
- ✂️ 英文智能断句（≤42 字符/行）
- 🤖 DeepSeek LLM 增强（可选）：语义断句 + 语义匹配
- 📊 质量检查：序号连续性、行长度、中英文数量一致性
- 🌐 REST API（FastAPI）

## 快速开始

### Web 界面
```bash
pip install streamlit python-docx
streamlit run subtitle_app/app.py
```

### API 服务
```bash
pip install fastapi uvicorn python-docx
uvicorn subtitle_app.api:app --port 8502
```

### API 调用
```bash
curl -X POST http://localhost:8502/api/bilingual-subtitle \
  -H "Content-Type: application/json" \
  -d '{
    "proofread": {"pairs": [{"chinese": "你好世界", "english": "Hello world"}]},
    "timeline": {"items": [{"index":1,"start":"00:00:01,000","end":"00:00:02,000","text":"你好"}]}
  }'
```

## 项目结构

```
subtitle_app/
├── app.py      # Streamlit Web 界面
├── api.py      # FastAPI REST API
├── core.py     # 核心匹配引擎
├── llm.py      # LLM 服务（DeepSeek）
└── __init__.py
```
