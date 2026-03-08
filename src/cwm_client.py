from __future__ import annotations

import re
import time

import requests

from .cwm_constants import BASE_URL, DEFAULT_HEADERS, DEFAULT_TIMEOUT_S

CWM_CRAWLER_DEBUG = False  # 爬虫调试日志开关（默认关闭）


class CiweimaoClient:
    def __init__(self, *, session: requests.Session | None = None, timeout_s: int = DEFAULT_TIMEOUT_S):
        self.session = session or requests.Session()
        self.timeout_s = int(timeout_s)
        self.session.headers.update(DEFAULT_HEADERS)

    def search_name(self, name: str, page: int = 1) -> str:
        url = f"{BASE_URL}/get-search-book-list/0-0-0-0-0-0/全部/{name}/{page}"
        from astrbot.api import logger

        CWM_CRAWLER_DEBUG and logger.debug(
            "[cwm] 爬虫请求：搜索。name=%s page=%s url=%s 超时=%ss", name, page, url, self.timeout_s
        )
        start_t = time.perf_counter()
        try:
            resp = self.session.get(url, timeout=self.timeout_s)
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            CWM_CRAWLER_DEBUG and logger.debug(
                "[cwm] 爬虫请求失败：搜索。name=%s page=%s 耗时ms=%s url=%s err=%s",
                name,
                page,
                elapsed_ms,
                url,
                e,
            )
            raise
        elapsed_ms = int((time.perf_counter() - start_t) * 1000)
        content_type = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip()
        text_len = -1
        try:
            text_len = len(resp.text or "")
        except Exception:
            text_len = -1

        CWM_CRAWLER_DEBUG and logger.debug(
            "[cwm] 爬虫响应：搜索。状态码=%s 耗时ms=%s 最终url=%s 内容类型=%s 编码=%s 猜测编码=%s 文本长度=%s",
            getattr(resp, "status_code", None),
            elapsed_ms,
            getattr(resp, "url", None),
            content_type or "未知",
            getattr(resp, "encoding", None),
            getattr(resp, "apparent_encoding", None),
            text_len,
        )
        resp.raise_for_status()
        return resp.text

    def get_book_details(self, book_id: int) -> str:
        url = f"{BASE_URL}/book/{int(book_id)}"
        from astrbot.api import logger

        CWM_CRAWLER_DEBUG and logger.debug(
            "[cwm] 爬虫请求：书籍详情。book_id=%s url=%s 超时=%ss", int(book_id), url, self.timeout_s
        )
        start_t = time.perf_counter()
        try:
            resp = self.session.get(url, timeout=self.timeout_s)
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            CWM_CRAWLER_DEBUG and logger.debug(
                "[cwm] 爬虫请求失败：书籍详情。book_id=%s 耗时ms=%s url=%s err=%s",
                int(book_id),
                elapsed_ms,
                url,
                e,
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
            m = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
            if m:
                title = re.sub(r"\s+", " ", m.group(1)).strip()[:80]

        markers = {
            "包含update-time": ("update-time" in html_text) if html_text else False,
            "包含最近更新": ("最近更新" in html_text) if html_text else False,
            "包含更新时间": ("更新时间" in html_text) if html_text else False,
            "包含验证码": ("验证码" in html_text) if html_text else False,
            "包含安全验证": ("安全验证" in html_text) if html_text else False,
            "包含Cloudflare": ("cloudflare" in html_text.lower()) if html_text else False,
        }

        CWM_CRAWLER_DEBUG and logger.debug(
            "[cwm] 爬虫响应：书籍详情。book_id=%s 状态码=%s 耗时ms=%s 重定向=%s 最终url=%s 内容类型=%s 编码=%s 猜测编码=%s 文本长度=%s 标题=%s 特征=%s",
            int(book_id),
            getattr(resp, "status_code", None),
            elapsed_ms,
            is_redirected,
            final_url,
            content_type or "未知",
            getattr(resp, "encoding", None),
            getattr(resp, "apparent_encoding", None),
            len(html_text),
            title or "未知",
            markers,
        )
        resp.raise_for_status()
        return html_text
