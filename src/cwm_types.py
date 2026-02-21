from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CardRenderResult:
    image_path: str
    data: Any

