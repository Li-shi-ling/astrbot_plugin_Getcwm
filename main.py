# pip install matplotlib
# pip install aiometer

import os
import re
import random
import aiohttp
import asyncio
import requests
import platform
import aiometer
import functools
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
from astrbot.api import logger
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from astrbot.api.star import Context, Star, register
from astrbot.api.event import AstrMessageEvent, filter

# 获取指令后面的参数
def extract_help_parameters(s, directives):
    escaped_directives = re.escape(directives)
    match = re.search(f'{escaped_directives}' + r'\s+(.*)', s)
    if match:
        params = re.split(r'\s+', match.group(1).strip())  # 使用 \s+ 来处理多个空格
        return params
    return []

# 设置各个系统的中文文字
def set_chinese_font():
    system = platform.system()

    # 常见中文字体列表（按优先级）
    font_candidates = {
        "Windows": ["SimHei", "Microsoft YaHei"],
        "Darwin": ["PingFang SC", "Heiti SC"],
        "Linux": ["Noto Sans CJK SC", "WenQuanYi Zen Hei"]
    }

    fonts = font_candidates.get(system, [])

    # 检查系统中是否存在字体
    available_fonts = set(f.name for f in fm.fontManager.ttflist)

    for font in fonts:
        if font in available_fonts:
            # 找到可用字体
            logger.info(f"使用中文字体: {font}")
            plt.rcParams['font.sans-serif'] = [font]
            return

    # 如果没找到可用字体 → 打印安装提示
    logger.warning("系统未找到可用中文字体，请手动安装。")

    if system == "Linux":
        logger.warning("❌ 未找到中文字体，可执行以下命令安装：")
        logger.warning("sudo apt install fonts-noto-cjk   # Debian/Ubuntu")
        logger.warning("sudo yum install google-noto-sans-cjk-fonts   # CentOS/RHEL")
    elif system == "Darwin":
        logger.warning("❌ macOS 可安装中文字体：")
        logger.warning("brew install --cask font-noto-sans-cjk")
    elif system == "Windows":
        logger.warning("❌ Windows 请安装黑体 SimHei.ttf 或 微软雅黑 MSYH.ttf")
        logger.warning("可从网上下载字体并安装。")
        
# 绘画
def plot_data(chapterdata, name, output_path="./img"):
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    df = pd.DataFrame(chapterdata, columns=["chapterid", "chaptername", "GapStickers", "updatatime", "words"])

    df['updatatime'] = pd.to_datetime(df['updatatime'])
    df['GapStickers'] = pd.to_numeric(df['GapStickers'], errors='coerce').fillna(0).astype(int)

    set_chinese_font()
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams['figure.dpi'] = 200

    plt.figure(figsize=(18, 8))

    plt.subplot(3, 2, 1)
    plt.title(f"每章间贴数")
    plt.xlabel('章节')
    plt.ylabel('数量')
    plt.bar(range(len(df)), df['GapStickers'])

    plt.subplot(3, 2, 2)
    updated_times = df['updatatime'].dt.hour
    updated_dict = updated_times.value_counts().sort_index()
    plt.title(f"更新时间点")
    plt.xlabel('时间点(24小时制)')
    plt.ylabel('计数')
    plt.bar(updated_dict.index, updated_dict.values)

    plt.subplot(3, 2, 3)
    plt.title(f"每章字数")
    plt.xlabel('章节')
    plt.ylabel('计数')
    plt.bar(range(len(df)), df['words'])

    plt.subplot(3, 2, 4)
    updated_words = df.groupby(df['updatatime'].dt.date)['words'].sum()
    updated_words.index = pd.to_datetime(updated_words.index).strftime('%Y-%m-%d')
    plt.title(f"日更新字数")
    plt.xlabel('时间')
    plt.ylabel('计数')
    plt.bar(updated_words.index, updated_words.values)

    step = max(1, len(updated_words) // 10)
    plt.xticks(updated_words.index[::step], updated_words.index[::step], rotation=0)

    df['GapStickers'] = pd.to_numeric(df['GapStickers'], errors='coerce')
    df['GapStickers'] = df['GapStickers'].fillna(0)

    plt.subplot(3, 2, 5)
    top_min_df = df.nsmallest(10, 'GapStickers')
    plt.barh(top_min_df['chaptername'], top_min_df['GapStickers'], color='skyblue')
    plt.xlabel('间贴数')
    plt.ylabel('章节名')
    plt.title(f'间贴排行榜后10')

    plt.subplot(3, 2, 6)
    top_max_df = df.nlargest(10, 'GapStickers')
    plt.barh(top_max_df['chaptername'], top_max_df['GapStickers'], color='skyblue')
    plt.xlabel('间贴数')
    plt.ylabel('章节名')
    plt.title(f'间贴排行榜前10')

    plt.tight_layout()
    plt.savefig(os.path.join(output_path, f"{name}.png"))
    plt.clf()

    logger.info("Charts have been generated and saved!")

# 刺猬猫爬虫类别
class GetCwm:
    def __init__(self):
        self.base_url = "https://www.ciweimao.com"
        # 添加常见浏览器请求头
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://www.ciweimao.com/',
            'Upgrade-Insecure-Requests': '1'
        }
        self.retry_times = 3  # 重试次数
        self.delay = 2  # 请求延迟(秒)

    # 异步获取网页内容
    async def fetch(self, session, url):
        for attempt in range(self.retry_times):
            try:
                self.delay = random.uniform(1, 3)
                # 添加延迟避免请求过于频繁
                await asyncio.sleep(self.delay)

                async with session.get(
                        url,
                        headers=self.headers,
                        timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 503:
                        # 如果遇到503，等待更长时间后重试
                        wait_time = (attempt + 1) * 5  # 等待时间递增
                        logger.warning(f"遇到503错误，等待{wait_time}秒后重试(第{attempt + 1}次)")
                        await asyncio.sleep(wait_time)
                        continue

                    response.raise_for_status()  # 如果不是2xx响应，会抛出异常
                    return await response.text()

            except aiohttp.ClientError as e:
                logger.error(f"请求失败(第{attempt + 1}次): {url}, 错误: {e}")
                if attempt == self.retry_times - 1:  # 最后一次尝试也失败
                    return None
                await asyncio.sleep(5)  # 等待5秒后重试
            except Exception as e:
                logger.error(f"未知错误: {url}, 错误: {e}")
                return None
        return None

    # 获取最新 n 章节的 ID 和名称
    async def get_chapter_list(self, session, book_id, n=50):
        url = f"{self.base_url}/chapter-list/{book_id}/book_detail"
        html = await self.fetch(session, url)
        if not html:
            return []

        datas = []
        try:
            soup = BeautifulSoup(html, 'html.parser')
            book_chapter_list = soup.find_all('ul', class_="book-chapter-list")
            for book_chapter in book_chapter_list:
                a_list = book_chapter.find_all('a')
                for a in a_list:
                    datas.append([
                        int(a['href'].split("/")[-1]),
                        a.text.strip()
                    ])
            datas.sort(key=lambda x: x[0])
            return datas[max(0, len(datas) - n):]
        except Exception as e:
            logger.error(f"解析章节列表失败: {e}")
            return []

    # 获取单个章节的详细信息
    async def get_chapter_info(self, session, chapter_id, chapter_name):
        url = f"{self.base_url}/chapter/{chapter_id}"
        html = await self.fetch(session, url)
        if not html:
            return None

        try:
            soup = BeautifulSoup(html, 'html.parser')
            read_hd_div = soup.find('div', class_="read-hd")
            GapStickers = read_hd_div.find("span", id="J_TsukkomiNum").text.strip()

            updatatime, words = None, None
            for span in read_hd_div.find("p").find_all("span"):
                if "更新时间" in span.text:
                    updatatime = span.text.split("更新时间：")[-1].strip()
                if "字数" in span.text:
                    words = int(span.text.split("字数：")[-1].strip())

            if GapStickers and updatatime and words:
                return [chapter_id, chapter_name, GapStickers, updatatime, words]
            else:
                logger.error(f"数据缺失: {chapter_id}, {chapter_name}, {GapStickers}, {updatatime}, {words}")
                return None
        except Exception as e:
            logger.error(f"解析章节信息失败: {chapter_id}, 错误: {e}")
            logger.error(f"url: {url}\n" + "-" * 10)
            logger.error(f"html: \n{html}\n" + "-" * 10)
            return None

    # 获取最新 n 章节的详细信息，使用aiometer控制并发
    async def get_chapter_informationforn(self, book_id, n=50):
        async with aiohttp.ClientSession(headers=self.headers) as session:
            chapters = await self.get_chapter_list(session, book_id, n)
            if not chapters:
                return []

            # 使用aiometer控制并发
            try:
                results = await aiometer.run_all(
                    [functools.partial(self.get_chapter_info, session, cid, cname) for cid, cname in chapters],
                    max_at_once=5,  # 最大并发数
                    max_per_second=2  # 每秒最大请求数
                )
                return [r for r in results if r is not None and not isinstance(r, Exception)]
            except Exception as e:
                logger.error(f"获取章节信息时出错: {e}")
                return []

    # 根据名称搜索书
    async def get_novel_id(self, book_name):
        data = requests.get('https://www.ciweimao.com/get-search-book-list/0-0-0-0-0-0/全部/' + book_name + '/1').text
        book_matches = re.findall(r'<p class="tit"><a href="https://www\.ciweimao\.com/book/(\d+)"[^>]+>([^<]+)</a></p>', data)
        outputdata = {}
        if book_matches:
            for book_id, title_text in book_matches:
                outputdata[title_text] = book_id

        if len(outputdata) == 0:
            return "未能搜到该书籍"
        else:
            return "\n" + "\n".join([
                f"{title_text}:{outputdata[title_text]}"
                for title_text in list(outputdata)
            ])

@register("Getcwm", "lishining", "一个刺猬猫小说数据获取与画图插件,/Getcwm help查看帮助", "1.0.5")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.getcwm = GetCwm()
        self.output_path = "./img"
        self.help_dict = {
            "help": "查看帮助",
            "jt": "即时爬取cwm小说数据并使用对应数据进行画图包括间贴,更新时间点,更新字数\n使用案例: /Getcwm jt [书籍id] [读取条数n(可选择,默认为50)]",
            "Search": "搜索小说id,\n使用案例: /Getcwm Search [书籍名称]"
        }
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)

    # 插件卸载/重载时调用，清理资源
    async def terminate(self):
        logger.info("正在停止论文推送插件定时任务...")

    # 一个刺猬猫小说数据获取与画图插件,/Getcwm help查看帮助
    @filter.command("Getcwm")
    async def Getcwm(self, event: AstrMessageEvent, bot):
        logger.info("/Getcwm接收到消息")
        text = event.get_message_str()
        params = extract_help_parameters(text, "Getcwm")
        logger.info("params为:" + ",".join(params))
        directives = params[0]
        if "help" in directives:
            yield event.plain_result("\n\n".join([f"{name}:{self.help_dict[name]}" for name in list(self.help_dict)]))
            return
        elif "jt" in directives:
            try:
                if len(params) == 3:
                    Novelid = int(params[1])
                    n = int(params[2])
                else:
                    Novelid = int(params[1])
                    n = 50
                img_name = f"{Novelid}-{datetime.now().strftime('%Y-%m-%d')}"
                if os.path.exists(os.path.join(self.output_path, f"{img_name}.png")):
                    yield event.make_result().file_image(os.path.join(self.output_path, f"{img_name}.png"))
                    return
                chapterdata = await self.getcwm.get_chapter_informationforn(Novelid, n)
            except Exception as e:
                logger.error(f"jt报错:{e}")
                yield event.plain_result(f"jt报错:{e}")
                return

            if chapterdata:
                plot_data(chapterdata, img_name, output_path="./img")
                yield event.make_result().file_image(os.path.join(self.output_path, f"{img_name}.png"))
                return
            else:
                yield event.plain_result(f"jt获取错误")
                return
        elif "Search" in directives:
            try:
                novelname = params[1]
                yield event.plain_result(await self.getcwm.get_novel_id(novelname))
            except Exception as e:
                logger.error(f"Search获取小说信息失败,参数:{params}, 错误: {e}")
            return
        else:
            yield event.plain_result(f"需要指令")
            return
