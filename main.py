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
from .src.cwm_renderers import render_book_details_card, render_search_card, render_subscribe_update_card
from .src.cwm_utils import format_ts_cn
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event.filter import PermissionType
import aiofiles
import json

CWM_SUBSCRIBE_DEBUG = False  # 订阅相关 debug 日志开关（默认关闭）

@register("Getcwm", "lishining", "刺猬猫小说数据获取与画图插件", "3.0.0")
class GetcwmPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self._cwm_client = CiweimaoClient()
        self._render_dir = str(StarTools.get_data_dir() / "renders")
        self._max_search_items = 8
        self.interval_time = config.get("interval_time", 20)
        self.subscribe_data_file = str(StarTools.get_data_dir() / "subscribe.json")
        self.b2u: dict[int, list[str]] = {}
        self.u2b: dict[str, list[int]] = {}
        self.bmeta: dict[int, dict] = {}
        self._subscribe_lock = asyncio.Lock()

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
            "/cwm 订阅 [书籍id]                 在当前会话订阅更新推送",
            "/cwm 订阅列表 [会话umo=当前会话]    查看会话的全部订阅（指定其他会话需管理员）",
            "/cwm 取消订阅 [书籍id] [会话umo=当前会话]  取消会话对该书的订阅（指定其他会话需管理员）",
            "/cwm 全部订阅                      展示所有订阅(管理员)",
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
        msg = await self._subscribe(event, int(book_id))
        yield event.plain_result(msg)

    @cwm.command("订阅列表")
    async def subscribe_list(self, event: AstrMessageEvent, umo: str | None = None):
        """/cwm 订阅列表 [会话umo=当前会话]，查看会话的全部订阅"""
        msg = await self._get_subscribe_list_text(event, umo=umo)
        yield event.plain_result(msg)

    @cwm.command("取消订阅")
    async def unsubscribe(self, event: AstrMessageEvent, book_id: int, umo: str | None = None):
        """/cwm 取消订阅 [书id] [会话umo=当前会话]，取消会话对该书的订阅"""
        msg = await self._unsubscribe(event, int(book_id), umo=umo)
        yield event.plain_result(msg)

    @cwm.command("全部订阅")
    @filter.permission_type(PermissionType.ADMIN)
    async def subscribe_all(self, event: AstrMessageEvent):
        """/cwm 全部订阅，展示所有订阅（管理员）"""
        msg = await self._get_all_subscribe_pairs_text()
        yield event.plain_result(msg)

    # 工具函数
    async def _subscribe(self, event: AstrMessageEvent, book_id: int) -> str:
        support_proactive = False
        try:
            support_proactive = bool(event.platform_meta.support_proactive_message)
        except Exception:
            support_proactive = False

        if not support_proactive:
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 订阅被拒绝：不支持主动消息。book_id=%s umo=%s",
                book_id,
                getattr(event, "unified_msg_origin", None),
            )
            return "该适配器不具有主动发送消息的能力，无法进行订阅"

        bid = int(book_id)
        umo = str(event.unified_msg_origin)
        CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 订阅请求：book_id=%s umo=%s", bid, umo)

        latest_meta = await self._fetch_latest_meta(bid)
        CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 订阅基线获取完成：book_id=%s meta=%s", bid, latest_meta)
        if latest_meta is None:
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 订阅失败：基线元数据缺失。book_id=%s umo=%s", bid, umo
            )
            return f"订阅失败：未能获取书籍信息（ID：{bid}）"

        async with self._subscribe_lock:
            before_book_subscribers = len(self.b2u.get(bid, []) or [])
            before_umo_books = len(self.u2b.get(umo, []) or [])

            umos = self.b2u.setdefault(bid, [])
            added_umo = False
            if umo not in umos:
                umos.append(umo)
                added_umo = True

            books = self.u2b.setdefault(umo, [])
            added_book = False
            if bid not in books:
                books.append(bid)
                added_book = True

            meta_updated = False
            if latest_meta and (bid not in self.bmeta or int(self.bmeta.get(bid, {}).get("timestamp", -1) or -1) <= 0):
                self.bmeta[bid] = latest_meta
                meta_updated = True

            after_book_subscribers = len(self.b2u.get(bid, []) or [])
            after_umo_books = len(self.u2b.get(umo, []) or [])

        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 订阅更新完成：book_id=%s umo=%s added_umo=%s added_book=%s meta_updated=%s book_subscribers=%s->%s umo_books=%s->%s",
            bid,
            umo,
            added_umo,
            added_book,
            meta_updated,
            before_book_subscribers,
            after_book_subscribers,
            before_umo_books,
            after_umo_books,
        )

        CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 持久化订阅数据：file=%s", self.subscribe_data_file)
        await self._save_subscribe_data()
        CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 确保定时任务运行中")
        await self.start_subscribe_task()

        title = (latest_meta or {}).get("title_text") if isinstance(latest_meta, dict) else None
        title_str = str(title).strip() if title else f"书籍ID：{bid}"
        return f"订阅成功：{title_str}\n检测间隔：{int(self.interval_time)} 分钟"

    async def _get_subscribe_list_text(self, event: AstrMessageEvent, *, umo: str | None = None) -> str:
        current_umo = str(event.unified_msg_origin)
        target_umo = current_umo if not (umo and str(umo).strip()) else str(umo).strip()

        if target_umo != current_umo and not event.is_admin():
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 订阅列表被拒绝：非管理员查询其他会话。current_umo=%s target_umo=%s",
                current_umo,
                target_umo,
            )
            return "权限不足：仅管理员可指定其他会话"

        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 订阅列表请求：current_umo=%s target_umo=%s", current_umo, target_umo
        )

        async with self._subscribe_lock:
            book_ids = list(self.u2b.get(target_umo, []) or [])
            metas = {int(bid): dict(self.bmeta.get(int(bid), {}) or {}) for bid in book_ids}

        if not book_ids:
            CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 订阅列表为空：target_umo=%s", target_umo)
            return "当前会话暂无订阅" if target_umo == current_umo else "该会话暂无订阅"

        try:
            interval_min = max(1, int(self.interval_time or 0))
        except Exception:
            interval_min = 20

        task_running = bool(self.subscribe_running and self.subscribe_task and not self.subscribe_task.done())
        task_status = "运行中" if task_running else "未运行"

        max_show = 200
        shown_ids = book_ids[:max_show]

        lines: list[str] = []
        lines.append(f"当前会话订阅（{len(book_ids)}）" if target_umo == current_umo else f"会话订阅（{len(book_ids)}）")
        if target_umo != current_umo:
            lines.append(f"会话umo：{target_umo}")
        lines.extend(
            [
                f"检测间隔：{interval_min} 分钟",
                f"订阅任务：{task_status}",
            ]
        )
        if len(book_ids) > max_show:
            lines.append(f"（订阅过多，仅展示前 {max_show} 本）")

        for idx, bid in enumerate(shown_ids, start=1):
            meta = metas.get(int(bid), {}) or {}
            title = str(meta.get("title_text", "") or "").strip() or f"书籍ID：{int(bid)}"
            chapter = str(meta.get("chapter", "") or "").strip()
            try:
                ts = int(meta.get("timestamp", -1) or -1)
            except Exception:
                ts = -1

            lines.append(f"\n{idx}. {title}")
            lines.append(f"   ID：{int(bid)}")
            if chapter:
                lines.append(f"   最新章节：{chapter}")
            if ts > 0:
                lines.append(f"   更新时间：{format_ts_cn(ts)}")
            lines.append(f"   链接：https://www.ciweimao.com/book/{int(bid)}")

        out = "\n".join(lines).strip()
        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 订阅列表获取成功：target_umo=%s books=%s chars=%s",
            target_umo,
            len(book_ids),
            len(out),
        )
        return out

    async def _unsubscribe(self, event: AstrMessageEvent, book_id: int, *, umo: str | None = None) -> str:
        bid = int(book_id)
        current_umo = str(event.unified_msg_origin)
        target_umo = current_umo if not (umo and str(umo).strip()) else str(umo).strip()

        if target_umo != current_umo and not event.is_admin():
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 取消订阅被拒绝：非管理员操作其他会话。current_umo=%s target_umo=%s book_id=%s",
                current_umo,
                target_umo,
                bid,
            )
            return "权限不足：仅管理员可指定其他会话"

        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 取消订阅请求：book_id=%s current_umo=%s target_umo=%s",
            bid,
            current_umo,
            target_umo,
        )

        removed_from_book = False
        removed_from_session = False
        before_book_subscribers = 0
        after_book_subscribers = 0
        before_session_books = 0
        after_session_books = 0
        meta_snapshot = None
        should_stop_task = False
        remaining_subscribed_books = 0

        async with self._subscribe_lock:
            meta_snapshot = dict(self.bmeta.get(bid, {}) or {})

            subs = self.b2u.get(bid, []) or []
            before_book_subscribers = len(subs)
            if target_umo in subs:
                try:
                    subs.remove(target_umo)
                except ValueError:
                    pass
                removed_from_book = True
            if subs:
                self.b2u[bid] = subs
            else:
                self.b2u.pop(bid, None)
                self.bmeta.pop(bid, None)
            after_book_subscribers = len(self.b2u.get(bid, []) or [])

            books = self.u2b.get(target_umo, []) or []
            before_session_books = len(books)
            if bid in books:
                try:
                    books.remove(bid)
                except ValueError:
                    pass
                removed_from_session = True
            if books:
                self.u2b[target_umo] = books
            else:
                self.u2b.pop(target_umo, None)
            after_session_books = len(self.u2b.get(target_umo, []) or [])

            remaining_subscribed_books = len(self.b2u)
            should_stop_task = remaining_subscribed_books <= 0

        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 取消订阅更新完成：book_id=%s target_umo=%s removed_from_book=%s removed_from_session=%s book_subscribers=%s->%s session_books=%s->%s remaining_books=%s",
            bid,
            target_umo,
            removed_from_book,
            removed_from_session,
            before_book_subscribers,
            after_book_subscribers,
            before_session_books,
            after_session_books,
            remaining_subscribed_books,
        )

        if not removed_from_book and not removed_from_session:
            return f"取消订阅失败：该会话未订阅该书（ID：{bid}）"

        CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 持久化取消订阅数据：file=%s", self.subscribe_data_file)
        await self._save_subscribe_data()

        if should_stop_task:
            CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 取消订阅：无任何订阅，停止定时任务")
            self.subscribe_running = False
            if self.subscribe_task and not self.subscribe_task.done():
                self.subscribe_task.cancel()
                try:
                    await self.subscribe_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 取消订阅：停止任务等待时出现异常：%s", e)
        else:
            CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 取消订阅：仍有订阅，确保定时任务运行中")
            await self.start_subscribe_task()

        title = str((meta_snapshot or {}).get("title_text") or "").strip()
        title_str = title if title else f"书籍ID：{bid}"
        session_suffix = "" if target_umo == current_umo else f"（会话：{target_umo}）"
        extra = "（已无任何订阅，订阅检测任务已停止）" if should_stop_task else ""
        return f"已取消订阅：{title_str}{session_suffix}{extra}"

    async def _get_all_subscribe_pairs_text(self) -> str:
        CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 全部订阅请求")
        async with self._subscribe_lock:
            pairs: list[tuple[str, int]] = []
            for umo, bids in (self.u2b or {}).items():
                if not bids:
                    continue
                for bid in bids:
                    try:
                        pairs.append((str(umo), int(bid)))
                    except Exception:
                        continue

        if not pairs:
            CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 全部订阅为空")
            return "暂无任何订阅"

        pairs.sort(key=lambda x: (x[0], x[1]))

        max_show = 5000
        show_pairs = pairs[:max_show]
        lines = [f"全部订阅（{len(pairs)}）"]
        if len(pairs) > max_show:
            lines.append(f"（仅展示前 {max_show} 条）")

        for umo, bid in show_pairs:
            lines.append(f"{umo}:{bid}")

        out = "\n".join(lines).strip()
        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 全部订阅获取成功：pairs=%s chars=%s", len(pairs), len(out)
        )
        return out

    async def _fetch_latest_meta(self, book_id: int) -> dict | None:
        CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 获取最新元数据开始：book_id=%s", book_id)
        try:
            html = await self._run_sync(self._cwm_client.get_book_details, int(book_id))
            data = parse_book_details_html_content(html) or {}
            title = data.get("Works_Name") or f"书籍ID：{int(book_id)}"
            chapter = data.get("Chapter_Name") or ""
            ts = int(data.get("Update_Time", -1) or -1)
            meta = {"title_text": str(title), "timestamp": ts, "chapter": str(chapter)}
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 获取最新元数据成功：book_id=%s ts=%s chapter=%s title=%s",
                book_id,
                ts,
                str(chapter),
                str(title),
            )
            return meta
        except Exception as e:
            logger.error(f"[Getcwm] 获取订阅基线失败 book_id={book_id}: {e}")
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 获取最新元数据失败：book_id=%s err=%s", book_id, e
            )
            return None

    async def _send_proactive_message(self, umo: str, chain):
        send = getattr(StarTools, "send_message", None)
        if callable(send):
            try:
                ret = send(umo, chain)
            except TypeError:
                ret = send(self.context, umo, chain)
            if asyncio.iscoroutine(ret):
                await ret
            return

        await self.context.send_message(umo, chain)

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
        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 初始化：加载订阅数据。file=%s", self.subscribe_data_file
        )
        subscribe_data = await self._load_subscribe_data()
        self.b2u = subscribe_data.get("b2u", {}) or {}
        self.u2b = subscribe_data.get("u2b", {}) or {}
        self.bmeta = subscribe_data.get("bmeta", {}) or {}
        total_links = sum(len(v) for v in (self.b2u or {}).values())
        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 初始化：订阅数据加载完成。books=%s sessions=%s links=%s meta=%s",
            len(self.b2u or {}),
            len(self.u2b or {}),
            total_links,
            len(self.bmeta or {}),
        )
        await self.start_subscribe_task()

    # 异步卸载函数
    async def terminate(self):
        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 终止：停止订阅任务。running=%s task=%s", self.subscribe_running, self.subscribe_task
        )
        self.subscribe_running = False
        if self.subscribe_task and not self.subscribe_task.done():
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 终止：取消订阅任务。task=%s", self.subscribe_task
            )
            self.subscribe_task.cancel()
            try:
                await self.subscribe_task
            except asyncio.CancelledError:
                CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 终止：订阅任务已取消")
                pass
            except Exception as e:
                CWM_SUBSCRIBE_DEBUG and logger.debug(
                    "[cwm] 终止：订阅任务取消等待时出现异常：%s", e
                )
                pass
        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 终止：持久化订阅数据。file=%s", self.subscribe_data_file
        )
        await self._save_subscribe_data()

    # 保存订阅数据
    async def _save_subscribe_data(self):
        """保存订阅数据"""
        async with self._subscribe_lock:
            b2u = {str(k): list(v) for k, v in self.b2u.items()}
            u2b = {str(k): list(v) for k, v in self.u2b.items()}
            bmeta = {str(k): dict(v) for k, v in self.bmeta.items()}
            books_count = len(b2u)
            sessions_count = len(u2b)
            links_count = sum(len(v) for v in b2u.values())
            meta_count = len(bmeta)
        payload = json.dumps({"b2u": b2u, "u2b": u2b, "bmeta": bmeta}, ensure_ascii=False)
        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 保存订阅数据：file=%s books=%s sessions=%s links=%s meta=%s payload_chars=%s",
            self.subscribe_data_file,
            books_count,
            sessions_count,
            links_count,
            meta_count,
            len(payload),
        )
        try:
            async with aiofiles.open(self.subscribe_data_file, 'w', encoding='utf-8') as f:
                await f.write(payload)
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 保存订阅数据成功：file=%s", self.subscribe_data_file
            )
        except OSError as e:
            logger.error(f"保存订阅数据失败: {e}")
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 保存订阅数据失败：file=%s err=%s", self.subscribe_data_file, e
            )

    # 异步加载订阅数据
    async def _load_subscribe_data(self):
        """异步加载订阅数据"""
        out = {"b2u": {}, "u2b": {}, "bmeta": {}}
        try:
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 加载订阅数据：file=%s", self.subscribe_data_file
            )
            if os.path.exists(self.subscribe_data_file):
                async with aiofiles.open(self.subscribe_data_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    CWM_SUBSCRIBE_DEBUG and logger.debug(
                        "[cwm] 加载订阅数据：读取成功。chars=%s", len(content)
                    )
                    if not content.strip():
                        CWM_SUBSCRIBE_DEBUG and logger.debug(
                            "[cwm] 加载订阅数据：文件为空，使用默认值"
                        )
                        return out
                    raw = json.loads(content) or {}

                    raw_b2u = raw.get("b2u", {}) or {}
                    if not isinstance(raw_b2u, dict):
                        raw_b2u = {}
                    b2u: dict[int, list[str]] = {}
                    for k, v in raw_b2u.items():
                        try:
                            bid = int(k)
                        except Exception:
                            continue
                        if not isinstance(v, list):
                            continue
                        umos = [str(x) for x in v if x]
                        seen: set[str] = set()
                        dedup: list[str] = []
                        for u in umos:
                            if u in seen:
                                continue
                            seen.add(u)
                            dedup.append(u)
                        b2u[bid] = dedup

                    u2b: dict[str, list[int]] = {}
                    for bid, umos in b2u.items():
                        for umo in umos:
                            ids = u2b.setdefault(umo, [])
                            if bid not in ids:
                                ids.append(bid)

                    raw_bmeta = raw.get("bmeta", {}) or {}
                    if not isinstance(raw_bmeta, dict):
                        raw_bmeta = {}
                    bmeta: dict[int, dict] = {}
                    for k, v in raw_bmeta.items():
                        try:
                            bid = int(k)
                        except Exception:
                            continue
                        if not isinstance(v, dict):
                            continue
                        title = str(v.get("title_text", v.get("title", "")) or "")
                        chapter = str(v.get("chapter", "") or "")
                        try:
                            ts = int(v.get("timestamp", -1) or -1)
                        except Exception:
                            ts = -1
                        bmeta[bid] = {"title_text": title, "timestamp": ts, "chapter": chapter}

                    out["b2u"] = b2u
                    out["u2b"] = u2b
                    out["bmeta"] = bmeta
            else:
                CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 加载订阅数据：文件不存在，使用默认值")

            links_count = sum(len(v) for v in (out.get("b2u", {}) or {}).values())
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 加载订阅数据成功：books=%s sessions=%s links=%s meta=%s",
                len(out.get("b2u", {}) or {}),
                len(out.get("u2b", {}) or {}),
                links_count,
                len(out.get("bmeta", {}) or {}),
            )
            return out
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"加载订阅数据失败: {e}")
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 加载订阅数据失败：file=%s err=%s", self.subscribe_data_file, e
            )
            return out
        except Exception as e:
            logger.error(f"加载订阅数据失败: {e}")
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 加载订阅数据意外错误：file=%s err=%s", self.subscribe_data_file, e
            )
            return out

    # 开启定时订阅任务
    async def start_subscribe_task(self):
        """启动定时订阅任务"""
        if self.subscribe_task:
            try:
                CWM_SUBSCRIBE_DEBUG and logger.debug(
                    "[cwm] 启动订阅任务：当前任务状态。task=%s done=%s cancelled=%s",
                    self.subscribe_task,
                    self.subscribe_task.done(),
                    self.subscribe_task.cancelled(),
                )
            except Exception:
                CWM_SUBSCRIBE_DEBUG and logger.debug(
                    "[cwm] 启动订阅任务：当前任务状态。task=%s", self.subscribe_task
                )

        if self.subscribe_task and not self.subscribe_task.done():
            CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 启动订阅任务：保留现有运行中的任务")
            return self.subscribe_task

        self.subscribe_running = True
        try:
            interval_min = max(1, int(self.interval_time or 0))
        except Exception:
            interval_min = 20
        CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 启动订阅任务：创建新任务。interval_min=%s", interval_min)
        self.subscribe_task = asyncio.create_task(
            self._periodic_subscribe(self.interval_time)
        )
        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 启动订阅任务：任务创建成功。task=%s", self.subscribe_task
        )
        return self.subscribe_task

    # 定时订阅任务
    async def _periodic_subscribe(self, interval_time=20):
        """可控制的订阅"""
        CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 定时订阅任务启动：interval_time=%s", interval_time)
        while self.subscribe_running:
            try:
                # 等待指定时间
                interval_min = max(1, int(interval_time or 0))
                CWM_SUBSCRIBE_DEBUG and logger.debug(
                    "[cwm] 定时订阅任务休眠：minutes=%s running=%s", interval_min, self.subscribe_running
                )
                await asyncio.sleep(interval_min * 60)

                # 检查是否还在运行
                if not self.subscribe_running:
                    CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 定时订阅任务在执行更新前停止")
                    break

                # 执行订阅检测
                CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 定时订阅任务唤醒：执行更新检测")
                await self._check_updates()

            except asyncio.CancelledError:
                # 任务被取消
                CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 定时订阅任务被取消")
                break
            except Exception as e:
                # 记录错误但不停止任务
                logger.error(f"[Getcwm] 订阅检测任务出错: {e}")
                CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 定时订阅任务出错，60秒后重试：err=%s", e)
                await asyncio.sleep(60)  # 出错后等待1分钟再重试
        CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 定时订阅任务退出：running=%s", self.subscribe_running)

    async def _check_updates(self):
        async with self._subscribe_lock:
            book_ids = list(self.b2u.keys())

        if not book_ids:
            CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 更新检测：无订阅书籍，跳过")
            return

        CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 更新检测：开始。books=%s", len(book_ids))
        dirty = False
        for bid in book_ids:
            CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 更新检测：获取详情。book_id=%s", bid)
            try:
                html = await self._run_sync(self._cwm_client.get_book_details, int(bid))
                details = parse_book_details_html_content(html) or {}
            except Exception as e:
                logger.error(f"[cwm] 获取订阅详情失败 book_id={bid}: {e}")
                CWM_SUBSCRIBE_DEBUG and logger.debug(
                    "[cwm] 更新检测：获取详情失败。book_id=%s err=%s", bid, e
                )
                continue

            new_ts = int(details.get("Update_Time", -1) or -1)
            if new_ts <= 0:
                CWM_SUBSCRIBE_DEBUG and logger.debug(
                    "[cwm] 更新检测：更新时间无效，跳过。book_id=%s update_time=%s", bid, new_ts
                )
                continue

            new_chapter = str(details.get("Chapter_Name") or "")
            works_name = str(details.get("Works_Name") or f"书籍ID：{int(bid)}")
            new_meta = {"title_text": works_name, "timestamp": new_ts, "chapter": new_chapter}

            async with self._subscribe_lock:
                subscribers = list(self.b2u.get(int(bid), []) or [])
                CWM_SUBSCRIBE_DEBUG and logger.debug(
                    "[cwm] 更新检测：加载订阅者。book_id=%s subscribers=%s", bid, len(subscribers)
                )
                if not subscribers:
                    self.bmeta.pop(int(bid), None)
                    dirty = True
                    CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 更新检测：无订阅者，清理元数据。book_id=%s", bid)
                    continue

                old_meta = dict(self.bmeta.get(int(bid), {}) or {})
                old_ts = int(old_meta.get("timestamp", -1) or -1)
                old_chapter = str(old_meta.get("chapter", "") or "")
                CWM_SUBSCRIBE_DEBUG and logger.debug(
                    "[cwm] 更新检测：比较元数据。book_id=%s old_ts=%s new_ts=%s old_chapter=%s new_chapter=%s",
                    bid,
                    old_ts,
                    new_ts,
                    old_chapter,
                    new_chapter,
                )

                if old_ts <= 0:
                    self.bmeta[int(bid)] = new_meta
                    dirty = True
                    CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 更新检测：基线缺失，仅设置基线。book_id=%s", bid)
                    continue

                if new_ts < old_ts:
                    CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 更新检测：新时间戳更旧，跳过。book_id=%s", bid)
                    continue

                if new_ts == old_ts and (not new_chapter or new_chapter == old_chapter):
                    CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 更新检测：无变化，跳过。book_id=%s", bid)
                    continue

                self.bmeta[int(bid)] = new_meta
                dirty = True
                CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 更新检测：检测到更新，准备推送。book_id=%s", bid)

            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 更新检测：推送更新。book_id=%s subscribers=%s", bid, len(subscribers)
            )
            await self._push_update(int(bid), details, subscribers, old_meta=old_meta)

        if dirty:
            CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 更新检测：元数据已变更，保存订阅数据")
            await self._save_subscribe_data()
        else:
            CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 更新检测：完成，无变更")

    async def _push_update(self, book_id: int, details: dict, subscribers: list[str], *, old_meta: dict | None = None):
        update_text = self._format_subscribe_update_text(book_id, details, old_meta=old_meta)
        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 推送更新：开始。book_id=%s subscribers=%s text_chars=%s has_old_meta=%s",
            book_id,
            len(subscribers or []),
            len(update_text or ""),
            bool(old_meta),
        )

        image_path = None
        try:
            image_path = await self._run_sync(
                render_subscribe_update_card,
                details,
                book_id=int(book_id),
                output_dir=self._render_dir,
                session=self._cwm_client.session,
            )
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 推送更新：卡片渲染完成。book_id=%s image_path=%s", book_id, image_path
            )
        except Exception as e:
            logger.error(f"[Getcwm] 订阅更新卡片渲染失败 book_id={book_id}: {e}")
            CWM_SUBSCRIBE_DEBUG and logger.debug(
                "[cwm] 推送更新：卡片渲染失败。book_id=%s err=%s", book_id, e
            )

        chain = [Comp.Plain(update_text)]
        has_image = bool(image_path and os.path.exists(str(image_path)))
        if has_image:
            chain.append(Comp.Image.fromFileSystem(str(image_path)))
        CWM_SUBSCRIBE_DEBUG and logger.debug(
            "[cwm] 推送更新：消息链构建完成。book_id=%s has_image=%s chain_len=%s",
            book_id,
            has_image,
            len(chain),
        )

        ok = 0
        failed = 0
        for umo in subscribers:
            try:
                CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 推送更新：发送中。book_id=%s umo=%s", book_id, umo)
                await self._send_proactive_message(str(umo), chain)
                ok += 1
                CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 推送更新：发送成功。book_id=%s umo=%s", book_id, umo)
            except Exception as e:
                failed += 1
                logger.error(f"[Getcwm] 推送失败 book_id={book_id} umo={umo}: {e}")
                CWM_SUBSCRIBE_DEBUG and logger.debug(
                    "[cwm] 推送更新：发送失败。book_id=%s umo=%s err=%s", book_id, umo, e
                )

        CWM_SUBSCRIBE_DEBUG and logger.debug("[cwm] 推送更新：完成。book_id=%s ok=%s failed=%s", book_id, ok, failed)

    def _format_subscribe_update_text(self, book_id: int, details: dict, *, old_meta: dict | None = None) -> str:
        works_name = details.get("Works_Name") or f"书籍ID：{int(book_id)}"
        chapter_name = details.get("Chapter_Name") or "未知章节"
        update_ts = int(details.get("Update_Time", -1) or -1)
        url = f"https://www.ciweimao.com/book/{int(book_id)}"

        lines = [f"《{works_name}》更新提醒", f"ID：{int(book_id)}", f"最新章节：{chapter_name}"]
        if update_ts > 0:
            lines.append(f"更新时间：{format_ts_cn(update_ts)}")
        if old_meta:
            old_ch = str(old_meta.get("chapter", "") or "")
            try:
                old_ts = int(old_meta.get("timestamp", -1) or -1)
            except Exception:
                old_ts = -1
            if old_ch or old_ts > 0:
                old_line = "上次记录："
                if old_ch:
                    old_line += f"{old_ch}"
                if old_ts > 0:
                    old_line += f" ({format_ts_cn(old_ts)})"
                lines.append(old_line)
        lines.append(f"链接：{url}")
        return "\n".join(lines).strip()
