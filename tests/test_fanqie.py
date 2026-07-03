from __future__ import annotations

import json
import sqlite3
from types import MethodType
from types import SimpleNamespace

import pytest
import requests


class DummyContext:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, object]] = []
        self.tool_manager = SimpleNamespace(get_func=lambda _name: None)

    async def send_message(self, umo: str, chain) -> None:
        self.sent_messages.append((umo, chain))

    def get_llm_tool_manager(self):
        return self.tool_manager


class DummyEvent:
    def __init__(self, umo: str = "session-1", *, admin: bool = False) -> None:
        self.unified_msg_origin = umo
        self._admin = admin
        self.message_obj = SimpleNamespace(message_str="")

    def is_admin(self) -> bool:
        return self._admin

    def plain_result(self, text: str):
        return {"kind": "plain", "text": text}

    def chain_result(self, chain):
        return {"kind": "chain", "chain": chain}


class FakeResponse:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": "text/html"}
        self.status_code = 200
        self.url = "https://fanqienovel.com/page/7657494514256333886"
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.headers = {}
        self.calls: list[tuple[str, int | None, dict | None]] = []

    def get(self, url: str, timeout=None, headers=None, **_kwargs):
        self.calls.append((url, timeout, headers))
        return self.response


def make_plugin(main_module, tmp_path):
    main_module.StarTools.get_data_dir = staticmethod(lambda: str(tmp_path))
    main_module.get_astrbot_temp_path = lambda: str(tmp_path / "temp")
    context = DummyContext()
    config = main_module.AstrBotConfig({"interval_time": 15})
    plugin = main_module.GetcwmPlugin(context, config)
    plugin.subscribe_data_file = tmp_path / "subscribe.json"
    plugin.subscribe_db_file = tmp_path / "subscribe.db"
    plugin.subscribe_db = main_module.DBManager(plugin.subscribe_db_file)
    plugin.subscribe_repo = main_module.SubscribeRepo(plugin.subscribe_db)
    return plugin


def test_parse_fanqie_book_details_html_content_extracts_initial_state(core_module):
    html = r'''
    <script>
    window.__INITIAL_STATE__={"page":{"bookId":"7657494514256333886","bookName":"弹幕都说我根本不是营业","authorName":"铁板大鲸鱼","creationStatus":1,"categoryV2":"[{\"Name\":\"都市脑洞\"},{\"Name\":\"都市\"}]","abstract":"作品简介","thumbUrl":"//example.test/cover.jpg","wordNumber":17450,"readCount":44,"lastPublishTime":"1782978266","lastChapterTitle":"第5章 磕cp被发现了！","chapterTotal":5}};
    </script>
    '''

    details = core_module.parse_fanqie_book_details_html_content(html)

    assert details["Works_Name"] == "弹幕都说我根本不是营业"
    assert details["Author_Name"] == "铁板大鲸鱼"
    assert details["Tag_List"] == ["连载中", "都市脑洞", "都市"]
    assert details["Chapter_Name"] == "第5章 磕cp被发现了！"
    assert details["Update_Time"] == 1782978266
    assert details["Cover_Image"] == "https://example.test/cover.jpg"
    assert details["data"]["来源"] == "番茄小说"
    assert details["data2"]["总字数"] == "1.7万"


def test_parse_fanqie_book_details_html_content_keeps_extra_fields(core_module):
    html = json.dumps(
        {
            "page": {
                "bookId": "7657494514256333886",
                "bookName": "Fanqie Book",
                "authorName": "Author",
                "authorId": "1651933863750916",
                "mediaId": "1869504742207497",
                "creationStatus": 1,
                "categoryV2": '[{"Name":"都市脑洞"}]',
                "abstract": "Intro",
                "readCount": 44,
                "wordNumber": 17450,
                "chapterTotal": 5,
                "lastChapterItemId": "7657832922602291736",
                "lastChapterTitle": "第5章 磕cp被发现了！",
                "lastPublishTime": "1782978266",
                "volumeNameList": ["第一卷：2nd公演"],
                "originalAuthors": [{"AuthorName": "Author"}],
                "chapterListWithVolume": [
                    [
                        {
                            "itemId": "7657494589602808382",
                            "title": "第1章 开始营业的那天",
                            "realChapterOrder": "1",
                            "volume_name": "第一卷：2nd公演",
                            "firstPassTime": "1782900773",
                        },
                        {
                            "itemId": "7657832922602291736",
                            "title": "第5章 磕cp被发现了！",
                            "realChapterOrder": "5",
                            "volume_name": "第一卷：2nd公演",
                            "firstPassTime": "1782978266",
                        },
                    ]
                ],
            }
        },
        ensure_ascii=False,
    )
    html = f"<script>window.__INITIAL_STATE__={html};</script>"

    details = core_module.parse_fanqie_book_details_html_content(html)

    assert details["data"]["媒体ID"] == "1869504742207497"
    assert details["data"]["作者ID"] == "1651933863750916"
    assert details["data"]["最新章节ID"] == "7657832922602291736"
    assert details["data2"]["阅读量"] == 44
    assert details["fanqie_extra"]["chapter_total"] == 5
    assert details["fanqie_extra"]["volume_names"] == ["第一卷：2nd公演"]
    assert details["fanqie_extra"]["chapter_preview"][-1]["item_id"] == "7657832922602291736"


def test_parse_fanqie_search_html_content_extracts_api_payload(core_module):
    html = json.dumps(
        {
            "code": 0,
            "data": {
                "search_book_data_list": [
                    {
                        "book_id": "7657494514256333886",
                        "book_name": "弹幕都说我根本不是营业",
                        "author": "铁板大鲸鱼",
                        "book_abstract": "作品简介",
                        "last_chapter_title": "第5章 磕cp被发现了！",
                        "last_chapter_time": "1782978266",
                    }
                ]
            },
        },
        ensure_ascii=False,
    )

    results = core_module.parse_fanqie_search_html_content(html)

    assert len(results) == 1
    assert results[0]["title"] == "弹幕都说我根本不是营业"
    assert results[0]["author"] == "铁板大鲸鱼"
    assert results[0]["read_url"] == "https://fanqienovel.com/page/7657494514256333886"
    assert "第5章" in results[0]["update_time"]


def test_fanqie_client_get_book_details_uses_session(core_module):
    session = FakeSession(FakeResponse("<title>Fanqie</title>"))
    client = core_module.FanqieNovelClient(session=session, timeout_s=6)

    html = client.get_book_details(7657494514256333886)

    assert "Fanqie" in html
    assert session.calls[0][0].endswith("/page/7657494514256333886")
    assert session.calls[0][1] == 6


def test_parse_fanqie_reader_book_id_extracts_chapter_book_id(core_module):
    html = """
    <script>
    window.__INITIAL_STATE__={"reader":{"chapterData":{"bookId":"7657494514256333886","itemId":"7657494589602808382"}}};
    </script>
    """

    assert core_module.parse_fanqie_reader_book_id(html) == 7657494514256333886


class FanqieReaderFallbackClient:
    def __init__(self, reader_id: int, book_id: int, reader_html: str, book_html: str):
        self.reader_id = reader_id
        self.book_id = book_id
        self.reader_html = reader_html
        self.book_html = book_html
        self.session = SimpleNamespace()
        self.calls: list[tuple[str, int]] = []

    def get_book_details(self, book_id: int) -> str:
        self.calls.append(("book", int(book_id)))
        if int(book_id) == self.reader_id:
            response = requests.Response()
            response.status_code = 404
            response.url = f"https://fanqienovel.com/page/{book_id}"
            raise requests.HTTPError("404 Client Error", response=response)
        assert int(book_id) == self.book_id
        return self.book_html

    def get_reader_details(self, item_id: int) -> str:
        self.calls.append(("reader", int(item_id)))
        assert int(item_id) == self.reader_id
        return self.reader_html


def make_fanqie_state_html(kind: str, payload: dict) -> str:
    return (
        "<script>window.__INITIAL_STATE__="
        + json.dumps({kind: payload}, ensure_ascii=False)
        + ";</script>"
    )


@pytest.mark.asyncio
async def test_fanqie_fetch_details_falls_back_from_reader_id(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)
    reader_id = 7657494589602808382
    book_id = 7657494514256333886
    plugin._fq_client = FanqieReaderFallbackClient(
        reader_id,
        book_id,
        make_fanqie_state_html(
            "reader",
            {"chapterData": {"bookId": str(book_id), "itemId": str(reader_id)}},
        ),
        make_fanqie_state_html(
            "page",
            {
                "bookId": str(book_id),
                "bookName": "Fanqie Book",
                "authorName": "Author",
                "lastPublishTime": "1782978266",
                "lastChapterTitle": "Chapter 1",
            },
        ),
    )

    resolved_book_id, details = await plugin._fetch_fanqie_book_details_by_any_id(
        reader_id
    )

    assert resolved_book_id == book_id
    assert details["Works_Name"] == "Fanqie Book"
    assert plugin._fq_client.calls == [
        ("book", reader_id),
        ("reader", reader_id),
        ("book", book_id),
    ]


@pytest.mark.asyncio
async def test_fq_subscribe_uses_resolved_book_id_for_reader_input(
    main_module, tmp_path
):
    plugin = make_plugin(main_module, tmp_path)
    reader_id = 7657494589602808382
    book_id = 7657494514256333886
    plugin._fq_client = FanqieReaderFallbackClient(
        reader_id,
        book_id,
        make_fanqie_state_html(
            "reader",
            {"chapterData": {"bookId": str(book_id), "itemId": str(reader_id)}},
        ),
        make_fanqie_state_html(
            "page",
            {
                "bookId": str(book_id),
                "bookName": "Fanqie Book",
                "authorName": "Author",
                "lastPublishTime": "1782978266",
                "lastChapterTitle": "Chapter 1",
            },
        ),
    )
    seen: dict[str, object] = {}

    async def fake_yield_card(self, event, resolved_id, data):
        seen["card_id"] = resolved_id
        yield event.plain_result(f"card:{resolved_id}:{data['Works_Name']}")

    async def fake_subscribe(self, event, resolved_id, *, source="cwm"):
        seen["subscribe_id"] = resolved_id
        seen["source"] = source
        return f"subscribed:{resolved_id}:{source}"

    plugin._yield_fanqie_card = MethodType(fake_yield_card, plugin)
    plugin._subscribe = MethodType(fake_subscribe, plugin)

    results = [item async for item in plugin.fq_subscribe(DummyEvent(), reader_id)]

    assert seen == {"card_id": book_id, "subscribe_id": book_id, "source": "fq"}
    assert results[-1]["text"] == f"subscribed:{book_id}:fq"


@pytest.mark.asyncio
async def test_fq_search_books_returns_structured_json(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)
    plugin._fq_client = SimpleNamespace(
        search_name=lambda keyword, page: f"{keyword}-{page}"
    )
    main_module.parse_fanqie_search_html_content = lambda _html: [
        {
            "title": "番茄书",
            "author": "Writer",
            "update_time": "Now",
            "description": "Desc",
            "read_url": "https://fanqienovel.com/page/7657494514256333886",
        }
    ]

    payload = json.loads(await plugin.fq_search_books(DummyEvent(), "alpha", page=2))

    assert payload["query"] == "alpha"
    assert payload["page"] == 2
    assert payload["returned_results"] == 1
    assert payload["results"][0]["book_id"] == 7657494514256333886
    assert payload["results"][0]["title"] == "番茄书"


def test_fanqie_formatters_use_page_urls(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)
    book_id = 7657494514256333886

    search_text = plugin._format_search_text(
        [
            {
                "title": "番茄书",
                "author": "Writer",
                "update_time": "Now",
                "description": "Description",
                "read_url": f"https://fanqienovel.com/page/{book_id}",
            }
        ],
        query="alpha",
        max_items=5,
        source="fq",
    )
    details_text = plugin._format_subscribe_update_text(
        book_id,
        {"Works_Name": "番茄书", "Chapter_Name": "C2", "Update_Time": 1782978266},
        source="fq",
    )

    assert "番茄小说搜索" in search_text
    assert str(book_id) in search_text
    assert f"https://fanqienovel.com/page/{book_id}" in search_text
    assert f"https://fanqienovel.com/page/{book_id}" in details_text


@pytest.mark.asyncio
async def test_fanqie_subscription_source_is_persisted(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)
    book_id = 7657494514256333886
    plugin.b2u = {book_id: ["session-1"]}
    plugin.u2b = {"session-1": [book_id]}
    plugin.bmeta = {
        book_id: {
            "source": "fq",
            "title_text": "番茄书",
            "timestamp": 1782978266,
            "chapter": "第5章",
        }
    }

    await plugin._save_subscribe_data()

    with sqlite3.connect(plugin.subscribe_db_file) as conn:
        subscription_rows = conn.execute(
            "SELECT source, book_id, session_id FROM cwm_subscription"
        ).fetchall()
        meta_rows = conn.execute(
            "SELECT source, book_id, title_text, timestamp, chapter FROM cwm_book_meta"
        ).fetchall()

    assert subscription_rows == [("fq", book_id, "session-1")]
    assert meta_rows == [("fq", book_id, "番茄书", 1782978266, "第5章")]

    loaded = await plugin._load_subscribe_data()

    assert loaded["bmeta"][book_id]["source"] == "fq"


@pytest.mark.asyncio
async def test_legacy_subscription_database_migrates_to_cwm_source(
    main_module, tmp_path
):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE cwm_subscription (
                book_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                PRIMARY KEY (book_id, session_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE cwm_book_meta (
                book_id INTEGER PRIMARY KEY,
                title_text TEXT NOT NULL DEFAULT '',
                timestamp INTEGER NOT NULL DEFAULT 0,
                chapter TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO cwm_subscription (book_id, session_id) VALUES (?, ?)",
            (42, "session-1"),
        )
        conn.execute(
            """
            INSERT INTO cwm_book_meta (book_id, title_text, timestamp, chapter)
            VALUES (?, ?, ?, ?)
            """,
            (42, "旧书", 123, "旧章"),
        )

    db = main_module.DBManager(db_path)
    await db.init_db()

    with sqlite3.connect(db_path) as conn:
        sub_rows = conn.execute(
            "SELECT source, book_id, session_id FROM cwm_subscription"
        ).fetchall()
        meta_rows = conn.execute(
            "SELECT source, book_id, title_text, timestamp, chapter FROM cwm_book_meta"
        ).fetchall()

    assert sub_rows == [("cwm", 42, "session-1")]
    assert meta_rows == [("cwm", 42, "旧书", 123, "旧章")]
