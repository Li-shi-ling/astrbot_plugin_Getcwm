import os
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from .src.Getcwm import GetCwm
from .src.tool import extract_help_parameters, set_chinese_font, plot_data


@register("Getcwm", "lishining", "刺猬猫小说数据获取与画图插件", "3.0.0")
class GetcwmPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.getcwm = GetCwm()

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
            "/cwm 搜索 [书名]                  搜索书名",
        ]
        yield event.plain_result("\n".join(help_text))

    @cwm.command("搜索")
    async def search(self, event: AstrMessageEvent, book_name:str):
        """/cwm 搜索 [书名]，搜索和这个名称相关的书籍"""
        result = await self.getcwm.get_novel_id(book_name)
        yield event.plain_result(result)
