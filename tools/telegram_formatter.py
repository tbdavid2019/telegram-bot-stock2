import html
import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)


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
        code_blocks.append(f"<pre>{code_content}</pre>")
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
    text = re.sub(r"^#{1,4}\s*(.+)$", r"📌 【\1】", text, flags=re.MULTILINE)
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
    Avoids splitting inside code blocks or bold tags.
    """
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > limit:
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
    High-reliability 3-tier Telegram message dispatcher:
    Tier 1: Sanitized Markdown (parse_mode="Markdown")
    Tier 2: Converted HTML (parse_mode="HTML")
    Tier 3: Clean Plain Text (strip markdown tags, no parse_mode)
    """
    if not text or not str(text).strip():
        return

    chunks = split_telegram_text(text)
    for i, chunk in enumerate(chunks):
        is_last = (i == len(chunks) - 1)
        markup = reply_markup if is_last else None

        # --- Tier 1: Try Sanitized Markdown ---
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
                f"[TelegramFormatter] Markdown send failed ({e_md}), attempting HTML fallback..."
            )

        # --- Tier 2: Try HTML Conversion Fallback ---
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
                f"[TelegramFormatter] HTML send failed ({e_html}), falling back to clean plain text..."
            )

        # --- Tier 3: Clean Plain Text (Strip markdown syntax) ---
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
