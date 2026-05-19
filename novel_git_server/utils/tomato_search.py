"""Pure HTTP client for Tomato Novel (番茄小说) online search and download.

Zero Flask dependency.  Only imports: requests + stdlib.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SEARCH_API_URL = "https://api5-normal-lf.fqnovel.com/reading/bookapi/search/page/v/"
_SEARCH_PAGE_URL = "https://fanqienovel.com/search/{query}"
_BOOK_PAGE_URL = "https://fanqienovel.com/page/{book_id}"
_CHAPTER_PROXY_URL = "https://fq.travacocro.com/content"
_CHAPTER_API_URL = "https://fanqienovel.com/api/reader/full"

_CHARSET_URL = (
    "https://raw.githubusercontent.com/ying-ck/fanqienovel-downloader/"
    "main/src/charset.json"
)
_CHARSET_LOCAL = Path(__file__).resolve().parent / "_tomato_charset.json"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

_INIT_STATE_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\})\s*;", re.DOTALL)

# ---------------------------------------------------------------------------
# Charset helpers
# ---------------------------------------------------------------------------

_charset_map: list[list[str]] | None = None


def _load_charset() -> list[list[str]]:
    global _charset_map
    if _charset_map is not None:
        return _charset_map

    if _CHARSET_LOCAL.exists():
        try:
            _charset_map = json.loads(_CHARSET_LOCAL.read_text("utf-8"))
            return _charset_map
        except (json.JSONDecodeError, OSError):
            pass

    try:
        resp = requests.get(_CHARSET_URL, headers={"User-Agent": _UA}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        _CHARSET_LOCAL.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        _charset_map = data
        return _charset_map
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch charset.json: {exc}") from exc


def _decode_content(encoded: str) -> str:
    charset = _load_charset()
    code_ranges = [
        [58344, 58715],
        [58345, 58716],
    ]
    result: list[str] = []
    for ch in encoded:
        cp = ord(ch)
        decoded = ch
        for mode, (start, end) in enumerate(code_ranges):
            if start <= cp < end:
                bias = cp - start
                arr = charset[mode]
                if 0 <= bias < len(arr) and arr[bias] != "?":
                    decoded = arr[bias]
                break
        result.append(decoded)
    return "".join(result)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _UA})
    web_id = str(random.randint(10**18, 10**19 - 1))
    s.cookies.set("novel_web_id", web_id, domain=".fanqienovel.com")
    return s


def _as_utf8(resp: requests.Response) -> requests.Response:
    resp.encoding = "utf-8"
    return resp


# ---------------------------------------------------------------------------
# Result normalization
# ---------------------------------------------------------------------------

def _normalize_search_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "book_id": str(item.get("book_id", "")),
        "book_name": item.get("book_name", ""),
        "author": item.get("author", ""),
        "word_count": item.get("word_number", 0),
        "chapter_count": item.get("chapter_count", 0),
        "cover_url": item.get("thumb_url", ""),
        "abstract": item.get("abstract", ""),
    }


# ---------------------------------------------------------------------------
# Search strategies
# ---------------------------------------------------------------------------

def _search_via_api(query: str, *, count: int = 20) -> list[dict[str, Any]] | None:
    """Try the mobile app search API. Returns results or None on failure."""
    params = {
        "aid": "1967",
        "offset": 0,
        "count": count,
        "query": query,
    }
    try:
        resp = requests.get(
            _SEARCH_API_URL,
            params=params,
            headers={"User-Agent": _UA},
            timeout=10,
        )
        if resp.status_code != 200 or not resp.text:
            return None
        body = resp.json()
        if body.get("code") != 0 or not body.get("data"):
            return None
        book_data = (
            body.get("data", {})
            .get("resp_data", {})
            .get("search_book_data", {})
            .get("book_data", [])
        )
        return [_normalize_search_item(item) for item in book_data[:count]]
    except Exception:
        return None


def _search_via_exe(query: str, *, count: int = 20) -> list[dict[str, Any]] | None:
    """Try searching via Tomato-Novel-Downloader exe server."""
    try:
        from utils.tomato_exe_client import build_client_from_env

        client = build_client_from_env()
        if client is None:
            return None
        client.ensure_running()
        resp = requests.get(
            f"{client.base_url}/api/search",
            params={"q": query, "count": count},
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        items = resp.json().get("items", [])
        if not items:
            return None
        results = []
        for item in items[:count]:
            raw = item.get("raw", {})
            # exe returns "title" not "book_name"; book_name is in raw
            book_name = item.get("book_name", "") or item.get("title", "") or raw.get("book_name", "")
            # chapter_count may be under various keys (snake_case or camelCase), value may be str or int
            chapter_count = 0
            for ck in ("chapter_count", "chapterCount", "item_cnt", "chapter_num",
                        "total_chapter_count", "chapter_total_cnt", "serial_count",
                        "content_chapter_number", "content_count", "book_item_cnt"):
                v = raw.get(ck)
                if v is not None:
                    try:
                        n = int(v)
                        if n > 0:
                            chapter_count = n
                            break
                    except (ValueError, TypeError):
                        pass
            results.append({
                "book_id": str(item.get("book_id", "")),
                "book_name": book_name,
                "author": item.get("author", "") or raw.get("author", ""),
                "word_count": int(raw.get("word_number", 0) or raw.get("wordNumber", 0) or 0),
                "chapter_count": chapter_count,
                "cover_url": raw.get("thumb_url", "") or raw.get("thumbUrl", ""),
                "abstract": raw.get("abstract", ""),
            })
        return results
    except Exception:
        logger.debug("exe search failed", exc_info=True)
        return None


def _search_via_html(query: str, *, count: int = 20) -> list[dict[str, Any]] | None:
    """Try scraping the fanqienovel.com search page for __INITIAL_STATE__ data."""
    url = _SEARCH_PAGE_URL.format(query=query)
    session = _make_session()
    try:
        resp = _as_utf8(session.get(url, timeout=15))
        resp.raise_for_status()
    except Exception:
        return None

    match = _INIT_STATE_RE.search(resp.text)
    if not match:
        return None

    state = json.loads(match.group(1))
    book_list = state.get("search", {}).get("searchBookList")
    if not book_list:
        return None

    return [_normalize_search_item(item) for item in book_list[:count]]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_novels(query: str, *, count: int = 20) -> list[dict[str, Any]]:
    """Search Tomato Novel by keyword.

    Tries the exe downloader first, then the mobile API, then HTML page scraping.

    Returns a list of dicts with keys:
        book_id, book_name, author, word_count, chapter_count, cover_url, abstract

    Raises RuntimeError if neither strategy returns results.
    """
    # Strategy 0: exe downloader search
    results = _search_via_exe(query, count=count)
    if results:
        logger.debug("search_via_exe returned %d results for '%s'", len(results), query)
        return results

    results = _search_via_api(query, count=count)
    if results:
        logger.debug("search_via_api returned %d results for '%s'", len(results), query)
        return results

    results = _search_via_html(query, count=count)
    if results:
        logger.debug("search_via_html returned %d results for '%s'", len(results), query)
        return results

    raise RuntimeError(
        f"番茄小说搜索失败：API 和页面抓取均未返回结果。"
        f"可能原因：(1) 网络/IP 受限 (2) 关键词无结果。"
        f"请尝试直接输入书籍 ID 导入。"
    )


def get_book_info(book_id: str) -> dict[str, Any]:
    """Fetch book metadata from the book page without downloading chapters.

    Returns dict with keys: book_id, book_name, author, chapter_count.
    """
    session = _make_session()
    url = _BOOK_PAGE_URL.format(book_id=book_id)
    resp = _as_utf8(session.get(url, timeout=15))
    resp.raise_for_status()

    match = _INIT_STATE_RE.search(resp.text)
    if not match:
        raise RuntimeError(f"Cannot extract __INITIAL_STATE__ from book page {book_id}")

    state = json.loads(match.group(1))
    page_data = state.get("page", {})
    book_name = page_data.get("bookName", "")
    author = page_data.get("author", "")
    abstract = page_data.get("abstract", "")
    word_count = page_data.get("wordCount", 0)

    item_ids = page_data.get("itemIds", [])
    if not item_ids:
        toc = state.get("tocItem", {})
        item_ids = toc.get("itemIds", [])

    return {
        "book_id": book_id,
        "book_name": book_name,
        "author": author,
        "abstract": abstract,
        "word_count": word_count,
        "chapter_count": len(item_ids),
    }


def _parse_chapter_list(state: dict[str, Any], book_id: str) -> list[dict[str, Any]]:
    """Extract ordered chapter list from page state via chapterListWithVolume.

    Returns list of dicts: {"item_id": str, "title": str, "is_locked": bool}.
    Falls back to flat itemIds when chapterListWithVolume is absent.
    """
    page_data = state.get("page", {})

    # Prefer chapterListWithVolume (forward-ordered, has lock status)
    volumes = page_data.get("chapterListWithVolume", [])
    if volumes:
        chapters = []
        for vol in volumes:
            for ch in vol:
                chapters.append({
                    "item_id": str(ch.get("itemId", "")),
                    "title": ch.get("title", ""),
                    "is_locked": ch.get("isChapterLock", False),
                })
        if chapters:
            return chapters

    # Fallback: flat itemIds (may be in reverse order, no lock info)
    item_ids: list[str] = page_data.get("itemIds", [])
    if not item_ids:
        toc = state.get("tocItem", {})
        item_ids = toc.get("itemIds", [])
    if not item_ids:
        raise RuntimeError(f"No chapter IDs found for book {book_id}")

    return [{"item_id": cid, "title": "", "is_locked": False} for cid in item_ids]


def _fetch_chapter_via_proxy(chapter_id: str) -> tuple[str, str] | None:
    """Try the third-party proxy for decoded content. Returns (title, content) or None."""
    try:
        resp = requests.get(
            _CHAPTER_PROXY_URL,
            params={"item_id": chapter_id},
            headers={"User-Agent": _UA},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
        data = body.get("data", {})
        title = data.get("title", "")
        content = data.get("content", "")
        if not content or len(content) < 50:
            return None
        return title, content
    except Exception:
        return None


def _fetch_chapter_via_api(session: requests.Session, chapter_id: str) -> tuple[str, str]:
    """Fetch chapter via official API + charset decode. Returns (title, content)."""
    resp = session.get(
        _CHAPTER_API_URL,
        params={"itemId": chapter_id},
        timeout=15,
    )
    if resp.status_code == 200 and resp.text:
        body = resp.json()
        chapter = body.get("data", {}).get("chapterData", {})
        title = chapter.get("title", "")
        encoded = chapter.get("content", "")
        if not encoded:
            raise RuntimeError(f"Empty content for chapter {chapter_id}")
        content = _decode_content(encoded)
        return title, content
    raise RuntimeError(f"API returned empty response for chapter {chapter_id}")


def _fetch_chapter_via_reader(chapter_id: str) -> tuple[str, str] | None:
    """Fetch chapter by scraping the reader page and extracting __INITIAL_STATE__."""
    try:
        cookie_val = f"novel_web_id={random.randint(10**18, 10**19 - 1)}"
        headers = {"User-Agent": _UA, "cookie": cookie_val}
        resp = _as_utf8(requests.get(
            f"https://fanqienovel.com/reader/{chapter_id}",
            headers=headers,
            timeout=15,
        ))
        if resp.status_code != 200:
            return None

        marker = "window.__INITIAL_STATE__="
        idx = resp.text.find(marker)
        if idx < 0:
            return None

        json_start = idx + len(marker)
        depth = 0
        json_end = json_start
        for i in range(json_start, min(json_start + 200000, len(resp.text))):
            if resp.text[i] == "{":
                depth += 1
            elif resp.text[i] == "}":
                depth -= 1
                if depth == 0:
                    json_end = i + 1
                    break

        raw = resp.text[json_start:json_end]
        raw = raw.replace(":undefined", ":null").replace(",undefined", ",null")
        state = json.loads(raw)
        chapter_data = state.get("reader", {}).get("chapterData", {})
        title = chapter_data.get("title", "")
        content_html = chapter_data.get("content", "")
        if not content_html:
            return None

        # Preserve paragraph structure before stripping tags
        text = content_html.replace("</p>", "\n\n")
        text = re.sub(r"<br\s*/?>", "\n", text)
        encoded = re.sub(r"<[^>]+>", "", text)
        content = _decode_content(encoded).strip()
        if len(content) < 50:
            return None
        return title, content
    except Exception:
        return None


def download_book(book_id: str, *, progress_cb: Any = None) -> dict[str, Any]:
    """Download all chapters of a book by its Tomato Novel book_id.

    Args:
        book_id: The numeric book ID string.
        progress_cb: Optional callback(current, total) called after each chapter.

    Returns:
        Dict with keys: book_name, author, chapters (list of dicts).
        Each chapter dict: index, title, body, char_count, is_locked.
    """
    session = _make_session()

    # Fetch book metadata and chapter list
    url = _BOOK_PAGE_URL.format(book_id=book_id)
    resp = _as_utf8(session.get(url, timeout=15))
    resp.raise_for_status()

    match = _INIT_STATE_RE.search(resp.text)
    if not match:
        raise RuntimeError(f"Cannot extract __INITIAL_STATE__ from book page {book_id}")

    state = json.loads(match.group(1))
    page_data = state.get("page", {})
    book_name = page_data.get("bookName", "")
    author = page_data.get("author", "")

    # Use structured chapter list (forward-ordered, with lock status)
    chapters_meta = _parse_chapter_list(state, book_id)
    total = len(chapters_meta)
    chapters: list[dict[str, Any]] = []

    for i, ch_meta in enumerate(chapters_meta):
        cid = ch_meta["item_id"]
        title = ""
        content = ""

        if ch_meta["is_locked"]:
            chapters.append({
                "index": i + 1,
                "title": ch_meta["title"] or f"第{i+1}章",
                "body": "",
                "char_count": 0,
                "is_locked": True,
            })
            if progress_cb:
                progress_cb(i + 1, total)
            continue

        # Strategy 1: reader page scraping + charset (most reliable)
        result = _fetch_chapter_via_reader(cid)
        if result:
            title, content = result
        else:
            # Strategy 2: official API + charset
            try:
                title, content = _fetch_chapter_via_api(session, cid)
            except Exception as exc:
                chapters.append({
                    "index": i + 1,
                    "title": ch_meta["title"] or f"第{i+1}章",
                    "body": "",
                    "char_count": 0,
                    "error": str(exc),
                })
                if progress_cb:
                    progress_cb(i + 1, total)
                continue

        chapters.append({
            "index": i + 1,
            "title": title or ch_meta["title"] or f"第{i+1}章",
            "body": content,
            "char_count": len(content),
        })

        if progress_cb:
            progress_cb(i + 1, total)

        if i < total - 1:
            time.sleep(0.3)

    return {
        "book_id": book_id,
        "book_name": book_name,
        "author": author,
        "chapter_count": len(chapters),
        "chapters": chapters,
    }
