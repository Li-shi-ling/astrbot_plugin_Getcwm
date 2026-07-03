from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.ciweimao.com"
FANQIE_BASE_URL = "https://fanqienovel.com"
DEFAULT_TIMEOUT_S = 10
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

CWM_CRAWLER_DEBUG = False


@dataclass(frozen=True)
class CardRenderResult:
    image_path: str
    data: Any


def asia_shanghai_tz() -> tzinfo:
    if ZoneInfo is not None:
        try:
            return ZoneInfo("Asia/Shanghai")  # type: ignore[return-value]
        except Exception:
            pass
    return timezone(timedelta(hours=8))


def cn_number_to_float(text: str) -> float | str:
    s = str(text).strip().replace(",", "")
    if not s:
        return s

    units = {"万": 10_000, "亿": 100_000_000}
    try:
        for unit, mul in units.items():
            if unit in s:
                return float(s.replace(unit, "")) * mul
        return float(s)
    except Exception:
        return s


def extract_chapter_info(update_text: str) -> tuple[str, int]:
    if not update_text:
        return "", -1

    text = update_text.strip()
    text = re.sub(r"^(最近更新|更新时间|最后更新|最新更新)[:：]?\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    chapter_part = text
    ts = -1

    dt_patterns: list[tuple[str, str]] = [
        (r"\[\s*(20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*\]", "%Y-%m-%d %H:%M:%S"),
        (r"(20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", "%Y-%m-%d %H:%M:%S"),
        (r"\[\s*(20\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s*\]", "%Y/%m/%d %H:%M:%S"),
        (r"(20\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})", "%Y/%m/%d %H:%M:%S"),
    ]

    for pat, fmt in dt_patterns:
        match = re.search(pat, text)
        if not match:
            continue
        dt_str = (match.group(1) or "").strip()
        try:
            dt = datetime.strptime(dt_str, fmt).replace(tzinfo=asia_shanghai_tz())
            ts = int(dt.timestamp())
        except Exception:
            ts = -1

        chapter_part = (text[: match.start()] + " " + text[match.end() :]).strip()
        chapter_part = re.sub(r"[\[\]]", " ", chapter_part)
        chapter_part = re.sub(r"\s+", " ", chapter_part).strip()
        break

    chapter_part = re.sub(r"^[\s/|:：–—-]+", "", chapter_part).strip()
    chapter_part = re.sub(r"[\s/|:：–—-]+$", "", chapter_part).strip()
    return chapter_part, ts


def safe_text(el: Any) -> str:
    if not el:
        return ""
    try:
        return el.get_text(" ", strip=True)
    except Exception:
        return str(el).strip()


def abspath_url(url: str) -> str:
    if not url:
        return ""
    return url if url.startswith("http") else urljoin(BASE_URL, url)


def fanqie_abspath_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    return url if url.startswith("http") else urljoin(FANQIE_BASE_URL, url)


def fetch_image_data_uri(
    url: str, session: requests.Session | None = None
) -> str | None:
    if not url:
        return None

    sess = session or requests.Session()
    try:
        resp = sess.get(
            abspath_url(url), timeout=DEFAULT_TIMEOUT_S, headers=DEFAULT_HEADERS
        )
        resp.raise_for_status()
        content_type = (
            (resp.headers.get("Content-Type") or "image/jpeg").split(";", 1)[0].strip()
        )
        b64 = base64.b64encode(resp.content).decode("ascii")
        return f"data:{content_type};base64,{b64}"
    except Exception as exc:
        logger.debug(
            "Failed to download cover image, fallback to placeholder: %s (%s)", url, exc
        )
        return None


def html_escape(s: Any) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def line_clamp_css(lines: int) -> str:
    return (
        "display:-webkit-box;"
        "-webkit-box-orient:vertical;"
        f"-webkit-line-clamp:{max(1, int(lines))};"
        "overflow:hidden;"
    )


def format_ts_cn(ts: int) -> str:
    if not ts or ts < 0:
        return "未知时间"
    try:
        dt = datetime.fromtimestamp(int(ts), tz=asia_shanghai_tz())
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "未知时间"


def parse_search_html_content(html_content: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html_content, "html.parser")
    novel_items = soup.select("li[data-book-id]")

    results: list[dict[str, str]] = []
    for item in novel_items:
        title = ""
        read_url = ""

        title_a = item.select_one("p.tit a")
        if title_a:
            title = safe_text(title_a)
            read_url = title_a.get("href", "") or ""

        if not read_url:
            cover_a = item.select_one("a.cover")
            if cover_a:
                read_url = cover_a.get("href", "") or ""

        if not title:
            title = safe_text(item.select_one("p.tit")) or "未知标题"

        author = "未知作者"
        update_time = "未知更新"

        for paragraph in item.find_all("p"):
            paragraph_text = safe_text(paragraph)
            if "小说作者" in paragraph_text:
                author_link = paragraph.find("a")
                if author_link:
                    author = safe_text(author_link) or author
            elif "最近更新" in paragraph_text:
                update_time = paragraph_text or update_time

        description = safe_text(item.select_one("div.desc"))

        results.append(
            {
                "title": title,
                "author": author,
                "update_time": update_time,
                "description": description,
                "read_url": abspath_url(read_url) or "未知链接",
            }
        )

    return results


def parse_book_details_html_content(html_content: str) -> dict[str, Any] | None:
    from astrbot.api import logger as plugin_logger

    html_len = len(html_content or "")
    CWM_CRAWLER_DEBUG and plugin_logger.debug(
        "[cwm] Parse details page: start. html_len=%s", html_len
    )

    try:
        soup = BeautifulSoup(html_content, "html.parser")
    except Exception as exc:
        logger.exception("Failed to parse HTML: %s", exc)
        CWM_CRAWLER_DEBUG and plugin_logger.debug(
            "[cwm] Parse details page: BeautifulSoup failed: %s", exc
        )
        return None

    works_name = ""
    breadcrumb = soup.select_one("div.breadcrumb")
    if breadcrumb:
        works_name = safe_text(breadcrumb).split(">")[-1].strip()

    author_name = safe_text(soup.select_one("h1.title a"))
    tag_list = [
        safe_text(tag) for tag in soup.select("p.label-box span") if safe_text(tag)
    ]

    chapter_name = ""
    update_time = -1
    update_text = ""
    update_el = soup.select_one("p.update-time")
    if update_el:
        update_text = safe_text(update_el)
        chapter_name, update_time = extract_chapter_info(update_text)

    def _short(s: str, n: int = 160) -> str:
        out = re.sub(r"\s+", " ", str(s or "")).strip()
        return out[:n] + ("..." if len(out) > n else "")

    CWM_CRAWLER_DEBUG and plugin_logger.debug(
        "[cwm] Parse details page: works=%s author=%s tags=%s has_update_el=%s update_text=%s chapter=%s update_time=%s",
        _short(works_name, 60) or "unknown",
        _short(author_name, 40) or "unknown",
        len(tag_list),
        bool(update_el),
        _short(update_text, 120) if update_el else "",
        _short(chapter_name, 80) if chapter_name else "",
        update_time,
    )

    if not update_el:
        candidates: list[str] = []
        for el in soup.find_all(["p", "div", "span", "li"]):
            text = safe_text(el)
            if not text:
                continue
            if "最近更新" in text or "更新时间" in text:
                candidates.append(_short(text, 140))
            if len(candidates) >= 3:
                break
        if candidates:
            CWM_CRAWLER_DEBUG and plugin_logger.debug(
                "[cwm] Parse details page: p.update-time missing, candidates=%s",
                candidates,
            )
        else:
            CWM_CRAWLER_DEBUG and plugin_logger.debug(
                "[cwm] Parse details page: p.update-time missing, no candidate text found",
            )

    brief_introduction = ""
    desc_el = soup.select_one("div.book-desc")
    if desc_el:
        brief_introduction = desc_el.get_text().replace(" ", "")

    cover_image = ""
    cover_img = soup.select_one("div.cover.ly-fl img")
    if cover_img and cover_img.get("src"):
        cover_image = cover_img["src"]
    if not cover_image:
        all_images = soup.find_all("img")
        if all_images:
            cover_image = all_images[-1].get("src", "") or ""

    data: dict[str, Any] = {}
    prop_div = soup.select_one("div.book-property.clearfix")
    if prop_div:
        for span in prop_div.find_all("span"):
            text = safe_text(span).replace("：", ":")
            if ":" not in text:
                continue
            key, val = [part.strip() for part in text.split(":", 1)]
            if key:
                data[key] = cn_number_to_float(val)

    data2: dict[str, Any] = {}
    grade_p = soup.select_one("p.book-grade")
    if grade_p:
        values = [safe_text(node) for node in grade_p.find_all("b") if safe_text(node)]
        if len(values) >= 3:
            data2["总点击"] = cn_number_to_float(values[0])
            data2["总收藏"] = cn_number_to_float(values[1])
            data2["总字数"] = cn_number_to_float(values[2])

    CWM_CRAWLER_DEBUG and plugin_logger.debug(
        "[cwm] Parse details page: works=%s chapter=%s update_time=%s cover=%s data_keys=%s data2_keys=%s",
        _short(works_name, 60) or "unknown",
        _short(chapter_name, 80) if chapter_name else "",
        update_time,
        bool(cover_image),
        list(data.keys())[:10],
        list(data2.keys()),
    )

    return {
        "Source": "cwm",
        "Works_Name": works_name,
        "Author_Name": author_name,
        "Tag_List": tag_list,
        "Chapter_Name": chapter_name,
        "Update_Time": update_time,
        "Brief_Introduction": brief_introduction,
        "Cover_Image": cover_image,
        "data": data,
        "data2": data2,
    }


def _extract_window_initial_state(html_content: str) -> dict[str, Any]:
    marker = "window.__INITIAL_STATE__="
    start = (html_content or "").find(marker)
    if start < 0:
        return {}

    pos = start + len(marker)
    while pos < len(html_content) and html_content[pos].isspace():
        pos += 1
    if pos >= len(html_content) or html_content[pos] != "{":
        return {}

    depth = 0
    in_string = False
    escape = False
    quote_char = ""
    for idx in range(pos, len(html_content)):
        ch = html_content[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote_char:
                in_string = False
            continue
        if ch in ("\"", "'"):
            in_string = True
            quote_char = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = html_content[pos : idx + 1]
                try:
                    return json.loads(raw)
                except Exception:
                    logger.debug("Failed to parse Fanqie initial state JSON")
                    return {}
    return {}


def _fanqie_ts(value: Any) -> int:
    try:
        ts = int(str(value or "").strip())
    except Exception:
        return -1
    if ts > 10_000_000_000:
        ts //= 1000
    return ts if ts > 0 else -1


def _fanqie_status_text(value: Any) -> str:
    try:
        status = int(value)
    except Exception:
        return "未知"
    return {0: "未知", 1: "连载中", 2: "已完结"}.get(status, "未知")


def _fanqie_category_names(raw: Any) -> list[str]:
    if isinstance(raw, list):
        data = raw
    else:
        try:
            data = json.loads(str(raw or "[]"))
        except Exception:
            data = []
    names: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or item.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _fanqie_word_text(value: Any) -> str:
    try:
        count = int(value or 0)
    except Exception:
        return str(value or "")
    if count >= 10_000:
        return f"{count / 10_000:.1f}万"
    return str(count)


def _fanqie_chapter_preview(page: dict[str, Any], limit: int = 4) -> list[dict[str, Any]]:
    volumes = page.get("chapterListWithVolume") or []
    chapters: list[dict[str, Any]] = []
    if isinstance(volumes, list):
        for volume in volumes:
            if not isinstance(volume, list):
                continue
            for chapter in volume:
                if isinstance(chapter, dict):
                    chapters.append(chapter)

    if not chapters:
        rows = page.get("chapterList") or []
        if isinstance(rows, list):
            chapters = [row for row in rows if isinstance(row, dict)]

    preview: list[dict[str, Any]] = []
    for chapter in chapters[-max(1, int(limit)) :]:
        title = str(chapter.get("title") or "").strip()
        item_id = str(chapter.get("itemId") or chapter.get("item_id") or "").strip()
        order = str(chapter.get("realChapterOrder") or chapter.get("order") or "").strip()
        volume = str(chapter.get("volume_name") or chapter.get("volumeName") or "").strip()
        first_pass_ts = _fanqie_ts(
            chapter.get("firstPassTime") or chapter.get("first_pass_time")
        )
        preview.append(
            {
                "title": title,
                "item_id": item_id,
                "order": order,
                "volume": volume,
                "first_pass_time": first_pass_ts,
                "need_pay": chapter.get("needPay"),
                "locked": bool(chapter.get("isChapterLock")),
            }
        )
    return preview


def parse_fanqie_book_details_html_content(html_content: str) -> dict[str, Any] | None:
    state = _extract_window_initial_state(html_content)
    page = state.get("page") if isinstance(state, dict) else {}
    page = page if isinstance(page, dict) else {}
    soup = BeautifulSoup(html_content or "", "html.parser")

    works_name = str(page.get("bookName") or "").strip()
    if not works_name:
        works_name = safe_text(soup.select_one("h1"))

    author_name = str(
        page.get("authorName") or page.get("author") or ""
    ).strip()
    if not author_name:
        author_name = safe_text(soup.select_one(".author-name-text"))

    tags = [_fanqie_status_text(page.get("creationStatus") or page.get("status"))]
    tags.extend(_fanqie_category_names(page.get("categoryV2")))
    if len(tags) <= 1:
        tags = [
            safe_text(tag)
            for tag in soup.select(".info-label span")
            if safe_text(tag)
        ]
    tags = [tag for idx, tag in enumerate(tags) if tag and tag not in tags[:idx]]

    chapter_name = str(page.get("lastChapterTitle") or "").strip()
    update_time = _fanqie_ts(page.get("lastPublishTime"))
    if not chapter_name:
        latest = soup.select_one(".info-last-title")
        latest_text = safe_text(latest)
        chapter_name = re.sub(r"^最近更新：", "", latest_text).strip()
    if update_time <= 0:
        latest_time = safe_text(soup.select_one(".info-last-time"))
        try:
            update_time = int(
                datetime.strptime(latest_time, "%Y-%m-%d %H:%M")
                .replace(tzinfo=asia_shanghai_tz())
                .timestamp()
            )
        except Exception:
            update_time = -1

    intro = str(page.get("abstract") or "").strip()
    if not intro:
        intro = safe_text(soup.select_one(".page-abstract-content"))

    cover = str(
        page.get("thumbUrl") or page.get("thumbUri") or page.get("sourceUri") or ""
    ).strip()
    if cover and cover.startswith("novel-pic/"):
        cover = "https://p9-novel-sign.byteimg.com/" + cover
    if not cover:
        img = soup.select_one(".book-cover-img")
        cover = str(img.get("src") or "") if img else ""

    word_count = page.get("wordNumber") or page.get("word_count") or 0
    read_count = page.get("readCount") or page.get("read_count") or 0
    chapter_total = page.get("chapterTotal") or 0
    volume_names = page.get("volumeNameList") or []
    if not isinstance(volume_names, list):
        volume_names = []
    volume_text = "、".join(str(item) for item in volume_names if str(item).strip())
    original_authors = page.get("originalAuthors") or []
    original_author_text = ""
    if isinstance(original_authors, list):
        original_author_text = "、".join(
            str(item.get("AuthorName") or item.get("authorName") or "").strip()
            for item in original_authors
            if isinstance(item, dict)
        ).strip("、")

    if not works_name and not author_name and not chapter_name:
        return None

    return {
        "Source": "fq",
        "Works_Name": works_name,
        "Author_Name": author_name,
        "Tag_List": tags,
        "Chapter_Name": chapter_name,
        "Update_Time": update_time,
        "Brief_Introduction": intro,
        "Cover_Image": fanqie_abspath_url(cover),
        "data": {
            "来源": "番茄小说",
            "状态": tags[0] if tags else "未知",
            "章节数": chapter_total,
            "书籍ID": page.get("bookId") or "",
            "媒体ID": page.get("mediaId") or "",
            "作者ID": page.get("authorId") or page.get("creatorId") or "",
            "最新章节ID": page.get("lastChapterItemId") or "",
            "分卷": volume_text or "未知",
        },
        "data2": {
            "总点击": read_count,
            "阅读量": read_count,
            "总收藏": "未知",
            "总字数": _fanqie_word_text(word_count),
        },
        "fanqie_extra": {
            "book_id": page.get("bookId") or "",
            "media_id": page.get("mediaId") or "",
            "author_id": page.get("authorId") or page.get("creatorId") or "",
            "author_avatar": fanqie_abspath_url(str(page.get("avatarUri") or "")),
            "source_uri": page.get("sourceUri") or "",
            "last_chapter_item_id": page.get("lastChapterItemId") or "",
            "chapter_total": chapter_total,
            "read_count": read_count,
            "word_count": word_count,
            "volume_names": volume_names,
            "original_authors": original_author_text,
            "author_description": page.get("description") or "",
            "chapter_preview": _fanqie_chapter_preview(page),
        },
    }


def parse_fanqie_reader_book_id(html_content: str) -> int | None:
    state = _extract_window_initial_state(html_content)
    reader = state.get("reader") if isinstance(state, dict) else {}
    reader = reader if isinstance(reader, dict) else {}
    chapter_data = reader.get("chapterData") if isinstance(reader, dict) else {}
    chapter_data = chapter_data if isinstance(chapter_data, dict) else {}

    raw_book_id = chapter_data.get("bookId") or chapter_data.get("book_id")
    if raw_book_id:
        try:
            return int(raw_book_id)
        except Exception:
            logger.warning("[fq] Reader state has invalid bookId: %r", raw_book_id)

    match = re.search(r'"bookId"\s*:\s*"?(\d+)"?', html_content or "")
    if match:
        return int(match.group(1))

    logger.warning(
        "[fq] Reader page did not expose bookId. html_len=%s has_initial_state=%s",
        len(html_content or ""),
        "window.__INITIAL_STATE__=" in (html_content or ""),
    )
    return None


def _normalize_fanqie_search_item(item: dict[str, Any]) -> dict[str, str] | None:
    book_id = str(item.get("book_id") or item.get("bookId") or "").strip()
    title = str(item.get("book_name") or item.get("bookName") or "").strip()
    if not book_id and not title:
        return None

    author = str(item.get("author") or item.get("authorName") or "未知作者").strip()
    chapter = str(
        item.get("last_chapter_title") or item.get("lastChapterTitle") or ""
    ).strip()
    update_ts = _fanqie_ts(item.get("last_chapter_time") or item.get("lastPublishTime"))
    update_time = f"最近更新：{chapter}" if chapter else "未知更新"
    if update_ts > 0:
        update_time += f" [{format_ts_cn(update_ts)}]"

    return {
        "title": title or f"番茄书籍 {book_id}",
        "author": author or "未知作者",
        "update_time": update_time,
        "description": str(
            item.get("book_abstract") or item.get("abstract") or ""
        ).strip(),
        "read_url": f"{FANQIE_BASE_URL}/page/{book_id}" if book_id else "",
    }


def parse_fanqie_search_html_content(html_content: str) -> list[dict[str, str]]:
    raw = html_content or ""
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(raw) if raw.strip().startswith("{") else {}
    except Exception:
        payload = {}

    if payload:
        data = payload.get("data") if isinstance(payload, dict) else {}
        data = data if isinstance(data, dict) else {}
        rows = data.get("search_book_data_list") or data.get("searchBookList") or []
        if isinstance(rows, list):
            results = [
                normalized
                for item in rows
                if isinstance(item, dict)
                for normalized in [_normalize_fanqie_search_item(item)]
                if normalized
            ]
            logger.debug(
                "[fq] Parsed search API payload. code=%s rows=%s results=%s html_len=%s",
                payload.get("code"),
                len(rows),
                len(results),
                len(raw),
            )
            return results

    state = _extract_window_initial_state(raw)
    search = state.get("search") if isinstance(state, dict) else {}
    search = search if isinstance(search, dict) else {}
    rows = search.get("searchBookList") or []
    if isinstance(rows, list):
        results = [
            normalized
            for item in rows
            if isinstance(item, dict)
            for normalized in [_normalize_fanqie_search_item(item)]
            if normalized
        ]
        logger.debug(
            "[fq] Parsed search initial state. rows=%s results=%s html_len=%s",
            len(rows),
            len(results),
            len(raw),
        )
        return results

    soup = BeautifulSoup(raw, "html.parser")
    results: list[dict[str, str]] = []
    for item in soup.select(".search-book-item"):
        link_id = ""
        title = safe_text(item.select_one(".title"))
        href = ""
        for link in item.select("a[href]"):
            candidate = str(link.get("href") or "")
            if "/page/" in candidate:
                href = candidate
                m = re.search(r"/page/(\d+)", candidate)
                link_id = m.group(1) if m else ""
                break
        if not title and not href:
            continue
        results.append(
            {
                "title": title or f"番茄书籍 {link_id}",
                "author": safe_text(item.select_one(".desc span")) or "未知作者",
                "update_time": safe_text(item.select_one(".footer")) or "未知更新",
                "description": safe_text(item.select_one(".abstract")),
                "read_url": fanqie_abspath_url(href),
            }
        )
    logger.debug(
        "[fq] Parsed search DOM fallback. dom_items=%s results=%s html_len=%s",
        len(soup.select(".search-book-item")),
        len(results),
        len(raw),
    )
    return results


class CiweimaoClient:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
    ):
        self.session = session or requests.Session()
        self.timeout_s = int(timeout_s)
        self.session.headers.update(DEFAULT_HEADERS)

    def search_name(self, name: str, page: int = 1) -> str:
        url = f"{BASE_URL}/get-search-book-list/0-0-0-0-0-0/全部/{name}/{page}"
        from astrbot.api import logger as plugin_logger

        CWM_CRAWLER_DEBUG and plugin_logger.debug(
            "[cwm] Request search page: name=%s page=%s url=%s timeout=%ss",
            name,
            page,
            url,
            self.timeout_s,
        )
        start_t = time.perf_counter()
        try:
            resp = self.session.get(url, timeout=self.timeout_s)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            CWM_CRAWLER_DEBUG and plugin_logger.debug(
                "[cwm] Search request failed: name=%s page=%s elapsed_ms=%s url=%s err=%s",
                name,
                page,
                elapsed_ms,
                url,
                exc,
            )
            raise

        elapsed_ms = int((time.perf_counter() - start_t) * 1000)
        content_type = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip()
        try:
            text_len = len(resp.text or "")
        except Exception:
            text_len = -1

        CWM_CRAWLER_DEBUG and plugin_logger.debug(
            "[cwm] Search response: status=%s elapsed_ms=%s final_url=%s content_type=%s encoding=%s apparent_encoding=%s text_len=%s",
            getattr(resp, "status_code", None),
            elapsed_ms,
            getattr(resp, "url", None),
            content_type or "unknown",
            getattr(resp, "encoding", None),
            getattr(resp, "apparent_encoding", None),
            text_len,
        )
        resp.raise_for_status()
        return resp.text

    def get_book_details(self, book_id: int) -> str:
        url = f"{BASE_URL}/book/{int(book_id)}"
        from astrbot.api import logger as plugin_logger

        CWM_CRAWLER_DEBUG and plugin_logger.debug(
            "[cwm] Request details page: book_id=%s url=%s timeout=%ss",
            int(book_id),
            url,
            self.timeout_s,
        )
        start_t = time.perf_counter()
        try:
            resp = self.session.get(url, timeout=self.timeout_s)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            CWM_CRAWLER_DEBUG and plugin_logger.debug(
                "[cwm] Details request failed: book_id=%s elapsed_ms=%s url=%s err=%s",
                int(book_id),
                elapsed_ms,
                url,
                exc,
            )
            raise

        elapsed_ms = int((time.perf_counter() - start_t) * 1000)
        content_type = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip()
        final_url = getattr(resp, "url", None)
        is_redirected = bool(final_url and str(final_url) != str(url))

        try:
            html_text = resp.text or ""
        except Exception:
            html_text = ""

        title = ""
        if html_text:
            match = re.search(
                r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL
            )
            if match:
                title = re.sub(r"\s+", " ", match.group(1)).strip()[:80]

        markers = {
            "has_update_time": "update-time" in html_text if html_text else False,
            "has_recent_update": "最近更新" in html_text if html_text else False,
            "has_update_label": "更新时间" in html_text if html_text else False,
            "has_captcha": "验证码" in html_text if html_text else False,
            "has_security_check": "安全验证" in html_text if html_text else False,
            "has_cloudflare": "cloudflare" in html_text.lower() if html_text else False,
        }

        CWM_CRAWLER_DEBUG and plugin_logger.debug(
            "[cwm] Details response: book_id=%s status=%s elapsed_ms=%s redirected=%s final_url=%s content_type=%s encoding=%s apparent_encoding=%s text_len=%s title=%s markers=%s",
            int(book_id),
            getattr(resp, "status_code", None),
            elapsed_ms,
            is_redirected,
            final_url,
            content_type or "unknown",
            getattr(resp, "encoding", None),
            getattr(resp, "apparent_encoding", None),
            len(html_text),
            title or "unknown",
            markers,
        )
        resp.raise_for_status()
        return html_text


class FanqieNovelClient:
    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
    ):
        self.session = session or requests.Session()
        self.timeout_s = int(timeout_s)
        self.session.headers.update(DEFAULT_HEADERS)

    def search_name(self, name: str, page: int = 1) -> str:
        query = str(name or "").strip()
        page_index = max(0, int(page) - 1)
        search_url = f"{FANQIE_BASE_URL}/search/{quote(query)}"
        logger.info(
            "[fq] Search request start. query=%r page=%s page_index=%s search_url=%s",
            query,
            page,
            page_index,
            search_url,
        )
        try:
            warm = self.session.get(search_url, timeout=self.timeout_s)
            logger.debug(
                "[fq] Search warm-up response. query=%r status=%s final_url=%s text_len=%s",
                query,
                getattr(warm, "status_code", None),
                getattr(warm, "url", None),
                len(getattr(warm, "text", "") or ""),
            )
        except Exception as exc:
            logger.warning("[fq] Search warm-up failed. query=%r err=%s", query, exc, exc_info=True)

        url = f"{FANQIE_BASE_URL}/api/author/search/search_book/v1"
        params = {
            "filter": "127,127,127,127",
            "page_count": 10,
            "page_index": page_index,
            "query_type": 0,
            "query_word": query,
        }
        start_t = time.perf_counter()
        resp = self.session.get(
            url,
            params=params,
            headers={
                **DEFAULT_HEADERS,
                "Accept": "application/json, text/plain, */*",
                "Referer": search_url,
            },
            timeout=self.timeout_s,
        )
        elapsed_ms = int((time.perf_counter() - start_t) * 1000)
        logger.info(
            "[fq] Search API response. query=%r page=%s status=%s elapsed_ms=%s final_url=%s text_len=%s content_type=%s has_verify=%s",
            query,
            page,
            getattr(resp, "status_code", None),
            elapsed_ms,
            getattr(resp, "url", None),
            len(getattr(resp, "text", "") or ""),
            (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip(),
            bool(resp.headers.get("bdturing-verify")),
        )
        resp.raise_for_status()
        if resp.text:
            return resp.text

        if resp.headers.get("bdturing-verify"):
            logger.warning(
                "[fq] Search API was blocked by bdturing verification. query=%r page=%s verify_header_len=%s",
                query,
                page,
                len(resp.headers.get("bdturing-verify") or ""),
            )
            return json.dumps(
                {
                    "code": -1001,
                    "message": "FANQIE_SEARCH_BLOCKED",
                    "data": {
                        "reason": "bdturing verification blocked the search API",
                        "query": query,
                        "page": page,
                    },
                },
                ensure_ascii=False,
            )

        logger.warning(
            "[fq] Search API returned empty body; fallback to search page for diagnostics only. query=%r page=%s",
            query,
            page,
        )
        fallback = self.session.get(search_url, timeout=self.timeout_s)
        logger.info(
            "[fq] Search fallback response. query=%r status=%s final_url=%s text_len=%s",
            query,
            getattr(fallback, "status_code", None),
            getattr(fallback, "url", None),
            len(getattr(fallback, "text", "") or ""),
        )
        fallback.raise_for_status()
        return fallback.text

    def get_book_details(self, book_id: int) -> str:
        url = f"{FANQIE_BASE_URL}/page/{int(book_id)}"
        logger.info("[fq] Book page request start. book_id=%s url=%s", int(book_id), url)
        start_t = time.perf_counter()
        resp = self.session.get(url, timeout=self.timeout_s)
        elapsed_ms = int((time.perf_counter() - start_t) * 1000)
        logger.info(
            "[fq] Book page response. book_id=%s status=%s elapsed_ms=%s final_url=%s text_len=%s",
            int(book_id),
            getattr(resp, "status_code", None),
            elapsed_ms,
            getattr(resp, "url", None),
            len(getattr(resp, "text", "") or ""),
        )
        resp.raise_for_status()
        return resp.text

    def get_reader_details(self, item_id: int) -> str:
        url = f"{FANQIE_BASE_URL}/reader/{int(item_id)}"
        logger.info("[fq] Reader page request start. item_id=%s url=%s", int(item_id), url)
        start_t = time.perf_counter()
        resp = self.session.get(url, timeout=self.timeout_s)
        elapsed_ms = int((time.perf_counter() - start_t) * 1000)
        logger.info(
            "[fq] Reader page response. item_id=%s status=%s elapsed_ms=%s final_url=%s text_len=%s",
            int(item_id),
            getattr(resp, "status_code", None),
            elapsed_ms,
            getattr(resp, "url", None),
            len(getattr(resp, "text", "") or ""),
        )
        resp.raise_for_status()
        return resp.text
