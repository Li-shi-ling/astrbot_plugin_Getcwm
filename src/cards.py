from __future__ import annotations

import math
import base64
import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

try:
    from html2image import Html2Image  # type: ignore
except Exception as e:  # pragma: no cover
    Html2Image = None  # type: ignore[assignment]
    _HTML2IMAGE_IMPORT_ERROR = e

from .core import (
    CardRenderResult,
    fetch_image_data_uri,
    format_ts_cn,
    html_escape,
    line_clamp_css,
    parse_book_details_html_content,
    parse_search_html_content,
)


def _calc_search_card_height(num_items: int) -> int:
    n = max(1, int(num_items))

    body_pad_y = 26 * 2
    card_pad_y = 22 + 18
    header_h = 64
    header_mb = 14
    item_h = 140
    list_gap = 12
    list_h = n * item_h + max(0, n - 1) * list_gap
    footer_mt = 10
    footer_h = 16
    safety = 80
    return (
        body_pad_y
        + card_pad_y
        + header_h
        + header_mb
        + list_h
        + footer_mt
        + footer_h
        + safety
    )


def _estimated_text_lines(text_len: int, chars_per_line: int, min_lines: int = 1) -> int:
    return max(int(min_lines), math.ceil(max(0, int(text_len)) / max(1, chars_per_line)))


def _calc_book_details_card_height(
    num_tags: int,
    num_props: int,
    num_chapters: int = 0,
    chapter_name_len: int = 0,
    chapter_preview_title_len: int = 0,
) -> int:
    tags = max(0, int(num_tags))
    props = max(0, int(num_props))

    body_pad_y = 26 * 2
    card_pad_y = 22 * 2
    top_h = 20
    main_mt = 14

    title_h = 82
    author_h = 26
    tag_rows = math.ceil(min(tags, 10) / 3) if tags else 0
    tags_h = 10 + (tag_rows * 27) + max(0, tag_rows - 1) * 8
    stats_h = 82
    chapter_lines = _estimated_text_lines(chapter_name_len, 32, min_lines=2)
    chapter_h = 48 + chapter_lines * 24
    prop_rows = math.ceil(min(props, 8) / 2) if props else 0
    props_h = 12 + (prop_rows * 58) + max(0, prop_rows - 1) * 10
    chapters_h = 0
    if num_chapters > 0:
        preview_lines = _estimated_text_lines(chapter_preview_title_len, 40)
        row_h = 34 + preview_lines * 20
        chapters_h = 14 + 36 + min(int(num_chapters), 4) * row_h
    intro_h = 124

    right_h = (
        title_h
        + author_h
        + tags_h
        + stats_h
        + chapter_h
        + props_h
        + chapters_h
        + intro_h
    )
    cover_h = 312
    main_h = max(cover_h, right_h)
    safety = 100
    return body_pad_y + card_pad_y + top_h + main_mt + main_h + safety


def _calc_subscribe_update_card_height(chapter_name_len: int = 0) -> int:
    chapter_lines = _estimated_text_lines(chapter_name_len, 36, min_lines=3)
    return 496 + chapter_lines * 28


def _display_value(value: Any, fallback: str = "未知") -> str:
    text = str(value if value is not None else "").strip()
    return text or fallback


def _compact_number(value: Any) -> str:
    try:
        num = int(value or 0)
    except Exception:
        return _display_value(value)
    if num >= 100_000_000:
        return f"{num / 100_000_000:.1f}亿"
    if num >= 10_000:
        return f"{num / 10_000:.1f}万"
    return str(num)


def _extract_display_book_id(url: Any) -> str:
    match = re.search(r"/(?:book|page)/(\d+)", str(url or ""))
    return match.group(1) if match else ""


_CARD_SOURCE_PROFILES: dict[str, dict[str, str]] = {
    "cwm": {
        "name": "刺猬猫",
        "search_title": "刺猬猫 · 搜索结果",
        "detail_title": "刺猬猫 · 书籍详情",
        "subscribe_title": "刺猬猫 · 订阅更新",
        "book_url_template": "https://www.ciweimao.com/book/{book_id}",
    },
    "fq": {
        "name": "番茄小说",
        "search_title": "番茄小说 · 搜索结果",
        "detail_title": "番茄小说 · 书籍详情",
        "subscribe_title": "番茄小说 · 订阅更新",
        "book_url_template": "https://fanqienovel.com/page/{book_id}",
    },
}


_CARD_STYLES = {
    "glass",
    "light",
    "industrial",
    "retro_win",
    "snowcap_shop",
    "constructivist_people",
}


@lru_cache(maxsize=64)
def _asset_data_url(asset_group: str, filename: str) -> str:
    asset_path = Path(__file__).resolve().parents[1] / "assets" / asset_group / filename
    try:
        data = asset_path.read_bytes()
    except OSError:
        return ""

    suffix = asset_path.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
    return f"data:image/{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _normalize_card_style(card_style: Any) -> str:
    style = str(card_style or "glass").strip().lower()
    return style if style in _CARD_STYLES else "glass"


def _card_theme_css(card_style: Any) -> str:
    style = _normalize_card_style(card_style)
    if style == "light":
        return """
  <style id="getcwm-card-theme">
    body {
      background:
        radial-gradient(1000px 540px at 12% 18%, rgba(14,165,233,0.16), transparent 60%),
        radial-gradient(920px 540px at 88% 22%, rgba(245,158,11,0.14), transparent 62%),
        linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%) !important;
      color: #0f172a !important;
    }
    .card, .item, .stat, .chapter, .chapter-list, .block {
      background: rgba(255,255,255,0.88) !important;
      border-color: rgba(2,6,23,0.12) !important;
      box-shadow: 0 18px 45px rgba(15,23,42,0.14) !important;
    }
    .kv, .intro { background: rgba(248,250,252,0.92) !important; border-color: rgba(2,6,23,0.10) !important; }
    .badge, .idx, .tag { background: linear-gradient(135deg, #f59e0b, #38bdf8) !important; color: #111827 !important; }
    .url, .meta, .sub, .time, .footer, .author, .k, .section-title, .chapter-meta { color: #475569 !important; opacity: 1 !important; }
  </style>
        """
    if style == "industrial":
        return """
  <style id="getcwm-card-theme">
    body {
      background:
        linear-gradient(90deg, rgba(148,163,184,0.06) 1px, transparent 1px),
        linear-gradient(0deg, rgba(148,163,184,0.06) 1px, transparent 1px),
        radial-gradient(900px 560px at 86% 18%, rgba(34,211,238,0.16), transparent 62%),
        radial-gradient(900px 560px at 14% 86%, rgba(251,191,36,0.12), transparent 64%),
        linear-gradient(135deg, #070a0f 0%, #0b1220 55%, #020617 100%) !important;
      background-size: 28px 28px, 28px 28px, auto, auto, auto !important;
      color: #e5e7eb !important;
    }
    .card, .item, .stat, .chapter, .chapter-list, .block {
      border-radius: 8px !important;
      background: rgba(17,24,39,0.92) !important;
      border-color: rgba(148,163,184,0.24) !important;
      box-shadow: 0 18px 48px rgba(0,0,0,0.48) !important;
    }
    .kv, .intro { border-radius: 6px !important; background: rgba(2,6,23,0.80) !important; }
    .badge, .idx, .tag { border-radius: 4px !important; background: linear-gradient(135deg, #fbbf24, #22d3ee) !important; color: #020617 !important; }
    .h1, .title { text-shadow: 0 0 18px rgba(34,211,238,0.16) !important; }
  </style>
        """
    if style == "retro_win":
        return """
  <style id="getcwm-card-theme">
    body {
      background: #c5ced1 !important;
      color: #1a1a1a !important;
      font-family: "Microsoft YaHei", "SimSun", Arial, sans-serif !important;
    }
    .card {
      border-radius: 0 !important;
      background: #f4f0e6 !important;
      border: 3px solid #1a1a1a !important;
      box-shadow: 8px 8px 0 #1a1a1a !important;
    }
    .card:before { display: none !important; }
    .item, .stat, .chapter, .chapter-list, .block, .kv, .intro {
      border-radius: 0 !important;
      background: #ffffff !important;
      border: 2px solid #1a1a1a !important;
      box-shadow: none !important;
    }
    .badge, .idx, .tag {
      border-radius: 0 !important;
      background: #f39800 !important;
      color: #1a1a1a !important;
      border: 2px solid #1a1a1a !important;
      box-shadow: none !important;
    }
    .h1, .title { text-shadow: none !important; }
    .url, .meta, .sub, .time, .footer, .author, .k, .section-title, .chapter-meta { color: #3b3b3b !important; opacity: 1 !important; }
  </style>
        """
    if style == "snowcap_shop":
        sign = _asset_data_url("snowcap_shop", "sign.png")
        bottle = _asset_data_url("snowcap_shop", "bottle.png")
        bag = _asset_data_url("snowcap_shop", "bag.png")
        tray = _asset_data_url("snowcap_shop", "tray.png")
        mascot = _asset_data_url("snowcap_shop", "mascot.png")
        return f"""
  <style id="getcwm-card-theme">
    body {{
      background:
        linear-gradient(to right, rgba(255,255,255,0.26) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(255,255,255,0.24) 1px, transparent 1px),
        radial-gradient(740px 420px at 15% 0%, rgba(239,223,199,0.24), transparent 64%),
        linear-gradient(180deg, #9aae7c, #7f965f) !important;
      background-size: 48px 48px, 48px 48px, auto, auto !important;
      color: #1f241a !important;
      font-family: "Bahnschrift", "Microsoft YaHei", "PingFang SC", Arial, sans-serif !important;
    }}
    .card {{
      border: 5px solid #5d7028 !important;
      border-radius: 18px !important;
      background:
        linear-gradient(180deg, rgba(255,247,233,0.92), rgba(239,223,199,0.96)) !important;
      box-shadow: 14px 14px 0 rgba(31,36,26,0.16) !important;
    }}
    .card:before {{
      content: "" !important;
      position: absolute !important;
      inset: 12px !important;
      width: auto !important;
      height: auto !important;
      border: 2px dashed rgba(93,112,40,0.42) !important;
      border-radius: 11px !important;
      background:
        url("{bottle}") no-repeat left 10px bottom 12px / 82px auto,
        url("{bag}") no-repeat right 16px top 76px / 84px auto,
        url("{tray}") no-repeat right 18px bottom 14px / 76px auto !important;
      transform: none !important;
      opacity: 0.34 !important;
    }}
    .card:after {{
      content: "" !important;
      position: absolute !important;
      right: 16px !important;
      top: 12px !important;
      width: 116px !important;
      height: 116px !important;
      background: url("{mascot}") no-repeat center / contain !important;
      opacity: 0.24 !important;
      pointer-events: none !important;
    }}
    .top, .header {{ padding-right: 124px !important; }}
    .brand, .h1 {{
      color: #c53926 !important;
      text-shadow: 2px 2px 0 rgba(255,247,233,0.92) !important;
    }}
    .header:before {{
      content: "" !important;
      display: block !important;
      width: 150px !important;
      height: 56px !important;
      margin-bottom: 8px !important;
      background: url("{sign}") no-repeat left center / contain !important;
    }}
    .item, .stat, .chapter, .chapter-list, .block, .kv, .intro {{
      border: 3px solid #5d7028 !important;
      border-radius: 8px !important;
      background: #fff7e9 !important;
      box-shadow: 4px 4px 0 rgba(93,112,40,0.16) !important;
    }}
    .badge, .idx, .tag, .book-id {{
      border: 2px solid #5d7028 !important;
      border-radius: 7px !important;
      background: #efdfc7 !important;
      color: #5d7028 !important;
      box-shadow: none !important;
    }}
    .url, .meta, .sub, .time, .footer, .author, .k, .section-title, .chapter-meta {{
      color: #6f7653 !important;
      opacity: 1 !important;
    }}
  </style>
        """
    if style == "constructivist_people":
        home_bg = _asset_data_url("constructivist_people", "people_we_home_bg.jpg")
        detail_bg = _asset_data_url("constructivist_people", "people_we_detail_bg.jpg")
        name_label = _asset_data_url("constructivist_people", "name_label.png")
        red_mark = _asset_data_url("constructivist_people", "red_brush_mark.png")
        barrage = _asset_data_url("constructivist_people", "barrage_strip.png")
        return f"""
  <style id="getcwm-card-theme">
    body {{
      background:
        linear-gradient(180deg, rgba(232,229,220,0.06), rgba(10,10,10,0.12)),
        url("{home_bg}") no-repeat center / cover,
        linear-gradient(180deg, #e8e5dc, #cfcfc9) !important;
      color: #24231f !important;
      font-family: "Bahnschrift", "Microsoft YaHei", "PingFang SC", sans-serif !important;
      letter-spacing: 0.01em !important;
    }}
    .card {{
      border: 0 !important;
      border-radius: 0 !important;
      background:
        linear-gradient(180deg, rgba(239,238,226,0.56), rgba(215,216,204,0.48)),
        url("{detail_bg}") no-repeat center / cover !important;
      box-shadow:
        0 0 0 2px rgba(38,37,34,0.12),
        18px 18px 0 rgba(38,37,34,0.20) !important;
    }}
    .card:before {{
      content: "" !important;
      position: absolute !important;
      left: 22px !important;
      top: 28px !important;
      width: 185px !important;
      height: 82px !important;
      background: url("{name_label}") no-repeat left top / contain !important;
      transform: none !important;
      opacity: 0.22 !important;
      pointer-events: none !important;
    }}
    .card:after {{
      content: "" !important;
      position: absolute !important;
      right: 22px !important;
      top: 58px !important;
      width: 220px !important;
      height: 54px !important;
      background: url("{barrage}") no-repeat center / contain !important;
      opacity: 0.54 !important;
      pointer-events: none !important;
    }}
    .top, .header {{
      padding: 10px 230px 12px 18px !important;
      min-height: 88px !important;
      border-left: 5px solid #9f302a !important;
      background:
        linear-gradient(90deg, rgba(239,238,226,0.42), rgba(239,238,226,0.12), transparent) !important;
    }}
    .brand, .h1, .title {{
      color: #262522 !important;
      text-shadow: none !important;
      font-weight: 950 !important;
    }}
    .top:after, .header:after {{
      content: "" !important;
      position: absolute !important;
      left: 18px !important;
      bottom: -18px !important;
      width: 210px !important;
      height: 40px !important;
      background: url("{red_mark}") no-repeat left center / contain !important;
      opacity: 0.72 !important;
    }}
    .item, .stat, .chapter, .chapter-list, .block, .kv, .intro {{
      border: 2px solid #262522 !important;
      border-radius: 0 !important;
      background: rgba(239,238,226,0.50) !important;
      box-shadow: 7px 7px 0 rgba(38,37,34,0.14) !important;
      backdrop-filter: blur(2px) !important;
    }}
    .badge, .idx, .tag, .book-id {{
      border: 2px solid #262522 !important;
      border-radius: 0 !important;
      background: rgba(25,25,25,0.92) !important;
      color: #f4f1e8 !important;
      box-shadow: 4px 4px 0 rgba(159,48,42,0.42) !important;
    }}
    .stat .v, .kv .v, .chapter .v {{ color: #9f302a !important; }}
    .url, .meta, .sub, .time, .footer, .author, .k, .section-title, .chapter-meta {{
      color: #5f5a4f !important;
      opacity: 1 !important;
      font-weight: 800 !important;
    }}
  </style>
        """
    return ""


def _card_source_profile(source: Any) -> dict[str, str]:
    source_key = str(source or "cwm").strip().lower()
    return _CARD_SOURCE_PROFILES.get(source_key, _CARD_SOURCE_PROFILES["cwm"])


def _build_search_card_data(
    results: list[Mapping[str, Any]],
    *,
    query: str | None,
    max_items: int,
    source: Any,
) -> dict[str, Any]:
    items = list(results)[: max(1, int(max_items))]
    return {
        "profile": _card_source_profile(source),
        "items": items,
        "query": query,
        "total_count": len(results),
        "shown_count": len(items),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _build_book_details_card_data(details: Mapping[str, Any]) -> dict[str, Any]:
    source = str(details.get("Source") or details.get("source") or "cwm").strip()
    profile = _card_source_profile(source)
    is_fanqie = profile["name"] == "番茄小说"

    stat_map = dict(details.get("data2", {}) or {})
    prop_map = dict(details.get("data", {}) or {})
    fanqie_extra = dict(details.get("fanqie_extra", {}) or {})
    chapter_preview = list(fanqie_extra.get("chapter_preview", []) or [])
    stat_click = stat_map.get("总点击", "")
    stat_fav = stat_map.get("总收藏", "")
    stat_words = stat_map.get("总字数", "")

    if is_fanqie:
        prop_items = [
            ("来源", prop_map.get("来源", profile["name"])),
            ("状态", prop_map.get("状态", "")),
            (
                "分卷",
                "、".join(fanqie_extra.get("volume_names", []) or [])
                or prop_map.get("分卷", ""),
            ),
            ("原始作者", fanqie_extra.get("original_authors", "")),
        ]
        prop_items = [(key, val) for key, val in prop_items if _display_value(val, "")]
        stat_cards = [
            (
                "阅读量",
                _compact_number(
                    fanqie_extra.get("read_count")
                    or stat_map.get("阅读量")
                    or stat_click
                ),
            ),
            (
                "章节数",
                _display_value(fanqie_extra.get("chapter_total") or prop_map.get("章节数")),
            ),
            ("总字数", _display_value(stat_words)),
        ]
    else:
        prop_items = list(prop_map.items())[:8]
        chapter_preview = []
        stat_cards = [
            ("总点击", _display_value(stat_click)),
            ("总收藏", _display_value(stat_fav)),
            ("总字数", _display_value(stat_words)),
        ]

    return {
        "profile": profile,
        "works_name": details.get("Works_Name", "") or "",
        "author_name": details.get("Author_Name", "") or "",
        "tag_list": list(details.get("Tag_List", []) or []),
        "chapter_name": details.get("Chapter_Name", "") or "",
        "update_ts": int(details.get("Update_Time", -1) or -1),
        "cover_url": details.get("Cover_Image", "") or "",
        "prop_items": prop_items,
        "stat_cards": stat_cards,
        "chapter_preview": chapter_preview,
        "intro": (details.get("Brief_Introduction", "") or "").strip() or "（无简介）",
    }


def _build_subscribe_update_card_data(
    details: Mapping[str, Any], *, book_id: int
) -> dict[str, Any]:
    source = str(details.get("Source") or details.get("source") or "cwm").strip()
    profile = _card_source_profile(source)
    return {
        "profile": profile,
        "works_name": details.get("Works_Name", "") or f"书籍ID：{int(book_id)}",
        "author_name": details.get("Author_Name", "") or "未知作者",
        "chapter_name": details.get("Chapter_Name", "") or "未知章节",
        "update_ts": int(details.get("Update_Time", -1) or -1),
        "cover_url": details.get("Cover_Image", "") or "",
        "book_url": profile["book_url_template"].format(book_id=int(book_id)),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _normalize_t2i_endpoint(endpoint: Any) -> str:
    base = str(endpoint or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/text2img/generate"):
        return base
    if base.endswith("/text2img"):
        return f"{base}/generate"
    return f"{base}/text2img/generate"


def _is_image_bytes(data: bytes) -> bool:
    return data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8")


def _decode_t2i_json_image(data: Any) -> bytes | None:
    if isinstance(data, str):
        text = data.strip()
        if text.startswith("data:image/") and "," in text:
            text = text.split(",", 1)[1]
        try:
            decoded = base64.b64decode(text, validate=False)
        except Exception:
            return None
        return decoded if _is_image_bytes(decoded) else None
    if isinstance(data, Mapping):
        for key in ("image", "img", "data", "result", "base64"):
            decoded = _decode_t2i_json_image(data.get(key))
            if decoded:
                return decoded
    return None


def _html_to_image_t2i_document(html_str: str, size: tuple[int, int]) -> str:
    width, height = int(size[0]), int(size[1])
    fixed_size_css = f"""
  <style id="getcwm-t2i-fixed-size">
    html, body {{
      width: 100vw !important;
      min-width: {width}px !important;
      max-width: none !important;
      height: auto !important;
      min-height: 0 !important;
      margin: 0 !important;
      overflow: visible !important;
    }}
    body {{
      padding: 26px !important;
    }}
    .card {{
      width: 100% !important;
      min-height: 0 !important;
      height: auto !important;
      overflow: hidden !important;
    }}
  </style>
    """
    if "</head>" in html_str:
        return html_str.replace("</head>", f"{fixed_size_css}</head>", 1)
    return fixed_size_css + html_str


def _render_html_to_png_t2i(
    *,
    html_str: str,
    size: tuple[int, int],
    output_dir: Path,
    filename: str,
    endpoint: str,
    timeout: float,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    url = _normalize_t2i_endpoint(endpoint)
    if not url:
        raise RuntimeError("T2I endpoint is empty")

    t2i_html = _html_to_image_t2i_document(html_str, size)
    payload = {
        "tmpl": t2i_html,
        "json": False,
        "tmpldata": {},
        "options": {
            "full_page": True,
            "type": "png",
            "scale": "device",
            "device_scale_factor_level": "ultra",
        },
    }
    response = requests.post(url, json=payload, timeout=max(1.0, float(timeout or 20)))
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    body = response.content

    image_bytes: bytes | None = body if _is_image_bytes(body) or "image/" in content_type else None
    if image_bytes is None:
        try:
            image_bytes = _decode_t2i_json_image(response.json())
        except Exception:
            image_bytes = None
    if image_bytes is None:
        raise RuntimeError(f"T2I returned non-image response: {body[:80]!r}")

    out_path = output_dir / filename
    out_path.write_bytes(image_bytes)
    return out_path


def _render_html_to_png(
    *,
    html_str: str,
    size: tuple[int, int],
    output_dir: Path,
    filename: str,
    t2i_enabled: bool = False,
    t2i_endpoint: str = "",
    t2i_timeout: float = 20,
) -> Path:
    if t2i_enabled and str(t2i_endpoint or "").strip():
        try:
            return _render_html_to_png_t2i(
                html_str=html_str,
                size=size,
                output_dir=output_dir,
                filename=filename,
                endpoint=t2i_endpoint,
                timeout=t2i_timeout,
            )
        except Exception:
            from astrbot.api import logger as _logger

            _logger.warning(
                "[Getcwm][渲染] T2I 渲染失败，回退到本地 Html2Image: endpoint=%s filename=%s",
                t2i_endpoint,
                filename,
                exc_info=True,
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    if Html2Image is None:  # pragma: no cover
        err = globals().get("_HTML2IMAGE_IMPORT_ERROR")
        raise RuntimeError(
            f"Missing dependency html2image, unable to render image: {err!s}"
        )
    hti = Html2Image(output_path=str(output_dir))
    try:
        hti.screenshot(html_str=html_str, save_as=filename, size=size)
    except Exception as exc:
        raise RuntimeError(f"Html2Image render failed: {exc}") from exc
    return output_dir / filename


def render_search_card(
    results: list[Mapping[str, Any]],
    *,
    query: str | None = None,
    max_items: int = 8,
    source: str = "cwm",
    card_style: str = "glass",
    t2i_enabled: bool = False,
    t2i_endpoint: str = "",
    t2i_timeout: float = 20,
    output_dir: str | Path = "./renders",
) -> str:
    card_data = _build_search_card_data(
        results, query=query, max_items=max_items, source=source
    )
    items = card_data["items"]
    profile = card_data["profile"]
    now_str = card_data["generated_at"]

    width = 1024
    height = _calc_search_card_height(len(items))
    query_badge = f"<div class='badge'>{html_escape(query)}</div>" if query else ""

    rows_html: list[str] = []
    for idx, item in enumerate(items, start=1):
        title = html_escape(item.get("title", ""))
        author = html_escape(item.get("author", ""))
        update_time = html_escape(item.get("update_time", ""))
        desc = html_escape(item.get("description", ""))
        raw_read_url = item.get("read_url", "")
        read_url = html_escape(raw_read_url)
        book_id = _extract_display_book_id(raw_read_url)
        id_badge = (
            f"<span class='book-id'>ID: {html_escape(book_id)}</span>"
            if book_id
            else ""
        )
        desc_html = (
            f"<div class='desc'>{desc}</div>"
            if desc
            else "<div class='desc muted'>(No description)</div>"
        )
        rows_html.append(
            f"""
            <div class="item">
              <div class="idx">{idx}</div>
              <div class="content">
                <div class="t">{title}</div>
                <div class="meta">作者：{author} · {update_time} {id_badge}</div>
                {desc_html}
                <div class="url">{read_url}</div>
              </div>
            </div>
            """
        )

    html_str = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ width: 100%; height: 100%; margin: 0; padding: 0; }}
    body {{
      font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif;
      background:
        radial-gradient(1200px 600px at 10% 10%, rgba(255, 120, 200, 0.45), transparent 60%),
        radial-gradient(900px 500px at 90% 20%, rgba(120, 180, 255, 0.45), transparent 55%),
        radial-gradient(1000px 700px at 50% 90%, rgba(170, 255, 210, 0.18), transparent 60%),
        linear-gradient(135deg, #1b1636 0%, #0d1026 40%, #101b2f 100%);
      color: rgba(255,255,255,0.92);
      padding: 26px;
    }}
    .card {{
      height: 100%;
      border-radius: 26px;
      padding: 22px 22px 18px 22px;
      background: rgba(255,255,255,0.10);
      border: 1px solid rgba(255,255,255,0.18);
      box-shadow: 0 18px 50px rgba(0,0,0,0.35);
      overflow: hidden;
      position: relative;
    }}
    .card:before {{
      content: "";
      position: absolute;
      inset: -120px -80px auto auto;
      width: 360px;
      height: 360px;
      background: radial-gradient(circle at 30% 30%, rgba(255,255,255,0.25), transparent 60%);
      transform: rotate(18deg);
      opacity: 0.9;
    }}
    .header {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      margin-bottom: 14px;
      position: relative;
      z-index: 1;
    }}
    .h1 {{
      font-size: 34px;
      font-weight: 900;
      letter-spacing: 0.5px;
      text-shadow: 0 2px 0 rgba(0,0,0,0.25);
    }}
    .sub {{
      margin-top: 6px;
      font-size: 13px;
      opacity: 0.85;
    }}
    .badge {{
      padding: 10px 14px;
      border-radius: 999px;
      background: linear-gradient(135deg, rgba(255,120,200,0.95), rgba(120,180,255,0.95));
      color: rgba(10, 10, 20, 0.95);
      font-weight: 800;
      box-shadow: 0 10px 22px rgba(0,0,0,0.22);
      max-width: 360px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .list {{ display: flex; flex-direction: column; gap: 12px; position: relative; z-index: 1; }}
    .item {{
      display: flex;
      gap: 14px;
      padding: 14px 16px;
      border-radius: 18px;
      background: linear-gradient(135deg, rgba(255,255,255,0.16), rgba(255,255,255,0.06));
      border: 1px solid rgba(255,255,255,0.14);
      backdrop-filter: blur(6px);
    }}
    .idx {{
      width: 38px;
      height: 38px;
      border-radius: 999px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 900;
      color: rgba(10, 10, 20, 0.95);
      background: linear-gradient(135deg, rgba(255,215,120,0.95), rgba(255,120,200,0.95));
      box-shadow: 0 10px 20px rgba(0,0,0,0.18);
      flex: 0 0 auto;
      margin-top: 2px;
    }}
    .content {{ flex: 1 1 auto; min-width: 0; }}
    .t {{
      font-size: 19px;
      font-weight: 900;
      line-height: 1.25;
      {line_clamp_css(1)}
    }}
    .meta {{
      margin-top: 5px;
      font-size: 13px;
      opacity: 0.88;
      {line_clamp_css(1)}
    }}
    .book-id {{
      display: inline-block;
      margin-left: 8px;
      padding: 2px 7px;
      border-radius: 999px;
      color: rgba(10,10,20,0.92);
      background: rgba(255,215,120,0.95);
      font-weight: 900;
    }}
    .desc {{
      margin-top: 7px;
      font-size: 13px;
      line-height: 1.35;
      opacity: 0.85;
      {line_clamp_css(2)}
    }}
    .desc.muted {{ opacity: 0.62; }}
    .url {{
      margin-top: 7px;
      font-size: 12px;
      opacity: 0.75;
      word-break: break-all;
      {line_clamp_css(1)}
    }}
    .footer {{
      margin-top: 10px;
      font-size: 12px;
      opacity: 0.7;
      text-align: right;
      position: relative;
      z-index: 1;
    }}
  </style>
  {_card_theme_css(card_style)}
</head>
<body>
  <div class="card">
    <div class="header">
      <div>
        <div class="h1">{html_escape(profile["search_title"])}</div>
        <div class="sub">共 {html_escape(card_data["total_count"])} 条 · 展示前 {html_escape(card_data["shown_count"])} 条 · 生成于 {now_str}</div>
      </div>
      {query_badge}
    </div>
    <div class="list">
      {"".join(rows_html)}
    </div>
    <div class="footer">Getcwm / Html2Image</div>
  </div>
</body>
</html>
"""

    filename = f"search_{uuid.uuid4().hex}.png"
    out_path = _render_html_to_png(
        html_str=html_str,
        size=(width, height),
        output_dir=Path(output_dir),
        filename=filename,
        t2i_enabled=t2i_enabled,
        t2i_endpoint=t2i_endpoint,
        t2i_timeout=t2i_timeout,
    )
    return str(out_path)


def render_book_details_card(
    details: Mapping[str, Any],
    *,
    output_dir: str | Path = "./renders",
    session: Any | None = None,
    card_style: str = "glass",
    t2i_enabled: bool = False,
    t2i_endpoint: str = "",
    t2i_timeout: float = 20,
) -> str:
    card_data = _build_book_details_card_data(details)
    profile = card_data["profile"]
    works_name = card_data["works_name"]
    author_name = card_data["author_name"]
    tag_list = card_data["tag_list"]
    chapter_name = card_data["chapter_name"]
    update_ts = card_data["update_ts"]
    cover_url = card_data["cover_url"]
    prop_items = card_data["prop_items"]
    stat_cards = card_data["stat_cards"]
    chapter_preview = card_data["chapter_preview"]
    intro = card_data["intro"]

    cover_data_uri = fetch_image_data_uri(str(cover_url), session=session)
    cover_html = (
        f"<img class='cover' src='{cover_data_uri}' alt='cover' />"
        if cover_data_uri
        else "<div class='cover placeholder'>无封面</div>"
    )

    tags_html = "".join(
        f"<span class='tag'>{html_escape(tag)}</span>" for tag in tag_list[:10]
    )
    props_html = "".join(
        f"<div class='kv'><div class='k'>{html_escape(key)}</div><div class='v'>{html_escape(val)}</div></div>"
        for key, val in prop_items
    )
    stats_html = "".join(
        f"<div class='stat'><div class='k'>{html_escape(key)}</div><div class='v'>{html_escape(val)}</div></div>"
        for key, val in stat_cards
    )
    chapter_rows_html = ""
    if chapter_preview:
        rows: list[str] = []
        for chapter in chapter_preview[-4:]:
            if not isinstance(chapter, Mapping):
                continue
            order = _display_value(chapter.get("order"), "")
            title = _display_value(chapter.get("title"), "未知章节")
            volume = _display_value(chapter.get("volume"), "")
            first_pass_ts = int(chapter.get("first_pass_time") or -1)
            prefix = f"第{order}章" if order else "章节"
            meta_parts = [part for part in [volume, format_ts_cn(first_pass_ts) if first_pass_ts > 0 else ""] if part]
            rows.append(
                f"<div class='chapter-row'><div class='chapter-title'>{html_escape(prefix)} · {html_escape(title)}</div><div class='chapter-meta'>{html_escape(' / '.join(meta_parts))}</div></div>"
            )
        if rows:
            chapter_rows_html = f"""
        <div class="chapter-list">
          <div class="section-title">最近章节</div>
          {"".join(rows)}
        </div>
            """

    width = 1024
    height = _calc_book_details_card_height(
        min(len(tag_list), 10),
        len(prop_items),
        len(chapter_preview),
        len(str(chapter_name or "")),
        max(
            [len(str(chapter.get("title", "") or "")) for chapter in chapter_preview if isinstance(chapter, Mapping)]
            or [0]
        ),
    )

    html_str = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ width: 100%; height: 100%; margin: 0; padding: 0; }}
    body {{
      font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif;
      background:
        radial-gradient(980px 580px at 15% 20%, rgba(255, 140, 210, 0.48), transparent 62%),
        radial-gradient(900px 640px at 88% 30%, rgba(125, 190, 255, 0.46), transparent 60%),
        radial-gradient(900px 520px at 55% 95%, rgba(180, 255, 215, 0.20), transparent 60%),
        linear-gradient(135deg, #201437 0%, #0f1026 45%, #0f1a33 100%);
      color: rgba(255,255,255,0.92);
      padding: 26px;
    }}
    .card {{
      height: 100%;
      border-radius: 28px;
      padding: 22px;
      background: rgba(255,255,255,0.10);
      border: 1px solid rgba(255,255,255,0.18);
      box-shadow: 0 18px 50px rgba(0,0,0,0.35);
      overflow: hidden;
      position: relative;
    }}
    .card:before {{
      content: "";
      position: absolute;
      inset: -140px auto auto -120px;
      width: 420px;
      height: 420px;
      background: radial-gradient(circle at 35% 35%, rgba(255,255,255,0.22), transparent 62%);
      transform: rotate(-18deg);
      opacity: 0.9;
    }}
    .top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      position: relative;
      z-index: 1;
    }}
    .brand {{
      font-weight: 900;
      font-size: 14px;
      letter-spacing: 0.5px;
      opacity: 0.88;
    }}
    .time {{
      font-size: 12px;
      opacity: 0.72;
    }}
    .main {{
      display: grid;
      grid-template-columns: 220px 1fr;
      gap: 18px;
      margin-top: 14px;
      position: relative;
      z-index: 1;
    }}
    .cover, .cover.placeholder {{
      width: 220px;
      height: 312px;
      border-radius: 20px;
      object-fit: cover;
      background: linear-gradient(135deg, rgba(255,120,200,0.35), rgba(120,180,255,0.35));
      border: 1px solid rgba(255,255,255,0.18);
      box-shadow: 0 18px 35px rgba(0,0,0,0.35);
    }}
    .cover.placeholder {{
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 900;
      color: rgba(10,10,20,0.92);
      letter-spacing: 1px;
    }}
    .right {{
      display: flex;
      flex-direction: column;
      min-width: 0;
    }}
    .title {{
      font-size: 34px;
      font-weight: 950;
      line-height: 1.18;
      text-shadow: 0 2px 0 rgba(0,0,0,0.25);
      {line_clamp_css(2)}
    }}
    .author {{
      margin-top: 8px;
      font-size: 14px;
      opacity: 0.88;
      {line_clamp_css(1)}
    }}
    .tags {{
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .tag {{
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      color: rgba(10,10,20,0.92);
      background: linear-gradient(135deg, rgba(255,215,120,0.95), rgba(255,120,200,0.95));
      box-shadow: 0 10px 18px rgba(0,0,0,0.16);
      max-width: 180px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .stats {{
      margin-top: 14px;
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }}
    .stat {{
      border-radius: 16px;
      padding: 12px 12px 10px 12px;
      background: linear-gradient(135deg, rgba(255,255,255,0.16), rgba(255,255,255,0.06));
      border: 1px solid rgba(255,255,255,0.14);
    }}
    .stat .k {{ font-size: 12px; opacity: 0.78; }}
    .stat .v {{ margin-top: 6px; font-size: 18px; font-weight: 900; }}
    .chapter {{
      margin-top: 12px;
      padding: 12px 14px;
      border-radius: 18px;
      background: linear-gradient(135deg, rgba(255,255,255,0.16), rgba(255,255,255,0.06));
      border: 1px solid rgba(255,255,255,0.14);
    }}
    .chapter .k {{ font-size: 12px; opacity: 0.78; }}
    .chapter .v {{
      margin-top: 7px;
      font-size: 14px;
      font-weight: 900;
      line-height: 1.28;
      white-space: normal;
      overflow-wrap: anywhere;
    }}
    .props {{
      margin-top: 12px;
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
    }}
    .kv {{
      border-radius: 16px;
      padding: 10px 12px;
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.12);
      min-width: 0;
    }}
    .kv .k {{ font-size: 12px; opacity: 0.78; {line_clamp_css(1)} }}
    .kv .v {{ margin-top: 5px; font-size: 14px; font-weight: 900; {line_clamp_css(1)} }}
    .chapter-list {{
      margin-top: 12px;
      border-radius: 18px;
      padding: 12px 14px;
      background: linear-gradient(135deg, rgba(255,255,255,0.14), rgba(255,255,255,0.05));
      border: 1px solid rgba(255,255,255,0.14);
    }}
    .section-title {{ font-size: 12px; opacity: 0.78; margin-bottom: 8px; }}
    .chapter-row {{
      padding: 8px 0;
      border-top: 1px solid rgba(255,255,255,0.10);
    }}
    .chapter-row:first-of-type {{ border-top: 0; padding-top: 0; }}
    .chapter-title {{
      font-size: 13px;
      font-weight: 900;
      line-height: 1.25;
      white-space: normal;
      overflow-wrap: anywhere;
    }}
    .chapter-meta {{
      margin-top: 4px;
      font-size: 11px;
      opacity: 0.72;
      {line_clamp_css(1)}
    }}
    .intro {{
      margin-top: 12px;
      border-radius: 18px;
      padding: 12px 14px;
      background: rgba(0,0,0,0.22);
      border: 1px solid rgba(255,255,255,0.12);
    }}
    .intro .k {{ font-size: 12px; opacity: 0.78; }}
    .intro .v {{
      margin-top: 7px;
      font-size: 13px;
      line-height: 1.45;
      opacity: 0.9;
      {line_clamp_css(4)}
    }}
  </style>
  {_card_theme_css(card_style)}
</head>
<body>
  <div class="card">
    <div class="top">
      <div class="brand">{html_escape(profile["detail_title"])}</div>
      <div class="time">更新时间：{html_escape(format_ts_cn(update_ts))}</div>
    </div>
    <div class="main">
      <div>
        {cover_html}
      </div>
      <div class="right">
        <div class="title">{html_escape(works_name)}</div>
        <div class="author">作者：{html_escape(author_name)}</div>
        <div class="tags">{tags_html}</div>

        <div class="stats">
          {stats_html}
        </div>

        <div class="chapter">
          <div class="k">最新章节</div>
          <div class="v">{html_escape(chapter_name)}</div>
        </div>

        <div class="props">
          {props_html}
        </div>

        {chapter_rows_html}

        <div class="intro">
          <div class="k">简介</div>
          <div class="v">{html_escape(intro)}</div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""

    filename = f"book_{uuid.uuid4().hex}.png"
    out_path = _render_html_to_png(
        html_str=html_str,
        size=(width, height),
        output_dir=Path(output_dir),
        filename=filename,
        t2i_enabled=t2i_enabled,
        t2i_endpoint=t2i_endpoint,
        t2i_timeout=t2i_timeout,
    )
    return str(out_path)


def render_subscribe_update_card(
    details: Mapping[str, Any],
    *,
    book_id: int,
    output_dir: str | Path = "./renders",
    session: Any | None = None,
    card_style: str = "glass",
    t2i_enabled: bool = False,
    t2i_endpoint: str = "",
    t2i_timeout: float = 20,
) -> str:
    card_data = _build_subscribe_update_card_data(details, book_id=book_id)
    profile = card_data["profile"]
    works_name = card_data["works_name"]
    author_name = card_data["author_name"]
    chapter_name = card_data["chapter_name"]
    update_ts = card_data["update_ts"]
    cover_url = card_data["cover_url"]
    book_url = card_data["book_url"]
    now_str = card_data["generated_at"]

    cover_data_uri = fetch_image_data_uri(str(cover_url), session=session)
    cover_html = (
        f"<img class='cover' src='{cover_data_uri}' alt='cover' />"
        if cover_data_uri
        else "<div class='cover placeholder'>无封面</div>"
    )

    width = 1024
    height = _calc_subscribe_update_card_height(len(str(chapter_name or "")))

    html_str = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ width: 100%; height: 100%; margin: 0; padding: 0; }}
    body {{
      font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", Arial, sans-serif;
      background:
        radial-gradient(1100px 620px at 12% 16%, rgba(130, 255, 210, 0.38), transparent 62%),
        radial-gradient(900px 560px at 92% 24%, rgba(120, 170, 255, 0.42), transparent 60%),
        radial-gradient(1000px 700px at 55% 95%, rgba(255, 210, 120, 0.18), transparent 62%),
        linear-gradient(135deg, #11243a 0%, #0d1426 45%, #0c1f2a 100%);
      color: rgba(255,255,255,0.92);
      padding: 26px;
    }}
    .card {{
      height: 100%;
      border-radius: 28px;
      padding: 22px;
      background: rgba(255,255,255,0.10);
      border: 1px solid rgba(255,255,255,0.18);
      box-shadow: 0 18px 50px rgba(0,0,0,0.35);
      overflow: hidden;
      position: relative;
    }}
    .card:before {{
      content: "";
      position: absolute;
      inset: -160px -120px auto auto;
      width: 520px;
      height: 520px;
      background: radial-gradient(circle at 30% 30%, rgba(255,255,255,0.20), transparent 62%);
      transform: rotate(16deg);
      opacity: 0.95;
    }}
    .top {{
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      position: relative;
      z-index: 1;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 950;
      letter-spacing: 0.5px;
    }}
    .brand .t {{ font-size: 14px; opacity: 0.88; }}
    .badge {{
      padding: 8px 12px;
      border-radius: 999px;
      background: linear-gradient(135deg, rgba(130, 255, 210, 0.95), rgba(120, 170, 255, 0.95));
      color: rgba(10, 10, 20, 0.92);
      font-weight: 950;
      font-size: 12px;
      box-shadow: 0 10px 22px rgba(0,0,0,0.22);
    }}
    .time {{
      font-size: 12px;
      opacity: 0.72;
      text-align: right;
      line-height: 1.2;
    }}
    .main {{
      display: grid;
      grid-template-columns: 210px 1fr;
      gap: 18px;
      margin-top: 14px;
      position: relative;
      z-index: 1;
    }}
    .cover, .cover.placeholder {{
      width: 210px;
      height: 300px;
      border-radius: 20px;
      object-fit: cover;
      background: linear-gradient(135deg, rgba(120,170,255,0.35), rgba(130,255,210,0.35));
      border: 1px solid rgba(255,255,255,0.18);
      box-shadow: 0 18px 35px rgba(0,0,0,0.35);
    }}
    .cover.placeholder {{
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 900;
      color: rgba(10,10,20,0.92);
      letter-spacing: 1px;
    }}
    .right {{
      display: flex;
      flex-direction: column;
      min-width: 0;
    }}
    .title {{
      font-size: 34px;
      font-weight: 950;
      line-height: 1.18;
      text-shadow: 0 2px 0 rgba(0,0,0,0.25);
      {line_clamp_css(2)}
    }}
    .author {{
      margin-top: 8px;
      font-size: 14px;
      opacity: 0.88;
      {line_clamp_css(1)}
    }}
    .block {{
      margin-top: 12px;
      padding: 12px 14px;
      border-radius: 18px;
      background: linear-gradient(135deg, rgba(255,255,255,0.16), rgba(255,255,255,0.06));
      border: 1px solid rgba(255,255,255,0.14);
    }}
    .block .k {{ font-size: 12px; opacity: 0.78; }}
    .block .v {{
      margin-top: 7px;
      font-size: 14px;
      font-weight: 950;
      line-height: 1.32;
      white-space: normal;
      overflow-wrap: anywhere;
    }}
    .row {{
      margin-top: 12px;
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
    }}
    .kv {{
      border-radius: 16px;
      padding: 10px 12px;
      background: rgba(0,0,0,0.18);
      border: 1px solid rgba(255,255,255,0.12);
      min-width: 0;
    }}
    .kv .k {{ font-size: 12px; opacity: 0.75; {line_clamp_css(1)} }}
    .kv .v {{
      margin-top: 5px;
      font-size: 12px;
      opacity: 0.88;
      word-break: break-all;
      {line_clamp_css(1)}
    }}
    .footer {{
      margin-top: auto;
      padding-top: 12px;
      font-size: 12px;
      opacity: 0.7;
      text-align: right;
    }}
  </style>
  {_card_theme_css(card_style)}
</head>
<body>
  <div class="card">
    <div class="top">
      <div class="brand">
        <div class="t">{html_escape(profile["subscribe_title"])}</div>
        <div class="badge">NEW</div>
      </div>
      <div class="time">
        更新于：{html_escape(format_ts_cn(update_ts))}<br/>
        生成于：{html_escape(now_str)}
      </div>
    </div>
    <div class="main">
      <div>
        {cover_html}
      </div>
      <div class="right">
        <div class="title">{html_escape(works_name)}</div>
        <div class="author">作者：{html_escape(author_name)} · ID：{html_escape(int(book_id))}</div>

        <div class="block">
          <div class="k">最新章节</div>
          <div class="v">{html_escape(chapter_name)}</div>
        </div>

        <div class="row">
          <div class="kv">
            <div class="k">直达链接</div>
            <div class="v">{html_escape(book_url)}</div>
          </div>
        </div>

        <div class="footer">Getcwm / Subscribe Push</div>
      </div>
    </div>
  </div>
</body>
</html>
"""

    filename = f"update_{int(book_id)}_{uuid.uuid4().hex}.png"
    out_path = _render_html_to_png(
        html_str=html_str,
        size=(width, height),
        output_dir=Path(output_dir),
        filename=filename,
        t2i_enabled=t2i_enabled,
        t2i_endpoint=t2i_endpoint,
        t2i_timeout=t2i_timeout,
    )
    return str(out_path)


def handle_search_html_content(
    html_content: str,
    *,
    query: str | None = None,
    output_dir: str | Path = "./renders",
    max_items: int = 8,
    return_data: bool = False,
) -> str | CardRenderResult:
    data = parse_search_html_content(html_content)
    image_path = render_search_card(
        data, query=query, max_items=max_items, output_dir=output_dir
    )
    return (
        CardRenderResult(image_path=image_path, data=data)
        if return_data
        else image_path
    )


def handle_book_details_html_content(
    html_content: str,
    *,
    output_dir: str | Path = "./renders",
    return_data: bool = False,
    session: Any | None = None,
) -> str | CardRenderResult:
    data = parse_book_details_html_content(html_content) or {}
    image_path = render_book_details_card(data, output_dir=output_dir, session=session)
    return (
        CardRenderResult(image_path=image_path, data=data)
        if return_data
        else image_path
    )
