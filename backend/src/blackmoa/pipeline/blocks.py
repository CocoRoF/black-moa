"""System prompt blocks (plan/07 §블록). Stable blocks first, volatile blocks last."""
from __future__ import annotations

from geny_executor.stages.s03_system.interface import PromptBlock


class StaticBlock(PromptBlock):
    def __init__(self, name: str, text: str, *, volatile: bool = False):
        self._name, self._text, self._volatile = name, text, volatile

    @property
    def name(self) -> str:
        return self._name

    @property
    def volatile(self) -> bool:
        return self._volatile

    def render(self, state) -> str:
        return self._text


class DynamicBlock(PromptBlock):
    """Volatile block whose text is set by the runner before each turn."""

    def __init__(self, name: str):
        self._name = name
        self.text = ""

    @property
    def name(self) -> str:
        return self._name

    @property
    def volatile(self) -> bool:
        return True

    def render(self, state) -> str:
        return self.text
