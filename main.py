import os
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from .src.Getcwm import GetCwm
from .src.tool import extract_help_parameters, set_chinese_font, plot_data

@register("Getcwm", "lishining", "刺猬猫小说数据获取与画图插件 /Getcwm help 查看帮助", "2.0.0")
class GetcwmPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.getcwm = GetCwm()
        self.output_path = "./img"

        self.help_dict = {
            "help": "查看帮助",
            "jt": "即时爬取数据并画图：/Getcwm jt [书籍id] [条数=50]",
            "Search": "搜索小说 ID：/Getcwm Search [书名]"
        }

    async def initialize(self):
        logger.info("Getcwm 插件初始化完成")

    @filter.command("Getcwm")
    async def getcwm_cmd(self, event: AstrMessageEvent):
        """Getcwm 指令处理函数"""
        text = event.message_str
        params = text.split()
        if len(params) <= 1:
            yield event.plain_result("请输入子命令，如：/Getcwm help")
            return
        cmd = params[1]
        # ===== help =====
        if cmd == "help":
            help_text = "\n\n".join([f"{k}: {v}" for k, v in self.help_dict.items()])
            yield event.plain_result(help_text)
            return
        # ===== jt =====
        elif cmd == "jt":
            try:
                novel_id = int(params[2])
                n = int(params[3]) if len(params) >= 4 else 50
            except:
                yield event.plain_result("格式错误，示例：/Getcwm jt 12345 50")
                return
            img_name = f"{novel_id}-{datetime.now().strftime('%Y-%m-%d')}"
            if os.path.exists(os.path.join(self.output_path,img_name)):
                yield event.make_result().file_image(os.path.join(self.output_path, f"{img_name}.png"))
                return
            chapterdata = await self.getcwm.get_chapter_informationforn(novel_id, n)
            if not chapterdata:
                yield event.plain_result("未能获取章节数据")
                return
            plot_data(chapterdata, img_name, output_path=self.output_path)
            yield event.make_result().file_image(os.path.join(self.output_path, f"{img_name}.png"))
            return
        # ===== Search =====
        elif cmd == "Search":
            if len(params) < 3:
                yield event.plain_result("格式错误：/Getcwm Search 书名")
                return
            book_name = params[2]
            result = await self.getcwm.get_novel_id(book_name)
            yield event.plain_result(result)
            return
        else:
            yield event.plain_result("未知指令，请使用 /Getcwm help 查看帮助")
            return

    async def terminate(self):
        logger.info("Getcwm 插件已卸载")
