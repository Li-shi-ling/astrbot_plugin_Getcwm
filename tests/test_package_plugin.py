from __future__ import annotations

import json
import importlib.util
from pathlib import Path


def test_package_file_list_includes_card_assets():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "package_plugin.py"
    spec = importlib.util.spec_from_file_location("package_plugin", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    files = {path.as_posix() for path in module.list_tracked_files()}

    assert "assets/snowcap_shop/sign.png" in files
    assert "assets/constructivist_people/people_we_home_bg.jpg" in files


def test_card_style_config_uses_dropdown_options():
    schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    card_style = schema["card_style"]

    assert card_style["type"] == "string"
    assert card_style["default"] == "glass"
    assert card_style["options"] == [
        "glass",
        "light",
        "industrial",
        "retro_win",
        "snowcap_shop",
        "constructivist_people",
    ]
