from __future__ import annotations

import logging
from typing import Any

from bs4 import BeautifulSoup

from .cwm_utils import cn_number_to_float, extract_chapter_info, safe_text

logger = logging.getLogger(__name__)


def parse_search_html_content(html_content: str) -> list[dict[str, str]]:
    """解析搜索页 HTML，输出结构与 handle_search_html_content.json 一致。"""
    soup = BeautifulSoup(html_content, "html.parser")
    novel_items = soup.select('li[data-book-id]')

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

        for p in item.find_all("p"):
            p_text = safe_text(p)
            if "小说作者" in p_text:
                a = p.find("a")
                if a:
                    author = safe_text(a) or author
            elif "最近更新" in p_text:
                update_time = p_text or update_time

        description = safe_text(item.select_one("div.desc"))

        results.append(
            {
                "title": title,
                "author": author,
                "update_time": update_time,
                "description": description,
                "read_url": read_url,
            }
        )

    # 统一 read_url（避免相对路径）
    from .cwm_utils import abspath_url

    for r in results:
        r["read_url"] = abspath_url(r.get("read_url", "")) or "未知链接"

    return results


def parse_book_details_html_content(html_content: str) -> dict[str, Any] | None:
    """解析书籍详情页 HTML，输出结构与 handle_book_details_html_content.json 一致。"""
    try:
        soup = BeautifulSoup(html_content, "html.parser")
    except Exception as e:
        logger.exception("解析 HTML 失败: %s", e)
        return None

    works_name = ""
    breadcrumb = soup.select_one("div.breadcrumb")
    if breadcrumb:
        works_name = safe_text(breadcrumb).split(">")[-1].strip()

    author_name = safe_text(soup.select_one("h1.title a"))
    tag_list = [safe_text(s) for s in soup.select("p.label-box span") if safe_text(s)]

    chapter_name = ""
    update_time = -1
    update_el = soup.select_one("p.update-time")
    if update_el:
        chapter_name, update_time = extract_chapter_info(safe_text(update_el))

    brief_introduction = ""
    desc_el = soup.select_one("div.book-desc")
    if desc_el:
        brief_introduction = desc_el.get_text().replace(" ", "")

    cover_image = ""
    cover_img = soup.select_one("div.cover.ly-fl img")
    if cover_img and cover_img.get("src"):
        cover_image = cover_img["src"]
    if not cover_image:
        any_img = soup.find_all("img")
        if any_img:
            cover_image = any_img[-1].get("src", "") or ""

    data: dict[str, Any] = {}
    prop_div = soup.select_one("div.book-property.clearfix")
    if prop_div:
        for span in prop_div.find_all("span"):
            text = safe_text(span).replace("：", ":")
            if ":" not in text:
                continue
            key, val = [p.strip() for p in text.split(":", 1)]
            if not key:
                continue
            data[key] = cn_number_to_float(val)

    data2: dict[str, Any] = {}
    grade_p = soup.select_one("p.book-grade")
    if grade_p:
        tmp = [safe_text(b) for b in grade_p.find_all("b") if safe_text(b)]
        if len(tmp) >= 3:
            data2["总点击"] = cn_number_to_float(tmp[0])
            data2["总收藏"] = cn_number_to_float(tmp[1])
            data2["总字数"] = cn_number_to_float(tmp[2])

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
