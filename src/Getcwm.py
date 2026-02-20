import re
import random
import aiohttp
import asyncio
import requests
import aiometer
import functools
from bs4 import BeautifulSoup
from astrbot.api import logger

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
        book_matches = re.findall(
            r'<p class="tit"><a href="https://www\.ciweimao\.com/book/(\d+)"[^>]+>([^<]+)</a></p>', data)
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
