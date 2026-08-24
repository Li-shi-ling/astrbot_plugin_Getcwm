from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest


class DummyContext:
    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, object]] = []
        self.tool_manager = SimpleNamespace(get_func=lambda _name: None)

    async def send_message(self, umo: str, chain) -> None:
        self.sent_messages.append((umo, chain))

    def get_llm_tool_manager(self):
        return self.tool_manager


class DummyEvent:
    def __init__(
        self,
        umo: str = "session-1",
        *,
        admin: bool = False,
        message_str: str = "",
    ) -> None:
        self.unified_msg_origin = umo
        self._admin = admin
        self.message_str = message_str
        self._extras: dict[str, object] = {}
        self.message_obj = SimpleNamespace(message_str=message_str)

    def is_admin(self) -> bool:
        return self._admin

    def set_extra(self, key, value):
        self._extras[key] = value

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def plain_result(self, text: str):
        return {"kind": "plain", "text": text}

    def chain_result(self, chain):
        return {"kind": "chain", "chain": chain}


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


def test_normalization_helpers(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)

    assert plugin._safe_int("12") == 12
    assert plugin._safe_int("bad", 7) == 7
    assert plugin._dedupe_str_list([" a ", "a", "", "b", "b"]) == ["a", "b"]
    assert plugin._normalize_book_subscribers({"1": ["u1", "u1", " u2 "], "x": ["u3"]}) == {
        1: ["u1", "u2"]
    }
    assert plugin._rebuild_session_books({1: ["u1", "u2"], 2: ["u1"]}) == {
        "u1": [1, 2],
        "u2": [1],
    }


def test_build_and_apply_book_meta(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)

    meta = plugin._build_book_meta(
        42,
        {"Works_Name": "Alpha", "Update_Time": "123", "Chapter_Name": "C1"},
    )
    merged = plugin._apply_meta_to_details({}, meta)

    assert meta == {
        "source": "cwm",
        "title_text": "Alpha",
        "timestamp": 123,
        "chapter": "C1",
    }
    assert merged["Works_Name"] == "Alpha"
    assert merged["Chapter_Name"] == "C1"
    assert merged["Update_Time"] == 123


def test_render_dir_uses_astrbot_temp_path(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)

    assert plugin._render_dir == tmp_path / "temp" / "Getcwm"
    assert plugin.subscribe_data_file == tmp_path / "subscribe.json"
    assert plugin.subscribe_db_file == tmp_path / "subscribe.db"


def test_card_render_config_defaults(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)

    assert plugin._card_render_kwargs() == {
        "card_style": "glass",
        "t2i_enabled": True,
        "t2i_endpoint": "",
        "t2i_timeout": 20,
    }


def test_card_render_config_can_be_overridden(main_module, tmp_path):
    main_module.StarTools.get_data_dir = staticmethod(lambda: str(tmp_path))
    main_module.get_astrbot_temp_path = lambda: str(tmp_path / "temp")
    config = main_module.AstrBotConfig(
        {
            "interval_time": 15,
            "card_style": "industrial",
            "t2i_enabled": False,
            "t2i_endpoint": "https://example.test/text2img",
            "t2i_timeout": 8,
        }
    )

    plugin = main_module.GetcwmPlugin(DummyContext(), config)

    assert plugin._card_render_kwargs() == {
        "card_style": "industrial",
        "t2i_enabled": False,
        "t2i_endpoint": "https://example.test/text2img",
        "t2i_timeout": 8,
    }


@pytest.mark.asyncio
async def test_update_book_meta_if_newer(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)

    assert await plugin._update_book_meta_if_newer(1, {"timestamp": 50, "title_text": "A"})
    assert plugin.bmeta[1]["timestamp"] == 50
    assert plugin._subscribe_data_dirty is True
    plugin._subscribe_data_dirty = False
    assert not await plugin._update_book_meta_if_newer(1, {"timestamp": 40, "title_text": "B"})
    assert plugin._subscribe_data_dirty is False
    assert await plugin._update_book_meta_if_newer(1, {"timestamp": 60, "title_text": "C"})
    assert plugin.bmeta[1]["title_text"] == "C"
    assert plugin._subscribe_data_dirty is True


@pytest.mark.asyncio
async def test_save_and_load_subscribe_data_round_trip(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)
    plugin.b2u = {1: ["u1", "u2"]}
    plugin.u2b = {"u1": [1], "u2": [1]}
    plugin.bmeta = {1: {"title_text": "Alpha", "timestamp": 123, "chapter": "C1"}}

    await plugin._save_subscribe_data()
    with sqlite3.connect(plugin.subscribe_db_file) as conn:
        subscription_rows = conn.execute(
            "SELECT book_id, session_id FROM cwm_subscription ORDER BY book_id, session_id"
        ).fetchall()
        meta_rows = conn.execute(
            "SELECT book_id, title_text, timestamp, chapter FROM cwm_book_meta"
        ).fetchall()

    assert subscription_rows == [(1, "u1"), (1, "u2")]
    assert meta_rows == [(1, "Alpha", 123, "C1")]
    assert plugin._subscribe_data_dirty is False

    loaded = await plugin._load_subscribe_data()

    assert loaded["b2u"] == {1: ["u1", "u2"]}
    assert loaded["u2b"] == {"u1": [1], "u2": [1]}
    assert loaded["bmeta"][1]["chapter"] == "C1"


@pytest.mark.asyncio
async def test_save_subscribe_data_keeps_existing_db_when_replace_fails(
    main_module, tmp_path, monkeypatch
):
    plugin = make_plugin(main_module, tmp_path)
    plugin.b2u = {1: ["old-user"]}
    plugin.u2b = {"old-user": [1]}
    plugin.bmeta = {1: {"title_text": "Old", "timestamp": 1, "chapter": "Old"}}
    await plugin._save_subscribe_data()

    plugin.b2u = {2: ["new-user"]}
    plugin.u2b = {"new-user": [2]}
    plugin.bmeta = {2: {"title_text": "New", "timestamp": 2, "chapter": "New"}}

    async def fail_replace(_b2u, _bmeta):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(plugin.subscribe_repo, "replace_state", fail_replace)

    await plugin._save_subscribe_data()

    with sqlite3.connect(plugin.subscribe_db_file) as conn:
        subscription_rows = conn.execute(
            "SELECT book_id, session_id FROM cwm_subscription ORDER BY book_id, session_id"
        ).fetchall()
        meta_rows = conn.execute(
            "SELECT book_id, title_text, timestamp, chapter FROM cwm_book_meta"
        ).fetchall()

    assert subscription_rows == [(1, "old-user")]
    assert meta_rows == [(1, "Old", 1, "Old")]
    assert plugin._subscribe_data_dirty is True


@pytest.mark.asyncio
async def test_save_subscribe_data_keeps_dirty_when_sqlite_write_fails(
    main_module, tmp_path, monkeypatch
):
    plugin = make_plugin(main_module, tmp_path)
    plugin.b2u = {1: ["old-user"]}
    plugin.u2b = {"old-user": [1]}
    plugin.bmeta = {1: {"title_text": "Old", "timestamp": 1, "chapter": "Old"}}

    async def fail_replace(_b2u, _bmeta):
        raise sqlite3.OperationalError("simulated sqlite failure")

    monkeypatch.setattr(plugin.subscribe_repo, "replace_state", fail_replace)

    await plugin._save_subscribe_data()

    assert plugin._subscribe_data_dirty is True


@pytest.mark.asyncio
async def test_terminate_skips_save_when_subscribe_data_is_not_dirty(
    main_module, tmp_path
):
    plugin = make_plugin(main_module, tmp_path)

    async def fail_if_saved():
        raise AssertionError("terminate should not save unchanged subscribe data")

    plugin._save_subscribe_data = fail_if_saved

    await plugin.terminate()


@pytest.mark.asyncio
async def test_load_subscribe_data_supports_legacy_keys(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)
    plugin.subscribe_data_file.write_text(
        json.dumps(
            {
                "b2u": {"3": ["u9"]},
                "bmeta": {"3": {"title": "Legacy", "timestamp": 88, "chapter": "Old"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = await plugin._load_subscribe_data()

    assert loaded["b2u"] == {3: ["u9"]}
    assert loaded["u2b"] == {"u9": [3]}
    assert loaded["bmeta"][3]["title_text"] == "Legacy"
    with sqlite3.connect(plugin.subscribe_db_file) as conn:
        subscription_rows = conn.execute(
            "SELECT book_id, session_id FROM cwm_subscription"
        ).fetchall()
        meta_rows = conn.execute(
            "SELECT book_id, title_text, timestamp, chapter FROM cwm_book_meta"
        ).fetchall()

    assert subscription_rows == [(3, "u9")]
    assert meta_rows == [(3, "Legacy", 88, "Old")]
    assert not plugin.subscribe_data_file.exists()


@pytest.mark.asyncio
async def test_load_subscribe_data_merges_and_deletes_legacy_json(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)
    plugin.b2u = {1: ["db-user"]}
    plugin.u2b = {"db-user": [1]}
    plugin.bmeta = {1: {"title_text": "DbBook", "timestamp": 1, "chapter": "Db"}}
    await plugin._save_subscribe_data()
    plugin.subscribe_data_file.write_text(
        json.dumps(
            {
                "subscriptions": {"1": ["legacy-user"], "2": ["legacy-2"]},
                "book_meta": {
                    "1": {"title_text": "LegacyBook", "timestamp": 2, "chapter": "Legacy"},
                    "2": {"title_text": "Book2", "timestamp": 3, "chapter": "C2"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = await plugin._load_subscribe_data()

    assert loaded["b2u"] == {1: ["db-user", "legacy-user"], 2: ["legacy-2"]}
    assert loaded["u2b"] == {"db-user": [1], "legacy-user": [1], "legacy-2": [2]}
    assert loaded["bmeta"][1]["title_text"] == "LegacyBook"
    assert loaded["bmeta"][2]["chapter"] == "C2"
    assert not plugin.subscribe_data_file.exists()
    with sqlite3.connect(plugin.subscribe_db_file) as conn:
        subscription_rows = conn.execute(
            "SELECT book_id, session_id FROM cwm_subscription ORDER BY book_id, session_id"
        ).fetchall()
        meta_rows = conn.execute(
            "SELECT book_id, title_text, timestamp, chapter FROM cwm_book_meta ORDER BY book_id"
        ).fetchall()

    assert subscription_rows == [(1, "db-user"), (1, "legacy-user"), (2, "legacy-2")]
    assert meta_rows == [(1, "LegacyBook", 2, "Legacy"), (2, "Book2", 3, "C2")]


@pytest.mark.asyncio
async def test_get_subscribe_list_text_checks_admin(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)
    plugin.u2b = {"other-session": [7]}
    event = DummyEvent("current-session", admin=False)

    result = await plugin._get_subscribe_list_text(event, umo="other-session")

    assert "current-session" not in result
    assert "other-session" not in result
    assert result


@pytest.mark.asyncio
async def test_send_proactive_message_falls_back_to_context(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)
    main_module.StarTools.send_message = None

    await plugin._send_proactive_message("umo-1", ["payload"])

    assert plugin.context.sent_messages == [("umo-1", ["payload"])]


@pytest.mark.asyncio
async def test_send_proactive_message_uses_startools_when_available(
    main_module, tmp_path
):
    plugin = make_plugin(main_module, tmp_path)
    calls = []

    async def fake_send_message(umo, chain):
        calls.append((umo, chain))

    main_module.StarTools.send_message = fake_send_message
    await plugin._send_proactive_message("umo-2", ["payload"])

    assert calls == [("umo-2", ["payload"])]
    assert plugin.context.sent_messages == []


@pytest.mark.asyncio
async def test_generate_image_or_fallback_handles_success_and_error(
    main_module, tmp_path
):
    plugin = make_plugin(main_module, tmp_path)
    event = DummyEvent()
    image_path = tmp_path / "card.png"
    image_path.write_bytes(b"png")

    async def good_image():
        return str(image_path)

    async def broken_image():
        raise RuntimeError("boom")

    def text_renderer():
        return "fallback text"

    success_results = [
        item
        async for item in plugin._generate_image_or_fallback(
            event, good_image, text_renderer
        )
    ]
    error_results = [
        item
        async for item in plugin._generate_image_or_fallback(
            event, broken_image, text_renderer
        )
    ]

    assert success_results[0]["kind"] == "chain"
    assert success_results[0]["chain"][0]["path"] == str(image_path)
    assert error_results[0]["kind"] == "plain"
    assert "fallback text" in error_results[0]["text"]
    assert "boom" in error_results[0]["text"]


@pytest.mark.asyncio
async def test_push_update_sends_message_chain_with_image(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)
    rendered_image = tmp_path / "update.png"
    rendered_image.write_bytes(b"png")
    sent_calls = []

    async def fake_send_message(umo, chain):
        sent_calls.append((umo, chain))

    main_module.StarTools.send_message = fake_send_message
    main_module.render_subscribe_update_card = lambda *_args, **_kwargs: str(
        rendered_image
    )

    result = await plugin._push_update(
        77,
        {
            "Works_Name": "Alpha",
            "Author_Name": "Writer",
            "Chapter_Name": "Chapter 3",
            "Update_Time": 1743480000,
        },
        ["session-1"],
        old_meta={"chapter": "Chapter 2", "timestamp": 1743470000},
    )

    assert result == {
        "ok": 1,
        "failed": 0,
        "has_image": True,
        "image_path": str(rendered_image),
    }
    assert len(sent_calls) == 1
    assert sent_calls[0][0] == "session-1"
    assert sent_calls[0][1].chain[0]["kind"] == "text"
    assert sent_calls[0][1].chain[1] == {
        "kind": "image",
        "path": str(rendered_image),
    }


@pytest.mark.asyncio
async def test_cwm_search_books_returns_structured_json(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)
    plugin._cwm_client = SimpleNamespace(
        search_name=lambda keyword, page: f"{keyword}-{page}"
    )
    main_module.parse_search_html_content = lambda _html: [
        {
            "title": "Alpha",
            "author": "Writer",
            "update_time": "Now",
            "description": "Desc",
            "read_url": "https://www.ciweimao.com/book/123",
        }
    ]

    payload = json.loads(await plugin.cwm_search_books(DummyEvent(), "alpha", page=2))

    assert payload["query"] == "alpha"
    assert payload["page"] == 2
    assert payload["returned_results"] == 1
    assert payload["results"][0]["book_id"] == 123
    assert payload["results"][0]["title"] == "Alpha"


def test_formatters_include_query_ids_and_urls(main_module, tmp_path):
    plugin = make_plugin(main_module, tmp_path)

    search_text = plugin._format_search_text(
        [
            {
                "title": "Alpha",
                "author": "Writer",
                "update_time": "Now",
                "description": "Description",
                "read_url": "https://www.ciweimao.com/book/12345",
            }
        ],
        query="alpha",
        max_items=5,
    )
    details_text = plugin._format_subscribe_update_text(
        99,
        {"Works_Name": "Alpha", "Chapter_Name": "C2", "Update_Time": 1743480000},
        old_meta={"chapter": "C1", "timestamp": 1743470000},
    )

    assert "alpha" in search_text
    assert "12345" in search_text
    assert "https://www.ciweimao.com/book/12345" in search_text
    assert "99" in details_text
    assert "https://www.ciweimao.com/book/99" in details_text


