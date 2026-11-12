import html
import logging
import re
from typing import Any, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


def format_card(
    title: str,
    pre_content: str,
    emoji: str = "📊",
    footer: str = "",
    extra_blocks: Optional[List[str]] = None,
) -> str:
    """
    Format structured data into a high-readability Telegram HTML card with <pre><code> block.
    Enables mobile one-tap copy, monospace column alignment, and clean visual presentation.
    """
    parts = []
    title = (title or "").strip()
    if title:
        if emoji and not title.startswith(emoji):
            parts.append(f"<b>{emoji} {html.escape(title)}</b>")
        else:
            parts.append(f"<b>{html.escape(title)}</b>")

    pre_body = (pre_content or "").strip()
    if pre_body:
        escaped_body = html.escape(pre_body, quote=False)
        parts.append(f"<pre><code>{escaped_body}</code></pre>")

    if extra_blocks:
        for block in extra_blocks:
            b = (block or "").strip()
            if b:
                parts.append(b)

    footer = (footer or "").strip()
    if footer:
        if not (footer.startswith("<i>") or footer.startswith("<em>")):
            parts.append(f"<i>{html.escape(footer)}</i>")
        else:
            parts.append(footer)

    return "\n\n".join(parts)


def build_inline_keyboard(rows: List[List[Any]]) -> Optional[Any]:
    """
    Build a Telegram InlineKeyboardMarkup from rows of button definitions.
    Supports dicts ({"text": "...", "callback_data": "...", "url": "..."}),
    tuples (("Text", "callback_data") or ("Text", "callback_data", "url")),
    or already-instantiated InlineKeyboardButton objects.
    Automatically handles callback_data 64-byte limits via cache_prompt when needed.
    """
    if not rows:
        return None

    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        if not isinstance(InlineKeyboardMarkup, type) or hasattr(InlineKeyboardMarkup, "_mock_return_value"):
            raise ImportError("telegram is mocked")
    except (ImportError, Exception):
        # Fallback container for environments or unit tests without python-telegram-bot
        class _MockInlineKeyboardButton:
            def __init__(self, text, callback_data=None, url=None):
                self.text = text
                self.callback_data = callback_data
                self.url = url

            def __repr__(self):
                return (
                    f"InlineKeyboardButton(text={self.text!r}, "
                    f"callback_data={self.callback_data!r}, url={self.url!r})"
                )

        class _MockInlineKeyboardMarkup:
            def __init__(self, inline_keyboard):
                self.inline_keyboard = inline_keyboard

            def __repr__(self):
                return f"InlineKeyboardMarkup({self.inline_keyboard!r})"

        InlineKeyboardButton = _MockInlineKeyboardButton
        InlineKeyboardMarkup = _MockInlineKeyboardMarkup

    keyboard = []
    for row in rows:
        btn_row = []
        for item in row:
            if hasattr(item, "callback_data") or hasattr(item, "url"):
                btn_row.append(item)
                continue

            text = ""
            cb_data = None
            url = None

            if isinstance(item, dict):
                text = str(item.get("text") or item.get("label") or "").strip()
                cb_data = item.get("callback_data") or item.get("data")
                url = item.get("url")
            elif isinstance(item, (list, tuple)):
                if len(item) == 1:
                    text = str(item[0]).strip()
                elif len(item) == 2:
                    text = str(item[0]).strip()
                    val = item[1]
                    if isinstance(val, str) and (
                        val.startswith("http://") or val.startswith("https://") or val.startswith("tg://")
                    ):
                        url = val
                    else:
                        cb_data = val
                elif len(item) >= 3:
                    text = str(item[0]).strip()
                    cb_data = item[1]
                    url = item[2]

            if not text:
                continue

            if cb_data:
                cb_str = str(cb_data)
                if len(cb_str.encode("utf-8")) > 64:
                    try:
                        from handlers.general import cache_prompt
                        cb_str = cache_prompt(cb_str)
                    except Exception:
                        import hashlib
                        cb_str = f"p:{hashlib.md5(cb_str.encode('utf-8')).hexdigest()[:12]}"
                cb_data = cb_str

            if url:
                btn_row.append(InlineKeyboardButton(text=text, url=str(url)))
            elif cb_data:
                btn_row.append(InlineKeyboardButton(text=text, callback_data=cb_data))
            else:
                btn_row.append(InlineKeyboardButton(text=text, callback_data="none"))
        if btn_row:
            keyboard.append(btn_row)

    if not keyboard:
        return None
    return InlineKeyboardMarkup(keyboard)


def parse_html_button_rows(text: str) -> Tuple[str, Optional[Any]]:
    """
    Extract <tg-button-row> tags containing <tg-button> elements and convert into InlineKeyboardMarkup.
    Returns (cleaned_text, reply_markup).
    Supported tag attributes: callback_data, data, url, text. Inner text also serves as button label.
    Supports both standard <tg-button ...>label</tg-button> and self-closing <tg-button ... />.
    """
    if not text or "<tg-button" not in text:
        return text, None

    row_pattern = re.compile(r"<tg-button-row>(.*?)</tg-button-row>", re.IGNORECASE | re.DOTALL)
    button_pattern = re.compile(
        r"<tg-button([^>]*?)(?:/>|>(.*?)</tg-button>)", re.IGNORECASE | re.DOTALL
    )
    attr_pattern = re.compile(r'(\w+)=["\']([^"\']*)["\']')

    rows = []
    for row_match in row_pattern.finditer(text):
        row_content = row_match.group(1)
        btn_list = []
        for btn_match in button_pattern.finditer(row_content):
            attrs_str = btn_match.group(1) or ""
            raw_inner = btn_match.group(2) or ""
            inner_text = re.sub(r"<[^>]+>", "", raw_inner).strip()
            attrs = dict(attr_pattern.findall(attrs_str))
            btn_text = attrs.get("text", inner_text).strip()
            cb_data = attrs.get("callback_data") or attrs.get("data")
            url = attrs.get("url")
            if btn_text:
                btn_list.append({"text": btn_text, "callback_data": cb_data, "url": url})
        if btn_list:
            rows.append(btn_list)

    cleaned = row_pattern.sub("", text).strip()
    cleaned = re.sub(r"</?tg-button[^>]*>", "", cleaned).strip()
    cleaned = re.sub(r"<tg-button[^>]*?/>", "", cleaned).strip()

    markup = build_inline_keyboard(rows) if rows else None
    return cleaned, markup


def _balance_html_tags(text: str) -> str:
    """
    Ensure balanced closure of Telegram supported HTML tags (pre, code, b, i, u, s, blockquote)
    to prevent Telegram parse mode 400 errors across chunk boundaries.
    """
    if not text:
        return ""
    tags = ["code", "pre", "b", "strong", "i", "em", "u", "s", "blockquote"]
    for t in tags:
        open_count = len(re.findall(rf"<{t}\b[^>]*>", text, re.IGNORECASE))
        close_count = len(re.findall(rf"</{t}>", text, re.IGNORECASE))
        if open_count > close_count:
            text += f"</{t}>" * (open_count - close_count)
    return text


def strip_html_and_markdown_tags(text: str) -> str:
    """
    Cleanly strips all HTML tags and Markdown syntax markers for final clean plain-text fallback.
    """
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return strip_markdown_tags(text)


def sanitize_telegram_markdown(text: str) -> str:
    """
    Sanitize and normalize Markdown text specifically for Telegram's legacy Markdown parser.
    Solves Telegram's entity parsing errors:
    1. Bullet lists starting with '*' or '+' (which Telegram mistakes for opening bold).
    2. Underscores in identifiers (e.g. 魏_家, action_decision, 2330_TW) which Telegram mistakes for italic.
    3. Spaces inside bold/italic tags (e.g. '** text **').
    4. Unbalanced code blocks (```) or backticks (`).
    5. Odd counts of formatting asterisks outside of code blocks.
    """
    if not text:
        return ""

    # 1. Convert bullet lists starting with '* ' or '+ ' to '• '
    # This prevents Telegram v1 from treating the leading '*' as an unclosed bold tag!
    text = re.sub(r"^(\s*)[\*\+]\s+", r"\1• ", text, flags=re.MULTILINE)

    # 2. Fix spaces inside bold/italic tokens: '** text **' -> '**text**'
    text = re.sub(r"\*\*([ \t]+)([^\*\n]+?)\*\*", r"**\2**", text)
    text = re.sub(r"\*\*([^\*\n]+?)([ \t]+)\*\*", r"**\1**", text)
    text = re.sub(r"(?<!\*)\*([ \t]+)([^\*\n]+?)\*(?!\*)", r"*\2*", text)
    text = re.sub(r"(?<!\*)\*([^\*\n]+?)([ \t]+)\*(?!\*)", r"*\1*", text)

    # 3. Escape intra-word underscores (e.g. 魏_家, action_decision, 2330_TW)
    # In Telegram Markdown v1, single underscores trigger italics. If unclosed, it fails entity parsing.
    text = re.sub(r"(?<=[^\s_])_(?=[^\s_])", r"\_", text)

    # 4. Fix bold headers like '💡 **【標題】**' to ensure no trailing orphan asterisks on the same line
    text = re.sub(r"(\*\*[^\*\n]+\*\*)[ \t]*\*", r"\1", text)

    # 5. Clean up redundant dividers
    text = re.sub(r"^\s*---\s*$", "", text, flags=re.MULTILINE)

    # 6. Handle unclosed code blocks (```)
    if text.count("```") % 2 != 0:
        text += "\n```"

    # 7. Check unclosed inline code (`) outside of ``` blocks
    non_code_blocks = re.sub(r"```[\s\S]*?```", "", text)
    if non_code_blocks.count("`") % 2 != 0:
        text += "`"

    # 8. Check unclosed asterisks outside code
    clean_for_asterisk = re.sub(r"```[\s\S]*?```", "", text)
    clean_for_asterisk = re.sub(r"`[^`]*`", "", clean_for_asterisk)
    if clean_for_asterisk.count("*") % 2 != 0:
        # Odd number of asterisks will crash Telegram parser; append an asterisk to close it
        text += "*"

    # 9. Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return text


def markdown_to_telegram_html(text: str) -> str:
    """
    Convert Markdown to Telegram-safe HTML format.
    HTML parse mode in Telegram is immune to underscore and asterisk entity parsing crashes.
    """
    if not text:
        return ""

    # 1. Escape HTML special characters first (preserve <, >, & safely)
    text = html.escape(text)

    # 2. Extract and preserve code blocks
    code_blocks: List[str] = []
    def save_code_block(match):
        code_content = match.group(2)
        code_blocks.append(f"<pre><code>{code_content}</code></pre>")
        return f"__CODE_BLOCK_{len(code_blocks)-1}__"

    text = re.sub(r"```(?:\w+)?\n([\s\S]*?)```", save_code_block, text)

    # 3. Extract and preserve inline code
    inline_codes: List[str] = []
    def save_inline_code(match):
        code_content = match.group(1)
        inline_codes.append(f"<code>{code_content}</code>")
        return f"__INLINE_CODE_{len(inline_codes)-1}__"

    text = re.sub(r"`([^`\n]+?)`", save_inline_code, text)

    # 4. Bold (**text** or __text__)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # 5. Italic (*text* or _text_)
    text = re.sub(r"(?<!\w)\*([^\*\n]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)

    # 6. Convert bullet lists starting with '* ' or '+ ' or '- ' to '• '
    text = re.sub(r"^(\s*)[\*\+\-]\s+", r"\1• ", text, flags=re.MULTILINE)

    # 7. Convert markdown links [text](url)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r'<a href="\2">\1</a>', text)

    # 8. Restore inline code and code blocks
    for idx, code_html in enumerate(inline_codes):
        text = text.replace(f"__INLINE_CODE_{idx}__", code_html)
    for idx, block_html in enumerate(code_blocks):
        text = text.replace(f"__CODE_BLOCK_{idx}__", block_html)

    # 9. Clean up redundant dividers
    text = re.sub(r"^\s*---\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return text


def strip_markdown_tags(text: str) -> str:
    """
    Cleanly strips markdown syntax markers (*, _, `, #) for ultimate plain text fallback.
    Guarantees user NEVER sees raw broken syntax like '* **' or '**【...】**'.
    """
    if not text:
        return ""
    # Code blocks
    text = re.sub(r"```(?:\w+)?\n([\s\S]*?)```", r"\1", text)
    # Inline code
    text = re.sub(r"`([^`\n]+?)`", r"\1", text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    # Italic
    text = re.sub(r"\*([^\*\n]+?)\*", r"\1", text)
    # Headers
    text = re.sub(r"^#{1,4}\s*(.+)$", r"📌 \1", text, flags=re.MULTILINE)
    # Bullet lists
    text = re.sub(r"^(\s*)[\*\+]\s+", r"\1• ", text, flags=re.MULTILINE)
    # Links
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r"\1 (\2)", text)
    # Dividers
    text = re.sub(r"^\s*---\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def split_telegram_text(text: str, limit: int = 3900) -> List[str]:
    """
    Split long output into chunks strictly within Telegram 4096 char limit.
    Avoids splitting inside code blocks or bold tags when possible.
    """
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > limit:
        split_at = -1
        # 1. Prefer splitting right after </pre> tag with spacing
        pre_close = remaining.rfind("</pre>\n\n", 0, limit)
        if pre_close >= limit // 3:
            split_at = pre_close + len("</pre>")
        else:
            # 2. Split on paragraph boundaries
            split_at = remaining.rfind("\n\n", 0, limit)
            if split_at < limit // 2:
                split_at = remaining.rfind("\n", 0, limit)
            if split_at < limit // 2:
                split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def safe_reply_formatted(
    message,
    text: str,
    reply_markup=None,
    disable_web_page_preview: bool = True
):
    """
    High-reliability Telegram message dispatcher with HTML Priority:
    - Auto-unwraps Update, CallbackQuery, or Message target objects safely.
    - Auto-extracts rich buttons (<tg-button-row>) when reply_markup is not pre-supplied.
    - HTML Priority: When HTML tags (<pre>, <code>, <b>, <i>, etc.) are present, dispatches via HTML first.
    - Multi-tier Fallback: HTML -> Markdown -> Clean Plain Text on 400 parsing errors.
    - Attaches reply_markup strictly to the final chunk.
    """
    if message is None:
        logger.warning("[TelegramFormatter] safe_reply_formatted received None message target")
        return

    # Intelligent target unwrapping: unwrap if target does not directly have reply_text
    if not hasattr(message, "reply_text"):
        if hasattr(message, "effective_message") and message.effective_message:
            message = message.effective_message
        elif hasattr(message, "callback_query") and message.callback_query and getattr(message.callback_query, "message", None):
            message = message.callback_query.message
        elif hasattr(message, "message") and message.message:
            message = message.message

    if not hasattr(message, "reply_text"):
        logger.error(f"[TelegramFormatter] Target {type(message)} does not have reply_text method")
        return

    if not text or not str(text).strip():
        return

    # 1. Check for HTML embedded buttons
    if "<tg-button" in text:
        clean_text, parsed_markup = parse_html_button_rows(text)
        text = clean_text
        if reply_markup is None and parsed_markup is not None:
            reply_markup = parsed_markup

    # 2. Detect HTML markup presence
    has_html_tags = bool(
        re.search(r"<(?:b|strong|i|em|u|ins|s|strike|del|a|code|pre|blockquote|tg-spoiler)\b", text, re.IGNORECASE)
    )

    chunks = split_telegram_text(text)
    for i, chunk in enumerate(chunks):
        is_last = (i == len(chunks) - 1)
        markup = reply_markup if is_last else None

        if has_html_tags:
            # --- Priority Track: HTML Parse Mode ---
            chunk_html = _balance_html_tags(chunk)
            try:
                await message.reply_text(
                    chunk_html,
                    reply_markup=markup,
                    parse_mode="HTML",
                    disable_web_page_preview=disable_web_page_preview
                )
                continue
            except Exception as e_html:
                logger.warning(
                    f"[TelegramFormatter] HTML dispatch failed ({e_html}), attempting Markdown fallback..."
                )

            # Fallback 1: Try Markdown
            sanitized_md = sanitize_telegram_markdown(chunk)
            try:
                await message.reply_text(
                    sanitized_md,
                    reply_markup=markup,
                    parse_mode="Markdown",
                    disable_web_page_preview=disable_web_page_preview
                )
                continue
            except Exception as e_md:
                logger.error(
                    f"[TelegramFormatter] Markdown fallback failed ({e_md}), falling back to plain text..."
                )

            # Fallback 2: Clean Plain Text
            plain_text = strip_html_and_markdown_tags(chunk)
            try:
                await message.reply_text(
                    plain_text,
                    reply_markup=markup,
                    disable_web_page_preview=disable_web_page_preview
                )
            except Exception as e_plain:
                logger.critical(
                    f"[TelegramFormatter] Fatal plain text delivery error: {e_plain}"
                )
        else:
            # --- Standard Track: Markdown / HTML Converted ---
            sanitized_md = sanitize_telegram_markdown(chunk)
            try:
                await message.reply_text(
                    sanitized_md,
                    reply_markup=markup,
                    parse_mode="Markdown",
                    disable_web_page_preview=disable_web_page_preview
                )
                continue
            except Exception as e_md:
                logger.warning(
                    f"[TelegramFormatter] Markdown dispatch failed ({e_md}), attempting HTML conversion..."
                )

            # Fallback 1: Converted HTML
            html_text = markdown_to_telegram_html(chunk)
            try:
                await message.reply_text(
                    html_text,
                    reply_markup=markup,
                    parse_mode="HTML",
                    disable_web_page_preview=disable_web_page_preview
                )
                continue
            except Exception as e_html:
                logger.error(
                    f"[TelegramFormatter] HTML fallback failed ({e_html}), falling back to plain text..."
                )

            # Fallback 2: Plain text
            plain_text = strip_markdown_tags(chunk)
            try:
                await message.reply_text(
                    plain_text,
                    reply_markup=markup,
                    disable_web_page_preview=disable_web_page_preview
                )
            except Exception as e_plain:
                logger.critical(
                    f"[TelegramFormatter] Fatal message delivery error: {e_plain}"
                )
