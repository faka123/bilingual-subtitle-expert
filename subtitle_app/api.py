"""
双语字幕排版 API

按《双语字幕排版规则确认》文档规范实现的 REST API。

POST /api/bilingual-subtitle
"""

from fastapi import FastAPI
from pydantic import BaseModel, Field

try:
    from .core import ProofreadPair, TimelineItem, process_bilingual_api, BilingualSubtitle
except ImportError:
    from core import ProofreadPair, TimelineItem, process_bilingual_api, BilingualSubtitle

# ── FastAPI 应用 ────────────────────────────────────────────

app = FastAPI(
    title="双语字幕精确排版专家",
    description="将校对好的中英对照文档与带时间轴的中文 SRT 字幕智能匹配，生成专业双语字幕文件",
    version="1.0.0",
)


# ── Pydantic 请求/响应模型 ──────────────────────────────────

class ProofreadPairModel(BaseModel):
    """校对文档中的一对中英对译"""
    chinese: str = Field(..., description="中文段落")
    english: str = Field(..., description="英文段落")


class ProofreadDocModel(BaseModel):
    """校对文档"""
    pairs: list[ProofreadPairModel] = Field(..., description="中英对译列表")


class TimelineItemModel(BaseModel):
    """时间轴中的一个条目"""
    index: int = Field(..., description="序号")
    start: str = Field(..., description="开始时间 HH:MM:SS,mmm")
    end: str = Field(..., description="结束时间 HH:MM:SS,mmm")
    text: str = Field(..., description="字幕文本（无标点中文）")


class TimelineDocModel(BaseModel):
    """时间轴文档"""
    items: list[TimelineItemModel] = Field(..., description="字幕条目列表")


class BilingualSubtitleRequest(BaseModel):
    """API 请求体"""
    proofread: ProofreadDocModel = Field(..., description="校对文档")
    timeline: TimelineDocModel = Field(..., description="时间轴文档")


class SubtitleItemResponse(BaseModel):
    """输出字幕条目"""
    index: int
    start: str
    end: str
    text: str


class BilingualSubtitleResponse(BaseModel):
    """API 响应体"""
    chinesePart: list[SubtitleItemResponse]
    englishPart: list[SubtitleItemResponse]


# ── API 端点 ────────────────────────────────────────────────

@app.get("/")
def root():
    """健康检查"""
    return {"service": "双语字幕精确排版专家", "version": "1.0.0"}


@app.post("/api/bilingual-subtitle", response_model=BilingualSubtitleResponse)
def bilingual_subtitle(request: BilingualSubtitleRequest):
    """
    将校对文档与时间轴文档合并为双语字幕。

    按《双语字幕排版规则确认》文档中的规范：
    1. 用 difflib 相似度将中文片段匹配到校对段落（强制匹配所有条目）
    2. 按自然断点将英文段落分割为对应份数
    3. 生成中英文双部分输出，英文部分从中文长度+1开始编号
    """
    # 转换为内部数据结构
    pairs = [
        ProofreadPair(chinese=p.chinese, english=p.english)
        for p in request.proofread.pairs
    ]
    items = [
        TimelineItem(index=t.index, start=t.start, end=t.end, text=t.text)
        for t in request.timeline.items
    ]

    # 调用核心处理逻辑
    result: BilingualSubtitle = process_bilingual_api(pairs, items)

    # 转换为响应格式
    return BilingualSubtitleResponse(
        chinesePart=[
            SubtitleItemResponse(
                index=e.index,
                start=e.start,
                end=e.end,
                text=e.text,
            )
            for e in result.chinese_part
        ],
        englishPart=[
            SubtitleItemResponse(
                index=e.index,
                start=e.start,
                end=e.end,
                text=e.text,
            )
            for e in result.english_part
        ],
    )
