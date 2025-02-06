import os
import re
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

    # pd.set_option('display.max_rows', None)
    # pd.set_option('display.max_columns', None)
    # logging.info(df)

    df['updatatime'] = pd.to_datetime(df['updatatime'])

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
    # 获取书籍名字对应的书籍(使用cwm的搜索引擎,可能会搜索不到)
    def Get_name(self, name):
        data = requests.get('https://www.ciweimao.com/get-search-book-list/0-0-0-0-0-0/全部/' + name + '/1').text
        book_matches = re.findall(
            r'<p class="tit"><a href="https://www\.ciweimao\.com/book/(\d+)"[^>]+>([^<]+)</a></p>', data)
        update_matches = re.findall(r"<p>最近更新：([\d-]+\s[\d:]+)\s/\s([^<]+)<\/p>", data)
        outputdata = {}
        if book_matches:
            for i, match in enumerate(book_matches):
                book_id, title_text = match
                if i < len(update_matches):
                    time_str, chapter = update_matches[i]
                    time_format = "%Y-%m-%d %H:%M:%S"
                    dt_obj = datetime.strptime(time_str, time_format)
                    timestamp = int(dt_obj.timestamp())
                    outputdata[book_id] = {
                        "title_text": title_text,
                        "time_str": time_str,
                        "timestamp": timestamp,
                        "chapter": chapter
                    }
                else:
                    logging.error("没有找到对应的更新时间和章节名称")
        else:
            logging.error("没有找到书籍信息")
        return outputdata

    # 获取书籍tag对应的书籍(使用cwm的搜索引擎,可能会搜索不到)(获取所有对应标签的书)
    def Get_tag(self, tag, n):
        return requests.get('https://www.ciweimao.com/get-search-book-list/0-0-0-0-0-0/全部/' + tag + '/' + str(n)).text

    # 网页解析
    def Get_tag_html_content(self, html_content):
        soup = BeautifulSoup(html_content, "html.parser")
        novel_list = soup.find_all("li", {"data-book-id": True})
        novels = []
        for novel in novel_list:
            title = novel.find("p", class_="tit").get_text(strip=True)
            link_tag = novel.find("a", class_="cover")
            if link_tag and link_tag.get("href"):
                read_url = link_tag["href"]
            else:
                read_url = "未知链接"
            author_tag = novel.find("p", text=lambda x: x and "小说作者" in x)
            if author_tag:
                author = author_tag.find("a").get_text(strip=True)
            else:
                author = "未知作者"
            update_time_p = novel.find("p", text=lambda x: x and "最近更新" in x)
            if update_time_p:
                update_time = update_time_p.get_text(strip=True)
            else:
                update_time = "未知更新"
            description = novel.find("div", class_="desc").get_text(strip=True)
            novels.append({
                "title": title,
                "author": author,
                "update_time": update_time,
                "description": description,
                "read_url": read_url
            })
        return novels

    # 获取书籍id对应的书籍
    def Get_id(self, id_data):
        return requests.get('https://www.ciweimao.com/book/' + str(id_data)).text

    # 只获取对应id的书
    def Get_id_html_content(self, html_content):
        try:
            soup = BeautifulSoup(html_content, "html.parser")
        except Exception as e:
            logging.error(f"解析阶段错误:{e}")
            return None

        try:
            Works_Name = str(soup.find("div", class_="breadcrumb").get_text(strip=True).split(">")[-1].strip())
        except Exception as e:
            logging.error(f"作品名称获取错误:{e}")
            Works_Name = ""

        try:
            Author_Name = soup.find("h1", class_="title").find("a").get_text(strip=True)
        except Exception as e:
            logging.error(f"作者名称获取错误:{e}")
            Author_Name = ""

        try:
            Tag_List = []
            for i in soup.find("p", class_="label-box").find_all("span"):
                Tag_List.append(i.get_text(strip=True))
        except Exception as e:
            logging.error(f"标签列表获取错误:{e}")
            Tag_List = []

        try:
            Chapter_Name, Update_Time = self.extract_chapter_info(
                soup.find("p", class_="update-time").get_text(strip=True))
        except Exception as e:
            logging.error(f"最新章节和时间获取错误:{e}")
            Chapter_Name = ""
            Update_Time = -1

        try:
            Brief_Introduction = soup.find("div", class_="book-desc J_mCustomScrollbar").get_text().replace(" ", "")
        except Exception as e:
            logging.error(f"简介获取错误:{e}")
            Brief_Introduction = ""

        try:
            data = [i.get_text(strip=True).replace("：", ":") for i in
                    soup.find("div", class_="book-property clearfix").find_all("span")]
        except Exception as e:
            logging.error(f"分析数据获取错误:{e}")
            data = []

        try:
            # 总点击,总收藏,总字数
            data2 = [i.get_text(strip=True) for i in soup.find("p", class_="book-grade").find_all("b")]
        except Exception as e:
            logging.error(f"总点击,总收藏,总字数获取错误:{e}")
            data2 = []

        outputdata = {
            "Works_Name": Works_Name,
            "Author_Name": Author_Name,
            "Tag_List": Tag_List,
            "Chapter_Name": Chapter_Name,
            "Update_Time": Update_Time,
            "Brief_Introduction": Brief_Introduction,
            "data": data,
            "data2": data2
        }
        return outputdata

    # 获取更新时间
    def extract_chapter_info(self, text):
        match = re.search(r'最后更新：(.*?)\s\[(.*?)\]', text)
        if match:
            chapter_title = match.group(1).strip()
            update_time_str = match.group(2).strip()
            update_time = datetime.strptime(update_time_str, '%Y-%m-%d %H:%M:%S')
            timestamp = int(update_time.timestamp())
            return chapter_title, timestamp
        else:
            return None, int(datetime.strptime(re.search(r'\[(.*?)\]', text).group(1).strip(), '%Y-%m-%d %H:%M:%S'))

    # 获取书籍id的更新时间
    def Get_id2time(self, id_data):
        try:
            html_content = requests.get('https://www.ciweimao.com/book/' + str(id_data)).text
        except Exception as e:
            logging.error(f"爬取阶段错误:{e}")
            return None

        try:
            soup = BeautifulSoup(html_content, "html.parser")
        except Exception as e:
            logging.error(f"解析阶段错误:{e}")
            return None

        try:
            Chapter_Name, Update_Time = self.extract_chapter_info(
                soup.find("p", class_="update-time").get_text(strip=True))
        except Exception as e:
            logging.error(f"最新章节和时间获取错误:{e}")
            Chapter_Name = ""
            Update_Time = -1

        try:
            Works_Name = str(soup.find("div", class_="breadcrumb").get_text(strip=True).split(">")[-1].strip())
        except Exception as e:
            Works_Name = ""
            logging.error(f"最新章节和时间获取错误:{e}")

        return Chapter_Name, Update_Time, Works_Name

    # 获取间贴数
    def Get_gap_stickers(self, id_data):
        datas = {}
        try:
            book_detail = requests.get(url=f"https://www.ciweimao.com/chapter-list/{id_data}/book_detail")
            soup = BeautifulSoup(book_detail.text, 'html.parser')
            book_chapter_list = soup.find_all('ul', class_="book-chapter-list")
            for book_chapter in book_chapter_list:
                a_list = book_chapter.find_all('a')
                for a in a_list:
                    chapterid = a['href'].split("/")[-1]
                    datas[chapterid] = {
                        "title": a.text.replace("\t", "").replace("\n", "").replace("\r", ""),
                    }
        except Exception as e:
            logging.error(f"GetGapStickers报错:{e}")
        return datas

    # 获取每一个章节的详细信息,并储存到csv
    def Get_chapter_information(self, datas, oldchapterids, outputputh):
        chapterids = list(datas)
        with open(outputputh, "a") as f:
            for chapterid in chapterids:
                if not int(chapterid) in oldchapterids:
                    GapStickers, updatatime, words = None, None, None
                    try:
                        chapterdata = requests.get(url=f"https://www.ciweimao.com/chapter/{chapterid}")
                        soup = BeautifulSoup(chapterdata.text, 'html.parser')
                        read_hd_div = soup.find('div', class_="read-hd")
                        GapStickers = read_hd_div.find("span", id="J_TsukkomiNum").text
                        for span in read_hd_div.find("p").find_all("span"):
                            if "更新时间" in span.text:
                                updatatime = span.text.split("更新时间：")[-1]
                            if "字数" in span.text:
                                words = span.text.split("字数：")[-1]
                    except Exception as e:
                        logging.error(f"Getchapterinformation报错:{e}")
                    finally:
                        if GapStickers is None or updatatime is None or words is None:
                            logging.error(
                                f"写入失败:{chapterid},{datas[chapterid]['title']},{GapStickers},{updatatime},{words}\n")
                        else:
                            logging.error(
                                f"已写入:{chapterid},{datas[chapterid]['title']},{GapStickers},{updatatime},{words}\n")
                            f.write(f"{chapterid},{datas[chapterid]['title']},{GapStickers},{updatatime},{words}\n")

    # 获取最新n个章节的详细信息
    def Get_chapter_informationforn(self, id_data, n=50):
        datas = []
        try:
            book_detail = requests.get(url=f"https://www.ciweimao.com/chapter-list/{id_data}/book_detail")
            soup = BeautifulSoup(book_detail.text, 'html.parser')
            book_chapter_list = soup.find_all('ul', class_="book-chapter-list")
            for book_chapter in book_chapter_list:
                a_list = book_chapter.find_all('a')
                for a in a_list:
                    datas.append(
                        [int(a['href'].split("/")[-1]), a.text.replace("\t", "").replace("\n", "").replace("\r", "")])
            datas.sort(key=lambda x: int(x[0]))
            datas = datas[max(0, len(datas) - n):]
        except Exception as e:
            logging.error(f"Get_chapter_informationforn报错:{e}")

        outputdata = []
        for data in datas:
            GapStickers, updatatime, words = None, None, None
            try:
                chapterdata = requests.get(url=f"https://www.ciweimao.com/chapter/{data[0]}")
                soup = BeautifulSoup(chapterdata.text, 'html.parser')
                read_hd_div = soup.find('div', class_="read-hd")
                GapStickers = read_hd_div.find("span", id="J_TsukkomiNum").text
                for span in read_hd_div.find("p").find_all("span"):
                    if "更新时间" in span.text:
                        updatatime = span.text.split("更新时间：")[-1]
                    if "字数" in span.text:
                        words = span.text.split("字数：")[-1]
            except Exception as e:
                logging.error(f"Get_chapter_informationforn报错:{e}")
            finally:
                if GapStickers is None or updatatime is None or words is None:
                    logging.error(f"写入失败:{data[0]},{data[1]},{GapStickers},{updatatime},{words}\n")
                else:
                    outputdata.append([data[0], data[1], GapStickers, updatatime, int(words)])
        return outputdata

@register("Getcwm", "lishining", "一个刺猬猫小说数据获取与画图插件,/Getcwm help查看帮助", "1.0.0", "repo url")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.getcwm = GetCwm()
        self.output_path = "./img"
        self.help_dict = {
            "help": "查看帮助",
            "jt": "即时爬取cwm小说数据并使用对应数据进行画图包括(每章间贴数,更新时间点,章更新字数,日更新字数,间贴排行榜前10,间贴排行榜后10)\n使用案例: /Getcwm jt [书籍id] [读取条数n(可选择,默认为50)]"
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
            yield event.plain_result("\n".join([f"{name}:{self.help_dict[name]}" for name in list(self.help_dict)]))
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
                chapterdata = self.getcwm.Get_chapter_informationforn(Novelid, n)
            except Exception as e:
                logging.error(f"jt报错:{e}")
                yield event.plain_result(f"jt报错:{e}")
                return

            if len(chapterdata) <= 0 or Novelid is None:
                yield event.plain_result(f"jt获取错误")
                return
            else:
                plot_data(chapterdata, img_name, output_path="./img")
                yield event.make_result().file_image(os.path.join(self.output_path, f"{img_name}.png"))
                return
        else:
            yield event.plain_result(f"需要指令")
            return
