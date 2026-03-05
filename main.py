import os
import re
import asyncio
import functools
from pathlib import Path
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register, StarTools
import astrbot.api.message_components as Comp
from .src.cwm_client import CiweimaoClient
from .src.cwm_parsers import parse_book_details_html_content, parse_search_html_content
from .src.cwm_renderers import render_book_details_card, render_search_card
from .src.cwm_utils import format_ts_cn
from astrbot.api import AstrBotConfig, logger
import aiofiles
import json

@register("Getcwm", "lishining", "刺猬猫小说数据获取与画图插件", "3.0.0")
class GetcwmPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self._cwm_client = CiweimaoClient()
        self._render_dir = str(StarTools.get_data_dir() / "renders")
        self._max_search_items = 8
        self.interval_time = config.get("interval_time", 20)
        self.subscribe_data_file = str(StarTools.get_data_dir() / "subscribe.json")
        self.b2u = {}
        self.u2b = {}

        # 订阅任务相关
        self.subscribe_task: asyncio.Task | None = None
        self.subscribe_running = True

    # cwm 指令
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
        """/cwm 详情 [书id]，获取小说名片（同 /cwm 名片）"""
        async for result in self.novel_card(event, book_id):
            yield result

    @cwm.command("订阅")
    async def subscribe(self, event: AstrMessageEvent, book_id:int):
        """/cwm 订阅 [书id],在当前会话订阅id对应的书"""
        async for result in self.novel_card(event, book_id):
            yield result

    # 工具函数
    async def _subscribe(self, event: AstrMessageEvent, book_id:int):
        if not event.platform_meta.support_proactive_message:
            yield event.plain_result("该适配器不具有主动发送消息的能力,无法进行订阅")
            return

        if self.b2u.get(book_id, None) is None:
            self.b2u[book_id] = [event.unified_msg_origin]
        else:
            self.b2u[book_id].append(event.unified_msg_origin)

        if self.u2b.get(book_id, None) is None:
            self.u2b[event.unified_msg_origin] = [book_id]
        else:
            self.b2u[event.unified_msg_origin].append(book_id)

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

    # 持久化数据相关
    # 异步初始化函数
    async def initialize(self):
        subscribe_data = await self._load_subscribe_data()
        self.b2u = subscribe_data["b2u"]
        self.u2b = subscribe_data["u2b"]

    # 异步卸载函数
    async def terminate(self):
        await self._save_subscribe_data()

    # 保存订阅数据
    async def _save_subscribe_data(self):
        """保存订阅数据"""
        try:
            async with aiofiles.open(self.subscribe_data_file, 'w', encoding='utf-8') as f:
                await f.write(
                    json.dumps({
                        "b2u":self.b2u,
                        "u2b":self.u2b
                    })
                )
        except OSError as e:
            logger.error(f"保存订阅数据失败: {e}")
        pass

    # 异步加载订阅数据
    async def _load_subscribe_data(self):
        """异步加载订阅数据"""
        try:
            if os.path.exists(self.subscribe_data_file):
                async with aiofiles.open(self.subscribe_data_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    if not content.strip():
                        return {}
                    return json.loads(content)
            return {}
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"加载订阅数据失败: {e}")
            return {}

    # 开启定时订阅任务
    async def start_subscribe_task(self):
        """启动定时订阅任务"""
        self.subscribe_running = True
        self.subscribe_task = asyncio.create_task(
            self._periodic_subscribe(
                self.interval_time
            )
        )
        return self.subscribe_task

    # 定时清理任务
    async def _periodic_subscribe(self, interval_time=20):
        """可控制的定期清理"""
        while self.subscribe_running:
            try:
                # 等待指定时间
                await asyncio.sleep(interval_time * 60)

                # 检查是否还在运行
                if not self.subscribe_running:
                    break

                # 执行订阅检测
                await self._check_updates()

            except asyncio.CancelledError:
                # 任务被取消
                break
            except Exception as e:
                # 记录错误但不停止任务
                logger.error(f"[Mrfzccl] 清理任务出错: {e}")
                await asyncio.sleep(60)  # 出错后等待1分钟再重试

    async def _check_updates(self):
        pass
