"""
双语字幕精确排版专家 - 核心匹配引擎

将校对好的中英对照文档与带时间轴的中文 SRT 字幕匹配，
生成符合专业标准的双语字幕文件。

支持 LLM 增强模式：
- 英文智能断句：语义级拆分，消除 "..." 占位符
- 语义匹配：用 AI 替代字符相似度算法
"""

import re
import difflib
from dataclasses import dataclass, field
from typing import Optional


# ── 数据结构（按双语字幕排版规则文档定义）────────────────────

@dataclass
class TimelineItem:
    """时间轴文档条目（对应文档 TimelineDoc.items）"""
    index: int
    start: str               # "HH:MM:SS,mmm"
    end: str
    text: str                # 字幕文本

    @property
    def start_time(self) -> str:
        """兼容旧属性名"""
        return self.start

    @start_time.setter
    def start_time(self, value: str):
        self.start = value

    @property
    def end_time(self) -> str:
        """兼容旧属性名"""
        return self.end

    @end_time.setter
    def end_time(self, value: str):
        self.end = value


@dataclass
class ProofreadPair:
    """校对文档中的中英对译（对应文档 ProofreadDoc.pairs）"""
    chinese: str
    english: str
    index: int = 0  # 在校对文档中的序号

    @property
    def zh(self) -> str:
        """兼容旧属性名"""
        return self.chinese

    @zh.setter
    def zh(self, value: str):
        self.chinese = value

    @property
    def en(self) -> str:
        """兼容旧属性名"""
        return self.english

    @en.setter
    def en(self, value: str):
        self.english = value

    # index 属性由 parse_proofread_doc 动态设置


@dataclass
class MatchResult:
    """匹配结果（内部中间结构）"""
    paragraph: ProofreadPair
    segments: list[TimelineItem]  # 属于该段落的中文 SRT 条目
    similarity: float             # 匹配相似度
    en_segments: list[str] = field(default_factory=list)  # 分割后的英文


@dataclass
class BilingualSubtitle:
    """双语字幕输出（对应文档 BilingualSubtitle）"""
    chinese_part: list[TimelineItem]
    english_part: list[TimelineItem]


# ── 向后兼容别名 ────────────────────────────────────────────

SrtEntry = TimelineItem          # 旧名
BilingualParagraph = ProofreadPair  # 旧名


# ── 文档解析 ──────────────────────────────────────────────

def parse_docx(file_path_or_bytes) -> str:
    """
    从 .docx 文件中提取文本，转换为校对文档格式。

    支持传入文件路径（str）或文件字节数据（bytes）。
    自动识别空段落作为双语对之间的分隔符。

    返回格式：
        中文段落1
        英文段落1

        中文段落2
        英文段落2
    """
    from docx import Document
    from io import BytesIO

    if isinstance(file_path_or_bytes, bytes):
        doc = Document(BytesIO(file_path_or_bytes))
    else:
        doc = Document(file_path_or_bytes)

    # 提取所有段落的文本，记录哪些是空段落
    para_texts = []
    for para in doc.paragraphs:
        text = para.text.strip()
        para_texts.append(text)

    # 也读取表格中的文本（中英对照文档常用表格排版）
    for table in doc.tables:
        for row in table.rows:
            row_texts = []
            for cell in row.cells:
                cell_text = cell.text.strip()
                if cell_text:
                    row_texts.append(cell_text)
            # 表格的每一行作为一个"段落"，多列用换行连接
            if row_texts:
                para_texts.append("\n".join(row_texts))
            else:
                para_texts.append("")  # 空行作为分隔

    # 构建输出：连续的非空段落合并为块，空段落作为块分隔符
    # 如果连续空段落过多则压缩为一个分隔
    lines = []
    prev_empty = False

    for text in para_texts:
        if text:
            lines.append(text)
            prev_empty = False
        else:
            if not prev_empty and lines:
                # 前一个非空，插入分隔空行
                lines.append("")
            prev_empty = True

    # 去掉末尾多余空行
    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def parse_proofread_doc(text: str) -> list[BilingualParagraph]:
    """
    解析校对文档，提取中英对译段落。

    输入格式（按空行分隔每个中英对）:
        中文段落1
        英文段落1

        中文段落2
        英文段落2

    也支持 docx 导出的连续格式（无空行分隔），自动按中/英交替检测。

    返回 BilingualParagraph 列表。
    """
    # 按空行分割段落块
    blocks = re.split(r'\n\s*\n', text.strip())

    paragraphs = []
    pair_index = 0

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # 提取块内的非空行
        block_lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(block_lines) < 2:
            continue

        # ── 在块内按中/英交替配对 ──
        i = 0
        while i < len(block_lines) - 1:
            zh_line = block_lines[i]
            en_line = block_lines[i + 1]

            zh_ratio = _chinese_char_ratio(zh_line)
            en_ratio = _english_char_ratio(en_line)

            if zh_ratio > 0.3 and en_ratio > 0.3:
                paragraphs.append(BilingualParagraph(
                    chinese=zh_line,
                    english=en_line,
                    index=pair_index,
                ))
                pair_index += 1
                i += 2
            else:
                # 不是标准的中-英对，尝试跳过当前行
                i += 1

        # 如果块内有落单行（奇数行），记录警告
        if i == len(block_lines) - 1:
            leftover = block_lines[i]
            # 仅在 leftover 看起来像有效文本时警告（非纯数字/符号）
            if len(leftover) > 3 and (_chinese_char_ratio(leftover) > 0.3 or _english_char_ratio(leftover) > 0.3):
                import logging
                logging.warning(f"校对文档解析：块内存在落单行（已丢弃）: {leftover[:80]}...")

    return paragraphs


def parse_srt(text: str) -> list[SrtEntry]:
    """
    解析 SRT 字幕文件。

    输入标准 SRT 格式:
        1
        00:00:00,200 --> 00:00:02,200
        字幕文本

    返回 SrtEntry 列表。
    """
    # 规范化换行符
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # 按空行分割
    blocks = re.split(r'\n\s*\n', text.strip())

    entries = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.split('\n')
        if len(lines) < 3:
            continue

        # 第一行：序号
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue

        # 第二行：时间轴
        time_match = re.match(
            r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})',
            lines[1].strip()
        )
        if not time_match:
            continue

        start_time = time_match.group(1)
        end_time = time_match.group(2)

        # 剩余行：字幕文本
        text_content = '\n'.join(lines[2:]).strip()

        entries.append(SrtEntry(
            index=index,
            start=start_time,
            end=end_time,
            text=text_content
        ))

    return entries


# ── 文本相似度 ────────────────────────────────────────────

def text_similarity(a: str, b: str) -> float:
    """
    计算两段文本的相似度 (0.0 ~ 1.0)。

    使用 difflib.SequenceMatcher 做字符级比较，
    同时对中文做特殊处理：忽略口语化虚词。
    """
    # 清理文本
    a_clean = _normalize_for_matching(a)
    b_clean = _normalize_for_matching(b)

    if not a_clean or not b_clean:
        return 0.0

    return difflib.SequenceMatcher(None, a_clean, b_clean).ratio()


# ── 中文口语虚词（匹配前过滤，提高相似度精度）─────────────

_FILLER_WORDS = set('呢啊吧嘛哦呀哇啦的了么吗喔哟咧呐')

def _normalize_for_matching(text: str) -> str:
    """清理文本用于匹配比较：去标点→去虚词→小写"""
    # 移除中文标点符号（含全角引号）
    text = re.sub(r'[，。！？、“”‘’“”（）《》【】\s]', '', text)
    # 移除英文标点
    text = re.sub(r'[,\.!\?;:\'"()\[\]\s]', '', text)
    # 移除中文口语虚词
    text = ''.join(c for c in text if c not in _FILLER_WORDS)
    return text.lower()


def _chinese_char_ratio(text: str) -> float:
    """计算中文字符占比"""
    if not text:
        return 0.0
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    total_chars = len(re.sub(r'\s', '', text))
    if total_chars == 0:
        return 0.0
    return chinese_chars / total_chars


def _english_char_ratio(text: str) -> float:
    """计算英文字符占比"""
    if not text:
        return 0.0
    english_chars = len(re.findall(r'[a-zA-Z]', text))
    total_chars = len(re.sub(r'\s', '', text))
    if total_chars == 0:
        return 0.0
    return english_chars / total_chars


# ── 段落匹配 ──────────────────────────────────────────────

def match_segments_to_paragraphs(
    srt_entries: list[SrtEntry],
    paragraphs: list[BilingualParagraph],
    threshold: float = 0.3
) -> list[MatchResult]:
    """
    将 SRT 字幕条目匹配到对应的双语段落。

    核心原则：**绝不丢弃任何条目**。每个 SRT 条目都会匹配到最佳段落，
    即使相似度低于阈值也会强制匹配。阈值仅影响统计报告中的"低置信度"计数，
    不影响实际匹配行为。
    """
    if not paragraphs:
        return []

    if not srt_entries:
        return []

    # ── 第一步：为每个 SRT 条目找到最匹配的段落（始终匹配，不用阈值过滤）──
    entry_para_map: dict[int, int] = {}       # entry_index -> paragraph_index
    entry_score_map: dict[int, float] = {}   # entry_index -> best_score

    for entry in srt_entries:
        best_idx = 0
        best_score = 0.0

        for pi, para in enumerate(paragraphs):
            score = text_similarity(entry.text, para.zh)
            if score > best_score:
                best_score = score
                best_idx = pi

        # 始终匹配到最佳段落（即使得分为 0）
        entry_para_map[entry.index] = best_idx
        entry_score_map[entry.index] = best_score

    # ── 第二步：按段落分组，保持 SRT 原始顺序 ──
    # 使用 dict 保持插入顺序（Python 3.7+）
    para_groups: dict[int, list[SrtEntry]] = {}
    para_group_order: list[int] = []

    for entry in srt_entries:
        pi = entry_para_map[entry.index]
        if pi not in para_groups:
            para_groups[pi] = []
            para_group_order.append(pi)
        para_groups[pi].append(entry)

    # ── 第三步：构建 MatchResult ──
    results = []
    for pi in para_group_order:
        group = para_groups[pi]
        # 计算组内平均相似度
        avg_sim = sum(
            entry_score_map.get(e.index, 0.0) for e in group
        ) / len(group)

        results.append(MatchResult(
            paragraph=paragraphs[pi],
            segments=sorted(group, key=lambda e: e.index),
            similarity=avg_sim
        ))

    return results


# ── 英文断句 ──────────────────────────────────────────────

def split_english_text(en_text: str, num_parts: int) -> list[str]:
    """
    将英文段落分割为指定数量的部分，尽量在自然断点处分割。

    策略：
    1. 如果 num_parts == 1，检查长度，超过 42 字符自动拆分
    2. 找到所有可能的断点位置（标点符号后）
    3. 按大致均匀长度选择 num_parts-1 个断点
    4. 确保不拆分完整短语
    5. 最终检查每个片段长度，超过 42 字符的进一步拆分
    """
    if num_parts <= 1:
        if len(en_text) <= 42:
            return [en_text]
        else:
            # 单个片段过长，尝试自然断点拆分
            parts = _split_long_segment(en_text)
            return parts if parts else [en_text]

    # 找到所有自然断点位置
    break_points = _find_natural_breaks(en_text)

    if len(break_points) < num_parts - 1:
        # 自然断点不够，用字符数均分
        parts = _split_by_chars(en_text, num_parts)
    else:
        # 目标每部分长度
        total_len = len(en_text)
        target_len = total_len / num_parts

        # 选择最接近目标长度的 num_parts-1 个断点
        selected = _select_breakpoints(break_points, num_parts - 1, total_len)

        # 按选定断点分割
        parts = []
        start = 0
        for bp in selected:
            part = en_text[start:bp].strip()
            parts.append(part)
            start = bp
        # 最后一部分
        last_part = en_text[start:].strip()
        parts.append(last_part)

    # 最终检查：将过长片段进一步在逗号处拆分
    final_parts = []
    for part in parts:
        if len(part) > 42:
            sub_parts = _split_long_segment(part)
            final_parts.extend(sub_parts)
        else:
            final_parts.append(part)

    return final_parts


def _split_long_segment(text: str) -> list[str]:
    """
    将超过42字符的英文片段在逗号处分拆为多段，保持每段≤42字符。
    优先在逗号后拆分，其次在 and/but/or 等连词前拆分。
    """
    MAX_LEN = 42
    parts = []
    remaining = text.strip()

    while len(remaining) > MAX_LEN:
        # 1) 在前42字符内找最后一个逗号+空格
        best = -1
        window = remaining[:MAX_LEN + 1]
        for m in re.finditer(r',\s+', window):
            if m.end() <= MAX_LEN:
                best = m.end()

        # 2) 没逗号，找连词边界
        if best <= 0:
            for m in re.finditer(r'\s+(and|but|or|that|which|who|while|when|where)\s+', window):
                if m.start() <= MAX_LEN:
                    best = m.start()

        # 3) 还是没有，在最后一个空格处拆分
        if best <= 0:
            last_space = window.rfind(' ')
            if last_space > 0:
                best = last_space + 1
            else:
                # 实在没法拆，强行截断
                best = MAX_LEN

        parts.append(remaining[:best].strip())
        remaining = remaining[best:].strip()

    if remaining:
        parts.append(remaining)
    return parts if parts else [text]


def _find_natural_breaks(text: str) -> list[tuple[int, int]]:
    """
    找到英文文本中的自然断点位置（标点符号后的空格）。

    返回 (位置, 优先级) 列表，优先级 1=句末标点（优先），2=逗号（次选）。
    """
    break_pattern = re.compile(r'[.!?;]\s+')
    priority_breaks = [(m.end(), 1) for m in break_pattern.finditer(text)]

    comma_pattern = re.compile(r',\s+')
    comma_breaks = [(m.end(), 2) for m in comma_pattern.finditer(text)]

    all_breaks = priority_breaks + comma_breaks
    all_breaks.sort(key=lambda x: x[0])

    return all_breaks


def _select_breakpoints(
    breaks: list[tuple[int, int]],
    num_needed: int,
    total_len: int
) -> list[int]:
    """
    从可选断点中选择 num_needed 个，优先选择高优先级（句末标点）的断点，
    同时使分割后各部分长度尽量均匀。

    breaks: [(位置, 优先级), ...]，优先级 1 最高。
    """
    target_len = total_len / (num_needed + 1)

    selected = []
    available = list(breaks)

    for i in range(num_needed):
        ideal_pos = target_len * (i + 1)

        # 在理想位置附近寻找最佳断点（综合考虑距离和优先级）
        best_bp = None
        best_score = float('inf')

        for bp_pos, bp_priority in available:
            dist = abs(bp_pos - ideal_pos)
            # 综合评分：距离权重 0.7 + 优先级权重 0.3
            # 优先选择靠近理想位置的高优先级断点
            score = dist * 0.7 + (bp_priority - 1) * total_len * 0.15

            if score < best_score:
                best_score = score
                best_bp = bp_pos

        if best_bp is not None:
            selected.append(best_bp)
            # 移除已选断点及其附近断点（避免选择过于接近的断点）
            available = [
                (p, pr) for p, pr in available
                if abs(p - best_bp) > 5  # 至少间隔 5 个字符
            ]

    selected.sort()
    return selected


def _split_by_chars(text: str, num_parts: int) -> list[str]:
    """按单词尽量均匀分割英文文本。当分段数超过单词数时，剩余段返回空字符串标记。"""
    words = text.split()
    total_words = len(words)

    if total_words == 0:
        return ["[EMPTY]"] + ["[...]"] * (num_parts - 1)

    # 当分段数超过单词数时，每个单词最多一段，剩余段落复用最后一个单词
    # （避免产生 "..." 占位符，确保每条字幕都有实际内容）
    if num_parts > total_words:
        parts = words[:]  # 每个单词一段
        # 剩余段落填入最后一个单词（比 "..." 占位符更好）
        parts.extend([words[-1]] * (num_parts - total_words))
        return parts

    # 按单词数尽量均匀分配到各部分
    parts = []
    idx = 0
    for i in range(num_parts):
        remaining = num_parts - i
        take = max(1, (total_words - idx) // remaining)
        end = min(idx + take, total_words)
        parts.append(" ".join(words[idx:end]))
        idx = end

    # 处理可能因四舍五入残留的单词（合并到最后一部分）
    if idx < total_words and parts:
        parts[-1] = parts[-1] + " " + " ".join(words[idx:])

    return parts


# ── LLM 增强：英文智能断句 ────────────────────────────────

def split_english_text_llm(
    en_text: str,
    num_parts: int,
    llm_service,
    errors=None,
) -> list[str]:
    """
    用 LLM 按语义自然断句，失败时回退到规则方法。

    当 LLM 调用失败或结果无效时，自动回退到现有的 split_english_text，
    并将错误信息记录到 errors 列表中。
    """
    if num_parts <= 1:
        return [en_text]

    try:
        parts = llm_service.split_english_text(en_text, num_parts)
        # 验证结果：不能有空字符串或 "..."
        if all(p and p.strip() and p.strip() != "..." for p in parts):
            return parts
        else:
            if errors is not None:
                errors.append(f"LLM 返回了空内容或 '...' 占位符: {parts}")
    except Exception as e:
        if errors is not None:
            errors.append(f"API 调用失败: {str(e)[:200]}")

    # 回退到规则方法
    return split_english_text(en_text, num_parts)


# ── SRT 生成 ──────────────────────────────────────────────

def generate_bilingual_srt(
    results: list[MatchResult],
    original_srt: list[SrtEntry],
    renumber: bool = True,
    llm_service=None,
) -> tuple[str, dict]:
    """
    生成双语 SRT 输出。

    返回 (output_text, llm_stats)，其中 llm_stats 包含 LLM 使用情况。
    """
    output_lines = []
    llm_split_count = 0
    rule_split_count = 0
    llm_errors = []

    # ── 第一步：为每个 MatchResult 生成英文断句 ──
    for mr in results:
        n = len(mr.segments)
        if n == 0:
            continue
        if llm_service:
            llm_parts = split_english_text_llm(mr.paragraph.en, n, llm_service, errors=llm_errors)
            rule_parts = split_english_text(mr.paragraph.en, n)
            # 判断 LLM 是否真正产生了不同的结果
            if llm_parts != rule_parts:
                llm_split_count += 1
                mr.en_segments = llm_parts
            else:
                rule_split_count += 1
                mr.en_segments = rule_parts
        else:
            rule_split_count += 1
            mr.en_segments = split_english_text(mr.paragraph.en, n)

    # ── 第二步：输出中文部分 ──
    if renumber:
        cn_index = 1
        for entry in original_srt:
            output_lines.append(str(cn_index))
            output_lines.append(f"{entry.start_time} --> {entry.end_time}")
            output_lines.append(entry.text)
            output_lines.append("")
            cn_index += 1
    else:
        for entry in original_srt:
            output_lines.append(str(entry.index))
            output_lines.append(f"{entry.start_time} --> {entry.end_time}")
            output_lines.append(entry.text)
            output_lines.append("")

    # ── 第三步：输出英文部分 ──
    if original_srt:
        max_cn_index = len(original_srt) if renumber else max(e.index for e in original_srt)
    else:
        max_cn_index = 0

    english_index = max_cn_index + 1

    for mr in sorted(results, key=lambda r: r.segments[0].index if r.segments else float('inf')):
        for i, seg in enumerate(mr.segments):
            if i < len(mr.en_segments):
                en_text = mr.en_segments[i]
            else:
                en_text = "[MISSING]"

            output_lines.append(str(english_index))
            output_lines.append(f"{seg.start_time} --> {seg.end_time}")
            output_lines.append(en_text)
            output_lines.append("")

            english_index += 1

    llm_stats = {
        "llm_enabled": llm_service is not None,
        "llm_split_count": llm_split_count,
        "rule_split_count": rule_split_count,
        "llm_errors": llm_errors,
    }
    return "\n".join(output_lines), llm_stats


# ── 完整处理管道 ─────────────────────────────────────────

def process_subtitles(
    proofread_text: str,
    srt_text: str,
    similarity_threshold: float = 0.3,
    renumber: bool = True,
    llm_service=None,
    use_llm_match: bool = False,
) -> tuple[str, dict]:
    """
    完整的字幕处理流程。

    参数：
    - proofread_text: 校对文档文本
    - srt_text: SRT 时间轴文档文本
    - similarity_threshold: 相似度匹配阈值（0.0～1.0，默认 0.3）
    - renumber: 是否重新编排序号为连续数字（推荐 True）
    - llm_service: LLM 服务实例（可选），启用 AI 增强功能
    - use_llm_match: 是否用 LLM 做语义匹配（需要 llm_service）

    返回：
    - output_srt: 生成的双语 SRT 文本
    - stats: 处理统计信息
    """
    # 1. 解析
    paragraphs = parse_proofread_doc(proofread_text)
    all_srt_entries = parse_srt(srt_text)

    # 2. 过滤：只保留中文 SRT 条目用于匹配（自动识别已包含英文的双语 SRT）
    cn_srt_entries = [e for e in all_srt_entries if _chinese_char_ratio(e.text) > 0.3]
    en_srt_entries = [e for e in all_srt_entries if _chinese_char_ratio(e.text) <= 0.3]

    # 用中文条目做匹配，用全部条目做原始参考
    srt_entries = cn_srt_entries if cn_srt_entries else all_srt_entries

    # 3. 匹配（可选 LLM 语义匹配）
    if use_llm_match and llm_service and paragraphs:
        try:
            srt_texts = [e.text for e in srt_entries]
            para_texts = [p.zh for p in paragraphs]
            llm_matches = llm_service.match_subtitles(srt_texts, para_texts)
            results = _build_match_results_from_llm(
                srt_entries, paragraphs, llm_matches, similarity_threshold
            )
        except Exception:
            # LLM 匹配失败，回退到规则匹配
            results = match_segments_to_paragraphs(
                srt_entries, paragraphs, similarity_threshold
            )
    else:
        results = match_segments_to_paragraphs(
            srt_entries, paragraphs, similarity_threshold
        )

    # 3. 生成输出（只传入中文 SRT 条目作为原始参考，避免重复已存在的英文）
    output, llm_stats = generate_bilingual_srt(
        results, srt_entries, renumber=renumber, llm_service=llm_service
    )

    # 4. 统计
    matched_count = sum(len(r.segments) for r in results)

    # 低置信度匹配：相似度低于阈值的组
    low_confidence_count = sum(
        1 for r in results if r.similarity < similarity_threshold
    )
    low_confidence_entries = sum(
        len(r.segments) for r in results if r.similarity < similarity_threshold
    )

    # 检测是否为双语 SRT
    bilingual_srt_detected = len(en_srt_entries) > 0

    stats = {
        "paragraphs": len(paragraphs),
        "srt_entries": len(srt_entries),
        "srt_total_entries": len(all_srt_entries),
        "srt_en_entries_filtered": len(en_srt_entries),
        "bilingual_srt_detected": bilingual_srt_detected,
        "matched_groups": len(results),
        "matched_entries": matched_count,
        "low_confidence_groups": low_confidence_count,
        "low_confidence_entries": low_confidence_entries,
        "unmatched_entries": 0,  # 始终为 0，因为强制匹配所有条目
        **llm_stats,
    }

    return output, stats


def _build_match_results_from_llm(
    srt_entries: list[SrtEntry],
    paragraphs: list[BilingualParagraph],
    llm_matches: list[dict],
    threshold: float,
) -> list[MatchResult]:
    """
    将 LLM 匹配结果转换为 MatchResult 列表。

    LLM 返回 [{srt_index, paragraph_index, confidence}, ...]，
    此函数将其整理为按段落分组的 MatchResult。
    """
    # 按段落索引分组
    para_groups: dict[int, list[SrtEntry]] = {}
    entry_confidence: dict[int, float] = {}

    for match in llm_matches:
        srt_idx = match.get("srt_index", 0)
        para_idx = match.get("paragraph_index", 0)
        confidence = match.get("confidence", 0.5)

        if para_idx not in para_groups:
            para_groups[para_idx] = []
        if srt_idx < len(srt_entries):
            para_groups[para_idx].append(srt_entries[srt_idx])
            entry_confidence[srt_idx] = confidence

    # 确保每个 SRT 条目都有归属（LLM 可能遗漏）
    matched_indices = set()
    for group in para_groups.values():
        for e in group:
            matched_indices.add(e.index)

    for entry in srt_entries:
        if entry.index not in matched_indices:
            # 未匹配条目归到第一个段落（兜底）
            if 0 not in para_groups:
                para_groups[0] = []
            para_groups[0].append(entry)

    # 构建结果
    results = []
    for pi in sorted(para_groups.keys()):
        group = para_groups[pi]
        if pi < len(paragraphs):
            para = paragraphs[pi]
        else:
            # LLM 可能返回越界索引，用第一个段落兜底
            para = paragraphs[0] if paragraphs else BilingualParagraph(chinese="", english="")

        avg_confidence = sum(
            entry_confidence.get(e.index, 0.5) for e in group
        ) / len(group) if group else 0.0

        results.append(MatchResult(
            paragraph=para,
            segments=sorted(group, key=lambda e: e.index),
            similarity=avg_confidence,
        ))

    return results


# ── 质量检查 ──────────────────────────────────────────────

def quality_check(output_srt: str, stats: dict) -> list[str]:
    """对输出结果进行质量检查，返回问题列表。"""
    issues = []

    entries = parse_srt(output_srt)

    if not entries:
        return ["输出为空，没有解析到任何字幕条目"]

    # 分离中英文
    cn_entries = [e for e in entries if _chinese_char_ratio(e.text) > 0.3]
    en_entries = [e for e in entries if _chinese_char_ratio(e.text) <= 0.3]

    # ─── 关键检查：中英文字幕数量必须一致 ───
    if len(en_entries) != len(cn_entries):
        issues.append(
            f"❌ 致命错误：中英文字幕数量不一致！"
            f"中文 {len(cn_entries)} 条，英文 {len(en_entries)} 条，"
            f"差额 {abs(len(cn_entries) - len(en_entries))} 条"
        )
    else:
        # 数量一致时才检查序号连续性
        cn_indices = [e.index for e in cn_entries]
        if cn_indices != list(range(1, len(cn_indices) + 1)):
            issues.append(f"中文序号不连续，检测到 {len(cn_indices)} 条字幕但有间隔")

        en_indices = [e.index for e in en_entries]
        expected_en_start = len(cn_indices) + 1
        expected_en = list(range(expected_en_start, expected_en_start + len(en_indices)))
        if en_indices != expected_en:
            issues.append(f"英文序号不连续，期望从 {expected_en_start} 开始")

    # 检查序号重复
    indices = [e.index for e in entries]
    if len(indices) != len(set(indices)):
        from collections import Counter
        duplicates = [idx for idx, count in Counter(indices).items() if count > 1]
        issues.append(f"序号重复：{duplicates}")

    # 检查空字幕
    for e in entries:
        if not e.text.strip():
            issues.append(f"序号 {e.index} 字幕为空")

    # 检查低置信度匹配
    if stats.get("low_confidence_entries", 0) > 0:
        issues.append(
            f"有 {stats['low_confidence_entries']} 条字幕匹配相似度低于阈值 "
            f"（共 {stats.get('low_confidence_groups', 0)} 组），建议手动检查"
        )

    # 检查每行长度（英文建议 ≤42 字符/行，中文建议 ≤20 字/行）
    for e in entries:
        text_len = len(e.text)
        is_cn = _chinese_char_ratio(e.text) > 0.3
        if is_cn and text_len > 30:
            issues.append(f"序号 {e.index} 中文字幕过长 ({text_len} 字符，建议 ≤30 字符)")
        elif not is_cn and text_len > 42:
            issues.append(f"序号 {e.index} 英文字幕过长 ({text_len} 字符，建议 ≤42 字符)")

    return issues


# ── API 兼容函数 ────────────────────────────────────────────

def process_bilingual_api(
    proofread_pairs: list[ProofreadPair],
    timeline_items: list[TimelineItem],
    similarity_threshold: float = 0.3,
) -> BilingualSubtitle:
    """
    API 兼容入口：接收结构化数据，返回 BilingualSubtitle。

    参数：
    - proofread_pairs: 校对文档中的中英对译列表
    - timeline_items: 时间轴中的中文条目列表
    - similarity_threshold: 相似度匹配阈值

    返回：
    - BilingualSubtitle: chinese_part + english_part
    """
    # 匹配
    results = match_segments_to_paragraphs(
        timeline_items, proofread_pairs, similarity_threshold
    )

    # 为每个匹配组分配英文断句
    for mr in results:
        n = len(mr.segments)
        if n == 0:
            continue
        mr.en_segments = split_english_text(mr.paragraph.english, n)

    # 构建中文部分（保持原始时间轴）
    chinese_part = [
        TimelineItem(index=t.index, start=t.start, end=t.end, text=t.text)
        for t in timeline_items
    ]

    # 构建英文部分（从中文数量+1开始编号）
    en_start_index = len(timeline_items) + 1
    english_part = []
    en_idx = en_start_index

    for mr in sorted(results, key=lambda r: r.segments[0].index if r.segments else float('inf')):
        for i, seg in enumerate(mr.segments):
            en_text = mr.en_segments[i] if i < len(mr.en_segments) else "[MISSING]"
            english_part.append(TimelineItem(
                index=en_idx,
                start=seg.start,
                end=seg.end,
                text=en_text,
            ))
            en_idx += 1

    return BilingualSubtitle(chinese_part=chinese_part, english_part=english_part)
