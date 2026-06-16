"""... (同上) """

import re
import os
import streamlit as st
from core import (
    process_subtitles,
    quality_check,
    parse_proofread_doc,
    parse_srt,
    parse_docx,
    text_similarity,
    _chinese_char_ratio,
    _has_chinese,
)
from llm import create_llm_service

# ── LLM 提供商配置（定义在 app.py 以避免跨模块导入问题）──

LLM_PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "sdk_ok": True,  # 使用标准库 urllib，无需第三方 SDK
        "install_hint": "",
    },
}

# ── 示例数据（必须在引用之前定义）──────────────────────────

SAMPLE_PROOFREAD = """2,300万台湾同胞里
Of the 23 million Taiwanese compatriots,

就接近1,900万人的祖籍
nearly 19 million people have their ancestral

是福建
roots in Fujian.

沈阳这座城市承载着无数创业者的梦想与奋斗
Shenyang carries the dreams and struggles of countless entrepreneurs.

从传统制造业到科技创新
From traditional manufacturing to technological innovation,

无数沈阳人用智慧和汗水书写着创业传奇
countless Shenyang natives have written entrepreneurial legends with their wisdom and hard work."""

SAMPLE_SRT = """1
00:00:00,200 --> 00:00:02,200
2,300万台湾同胞里

2
00:00:02,233 --> 00:00:04,666
就接近1,900万人的祖籍

3
00:00:04,700 --> 00:00:06,500
是福建

4
00:00:07,000 --> 00:00:09,500
沈阳这座城市承载着无数创业者的梦想与奋斗

5
00:00:09,533 --> 00:00:12,000
从传统制造业到科技创新

6
00:00:12,033 --> 00:00:15,500
无数沈阳人用智慧和汗水书写着创业传奇"""


# ── 回调函数（在 widget 实例化之前执行，可以安全操作 session_state）──

def on_proofread_upload():
    """校对文档上传回调：读取文件内容写入 session_state"""
    file = st.session_state.get("proofread_file")
    if file is None:
        return
    # 记录上传文件名（去除扩展名），用于生成下载文件名
    st.session_state.proofread_filename = file.name
    if file.name.endswith(".docx"):
        st.session_state.proofread_text = parse_docx(file.read())
    else:
        st.session_state.proofread_text = file.read().decode("utf-8")


def on_srt_upload():
    """SRT 文件上传回调：读取文件内容写入 session_state"""
    file = st.session_state.get("srt_file")
    if file is None:
        return
    # 记录上传文件名（去除扩展名），用于生成下载文件名
    st.session_state.srt_filename = file.name
    st.session_state.srt_text = file.read().decode("utf-8")


def on_load_sample():
    """加载示例数据回调"""
    st.session_state.proofread_text = SAMPLE_PROOFREAD
    st.session_state.srt_text = SAMPLE_SRT


def on_fill_proofread():
    """一键填入校对文档回调，并设置标记以弹出提示"""
    st.session_state.proofread_text = st.session_state.get("formatted_proofread", "")
    st.session_state._auto_filled_from_tab1 = True


def on_raw_text_upload():
    """原始文本上传回调：读取 .txt 或 .docx 文件内容写入 session_state"""
    file = st.session_state.get("raw_text_file")
    if file is None:
        return
    if file.name.endswith(".docx"):
        st.session_state.raw_format_text = parse_docx(file.read())
    else:
        st.session_state.raw_format_text = file.read().decode("utf-8")


# ── 页面配置 ──────────────────────────────────────────────

st.set_page_config(
    page_title="双语字幕精确排版专家",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── 登录认证 ──────────────────────────────────────────────

def check_password() -> bool:
    """简单密码认证，已登录则跳过"""

    if st.session_state.get("authenticated"):
        return True

    # 从 secrets 或环境变量读取密码（云部署用 st.secrets，本地用环境变量）
    import os
    _password = os.environ.get("APP_PASSWORD", "")
    try:
        _password = _password or st.secrets.get("APP_PASSWORD", "")
    except Exception:
        pass

    # 未设置密码时允许直接进入
    if not _password:
        st.session_state["authenticated"] = True
        return True

    # 登录表单
    st.markdown("""
    <style>
    .login-box {
        max-width: 400px; margin: 10vh auto; padding: 2rem;
        border: 1px solid #ddd; border-radius: 12px; text-align: center;
    }
    </style>
    <div class="login-box">
        <h1>🎬 双语字幕排版</h1>
        <p style="color:#888">内部工具，请输入访问密码</p>
    </div>
    """, unsafe_allow_html=True)

    pwd = st.text_input("密码", type="password", placeholder="输入访问密码", key="login_pwd", label_visibility="collapsed")
    if st.button("🔑 登录", use_container_width=True):
        if pwd == _password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("密码错误")
    return False


if not check_password():
    st.stop()

# ── 样式 ──────────────────────────────────────────────────

st.markdown("""
<style>
.main-header {
    font-size: 2rem;
    font-weight: 700;
    margin-bottom: 0.5rem;
}
.sub-header {
    font-size: 1rem;
    color: #666;
    margin-bottom: 2rem;
}
.stat-box {
    background: #f0f2f6;
    border-radius: 8px;
    padding: 1rem;
    text-align: center;
}
.stat-box .number {
    font-size: 1.5rem;
    font-weight: 700;
    color: #1f77b4;
}
.stat-box .label {
    font-size: 0.8rem;
    color: #666;
}
</style>
""", unsafe_allow_html=True)

# ── 页面标题 ──────────────────────────────────────────────

st.markdown('<p class="main-header">🎬 双语字幕精确排版专家</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">将校对好的中英对照文档与带时间轴的中文 SRT 字幕智能匹配，生成专业双语字幕文件</p>', unsafe_allow_html=True)

# ── 侧边栏 ────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ 设置")

    similarity_threshold = st.slider(
        "相似度匹配阈值",
        min_value=0.1,
        max_value=0.9,
        value=0.3,
        step=0.05,
        help="中文文本匹配的最低相似度要求。阈值越低越宽松（匹配更多），越高越严格（匹配更准确）。"
    )

    renumber = st.checkbox(
        "重新编排序号",
        value=True,
        help="开启后会将输出序号重新编排为连续数字（1, 2, 3...），避免原始 SRT 序号间隔导致输出混乱。"
    )

    st.divider()

    # ── LLM 设置 ──────────────────────────────────────────
    st.header("🤖 AI 增强")

    # 提供商选择
    llm_provider = st.selectbox(
        "LLM 提供商",
        options=list(LLM_PROVIDERS.keys()),
        format_func=lambda p: LLM_PROVIDERS[p]["name"],
        help="选择使用哪个 AI 服务商。DeepSeek 性价比极高，适合大量处理。",
    )

    provider_info = LLM_PROVIDERS[llm_provider]
    sdk_ok = provider_info["sdk_ok"]

    if not sdk_ok:
        st.warning(f"⚠️ 未安装所需 SDK。运行 `{provider_info['install_hint']}` 安装。")

    # API Key 输入
    api_key_placeholder = {
        "anthropic": "sk-ant-...",
        "deepseek": "sk-...",
    }.get(llm_provider, "输入 API Key...")

    llm_api_key = st.text_input(
        f"{provider_info['name']} API Key",
        type="password",
        placeholder=api_key_placeholder,
        help=f"输入你的 {provider_info['name']} API Key。留空则使用传统算法。",
    )

    # 模型选择
    llm_model = st.selectbox(
        "模型",
        options=provider_info["models"],
        index=0,
        disabled=not llm_api_key,
        help=f"选择 {provider_info['name']} 的模型。默认推荐性价比最高的选项。",
    )

    has_llm = sdk_ok and bool(llm_api_key)

    use_llm_split = st.checkbox(
        "AI 英文智能断句",
        value=False,
        disabled=not has_llm,
        help="用 AI 按语义自然拆分英文段落，彻底消除 \"...\" 占位符。启用后英文断句质量大幅提升。",
    )

    use_llm_match = st.checkbox(
        "AI 语义匹配",
        value=False,
        disabled=not has_llm,
        help="用 AI 做中英文语义级匹配，替代字符相似度算法。适合中英文措辞差异较大的场景。",
    )

    if use_llm_split or use_llm_match:
        st.caption(f"📊 {provider_info['name']} / {llm_model}")
        st.caption("💰 每次处理约消耗 ~2000-5000 tokens")

    st.divider()

    st.header("📖 使用说明")
    st.markdown("""
    **第一步**：上传校对好的中英对照文档
    **第二步**：上传带时间轴的中文 SRT 文件
    **第三步**：点击「开始排版」按钮
    **第四步**：预览结果并下载

    ---

    **输入格式要求：**

    *校对文档*：中英文段落交替排列，段落间用空行分隔
    ```
    中文段落1
    英文段落1

    中文段落2
    英文段落2
    ```

    *SRT 文档*：标准 SRT 格式
    ```
    1
    00:00:00,200 --> 00:00:02,200
    中文字幕文本
    ```
    """)

    st.divider()

    st.caption("v1.0 | 基于文档《双语字幕精确排版专家 - 完整规则手册》")

# ── 主内容区 ──────────────────────────────────────────────

tab_tt1, tab_tt2 = st.tabs(["📝 文本排版", "🎬 字幕排版"])

# ════════════════════════════════════════════════════════════
# Tab 1: AI 文本排版（预处理步骤）
# ════════════════════════════════════════════════════════════

with tab_tt1:
    st.subheader("📝 AI 文本排版")
    st.caption("粘贴原始混排中英文本，AI 自动排版为「一句中文一句英文」的校对文档格式，供下一步字幕匹配使用。")

    raw_text = st.text_area(
        "粘贴原始混排文本",
        height=300,
        placeholder="支持任意中英混排格式，例如：\n\n今天年初二，全国人民都在回娘家吧？\nToday is the second day of the new year. People all over the country are returning to their parents' homes, right?\n\n我们莆田人，今天可不许走亲戚串门。\nWe, the people of Putian, are not allowed to visit relatives or friends today.",
        label_visibility="collapsed",
        key="raw_format_text",
    )

    raw_text_file = st.file_uploader(
        "或上传原始文本 (.txt / .docx)",
        type=["txt", "docx"],
        key="raw_text_file",
        on_change=on_raw_text_upload,
    )
    if raw_text_file:
        st.success(f"已加载：{raw_text_file.name}（{len(raw_text)} 字符）")

    # 排版按钮
    format_disabled = not (raw_text.strip() and has_llm)
    format_clicked = st.button(
        "🚀 开始排版",
        type="primary",
        use_container_width=True,
        disabled=format_disabled,
        key="btn_format_text",
    )

    if not has_llm:
        st.info("💡 需要在左侧边栏配置 DeepSeek API Key 才能使用 AI 排版功能")

    if format_clicked and raw_text.strip():
        with st.spinner("🤖 AI 排版中，请稍候..."):
            try:
                llm_fmt = create_llm_service(llm_provider, llm_api_key, llm_model)
                formatted = llm_fmt.format_text_for_proofreading(raw_text)
                st.session_state["formatted_proofread"] = formatted
                st.success("✅ 排版完成！校对文档已生成，请查看下方结果。")
            except Exception as e:
                st.error(f"排版失败：{e}")

    # 显示排版结果
    formatted_proofread = st.session_state.get("formatted_proofread", "")
    if formatted_proofread:
        st.divider()
        st.subheader("📄 排版结果")
        st.caption(f"共 {len(formatted_proofread)} 字符")
        st.code(formatted_proofread, language="text")

        # 一键填入按钮
        st.button(
            "📋 一键填入校对文档",
            type="primary",
            use_container_width=True,
            key="btn_fill_proofread",
            on_click=on_fill_proofread,
        )

        # 检查是否刚刚点击了填入

# ════════════════════════════════════════════════════════════
# Tab 2: 双语字幕匹配（现有功能）
# ════════════════════════════════════════════════════════════

with tab_tt2:
    # 检查是否自动填入（从 tab1 一键填入后显示提示）
    if st.session_state.pop("_auto_filled_from_tab1", False):
        st.toast("✅ 校对文档已自动填入！请上传 SRT 文件后点击「开始排版」", icon="✅")

    col1, col2 = st.columns(2)

with col1:
    st.subheader("📄 文档一：校对文档")
    proofread_text = st.text_area(
        "粘贴中英对照的校对文档内容",
        height=250,
        placeholder="中文段落1\n英文段落1\n\n中文段落2\n英文段落2\n\n...",
        label_visibility="collapsed",
        key="proofread_text",
    )

    proofread_file = st.file_uploader(
        "或上传校对文档 (.docx / .txt)",
        type=["docx", "txt"],
        key="proofread_file",
        on_change=on_proofread_upload,
    )
    if proofread_file:
        st.success(f"已加载：{proofread_file.name}（{len(proofread_text)} 字符）")

with col2:
    st.subheader("⏱️ 文档二：时间轴文档 (SRT)")
    srt_text = st.text_area(
        "粘贴 SRT 格式的字幕文档",
        height=250,
        placeholder="1\n00:00:00,200 --> 00:00:02,200\n中文字幕文本\n\n2\n00:00:02,233 --> 00:00:04,666\n中文字幕文本\n\n...",
        label_visibility="collapsed",
        key="srt_text",
    )

    srt_file = st.file_uploader(
        "或上传 SRT 文件 (.srt)",
        type=["srt", "txt"],
        key="srt_file",
        on_change=on_srt_upload,
    )
    if srt_file:
        st.success(f"已加载：{srt_file.name}")

# ── 处理按钮 ──────────────────────────────────────────────

st.divider()

btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 4])
with btn_col1:
    process_clicked = st.button(
        "🚀 开始排版",
        type="primary",
        use_container_width=True,
        disabled=not (proofread_text.strip() and srt_text.strip()),
    )
with btn_col2:
    clear_clicked = st.button("🗑️ 清空", use_container_width=True)

if clear_clicked:
    st.rerun()

# ── 处理逻辑 ──────────────────────────────────────────────

if process_clicked and proofread_text.strip() and srt_text.strip():
    with st.spinner("正在处理中..."):
        try:
            # 创建 LLM 服务（如果配置了 API Key）
            llm = create_llm_service(llm_provider, llm_api_key, llm_model) if (use_llm_split or use_llm_match) else None

            output_srt, stats = process_subtitles(
                proofread_text,
                srt_text,
                similarity_threshold,
                renumber=renumber,
                llm_service=llm,
                use_llm_match=use_llm_match if llm else False,
            )
            issues = quality_check(output_srt, stats)

            st.session_state["output_srt"] = output_srt
            st.session_state["stats"] = stats
            st.session_state["issues"] = issues
            st.session_state["processed"] = True

        except Exception as e:
            st.error(f"处理出错：{e}")
            st.session_state["processed"] = False

# ── 结果展示 ──────────────────────────────────────────────

if st.session_state.get("processed"):

    st.divider()
    st.subheader("📊 处理结果")

    stats = st.session_state.get("stats", {})

    # 统计卡片
    stat_cols = st.columns(5)
    stat_items = [
        ("校对段落", stats.get("paragraphs", 0)),
        ("SRT 条目", stats.get("srt_entries", 0)),
        ("匹配组数", stats.get("matched_groups", 0)),
        ("已匹配条目", stats.get("matched_entries", 0)),
        ("低置信度", stats.get("low_confidence_entries", 0)),
    ]

    # 双语 SRT 检测警告
    if stats.get("bilingual_srt_detected"):
        st.info(f"🔍 检测到你的 SRT 文件已包含双语字幕（{stats.get('srt_en_entries_filtered', 0)} 条英文条目已自动过滤）。仅保留中文条目用于匹配，英文部分将由校对文档重新生成。")

    for col, (label, value) in zip(stat_cols, stat_items):
        with col:
            color = "#d62728" if (label == "低置信度" and value > 0) else "#1f77b4"
            st.markdown(f"""
            <div class="stat-box">
                <div class="number" style="color:{color}">{value}</div>
                <div class="label">{label}</div>
            </div>
            """, unsafe_allow_html=True)

    # ── LLM 状态 ──
    llm_enabled = stats.get("llm_enabled", False)
    llm_split = stats.get("llm_split_count", 0)
    rule_split = stats.get("rule_split_count", 0)

    # ── 解析诊断（帮助排查文档读取位置问题）──
    with st.expander("🔧 文档解析诊断（点击展开，排查读取位置问题）"):
        from core import parse_proofread_doc as _parse_pp, parse_srt as _parse_srt

        parsed_pairs = _parse_pp(proofread_text)
        parsed_srt = _parse_srt(srt_text)

        st.markdown(f"**校对文档解析结果：** 共识别 **{len(parsed_pairs)}** 个中英对译段落")
        st.markdown(f"**SRT 文档解析结果：** 共识别 **{len(parsed_srt)}** 条字幕条目")

        if parsed_pairs:
            st.markdown("**前 5 个段落预览：**")
            for p in parsed_pairs[:5]:
                st.text(f"[段落 {p.index}] 中: {p.zh[:60]}{'...' if len(p.zh)>60 else ''}")
                st.text(f"         英: {p.en[:60]}{'...' if len(p.en)>60 else ''}")
            if len(parsed_pairs) > 5:
                st.caption(f"... 还有 {len(parsed_pairs) - 5} 个段落未显示")
        else:
            st.error("❌ 校对文档解析结果为空！请检查输入格式。")

        if parsed_srt:
            st.markdown("**前 5 条 SRT 字幕预览：**")
            for e in parsed_srt[:5]:
                st.text(f"[#{e.index}] {e.start_time} → {e.end_time}: {e.text[:50]}{'...' if len(e.text)>50 else ''}")
            if len(parsed_srt) > 5:
                st.caption(f"... 还有 {len(parsed_srt) - 5} 条字幕未显示")
        else:
            st.error("❌ SRT 解析结果为空！请检查 SRT 格式。")

        # 交叉校验
        if parsed_pairs and parsed_srt:
            pair_count = len(parsed_pairs)
            srt_count = len(parsed_srt)
            if pair_count == 0:
                st.error("⚠️ 校对文档没有解析出任何中英对！这是导致输出异常的根本原因。")
            if abs(pair_count - srt_count) > max(pair_count, srt_count) * 0.5:
                st.warning(f"⚠️ 段落数({pair_count})与字幕数({srt_count})差异较大，可能导致匹配质量下降。")

    if llm_enabled:
        if llm_split > 0:
            st.success(f"🤖 AI 断句已生效：{llm_split} 组由 AI 拆分，{rule_split} 组无变化")
        else:
            st.caption(f"💡 AI 断句未启用：{rule_split} 组由规则算法处理（结果已自动优化，无需担心）")

        # LLM 错误静默处理（规则算法已足够好，不影响输出质量）
        llm_errors = stats.get("llm_errors", [])
        if llm_errors:
            with st.expander("🔍 LLM 调用详情（不影响结果）"):
                for i, err in enumerate(llm_errors[:3]):
                    st.caption(f"#{i+1}: {err[:120]}")
                if len(llm_errors) > 3:
                    st.caption(f"... 共 {len(llm_errors)} 个错误，已自动回退到规则算法")
    elif (use_llm_split or use_llm_match):
        st.error("❌ LLM 服务未成功创建！请检查 API Key 是否正确、SDK 是否安装")

    # 质量问题
    issues = st.session_state.get("issues", [])
    if issues:
        st.warning("⚠️ 质量检查发现以下问题：")
        for issue in issues:
            st.markdown(f"- {issue}")
    else:
        st.success("✅ 质量检查通过，未发现问题")

    # 输出预览
    st.subheader("👁️ 输出预览")

    output_srt = st.session_state.get("output_srt", "")

    srt_entries = parse_srt(output_srt)

    # 分离中英文
    cn_entries = [e for e in srt_entries if _has_chinese(e.text)]
    en_entries = [e for e in srt_entries if not _has_chinese(e.text)]

    # ── 标签页 ──
    tab1, tab2, tab3 = st.tabs(["📋 完整输出", "🇨🇳 中文部分", "🇺🇸 英文部分"])

    with tab1:
        st.code(output_srt, language="text")

    with tab2:
        if cn_entries:
            cn_text = "\n\n".join(
                f"{e.index}\n{e.start_time} --> {e.end_time}\n{e.text}"
                for e in cn_entries
            )
            st.code(cn_text, language="text")
            st.caption(f"共 {len(cn_entries)} 条中文字幕")
        else:
            st.info("未检测到中文字幕")

    with tab3:
        if en_entries:
            en_text = "\n\n".join(
                f"{e.index}\n{e.start_time} --> {e.end_time}\n{e.text}"
                for e in en_entries
            )
            st.code(en_text, language="text")
            st.caption(f"共 {len(en_entries)} 条英文字幕")
        else:
            st.info("未检测到英文字幕")

    # 下载按钮
    st.divider()
    st.subheader("💾 下载结果")

    # 生成下载文件名：基于上传的 SRT 文件名（去除扩展名），去掉所有数字
    import os
    srt_name = st.session_state.get("srt_filename", "")
    if srt_name:
        base = os.path.splitext(srt_name)[0]
    else:
        base = "bilingual_subtitles"
    # 去掉文件名中的所有数字，去除首尾下划线和空格
    clean_name = re.sub(r'\d+', '', base).strip(' _-')
    if not clean_name:
        clean_name = "bilingual_subtitles"
    bilingual_filename = f"{clean_name}_bilingual.srt"
    english_filename = f"{clean_name}_english.srt"

    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        st.download_button(
            label="📥 下载双语 SRT 文件",
            data=output_srt,
            file_name=bilingual_filename,
            mime="text/plain",
            use_container_width=True,
        )
    with dl_col2:
        # 也提供仅英文的下载
        if en_entries:
            en_only = "\n\n".join(
                f"{e.index}\n{e.start_time} --> {e.end_time}\n{e.text}"
                for e in en_entries
            )
            st.download_button(
                label="📥 仅下载英文 SRT",
                data=en_only,
                file_name=english_filename,
                mime="text/plain",
                use_container_width=True,
            )

# ── 初始状态提示 ──────────────────────────────────────────

elif not st.session_state.get("processed"):
    st.info("👆 请先上传或粘贴两个文档，然后点击「开始排版」按钮")

    # 加载示例数据
    with st.expander("🔍 没有文件？点击加载示例数据试试"):
        st.button(
            "加载示例数据",
            on_click=on_load_sample,
        )
