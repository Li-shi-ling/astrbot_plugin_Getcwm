from __future__ import annotations

import math
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

try:
    from html2image import Html2Image  # type: ignore
except Exception as e:  # pragma: no cover
    Html2Image = None  # type: ignore[assignment]
    _HTML2IMAGE_IMPORT_ERROR = e

from .cwm_utils import fetch_image_data_uri, format_ts_cn, html_escape, line_clamp_css

def _calc_search_card_height(num_items: int) -> int:
    """根据当前 CSS 估算搜索卡片所需画布高度，避免底部被裁切。"""
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

    # 预留一些冗余，避免不同字体/渲染差异导致裁切
    safety = 80
    return body_pad_y + card_pad_y + header_h + header_mb + list_h + footer_mt + footer_h + safety

def _calc_book_details_card_height(num_tags: int, num_props: int) -> int:
    """根据当前 CSS 估算详情卡片所需画布高度，避免信息块被裁切。"""
    tags = max(0, int(num_tags))
    props = max(0, int(num_props))

    # 画布结构：body padding + card padding + (top + main + margin)
    body_pad_y = 26 * 2
    card_pad_y = 22 * 2
    top_h = 20
    main_mt = 14

    # main 的高度需要覆盖右侧信息列的总高度（否则 card overflow:hidden 会裁切）
    title_h = 82  # 2 行标题（34px * 1.18）
    author_h = 26  # 8px margin + 1 行作者

    # tags：右侧列宽约 690px，标签 max-width 180px，保守估算每行 3 个
    tag_rows = math.ceil(min(tags, 10) / 3) if tags else 0
    tags_h = 10 + (tag_rows * 27) + max(0, tag_rows - 1) * 8  # margin-top + rows + gap

    stats_h = 82  # margin-top + 统计块高度
    chapter_h = 96  # margin-top + 章节块高度（2 行）

    prop_rows = math.ceil(min(props, 8) / 2) if props else 0
    props_h = 12 + (prop_rows * 58) + max(0, prop_rows - 1) * 10  # margin-top + rows + gap

    intro_h = 124  # 简介块（4 行）高度上限

    right_h = title_h + author_h + tags_h + stats_h + chapter_h + props_h + intro_h
    cover_h = 312
    main_h = max(cover_h, right_h)

    # 预留一些冗余，避免不同字体/渲染差异导致裁切
    safety = 100
    return body_pad_y + card_pad_y + top_h + main_mt + main_h + safety

def _render_html_to_png(*, html_str: str, size: tuple[int, int], output_dir: Path, filename: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if Html2Image is None:  # pragma: no cover
        err = globals().get("_HTML2IMAGE_IMPORT_ERROR")
        raise RuntimeError(f"缺少依赖 html2image，无法渲染图片：{err!s}")
    hti = Html2Image(
        output_path=str(output_dir),
    )
    try:
        hti.screenshot(html_str=html_str, save_as=filename, size=size)
    except Exception as e:
        raise RuntimeError(f"Html2Image 渲染失败：{e}") from e
    return output_dir / filename


def render_search_card(
    results: list[Mapping[str, Any]],
    *,
    query: str | None = None,
    max_items: int = 8,
    output_dir: str | Path = "./renders",
) -> str:
    items = list(results)[: max(1, int(max_items))]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    width = 1024
    height = _calc_search_card_height(len(items))

    query_badge = f"<div class='badge'>{html_escape(query)}</div>" if query else ""

    rows_html: list[str] = []
    for idx, it in enumerate(items, start=1):
        title = html_escape(it.get("title", ""))
        author = html_escape(it.get("author", ""))
        update_time = html_escape(it.get("update_time", ""))
        desc = html_escape(it.get("description", ""))
        read_url = html_escape(it.get("read_url", ""))

        desc_html = f"<div class='desc'>{desc}</div>" if desc else "<div class='desc muted'>（无简介）</div>"
        rows_html.append(
            f"""
            <div class="item">
              <div class="idx">{idx}</div>
              <div class="content">
                <div class="t">{title}</div>
                <div class="meta">作者：{author} · {update_time}</div>
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
</head>
<body>
  <div class="card">
    <div class="header">
      <div>
        <div class="h1">刺猬猫 · 搜索结果</div>
        <div class="sub">共 {html_escape(len(results))} 条 · 展示前 {html_escape(len(items))} 条 · 生成于 {now_str}</div>
      </div>
      {query_badge}
    </div>
    <div class="list">
      {''.join(rows_html)}
    </div>
    <div class="footer">Getcwm / Html2Image</div>
  </div>
</body>
</html>
"""

    filename = f"search_{uuid.uuid4().hex}.png"
    out_path = _render_html_to_png(html_str=html_str, size=(width, height), output_dir=Path(output_dir), filename=filename)
    return str(out_path)


def render_book_details_card(
    details: Mapping[str, Any],
    *,
    output_dir: str | Path = "./renders",
    session: Any | None = None,
) -> str:
    works_name = details.get("Works_Name", "") or ""
    author_name = details.get("Author_Name", "") or ""
    tag_list = list(details.get("Tag_List", []) or [])
    chapter_name = details.get("Chapter_Name", "") or ""
    update_ts = int(details.get("Update_Time", -1) or -1)
    cover_url = details.get("Cover_Image", "") or ""

    stat_map = dict(details.get("data2", {}) or {})
    stat_click = stat_map.get("总点击", "")
    stat_fav = stat_map.get("总收藏", "")
    stat_words = stat_map.get("总字数", "")

    prop_map = dict(details.get("data", {}) or {})
    prop_items = list(prop_map.items())[:8]

    intro = (details.get("Brief_Introduction", "") or "").strip()
    if not intro:
        intro = "（无简介）"

    cover_data_uri = fetch_image_data_uri(str(cover_url), session=session)
    cover_html = (
        f"<img class='cover' src='{cover_data_uri}' alt='cover' />"
        if cover_data_uri
        else "<div class='cover placeholder'>无封面</div>"
    )

    tags_html = "".join([f"<span class='tag'>{html_escape(t)}</span>" for t in tag_list[:10]])
    props_html = "".join(
        [
            f"<div class='kv'><div class='k'>{html_escape(k)}</div><div class='v'>{html_escape(v)}</div></div>"
            for k, v in prop_items
        ]
    )

    width = 1024
    height = _calc_book_details_card_height(min(len(tag_list), 10), len(prop_items))

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
      {line_clamp_css(2)}
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
</head>
<body>
  <div class="card">
    <div class="top">
      <div class="brand">刺猬猫 · 书籍详情</div>
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
          <div class="stat"><div class="k">总点击</div><div class="v">{html_escape(stat_click)}</div></div>
          <div class="stat"><div class="k">总收藏</div><div class="v">{html_escape(stat_fav)}</div></div>
          <div class="stat"><div class="k">总字数</div><div class="v">{html_escape(stat_words)}</div></div>
        </div>

        <div class="chapter">
          <div class="k">最新章节</div>
          <div class="v">{html_escape(chapter_name)}</div>
        </div>

        <div class="props">
          {props_html}
        </div>

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
    out_path = _render_html_to_png(html_str=html_str, size=(width, height), output_dir=Path(output_dir), filename=filename)
    return str(out_path)
