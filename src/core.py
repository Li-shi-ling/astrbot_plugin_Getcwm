from __future__ import annotations

import base64
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.ciweimao.com"
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

    chapter_part = re.sub(r"^[\s/|:：-–—]+", "", chapter_part).strip()
    chapter_part = re.sub(r"[\s/|:：-–—]+$", "", chapter_part).strip()
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
