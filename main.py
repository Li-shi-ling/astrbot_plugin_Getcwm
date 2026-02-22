import os
import re
import asyncio
import functools
from pathlib import Path
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
from .src.Getcwm import GetCwm
from .src.cwm_client import CiweimaoClient
from .src.cwm_parsers import parse_book_details_html_content, parse_search_html_content
from .src.cwm_renderers import render_book_details_card, render_search_card
from .src.cwm_utils import format_ts_cn
from .src.tool import extract_help_parameters, set_chinese_font, plot_data


@register("Getcwm", "lishining", "刺猬猫小说数据获取与画图插件", "3.0.0")
class GetcwmPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.getcwm = GetCwm()
        self._cwm_client = CiweimaoClient()
        self._render_dir = Path(__file__).resolve().parent / "renders"
        self._max_search_items = 8

    async def initialize(self):
        logger.info("Getcwm 插件初始化完成")

    @filter.command_group("cwm")
    def cwm(self):
        pass

    @cwm.command("help")
    async def help(self, event: AstrMessageEvent):
        """获取代码帮助"""
        help_text = [
            "Getcwm 插件",
            "/cwm 搜索 [书名] [页码=1]          搜索书籍名片",
            "/cwm 名片 [书籍id]                 获取小说名片",
        ]
        yield event.plain_result("\n".join(help_text))

    @cwm.command("搜索")
    async def search(self, event: AstrMessageEvent, book_name: str, page: int = 1):
        """/cwm 搜索 [书名] [页码=1]，搜索书籍并返回名片"""
        try:
            query = (book_name or "").strip()
            if not query:
                yield event.plain_result("请输入书名，例如：/cwm 搜索 书名 1")
                return

            page = max(1, int(page))
            html = await self._run_sync(self._cwm_client.search_name, query, page)
            items = parse_search_html_content(html)

            if not items:
                yield event.plain_result("未找到相关书籍")
                return

            async def gen_img():
                return await self._run_sync(
                    render_search_card,
                    items,
                    query=query,
                    max_items=self._max_search_items,
                    output_dir=self._render_dir,
                )

            def gen_text():
                return self._format_search_text(items, query=query, max_items=self._max_search_items)

            async for result in self._generate_image_or_fallback(event, gen_img, gen_text):
                yield result

        except Exception as e:
            logger.exception("cwm 搜索失败: %s", e)
            yield event.plain_result(f"搜索失败: {str(e)}")

    @cwm.command("名片")
    async def novel_card(self, event: AstrMessageEvent, book_id: int):
        """/cwm 名片 [书籍id]，获取小说名片"""
        try:
            bid = int(book_id)
            html = await self._run_sync(self._cwm_client.get_book_details, bid)
            data = parse_book_details_html_content(html) or {}

            if not data:
                yield event.plain_result("未能获取到书籍信息")
                return

            async def gen_img():
                return await self._run_sync(
                    render_book_details_card,
                    data,
                    output_dir=self._render_dir,
                    session=self._cwm_client.session,
                )

            def gen_text():
                return self._format_book_details_text(data, book_id=bid)

            async for result in self._generate_image_or_fallback(event, gen_img, gen_text):
                yield result

        except Exception as e:
            logger.exception("cwm 名片失败: %s", e)
            yield event.plain_result(f"获取小说名片失败: {str(e)}")

    @cwm.command("详情")
    async def details(self, event: AstrMessageEvent, book_id:int):
        """/cwm 详情 [书的id]，获取小说名片（同 /cwm 名片）"""
        async for result in self.novel_card(event, book_id):
            yield result

    async def _run_sync(self, func, /, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))

    def _extract_book_id(self, url: str) -> int | None:
        if not url:
            return None
        m = re.search(r"/book/(\d+)", url)
        return int(m.group(1)) if m else None

    def _format_search_text(self, items: list[dict[str, str]], *, query: str, max_items: int) -> str:
        results = list(items)[: max(1, int(max_items))]
        lines: list[str] = [f"刺猬猫搜索：{query}", f"共找到 {len(items)} 条结果，展示前 {len(results)} 条："]
        for idx, it in enumerate(results, start=1):
            title = it.get("title", "") or "未知标题"
            author = it.get("author", "") or "未知作者"
            update_time = it.get("update_time", "") or "未知更新"
            read_url = it.get("read_url", "") or ""
            book_id = self._extract_book_id(read_url)
            desc = (it.get("description", "") or "").strip()
            if len(desc) > 80:
                desc = desc[:80].rstrip() + "…"

            lines.append(f"\n{idx}. 《{title}》")
            lines.append(f"   作者：{author}")
            lines.append(f"   {update_time}")
            if book_id is not None:
                lines.append(f"   ID：{book_id}")
            if read_url:
                lines.append(f"   链接：{read_url}")
            if desc:
                lines.append(f"   简介：{desc}")
        return "\n".join(lines).strip()

    def _format_book_details_text(self, data: dict, *, book_id: int) -> str:
        works_name = data.get("Works_Name") or f"书籍ID：{book_id}"
        author_name = data.get("Author_Name") or "未知作者"
        tags = data.get("Tag_List") or []
        chapter_name = data.get("Chapter_Name") or "未知章节"
        update_ts = data.get("Update_Time")
        intro = (data.get("Brief_Introduction") or "").strip()
        cover = data.get("Cover_Image") or ""

        stat = data.get("data2") or {}
        click = stat.get("总点击", "未知")
        fav = stat.get("总收藏", "未知")
        words = stat.get("总字数", "未知")

        lines: list[str] = [f"《{works_name}》", f"作者：{author_name}"]
        if tags:
            lines.append("标签：" + " / ".join([str(t) for t in tags if t]))
        lines.append(f"最新章节：{chapter_name}")
        if isinstance(update_ts, int) and update_ts > 0:
            lines.append(f"更新时间：{format_ts_cn(update_ts)}")
        lines.append(f"总点击：{click}  总收藏：{fav}  总字数：{words}")

        extra = data.get("data") or {}
        if extra:
            extras = []
            for k, v in list(extra.items())[:8]:
                extras.append(f"{k}:{v}")
            if extras:
                lines.append("其它：" + "  ".join(extras))

        if intro:
            if len(intro) > 320:
                intro = intro[:320].rstrip() + "…"
            lines.append("\n简介：\n" + intro)
        if cover:
            lines.append("\n封面：\n" + str(cover))

        return "\n".join(lines).strip()

    async def _generate_image_or_fallback(self, event, generate_image_func, generate_text_func, *args, **kwargs):
        """统一的图片生成和回退处理"""
        try:
            image_path = await generate_image_func(*args, **kwargs)
            if image_path and os.path.exists(image_path):
                yield event.chain_result([Comp.Image.fromFileSystem(image_path)])
                return

            text_message = generate_text_func(*args, **kwargs)
            yield event.plain_result(f"图片生成失败，使用文本模式显示\n\n{text_message}")

        except Exception as render_error:
            text_message = generate_text_func(*args, **kwargs)
            yield event.plain_result(f"图片生成失败，使用文本模式显示\n错误: {str(render_error)}\n\n{text_message}")
