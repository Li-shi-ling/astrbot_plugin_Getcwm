from __future__ import annotations

import importlib.util
import logging
import sys
import types
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "astrbot_plugin_Getcwm"


class _AstrBotConfig(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _CommandGroup:
    def __call__(self, func):
        return self

    def command(self, _name):
        def decorator(func):
            return func

        return decorator


class _FilterModule:
    EventMessageType = type("EventMessageType", (), {"ALL": "all"})

    @staticmethod
    def command_group(_name):
        return _CommandGroup()

    @staticmethod
    def permission_type(_permission):
        def decorator(func):
            return func

        return decorator

    @staticmethod
    def event_message_type(_message_type, priority=0):
        def decorator(func):
            return func

        return decorator

    @staticmethod
    def on_llm_request(priority=0):
        def decorator(func):
            return func

        return decorator

    @staticmethod
    def llm_tool(name: str):
        def decorator(func):
            func._llm_tool_name = name
            return func

        return decorator


class _Star:
    def __init__(self, context):
        self.context = context


class _StarTools:
    send_message = None

    @staticmethod
    def get_data_dir() -> str:
        return str(PLUGIN_DIR / ".test-data")


def _get_astrbot_temp_path() -> str:
    return str(PLUGIN_DIR / ".test-temp")


class _ImageComponent:
    @staticmethod
    def fromFileSystem(path: str):
        return {"kind": "image", "path": path}


class _MessageChain:
    def __init__(self) -> None:
        self.chain: list[object] = []

    def message(self, text: str):
        self.chain.append({"kind": "text", "text": text})
        return self

    def file_image(self, path: str):
        self.chain.append({"kind": "image", "path": path})
        return self


class _ToolSet:
    def __init__(self) -> None:
        self.tools: list[object] = []

    def add_tool(self, tool: object) -> None:
        self.tools.append(tool)

    def get_tool(self, name: str):
        for tool in self.tools:
            if getattr(tool, "name", None) == name:
                return tool
        return None

    def remove_tool(self, name: str) -> None:
        self.tools = [tool for tool in self.tools if getattr(tool, "name", None) != name]


def _register(*_args, **_kwargs):
    def decorator(cls):
        return cls

    return decorator


def install_astrbot_stubs() -> None:
    if "astrbot.api" in sys.modules:
        return

    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    core_module = types.ModuleType("astrbot.core")
    utils_module = types.ModuleType("astrbot.core.utils")
    astrbot_path_module = types.ModuleType("astrbot.core.utils.astrbot_path")
    astrbot_path_module.get_astrbot_temp_path = _get_astrbot_temp_path
    api.AstrBotConfig = _AstrBotConfig
    api.ToolSet = _ToolSet
    api.logger = logging.getLogger("astrbot-plugin-tests")

    message_components = types.ModuleType("astrbot.api.message_components")
    message_components.Image = _ImageComponent

    event_module = types.ModuleType("astrbot.api.event")
    event_module.AstrMessageEvent = object
    event_module.MessageChain = _MessageChain
    event_module.filter = _FilterModule()

    event_filter_module = types.ModuleType("astrbot.api.event.filter")
    event_filter_module.PermissionType = type("PermissionType", (), {"ADMIN": "admin"})

    provider_module = types.ModuleType("astrbot.api.provider")
    provider_module.ProviderRequest = object

    star_module = types.ModuleType("astrbot.api.star")
    star_module.Context = object
    star_module.Star = _Star
    star_module.StarTools = _StarTools
    star_module.register = _register

    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api
    sys.modules["astrbot.core"] = core_module
    sys.modules["astrbot.core.utils"] = utils_module
    sys.modules["astrbot.core.utils.astrbot_path"] = astrbot_path_module
    sys.modules["astrbot.api.message_components"] = message_components
    sys.modules["astrbot.api.event"] = event_module
    sys.modules["astrbot.api.event.filter"] = event_filter_module
    sys.modules["astrbot.api.provider"] = provider_module
    sys.modules["astrbot.api.star"] = star_module


def _ensure_package(module_name: str) -> None:
    package_parts = module_name.split(".")[:-1]
    current_path = PLUGIN_DIR
    base_name = PACKAGE_NAME

    if PACKAGE_NAME not in sys.modules:
        package = types.ModuleType(PACKAGE_NAME)
        package.__path__ = [str(PLUGIN_DIR)]
        sys.modules[PACKAGE_NAME] = package

    for part in package_parts:
        base_name = f"{base_name}.{part}"
        current_path = current_path / part
        if base_name in sys.modules:
            continue
        package = types.ModuleType(base_name)
        package.__path__ = [str(current_path)]
        sys.modules[base_name] = package


def load_plugin_module(module_relpath: str, module_name: str):
    install_astrbot_stubs()
    _ensure_package(module_name)

    full_name = f"{PACKAGE_NAME}.{module_name}"
    sys.modules.pop(full_name, None)

    spec = importlib.util.spec_from_file_location(full_name, PLUGIN_DIR / module_relpath)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module {full_name}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def core_module():
    return load_plugin_module("src/core.py", "src.core")


@pytest.fixture
def cards_module():
    return load_plugin_module("src/cards.py", "src.cards")


@pytest.fixture
def main_module():
    return load_plugin_module("main.py", "main")
