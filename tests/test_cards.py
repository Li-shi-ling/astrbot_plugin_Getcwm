from __future__ import annotations

from pathlib import Path


def test_calc_card_heights_grow_with_content(cards_module):
    assert cards_module._calc_search_card_height(3) > cards_module._calc_search_card_height(1)
    assert cards_module._calc_book_details_card_height(6, 4) > cards_module._calc_book_details_card_height(1, 1)


def test_render_search_card_calls_renderer(monkeypatch, tmp_path, cards_module):
    captured = {}

    def fake_render_html_to_png(**kwargs):
        captured.update(kwargs)
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(cards_module, "_render_html_to_png", fake_render_html_to_png)

    image_path = cards_module.render_search_card(
        [
          {"title": "Alpha", "author": "A", "update_time": "Now", "description": "desc", "read_url": "https://example.test/book/1"},
          {"title": "Beta", "author": "B", "update_time": "Later", "description": "desc2", "read_url": "https://example.test/book/2"},
        ],
        query="keyword",
        max_items=1,
        output_dir=tmp_path,
    )

    assert image_path.endswith(".png")
    assert captured["output_dir"] == Path(tmp_path)
    assert captured["size"] == (1024, cards_module._calc_search_card_height(1))
    assert "keyword" in captured["html_str"]
    assert "刺猬猫 · 搜索结果" in captured["html_str"]
    assert "Alpha" in captured["html_str"]
    assert "ID: 1" in captured["html_str"]
    assert "Beta" not in captured["html_str"]


def test_render_fanqie_search_card_uses_fanqie_brand(
    monkeypatch, tmp_path, cards_module
):
    captured = {}

    def fake_render_html_to_png(**kwargs):
        captured.update(kwargs)
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(cards_module, "_render_html_to_png", fake_render_html_to_png)

    cards_module.render_search_card(
        [
            {
                "title": "Fanqie",
                "author": "Author",
                "update_time": "Now",
                "description": "desc",
                "read_url": "https://fanqienovel.com/page/7657494514256333886",
            },
        ],
        query="keyword",
        source="fq",
        output_dir=tmp_path,
    )

    html = captured["html_str"]
    assert "番茄小说 · 搜索结果" in html
    assert "刺猬猫 · 搜索结果" not in html
    assert "ID: 7657494514256333886" in html


def test_render_search_card_can_use_other_card_style(monkeypatch, tmp_path, cards_module):
    captured = {}

    def fake_render_html_to_png(**kwargs):
        captured.update(kwargs)
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(cards_module, "_render_html_to_png", fake_render_html_to_png)

    cards_module.render_search_card(
        [
            {
                "title": "Alpha",
                "author": "A",
                "update_time": "Now",
                "description": "desc",
                "read_url": "https://example.test/book/1",
            },
        ],
        card_style="industrial",
        output_dir=tmp_path,
    )

    assert 'id="getcwm-card-theme"' in captured["html_str"]
    assert "#070a0f" in captured["html_str"]


def test_render_search_card_can_use_asset_card_styles(
    monkeypatch, tmp_path, cards_module
):
    captured = {}

    def fake_render_html_to_png(**kwargs):
        captured.setdefault("html", []).append(kwargs["html_str"])
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(cards_module, "_render_html_to_png", fake_render_html_to_png)
    item = {
        "title": "Alpha",
        "author": "A",
        "update_time": "Now",
        "description": "desc",
        "read_url": "https://example.test/book/1",
    }

    cards_module.render_search_card([item], card_style="snowcap_shop", output_dir=tmp_path)
    cards_module.render_search_card(
        [item], card_style="constructivist_people", output_dir=tmp_path
    )

    assert "data:image/png;base64" in captured["html"][0]
    assert "#5d7028" in captured["html"][0]
    assert "data:image/jpeg;base64" in captured["html"][1]
    assert "#9f302a" in captured["html"][1]


def test_render_html_to_png_uses_t2i_endpoint(monkeypatch, tmp_path, cards_module):
    seen = {}

    class FakeResponse:
        headers = {"content-type": "image/png"}
        content = b"\x89PNG\r\n\x1a\nabc"

        def raise_for_status(self):
            return None

    def fake_post(url, json, timeout):
        seen["url"] = url
        seen["json"] = json
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(cards_module.requests, "post", fake_post)

    out_path = cards_module._render_html_to_png(
        html_str="<html></html>",
        size=(100, 100),
        output_dir=tmp_path,
        filename="out.png",
        t2i_enabled=True,
        t2i_endpoint="https://example.test",
        t2i_timeout=7,
    )

    assert out_path == tmp_path / "out.png"
    assert out_path.read_bytes().startswith(b"\x89PNG")
    assert seen["url"] == "https://example.test/text2img/generate"
    assert "<html></html>" in seen["json"]["tmpl"]
    assert "id=\"getcwm-t2i-fixed-size\"" in seen["json"]["tmpl"]
    assert "width: 100vw" in seen["json"]["tmpl"]
    assert "min-width: 100px" in seen["json"]["tmpl"]
    assert "height: auto" in seen["json"]["tmpl"]
    assert seen["json"]["json"] is False
    assert seen["json"]["options"]["full_page"] is True
    assert seen["timeout"] == 7


def test_render_book_details_card_uses_placeholder_when_cover_missing(
    monkeypatch, tmp_path, cards_module
):
    captured = {}

    monkeypatch.setattr(cards_module, "fetch_image_data_uri", lambda *_args, **_kwargs: None)

    def fake_render_html_to_png(**kwargs):
        captured.update(kwargs)
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(cards_module, "_render_html_to_png", fake_render_html_to_png)

    image_path = cards_module.render_book_details_card(
        {
            "Works_Name": "Alpha",
            "Author_Name": "Author",
            "Tag_List": ["Fantasy"],
            "Chapter_Name": "Chapter 1",
            "Update_Time": 1743480000,
            "Brief_Introduction": "Some intro",
            "Cover_Image": "/cover.jpg",
            "data": {"Status": "Ongoing"},
            "data2": {"a": 1, "b": 2, "c": 3},
        },
        output_dir=tmp_path,
    )

    assert image_path.endswith(".png")
    assert "Alpha" in captured["html_str"]
    assert "placeholder" in captured["html_str"]
    assert captured["size"][0] == 1024


def test_render_book_details_card_does_not_clamp_chapter_titles(
    monkeypatch, tmp_path, cards_module
):
    captured = {}
    long_chapter = "第 128 章 这是一个非常非常长的最新章节标题用来确认不同主题下不会被截断显示完整"
    monkeypatch.setattr(cards_module, "fetch_image_data_uri", lambda *_args, **_kwargs: None)

    def fake_render_html_to_png(**kwargs):
        captured.update(kwargs)
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(cards_module, "_render_html_to_png", fake_render_html_to_png)

    cards_module.render_book_details_card(
        {
            "Source": "fq",
            "Works_Name": "Fanqie",
            "Author_Name": "Author",
            "Tag_List": ["Ongoing"],
            "Chapter_Name": long_chapter,
            "Update_Time": 1743480000,
            "Brief_Introduction": "Intro",
            "Cover_Image": "",
            "data": {"来源": "番茄小说", "状态": "连载中"},
            "data2": {"阅读量": 44, "总字数": "1.7万"},
            "fanqie_extra": {
                "chapter_total": 128,
                "read_count": 44,
                "chapter_preview": [
                    {
                        "title": long_chapter,
                        "order": "128",
                        "volume": "V1",
                        "first_pass_time": 1743480000,
                    }
                ],
            },
        },
        card_style="constructivist_people",
        output_dir=tmp_path,
    )

    html = captured["html_str"]
    assert long_chapter in html
    assert ".chapter .v" in html
    assert ".chapter-title" in html
    chapter_block = html.split(".chapter .v", 1)[1].split(".props", 1)[0]
    preview_block = html.split(".chapter-title", 1)[1].split(".chapter-meta", 1)[0]
    assert "-webkit-line-clamp" not in chapter_block
    assert "-webkit-line-clamp" not in preview_block
    assert captured["size"][1] > cards_module._calc_book_details_card_height(1, 2)


def test_render_fanqie_book_details_card_hides_internal_ids(
    monkeypatch, tmp_path, cards_module
):
    captured = {}
    monkeypatch.setattr(cards_module, "fetch_image_data_uri", lambda *_args, **_kwargs: None)

    def fake_render_html_to_png(**kwargs):
        captured.update(kwargs)
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(cards_module, "_render_html_to_png", fake_render_html_to_png)

    cards_module.render_book_details_card(
        {
            "Source": "fq",
            "Works_Name": "Fanqie",
            "Author_Name": "Author",
            "Tag_List": ["Ongoing"],
            "Chapter_Name": "Chapter 2",
            "Update_Time": 1743480000,
            "Brief_Introduction": "Intro",
            "Cover_Image": "",
            "data": {
                "来源": "番茄小说",
                "状态": "连载中",
                "书籍ID": "7657494514256333886",
                "媒体ID": "1869504742207497",
                "作者ID": "1651933863750916",
                "最新章节ID": "7657832922602291736",
            },
            "data2": {"阅读量": 44, "总字数": "1.7万"},
            "fanqie_extra": {
                "book_id": "7657494514256333886",
                "media_id": "1869504742207497",
                "author_id": "1651933863750916",
                "last_chapter_item_id": "7657832922602291736",
                "chapter_total": 5,
                "read_count": 44,
                "chapter_preview": [
                    {
                        "title": "Chapter 2",
                        "item_id": "7657832922602291736",
                        "order": "2",
                        "volume": "V1",
                        "first_pass_time": 1743480000,
                    }
                ],
            },
        },
        output_dir=tmp_path,
    )

    html = captured["html_str"]
    assert "番茄小说 · 书籍详情" in html
    assert "刺猬猫" not in html
    assert "书籍ID" not in html
    assert "媒体ID" not in html
    assert "作者ID" not in html
    assert "最新章节ID" not in html
    assert "7657494514256333886" not in html
    assert "7657832922602291736" not in html


def test_render_subscribe_update_card_embeds_link(monkeypatch, tmp_path, cards_module):
    captured = {}

    monkeypatch.setattr(
        cards_module,
        "fetch_image_data_uri",
        lambda *_args, **_kwargs: "data:image/png;base64,abc",
    )

    def fake_render_html_to_png(**kwargs):
        captured.update(kwargs)
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(cards_module, "_render_html_to_png", fake_render_html_to_png)

    image_path = cards_module.render_subscribe_update_card(
        {
            "Works_Name": "Alpha",
            "Author_Name": "Author",
            "Chapter_Name": "Chapter 2",
            "Update_Time": 1743480000,
            "Cover_Image": "/cover.jpg",
        },
        book_id=77,
        output_dir=tmp_path,
    )

    assert image_path.endswith(".png")
    assert "https://www.ciweimao.com/book/77" in captured["html_str"]
    assert "data:image/png;base64,abc" in captured["html_str"]


def test_render_subscribe_update_card_does_not_clamp_chapter_title(
    monkeypatch, tmp_path, cards_module
):
    captured = {}
    long_chapter = "第 99 章 这个订阅推送章节标题非常长需要完整展示而不是在卡面里被截断"

    monkeypatch.setattr(
        cards_module,
        "fetch_image_data_uri",
        lambda *_args, **_kwargs: "data:image/png;base64,abc",
    )

    def fake_render_html_to_png(**kwargs):
        captured.update(kwargs)
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(cards_module, "_render_html_to_png", fake_render_html_to_png)

    cards_module.render_subscribe_update_card(
        {
            "Source": "fq",
            "Works_Name": "Fanqie",
            "Author_Name": "Author",
            "Chapter_Name": long_chapter,
            "Update_Time": 1743480000,
            "Cover_Image": "/cover.jpg",
        },
        book_id=7657494514256333886,
        card_style="snowcap_shop",
        output_dir=tmp_path,
    )

    html = captured["html_str"]
    assert long_chapter in html
    block = html.split(".block .v", 1)[1].split(".row", 1)[0]
    assert "-webkit-line-clamp" not in block
    assert captured["size"][1] > 520


def test_render_fanqie_subscribe_update_card_uses_fanqie_brand(
    monkeypatch, tmp_path, cards_module
):
    captured = {}

    monkeypatch.setattr(
        cards_module,
        "fetch_image_data_uri",
        lambda *_args, **_kwargs: "data:image/png;base64,abc",
    )

    def fake_render_html_to_png(**kwargs):
        captured.update(kwargs)
        return tmp_path / kwargs["filename"]

    monkeypatch.setattr(cards_module, "_render_html_to_png", fake_render_html_to_png)

    cards_module.render_subscribe_update_card(
        {
            "Source": "fq",
            "Works_Name": "Fanqie",
            "Author_Name": "Author",
            "Chapter_Name": "Chapter 2",
            "Update_Time": 1743480000,
            "Cover_Image": "/cover.jpg",
        },
        book_id=7657494514256333886,
        output_dir=tmp_path,
    )

    html = captured["html_str"]
    assert "番茄小说 · 订阅更新" in html
    assert "刺猬猫 · 订阅更新" not in html
    assert "https://fanqienovel.com/page/7657494514256333886" in html


def test_handle_search_html_content_can_return_data(monkeypatch, cards_module):
    data = [{"title": "Alpha"}]
    monkeypatch.setattr(cards_module, "parse_search_html_content", lambda _html: data)
    monkeypatch.setattr(cards_module, "render_search_card", lambda *_args, **_kwargs: "out.png")

    result = cards_module.handle_search_html_content(
        "<html/>", query="Alpha", return_data=True
    )

    assert result.image_path == "out.png"
    assert result.data == data


def test_handle_book_details_html_content_can_return_data(monkeypatch, cards_module):
    data = {"Works_Name": "Alpha"}
    monkeypatch.setattr(
        cards_module, "parse_book_details_html_content", lambda _html: data
    )
    monkeypatch.setattr(
        cards_module, "render_book_details_card", lambda *_args, **_kwargs: "detail.png"
    )

    result = cards_module.handle_book_details_html_content(
        "<html/>", return_data=True
    )

    assert result.image_path == "detail.png"
    assert result.data == data
