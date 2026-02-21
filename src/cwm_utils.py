from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from urllib.parse import urljoin

import requests

from cwm_constants import BASE_URL, DEFAULT_HEADERS, DEFAULT_TIMEOUT_S

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def asia_shanghai_tz() -> tzinfo:
    if ZoneInfo is not None:
        try:
            return ZoneInfo("Asia/Shanghai")  # type: ignore[return-value]
        except Exception:
            pass
    return timezone(timedelta(hours=8))


def cn_number_to_float(text: str) -> float | str:
    """把 '1,234' / '1.2万' / '3亿' 转成 float；无法解析时原样返回。"""
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
    """
    解析类似：'最近更新：2019-08-05 23:39:07 / 571 少女的膝枕'
    返回：(章节名, 时间戳秒)。失败返回 ('', -1)。
    """
    if not update_text:
        return "", -1

    text = update_text.strip()
    text = re.sub(r"^(最近更新|更新时间)[:：]\s*", "", text)

    if "/" in text:
        time_part, chapter_part = [p.strip() for p in text.split("/", 1)]
    else:
        parts = text.split()
        if len(parts) < 2:
            return "", -1
        time_part = " ".join(parts[:2])
        chapter_part = " ".join(parts[2:]).strip()

    try:
        dt = datetime.strptime(time_part, "%Y-%m-%d %H:%M:%S").replace(tzinfo=asia_shanghai_tz())
        ts = int(dt.timestamp())
    except Exception:
        ts = -1

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


def fetch_image_data_uri(url: str, session: requests.Session | None = None) -> str | None:
    """下载图片并转成 data URI，避免渲染时依赖外网资源。失败返回 None。"""
    if not url:
        return None

    sess = session or requests.Session()
    try:
        resp = sess.get(abspath_url(url), timeout=DEFAULT_TIMEOUT_S, headers=DEFAULT_HEADERS)
        resp.raise_for_status()
        content_type = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
        b64 = base64.b64encode(resp.content).decode("ascii")
        return f"data:{content_type};base64,{b64}"
    except Exception as e:
        logger.debug("封面下载失败，将使用占位图: %s (%s)", url, e)
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

