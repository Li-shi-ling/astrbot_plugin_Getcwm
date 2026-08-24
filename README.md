# Getcwm

刺猬猫小说、番茄小说：搜索 / 详情卡片 / 订阅更新推送。

## 指令

- `/cwm help`
- `/cwm 搜索 书名 [页码=1]`
- `/cwm 名片 书籍ID`
- `/cwm 详情 书籍ID`
- `/cwm 订阅 书籍ID`：在当前会话订阅该书更新（需要平台支持主动消息）
- `/cwm 订阅列表 [会话umo=当前会话]`：查看会话的全部订阅（指定其他会话需管理员）
- `/cwm 取消订阅 书籍ID [会话umo=当前会话]`：取消会话对该书的订阅（指定其他会话需管理员）
- `/cwm 全部订阅`：展示所有订阅（管理员）
- `/fq help`
- `/fq 搜索 书名 [页码=1]`
- `/fq 名片 书籍ID或章节ID`
- `/fq 详情 书籍ID`
- `/fq 订阅 书籍ID或章节ID`：在当前会话订阅该书更新（需要平台支持主动消息；章节ID会自动解析为书籍ID）
- `/fq 订阅列表 [会话umo=当前会话]`：查看会话的全部订阅（指定其他会话需管理员）
- `/fq 取消订阅 书籍ID [会话umo=当前会话]`：取消会话对该书的订阅（指定其他会话需管理员）
- `/fq 全部订阅`：展示所有订阅（管理员）

番茄名片会展示番茄页面可获取的扩展数据，包括阅读量、章节数、分卷和最近章节预览；内部ID仅用于请求与订阅，不在卡片中展示。
搜索结果卡片会显示书籍ID，方便直接使用 `/fq 订阅 书籍ID`。
搜索、详情、订阅更新图片使用统一卡片模板，刺猬猫与番茄只通过输入数据和站点资料区分。
卡片样式可通过 `card_style` 切换：`glass`、`light`、`industrial`、`retro_win`、`snowcap_shop`、`constructivist_people`。
如果番茄搜索接口触发风控验证，插件会直接提示当前无法获取搜索结果，并写入日志。

## 订阅更新推送

- 检测间隔：配置项 `interval_time`（分钟，默认 20）
- 存储：`{StarTools.get_data_dir()}/subscribe.json`（自动创建）
- 推送内容：文字 + “订阅更新”图片卡片（渲染失败自动只推文字）
- 番茄小说使用 `/page/书籍ID` 页面数据，订阅检测会按书籍 ID 自动分派到对应站点。
- 数据库使用 `source` 字段区分 `cwm` 与 `fq` 订阅，旧数据会按 `cwm` 自动迁移。

## 图片渲染依赖（可选）

- `t2i_enabled`：是否启用远程 T2I，默认开启
- `t2i_endpoint`：远程 T2I 服务地址，默认留空；可填写根地址、`/text2img` 或 `/text2img/generate`
- `t2i_timeout`：远程 T2I 请求超时时间（秒）
- `html2image`：远程 T2I 失败时的本地回退渲染；缺失且远程渲染失败时会回退为纯文本输出

 ## 👨‍💻 开发者 
 - **开发者**：Lishining 
 - **版本**：v1.1.19
 - **标语**：cwm有些小说还是挺好看的
 - **QQ群**: 1083090761 

[![Moe Counter](https://count.getloli.com/get/@li-shi-ling?theme=minecraft)](https://github.com/Li-shi-ling/astrbot_plugin_Getcwm)
