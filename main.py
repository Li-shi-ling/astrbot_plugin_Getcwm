import os
import re
import aiohttp
import asyncio
import logging
import requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 获取指令后面的参数
def extract_help_parameters(s, directives):
    escaped_directives = re.escape(directives)
    match = re.search(f'{escaped_directives}' + r'\s+(.*)', s)
    if match:
        params = re.split(r'\s+', match.group(1).strip())  # 使用 \s+ 来处理多个空格
        return params
    return []

# 绘画
def plot_data(chapterdata, name, output_path="./img"):
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    df = pd.DataFrame(chapterdata, columns=["chapterid", "chaptername", "GapStickers", "updatatime", "words"])

    df['updatatime'] = pd.to_datetime(df['updatatime'])
    df['GapStickers'] = pd.to_numeric(df['GapStickers'], errors='coerce').fillna(0).astype(int)

    plt.rcParams['font.sans-serif'] = ['SimHei']
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

    logging.info("Charts have been generated and saved!")

# 刺猬猫爬虫类别
class GetCwm:
    def __init__(self):
        self.base_url = "https://www.ciweimao.com"

    async def fetch(self, session, url):
        """异步获取网页内容"""
        try:
            async with session.get(url) as response:
                return await response.text()
        except Exception as e:
            logging.error(f"请求失败: {url}, 错误: {e}")
            return None

    async def get_chapter_list(self, session, book_id, n=50):
        """获取最新 n 章节的 ID 和名称"""
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
            logging.error(f"解析章节列表失败: {e}")
            return []

    async def get_chapter_info(self, session, chapter_id, chapter_name):
        """获取单个章节的详细信息"""
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
                logging.error(f"数据缺失: {chapter_id}, {chapter_name}, {GapStickers}, {updatatime}, {words}")
                return None
        except Exception as e:
            logging.error(f"解析章节信息失败: {chapter_id}, 错误: {e}")
            logging.error(f"url: {url}\n" + "-" * 10)
            logging.error(f"html: \n{html}\n" + "-" * 10)
            return None

    async def get_chapter_informationforn(self, book_id, n=50):
        """获取最新 n 章节的详细信息"""
        async with aiohttp.ClientSession() as session:
            chapters = await self.get_chapter_list(session, book_id, n)
            if not chapters:
                return []

            tasks = [self.get_chapter_info(session, cid, cname) for cid, cname in chapters]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            return [r for r in results if not isinstance(r, Exception)]

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

@register("Getcwm", "lishining", "一个刺猬猫小说数据获取与画图插件,/Getcwm help查看帮助", "1.0.1", "repo url")
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

    # 获取cwm数据代码
    @filter.command("Getcwm")
    async def Getcwm(self, event: AstrMessageEvent):
        '''一个刺猬猫小说数据获取与画图插件,/Getcwm help查看帮助'''
        logging.info("/Getcwm接收到消息")
        text = event.get_message_str()
        params = extract_help_parameters(text, "Getcwm")
        logging.info("params为:" + ",".join(params))
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
                logging.error(f"jt报错:{e}")
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
                logging.error(f"Search获取小说信息失败,参数:{params}, 错误: {e}")
            return
        else:
            yield event.plain_result(f"需要指令")
            return
