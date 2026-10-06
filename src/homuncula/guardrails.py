from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


MUTATING_TOOLS = frozenset(
    {
        "write_file",
        "run_process",
        "start_process",
        "browser_click",
        "browser_fill",
        "browser_press",
        "browser_select",
        "browser_upload",
        "windows_focus",
        "windows_invoke",
        "windows_set_text",
        "windows_select",
        "windows_scroll",
        "skill_install",
    }
)


def _canonical_args(args: dict[str, Any]) -> str:
    return json.dumps(
        args,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _signature(name: str, args: dict[str, Any]) -> str:
    material = name + "\n" + _canonical_args(args)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _result_hash(result: dict[str, Any]) -> str:
    material = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _failed(result: dict[str, Any]) -> bool:
    if "error" in result:
        return True
    return result.get("status") in {"failed", "denied"}


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    code: str = "allow"
    message: str = ""


class ToolLoopGuard:
    def __init__(
        self,
        *,
        max_calls: int = 64,
        repeated_failure_limit: int = 4,
        no_progress_limit: int = 4,
    ):
        self.max_calls = max(8, max_calls)
        self.repeated_failure_limit = max(2, repeated_failure_limit)
        self.no_progress_limit = max(2, no_progress_limit)
        self.total_calls = 0
        self._failures: dict[str, int] = {}
        self._last_result: dict[str, tuple[str, int]] = {}
        self._completed_mutations: set[str] = set()

    def before(self, name: str, args: dict[str, Any]) -> GuardDecision:
        if self.total_calls >= self.max_calls:
            return GuardDecision(
                False,
                "turn_tool_budget_exhausted",
                (
                    f"Blocked {name}: this turn reached the {self.max_calls}-tool safety "
                    "budget. Use the evidence already gathered or continue in another turn."
                ),
            )

        signature = _signature(name, args)
        failures = self._failures.get(signature, 0)
        if failures >= self.repeated_failure_limit:
            return GuardDecision(
                False,
                "repeated_exact_failure",
                (
                    f"Blocked {name}: the same call failed {failures} times with identical "
                    "arguments. Change strategy instead of replaying it."
                ),
            )

        previous = self._last_result.get(signature)
        if previous and previous[1] >= self.no_progress_limit:
            return GuardDecision(
                False,
                "identical_no_progress",
                (
                    f"Blocked {name}: the same call returned the same result "
                    f"{previous[1]} times. Reuse that result or change the query."
                ),
            )

        if name in MUTATING_TOOLS and signature in self._completed_mutations:
            return GuardDecision(
                False,
                "duplicate_mutation",
                (
                    f"Blocked {name}: an identical mutation already completed this turn. "
                    "Inspect the result before attempting another change."
                ),
            )

        self.total_calls += 1
        return GuardDecision(True)

    def after(
        self,
        name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        signature = _signature(name, args)

        if _failed(result):
            self._failures[signature] = self._failures.get(signature, 0) + 1
            self._last_result.pop(signature, None)
            return

        self._failures.pop(signature, None)
        result_hash = _result_hash(result)
        previous = self._last_result.get(signature)
        repeat_count = (
            previous[1] + 1
            if previous is not None and previous[0] == result_hash
            else 1
        )
        self._last_result[signature] = (result_hash, repeat_count)

        if name in MUTATING_TOOLS and result.get("status") == "completed":
            self._completed_mutations.add(signature)
