import re
import time
import logging
import requests
from typing import Dict, Optional

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(fn):
        fn.invoke = lambda args: fn(**args) if isinstance(args, dict) else fn(args)
        return fn

from config import WIKI_API_URL, WIKI_BASE_URL

logger = logging.getLogger(__name__)

VALID_THEMES = {
    "ayu-light", "bauhaus", "botanical", "catppuccin-latte", "catppuccin-macchiato",
    "claude-canvas", "green-simple", "kanagawa", "neo-brutalism", "newsprint",
    "notion-clean", "organic", "playful-geometric", "professional", "retro",
    "shopify-mint", "sketch", "terminal", "tokyo-night", "x-ai"
}

def sanitize_slug(text: str) -> str:
    """Generate a clean ASCII-compatible URL slug from title."""
    clean = re.sub(r'[^\w\s-]', '', text.lower())
    clean = re.sub(r'[-\s]+', '-', clean).strip('-')
    return clean[:30] if clean else "report"

def format_wiki_markdown(title: str, content: str) -> str:
    """
    Formats the markdown content according to David888 Wiki Publisher specifications:
    1. MUST start with '# Title' on the very first line.
    2. Strips out conversational chatter/small talk from the top.
    3. Adds [TOC] if not present and content is substantial.
    """
    clean_content = content.strip()
    
    # Remove any markdown code fence wrapping the entire content
    if clean_content.startswith("```markdown") or clean_content.startswith("```md"):
        clean_content = re.sub(r"^```(?:markdown|md)?\s*\n", "", clean_content)
        clean_content = re.sub(r"\n```\s*$", "", clean_content)

    # Ensure title heading
    title_header = f"# {title.strip()}"
    if not clean_content.startswith("# "):
        full_md = f"{title_header}\n\n{clean_content}"
    else:
        full_md = clean_content

    # Insert [TOC] after the title / executive summary if not already present
    if "[TOC]" not in full_md and len(full_md.splitlines()) > 15:
        # Insert [TOC] after first heading or first blockquote
        lines = full_md.splitlines()
        insert_idx = 1
        for i, line in enumerate(lines[:10]):
            if line.startswith("# "):
                insert_idx = i + 1
            elif line.startswith(">"):
                insert_idx = i + 1
        lines.insert(insert_idx, "\n[TOC]\n")
        full_md = "\n".join(lines)

    return full_md

def publish_wiki_report(title: str, content: str, theme: str = "claude-canvas") -> Optional[str]:
    """
    Publishes markdown content directly to David888 Wiki REST API.
    Returns the public shareUrl (e.g. https://wiki.david888.com/share/abc123) upon success.
    """
    if theme not in VALID_THEMES:
        theme = "claude-canvas"

    slug_base = sanitize_slug(title)
    path_slug = f"stock-{slug_base}-{int(time.time())}"
    post_url = f"{WIKI_API_URL.rstrip('/')}/{path_slug}"

    full_markdown = format_wiki_markdown(title, content)

    payload = {
        "text": full_markdown,
        "public": True,
        "theme": theme
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "telegram-bot-stock2/2.2.0"
    }

    try:
        response = requests.post(post_url, json=payload, headers=headers, timeout=12.0)
        if response.status_code == 200:
            data = response.json()
            if data.get("err") == 0 and "data" in data:
                share_url = data["data"].get("shareUrl")
                if share_url:
                    logger.info(f"Successfully published report '{title}' to David888 Wiki: {share_url}")
                    return share_url
                else:
                    logger.warning(f"David888 Wiki returned success but missing shareUrl: {data}")
            else:
                logger.error(f"David888 Wiki publish error: {data.get('msg')}")
        else:
            logger.error(f"David888 Wiki HTTP error {response.status_code}: {response.text}")
    except Exception as e:
        logger.error(f"Failed to publish report to David888 Wiki: {e}")

    return None

@tool
def publish_to_wiki(title: str, content: str, theme: str = "claude-canvas") -> Dict:
    """
    Publishes a formatted financial research report, stock comparison, or in-depth analysis to David888 Wiki.
    ALWAYS use this tool whenever generating long comprehensive investment reports or when the user requests a Wiki link/share URL.
    Returns the public shareUrl to share with the user.
    """
    logger.info(f"=== [Tool] publish_to_wiki called for title: {title} (theme: {theme})")
    share_url = publish_wiki_report(title, content, theme=theme)
    
    if share_url:
        return {
            "success": True,
            "title": title,
            "shareUrl": share_url,
            "message": f"📊 報告已成功發布至 David888 Wiki！公開閱讀連結：{share_url}"
        }
    else:
        return {
            "success": False,
            "title": title,
            "error": "無法將報告發布至 David888 Wiki，請直接以文字呈現分析內容。"
        }
