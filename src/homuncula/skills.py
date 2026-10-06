from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SLUG_RE = re.compile(r"[^a-z0-9_-]+")
SAFE_TOOL_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")


class SkillError(RuntimeError):
    pass


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    instructions: str
    allowed_tools: tuple[str, ...]
    source: str
    path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "allowed_tools": list(self.allowed_tools),
            "source": self.source,
            "path": self.path,
        }


class SkillStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def normalize_name(name: str) -> str:
        slug = SLUG_RE.sub("-", name.strip().lower()).strip("-_")
        if not slug:
            raise ValueError("Skill name must contain letters or numbers")
        if len(slug) > 80:
            raise ValueError("Skill name is too long")
        return slug

    def _skill_dir(self, name: str) -> Path:
        slug = self.normalize_name(name)
        candidate = (self.root / slug).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise SkillError("Skill path escapes the skill root") from exc
        return candidate

    def install(
        self,
        *,
        name: str,
        description: str,
        instructions: str,
        allowed_tools: list[str] | None = None,
        source: str = "generated",
        replace: bool = False,
    ) -> dict[str, Any]:
        slug = self.normalize_name(name)
        skill_dir = self._skill_dir(slug)
        if skill_dir.exists() and not replace:
            raise SkillError(f"Skill already exists: {slug}")

        tools = tuple(dict.fromkeys(allowed_tools or []))
        for tool in tools:
            if not SAFE_TOOL_RE.fullmatch(tool):
                raise ValueError(f"Invalid tool name in skill: {tool}")

        if not description.strip():
            raise ValueError("Skill description is required")
        if not instructions.strip():
            raise ValueError("Skill instructions are required")

        skill_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema": 1,
            "name": slug,
            "description": description.strip(),
            "allowed_tools": list(tools),
            "source": source,
        }
        (skill_dir / "skill.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (skill_dir / "SKILL.md").write_text(
            instructions.strip() + "\n",
            encoding="utf-8",
        )
        return self.get(slug).as_dict()

    def get(self, name: str) -> Skill:
        slug = self.normalize_name(name)
        skill_dir = self._skill_dir(slug)
        manifest_path = skill_dir / "skill.json"
        body_path = skill_dir / "SKILL.md"
        if not manifest_path.exists() or not body_path.exists():
            raise KeyError(slug)

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillError(f"Invalid skill manifest: {slug}") from exc

        if manifest.get("schema") != 1 or manifest.get("name") != slug:
            raise SkillError(f"Unsupported or mismatched skill manifest: {slug}")

        instructions = body_path.read_text(encoding="utf-8")
        tools = tuple(
            str(tool)
            for tool in manifest.get("allowed_tools", [])
            if SAFE_TOOL_RE.fullmatch(str(tool))
        )
        return Skill(
            name=slug,
            description=str(manifest.get("description") or "").strip(),
            instructions=instructions.strip(),
            allowed_tools=tools,
            source=str(manifest.get("source") or "unknown"),
            path=str(skill_dir),
        )

    def list(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for child in sorted(self.root.iterdir(), key=lambda path: path.name.lower()):
            if not child.is_dir():
                continue
            try:
                result.append(self.get(child.name).as_dict())
            except (KeyError, SkillError, ValueError):
                continue
        return result

    def search(self, query: str, *, limit: int = 4) -> list[dict[str, Any]]:
        terms = {
            term
            for term in re.findall(r"[a-z0-9_'-]+", query.lower())
            if len(term) > 2
        }
        scored: list[tuple[float, dict[str, Any]]] = []
        for skill in self.list():
            haystack = (
                skill["name"]
                + " "
                + skill["description"]
                + " "
                + skill["instructions"][:4000]
            ).lower()
            if not terms:
                score = 0.0
            else:
                matched = sum(1 for term in terms if term in haystack)
                score = matched / len(terms)
                if any(term in skill["name"] for term in terms):
                    score += 0.35
                if any(term in skill["description"].lower() for term in terms):
                    score += 0.20
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda item: (item[0], item[1]["name"]), reverse=True)
        return [skill for _, skill in scored[: max(1, min(limit, 12))]]

    def remove(self, name: str) -> None:
        skill_dir = self._skill_dir(name)
        if not skill_dir.exists():
            raise KeyError(name)
        for path in sorted(skill_dir.rglob("*"), reverse=True):
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        skill_dir.rmdir()
