from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    code: str
    message: str
    count: int = 0


class ToolLoopGuard:
    def __init__(
        self,
        *,
        max_total_calls: int = 80,
        max_same_tool: int = 24,
        max_same_call: int = 4,
        max_same_result: int = 3,
    ):
        self.max_total_calls = max_total_calls
        self.max_same_tool = max_same_tool
        self.max_same_call = max_same_call
        self.max_same_result = max_same_result
        self.total_calls = 0
        self.tool_counts: dict[str, int] = {}
        self.call_counts: dict[str, int] = {}
        self.result_counts: dict[tuple[str, str], int] = {}

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    @classmethod
    def _signature(cls, name: str, args: dict[str, Any]) -> str:
        material = name + "\n" + cls._canonical(args)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def before(self, name: str, args: dict[str, Any]) -> GuardDecision:
        signature = self._signature(name, args)
        if self.total_calls >= self.max_total_calls:
            return GuardDecision(
                False,
                "turn_call_cap",
                "Stopped this turn because it reached the tool-call safety cap.",
                self.total_calls,
            )

        tool_count = self.tool_counts.get(name, 0)
        if tool_count >= self.max_same_tool:
            return GuardDecision(
                False,
                "same_tool_cap",
                f"Stopped repeated use of {name} in this turn.",
                tool_count,
            )

        call_count = self.call_counts.get(signature, 0)
        if call_count >= self.max_same_call:
            return GuardDecision(
                False,
                "same_call_cap",
                f"Stopped {name} because the same call was repeated without enough progress.",
                call_count,
            )

        self.total_calls += 1
        self.tool_counts[name] = tool_count + 1
        self.call_counts[signature] = call_count + 1
        return GuardDecision(True, "allow", "allowed", call_count + 1)

    def after(
        self,
        name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> GuardDecision:
        signature = self._signature(name, args)
        result_hash = hashlib.sha256(
            self._canonical(result).encode("utf-8")
        ).hexdigest()
        key = (signature, result_hash)
        count = self.result_counts.get(key, 0) + 1
        self.result_counts[key] = count

        if count >= self.max_same_result:
            return GuardDecision(
                False,
                "same_result_cap",
                (
                    f"{name} returned the same result {count} times for the same call. "
                    "Change strategy instead of repeating it."
                ),
                count,
            )
        return GuardDecision(True, "allow", "allowed", count)
