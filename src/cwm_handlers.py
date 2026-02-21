from __future__ import annotations

from pathlib import Path
from typing import Any

from cwm_parsers import parse_book_details_html_content, parse_search_html_content
from cwm_renderers import render_book_details_card, render_search_card
from cwm_types import CardRenderResult


def handle_search_html_content(
    html_content: str,
    *,
    query: str | None = None,
    output_dir: str | Path = "./renders",
    max_items: int = 8,
    return_data: bool = False,
) -> str | CardRenderResult:
    """
    解析搜索页 HTML -> 动漫风格卡牌 PNG（Html2Image 渲染）。
    默认只返回图片路径；return_data=True 时同时返回解析后的 json 数据。
    """
    data = parse_search_html_content(html_content)
    image_path = render_search_card(data, query=query, max_items=max_items, output_dir=output_dir)
    return CardRenderResult(image_path=image_path, data=data) if return_data else image_path


def handle_book_details_html_content(
    html_content: str,
    *,
    output_dir: str | Path = "./renders",
    return_data: bool = False,
    session: Any | None = None,
) -> str | CardRenderResult:
    """
    解析详情页 HTML -> 动漫风格卡牌 PNG（Html2Image 渲染）。
    默认只返回图片路径；return_data=True 时同时返回解析后的 json 数据。
    可传 session 用于封面下载复用连接。
    """
    data = parse_book_details_html_content(html_content) or {}
    image_path = render_book_details_card(data, output_dir=output_dir, session=session)
    return CardRenderResult(image_path=image_path, data=data) if return_data else image_path

