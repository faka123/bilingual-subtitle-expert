# 双语字幕精确排版专家

将校对好的中英对照文档与中文字幕时间轴匹配，输出先中文、后英文的 SRT。
详细维护依据见 [双语字幕排版规则](docs/双语字幕排版规则.md)。

## 处理规则

- 中文序号、时间轴和文本默认原样保留，包括重复、空文本和时间轴异常；问题在质量检查中提示。
- 旧英文字幕不参与输出，英文只来自校对文档。中英文条目一一对应，英文按中文输入顺序输出。
- 英文从中文最大序号 + 1 开始编号。中文原始编号异常时优先保留原文，并报告问题；可主动开启重新编号。
- 相似度低于阈值或中文为空时不强行匹配，英文留空并提示；未使用的校对段落也会提示。
- 英文按自然停顿和中文长度比例断句，以完整内容为优先，42 字符为建议长度。英文词数不足时留空，不复制末尾单词凑条数。
- 默认保留英文标点，可选择只去掉每条英文末尾的句号、逗号、问号和感叹号。
- DOCX 按正文及表格顺序读取，忽略删除修订、保留插入修订；清理 `{.mark}`、文本修订外壳及引号转义。
- 支持 UTF-8、带 BOM 的 UTF-8/UTF-16、GB18030 文本。TXT 时间轴内容必须采用 SRT 结构。
- DeepSeek 匹配与断句分别启用。AI 断句遗漏、增加或调换原文时回退到规则断句；调用失败会提示。

语言识别和相似度仍是启发式处理，匹配结果需要结合具体视频核对，尤其是只有数字、屏蔽字或中英混排的条目。

## 本地启动

```sh
bash subtitle_app/run.sh
```

脚本自动创建仓库根目录的 `.venv`，按 `requirements.txt` 安装缺失依赖，并启动根目录入口。
默认打开 http://localhost:8501 。指定端口：

```sh
bash subtitle_app/run.sh --server.port=8503
```

手动安装和运行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run streamlit_app.py
```

页面清空按钮清除输入、上传文件和输出；修改输入会清除旧结果，需重新处理。

## API

```sh
.venv/bin/python -m uvicorn subtitle_app.api:app --port 8502
```

```sh
curl -X POST http://localhost:8502/api/bilingual-subtitle \
  -H 'Content-Type: application/json' \
  -d '{"proofread":{"pairs":[{"chinese":"你好世界","english":"Hello world"}]},"timeline":{"items":[{"index":1,"start":"00:00:01,000","end":"00:00:02,000","text":"你好世界"}]}}'
```

空校对列表或空时间轴返回 HTTP 422。时间轴条目按调用者输入保留，英文从最大中文序号 + 1 开始。

## Render

已有配置 `render.yaml`：构建 `pip install -r requirements.txt`，启动 `python -m streamlit run streamlit_app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true`，健康检查路径为 `/_stcore/health`。
如需登录密码，使用 Render 环境变量 `APP_PASSWORD`。不要提交密码、API Key 或本机虚拟环境。

## 验证

```sh
.venv/bin/python -m unittest discover -s tests -v
```

覆盖 BOM/编码、重复序号、空字幕、异常时间、英文顺序、旧英文过滤、未匹配、文本完整性、Word 读取、清空按钮及 API。
