from __future__ import annotations

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
