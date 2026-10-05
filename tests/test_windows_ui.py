from __future__ import annotations

import pytest

from homuncula.windows_ui import StaleElementReference, WindowsUIProvider


class FakeInfo:
    control_type = "Button"
    automation_id = "save"
    class_name = "Button"


class FakeRect:
    left = 1
    top = 2
    right = 30
    bottom = 40


class FakeWrapper:
    def __init__(self, name: str, children: list["FakeWrapper"] | None = None):
        self.name = name
        self.element_info = FakeInfo()
        self._children = children or []
        self.alive = True
        self.invoked = False

    def window_text(self):
        return self.name

    def rectangle(self):
        return FakeRect()

    def is_enabled(self):
        return True

    def is_visible(self):
        return True

    def exists(self, timeout=0):
        return self.alive

    def children(self):
        return self._children

    def set_focus(self):
        return None

    def invoke(self):
        self.invoked = True


class FakeDesktop:
    def __init__(self, windows):
        self._windows = windows

    def windows(self, visible_only=True):
        return self._windows


def test_windows_provider_references_and_stale_detection() -> None:
    child = FakeWrapper("Save")
    root = FakeWrapper("Editor", [child])
    provider = WindowsUIProvider(FakeDesktop([root]))

    windows = provider.list_windows()
    assert windows[0]["name"] == "Editor"

    snapshot = provider.snapshot(windows[0]["ref"])
    child_ref = snapshot["children"][0]["ref"]
    provider.invoke(child_ref)
    assert child.invoked is True

    child.alive = False
    with pytest.raises(StaleElementReference):
        provider.invoke(child_ref)
