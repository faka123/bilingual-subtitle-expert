"""
LLM 服务模块 - 为双语字幕排版提供 AI 能力

支持多种 LLM 后端：
- Anthropic Claude（Anthropic 官方 SDK）
- DeepSeek（兼容 OpenAI SDK）

功能：
1. 英文智能断句：按语义自然拆分英文段落，消除 "..." 占位符
2. 语义匹配：用 LLM 做中英文语义级匹配，替代字符相似度算法
"""

import json
import re
import traceback
from typing import Optional

# ── SDK 可用性检测 ────────────────────────────────────────

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


def _check_openai_sdk():
    return HAS_OPENAI


# ── 提供商预设 ────────────────────────────────────────────

PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "sdk_available": lambda: True,  # DeepSeek 使用标准库 urllib，无需第三方 SDK
        "install_hint": "",
    },
}


# ── LLM 服务基类 ─────────────────────────────────────────

class LLMService:
    """
    LLM 服务统一接口。

    不同提供商只覆盖 _call_api() 方法，split_english_text 和
    match_subtitles 的提示词和 JSON 解析逻辑完全复用。
    """

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def _call_api(self, prompt: str, max_tokens: int) -> str:
        """调用 LLM API，返回文本响应。子类必须实现。"""
        raise NotImplementedError

    # ── 英文智能断句 ──────────────────────────────────────

    def split_english_text(self, en_text: str, num_parts: int) -> list[str]:
        """
        按语义自然断句，将英文段落分为指定数量的部分。

        与现有 _split_by_chars 不同，LLM 会：
        - 优先在句末标点处断句
        - 保持短语完整性
        - 彻底避免 "..." 占位符
        """
        if num_parts <= 1:
            return [en_text]

        prompt = f"""You are a professional bilingual subtitle editor. Split the following English text into exactly {num_parts} parts.

## Core Rules (from 《双语字幕精确排版专家 - 完整规则手册》):

1. **行数一致**: The number of English parts MUST equal {num_parts} exactly — one-to-one correspondence with Chinese segments
2. **自然断点**: Split at natural pause points — periods (.), semicolons (;), commas (,) — in that priority order
3. **不拆短语**: Never split a complete phrase, collocation, or semantic unit across two parts. For example, keep "the dreams and struggles" together
4. **内容完整**: Every word from the original English text must appear in exactly one part — nothing omitted, nothing repeated
5. **禁止占位**: Never output "..." or "[...]" or empty strings — every part must contain real, readable English text
6. **每行长度**: Keep each part under 42 characters when possible, but prioritize rule #3 (don't split phrases) over strict length limits
7. **禁止跨段**: All splits must stay within this single paragraph — do not reference or mix with other content

## English text to split:
{en_text}

Return ONLY a JSON object:
{{"parts": ["part 1 text", "part 2 text", ...]}}

The array must have exactly {num_parts} elements. Output JSON only, no other text."""

        try:
            result_text = self._call_api(prompt, max_tokens=1024)
            parts = self._extract_parts(result_text)

            if len(parts) == num_parts:
                return parts
            elif len(parts) > num_parts:
                merged = parts[:num_parts - 1]
                merged.append(" ".join(parts[num_parts - 1:]))
                return merged
            else:
                return parts + [""] * (num_parts - len(parts))

        except Exception as e:
            raise RuntimeError(f"LLM 英文断句失败: {e}") from e

    # ── 语义匹配 ──────────────────────────────────────────

    def match_subtitles(
        self,
        srt_texts: list[str],
        paragraph_texts: list[str],
    ) -> list[dict]:
        """
        用 LLM 做语义匹配，将 SRT 字幕条目匹配到对应的段落。

        相比字符相似度算法，LLM 能：
        - 理解中英文之间的语义对应关系
        - 处理措辞差异
        - 利用上下文信息做出更准确的匹配
        """
        srt_lines = "\n".join(
            f"[{i}] {text}" for i, text in enumerate(srt_texts)
        )
        para_lines = "\n".join(
            f"[P{i}] {text}" for i, text in enumerate(paragraph_texts)
        )

        prompt = f"""You are a professional bilingual subtitle alignment expert, following the 《双语字幕精确排版专家》rules.

## Core Matching Rules:
1. **语义匹配**: Match based on semantic meaning, not just character overlap — understand that different wording can express the same idea
2. **段落边界**: Adjacent SRT entries with similar content should typically map to the same paragraph
3. **口语化处理**: Ignore colloquial filler words (呢, 啊, 吧) when comparing — focus on core content
4. **强制匹配**: Every SRT entry MUST be matched to exactly one paragraph — choose the best match even if uncertain
5. **置信度**: Score 0.0-1.0 based on semantic similarity, not character-level overlap

SRT subtitle entries (with index):
{srt_lines}

Paragraphs from proofread document (with index):
{para_lines}

Return ONLY a JSON object:
{{"matches": [
  {{"srt_index": 0, "paragraph_index": 2, "confidence": 0.95}},
  ...
]}}

Rules:
- Every SRT entry gets exactly one match
- confidence: 0.0 (completely unrelated) to 1.0 (exact semantic match)
- Adjacent SRT entries often share the same paragraph index
- Base your matching on meaning, topic, and key concepts — not surface-level character comparison

Output JSON only, no other text."""

        try:
            result_text = self._call_api(prompt, max_tokens=4096)
            json_match = re.search(r'\{[\s\S]*\}', result_text)
            if json_match:
                data = json.loads(json_match.group())
                return data.get("matches", [])
            else:
                data = json.loads(result_text)
                return data.get("matches", [])

        except Exception as e:
            raise RuntimeError(f"LLM 字幕匹配失败: {e}")

    # ── 辅助方法 ──────────────────────────────────────────

    @staticmethod
    def _extract_parts(result_text: str) -> list[str]:
        """从 LLM 响应中提取 parts 数组"""
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if json_match:
            data = json.loads(json_match.group())
        else:
            data = json.loads(result_text)
        return data.get("parts", [])


# ── DeepSeek 实现 ────────────────────────────────────────

class DeepSeekService(LLMService):
    """通过 OpenAI 兼容接口调用 DeepSeek 模型"""

    BASE_URL = "https://api.deepseek.com/chat/completions"

    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        super().__init__(api_key, model)

        # 确保 API Key 是纯 ASCII，避免 HTTP 头编码错误
        self._clean_key = api_key.strip()
        if not self._clean_key.isascii():
            original = self._clean_key
            self._clean_key = self._clean_key.encode("ascii", errors="ignore").decode("ascii")
            if len(self._clean_key) < len(original) * 0.8:
                raise ValueError(
                    f"API Key 包含大量非 ASCII 字符，请检查是否粘贴错误。"
                    f"原始长度 {len(original)}，清理后 {len(self._clean_key)}"
                )

    def _call_api(self, prompt: str, max_tokens: int) -> str:
        """使用 urllib 直接调用 DeepSeek API，绕过 httpx 编码问题"""
        import urllib.request
        import urllib.error

        body = json.dumps({
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            self.BASE_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self._clean_key}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp_body = resp.read().decode("utf-8")
                data = json.loads(resp_body)
                content = data["choices"][0]["message"]["content"]
                if content is None:
                    raise RuntimeError("LLM 返回空内容")
                return content.strip()
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek API HTTP {e.code}: {err_body[:500]}")
        except Exception as e:
            tb = traceback.format_exc()
            raise RuntimeError(f"LLM API 调用失败: {e}\n{tb}")


# ── 工厂函数 ─────────────────────────────────────────────

def create_llm_service(
    provider: str,
    api_key: str,
    model: Optional[str] = None,
) -> Optional[LLMService]:
    """
    工厂函数：根据提供商创建对应的 LLM 服务实例。

    参数：
    - provider: 提供商 ID（"anthropic" 或 "deepseek"）
    - api_key: API Key（为空则返回 None）
    - model: 模型 ID（为 None 则使用该提供商的默认模型）

    返回：
    - LLMService 实例，或 None（当 api_key 为空或 SDK 未安装时）
    """
    if not api_key or not api_key.strip():
        return None

    provider_info = PROVIDERS.get(provider)
    if not provider_info:
        return None

    if not provider_info["sdk_available"]():
        return None

    if model is None:
        model = provider_info["default_model"]

    try:
        if provider == "deepseek":
            return DeepSeekService(api_key=api_key, model=model)
        else:
            return None
    except Exception:
        return None
