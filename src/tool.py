import matplotlib.pyplot as plt
from astrbot.api import logger
import matplotlib.font_manager as fm
import pandas as pd
import platform
import re
import os

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
