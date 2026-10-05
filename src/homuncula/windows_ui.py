from __future__ import annotations

import os
import uuid
from typing import Any


class WindowsUIUnavailable(RuntimeError):
    pass


class StaleElementReference(LookupError):
    pass


class WindowsUIProvider:
    def __init__(self, desktop: Any | None = None):
        self._desktop_override = desktop
        self._registry: dict[str, Any] = {}

    def _desktop(self) -> Any:
        if self._desktop_override is not None:
            return self._desktop_override
        if os.name != "nt":
            raise WindowsUIUnavailable("Windows UI Automation requires Windows")
        try:
            from pywinauto import Desktop
        except ImportError as exc:
            raise WindowsUIUnavailable("pywinauto is not installed") from exc
        return Desktop(backend="uia")

    def _register(self, wrapper: Any) -> str:
        existing = getattr(wrapper, "_homuncula_ref", None)
        if existing and existing in self._registry:
            return existing
        reference = "uia_" + uuid.uuid4().hex
        try:
            setattr(wrapper, "_homuncula_ref", reference)
        except (AttributeError, TypeError):
            pass
        self._registry[reference] = wrapper
        return reference

    @staticmethod
    def _safe(callable_value: Any, default: Any = None) -> Any:
        try:
            return callable_value()
        except Exception:  # noqa: BLE001
            return default

    def _describe(self, wrapper: Any) -> dict[str, Any]:
        element_info = getattr(wrapper, "element_info", None)
        name = self._safe(getattr(wrapper, "window_text", lambda: ""), "")
        control_type = getattr(element_info, "control_type", None)
        automation_id = getattr(element_info, "automation_id", None)
        class_name = getattr(element_info, "class_name", None)
        rectangle = self._safe(getattr(wrapper, "rectangle", lambda: None))
        rect = None
        if rectangle is not None:
            rect = {
                "left": getattr(rectangle, "left", None),
                "top": getattr(rectangle, "top", None),
                "right": getattr(rectangle, "right", None),
                "bottom": getattr(rectangle, "bottom", None),
            }
        return {
            "ref": self._register(wrapper),
            "name": name,
            "control_type": control_type,
            "automation_id": automation_id,
            "class_name": class_name,
            "enabled": bool(self._safe(getattr(wrapper, "is_enabled", lambda: True), True)),
            "visible": bool(self._safe(getattr(wrapper, "is_visible", lambda: True), True)),
            "rectangle": rect,
        }

    def list_windows(self, *, limit: int = 100) -> list[dict[str, Any]]:
        desktop = self._desktop()
        windows = desktop.windows(visible_only=True)
        return [self._describe(wrapper) for wrapper in windows[: max(1, min(limit, 300))]]

    def snapshot(
        self,
        reference: str,
        *,
        depth: int = 4,
        max_nodes: int = 400,
    ) -> dict[str, Any]:
        wrapper = self._resolve(reference)
        remaining = max(1, min(max_nodes, 1500))

        def walk(node: Any, level: int) -> dict[str, Any]:
            nonlocal remaining
            remaining -= 1
            described = self._describe(node)
            described["children"] = []
            if level >= depth or remaining <= 0:
                return described
            children = self._safe(getattr(node, "children", lambda: []), []) or []
            for child in children:
                if remaining <= 0:
                    break
                described["children"].append(walk(child, level + 1))
            return described

        return walk(wrapper, 0)

    def focus(self, reference: str) -> dict[str, Any]:
        wrapper = self._resolve(reference)
        wrapper.set_focus()
        return {"ref": reference, "focused": True}

    def invoke(self, reference: str) -> dict[str, Any]:
        wrapper = self._resolve(reference)
        invoke = getattr(wrapper, "invoke", None)
        if callable(invoke):
            invoke()
        else:
            wrapper.click_input()
        return {"ref": reference, "invoked": True}

    def set_text(self, reference: str, text: str) -> dict[str, Any]:
        wrapper = self._resolve(reference)
        setter = getattr(wrapper, "set_edit_text", None)
        if callable(setter):
            setter(text)
        else:
            wrapper.set_focus()
            wrapper.type_keys("^a{BACKSPACE}", set_foreground=True)
            wrapper.type_keys(text, with_spaces=True, set_foreground=True)
        return {"ref": reference, "characters": len(text)}

    def select(self, reference: str) -> dict[str, Any]:
        wrapper = self._resolve(reference)
        selector = getattr(wrapper, "select", None)
        if not callable(selector):
            raise WindowsUIUnavailable("Control does not expose a select pattern")
        selector()
        return {"ref": reference, "selected": True}

    def scroll(
        self,
        reference: str,
        *,
        direction: str,
        amount: str = "page",
        count: int = 1,
    ) -> dict[str, Any]:
        wrapper = self._resolve(reference)
        scroller = getattr(wrapper, "scroll", None)
        if not callable(scroller):
            raise WindowsUIUnavailable("Control does not expose a scroll pattern")
        scroller(direction, amount, max(1, min(count, 20)))
        return {
            "ref": reference,
            "direction": direction,
            "amount": amount,
            "count": count,
        }

    def invalidate(self, reference: str) -> None:
        self._registry.pop(reference, None)

    def _resolve(self, reference: str) -> Any:
        wrapper = self._registry.get(reference)
        if wrapper is None:
            raise StaleElementReference(reference)
        exists = getattr(wrapper, "exists", None)
        if callable(exists) and not bool(self._safe(lambda: exists(timeout=0), False)):
            self.invalidate(reference)
            raise StaleElementReference(reference)
        return wrapper
