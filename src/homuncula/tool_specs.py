from __future__ import annotations


def function_tool(
    name: str,
    description: str,
    properties: dict,
    *,
    required: list[str] | None = None,
) -> dict:
    parameters = {
        "type": "object",
        "properties": properties,
    }
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


TOOLS = [
    function_tool(
        "list_files",
        "List files inside the configured local workspace.",
        {
            "path": {"type": "string", "default": "."},
            "limit": {"type": "integer", "default": 200},
        },
    ),
    function_tool(
        "read_file",
        "Read a UTF-8 text file inside the configured workspace.",
        {"path": {"type": "string"}},
        required=["path"],
    ),
    function_tool(
        "write_file",
        "Propose writing a UTF-8 text file inside the workspace.",
        {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "intent": {"type": "string"},
        },
        required=["path", "content", "intent"],
    ),
    function_tool(
        "run_process",
        "Propose running a process and wait for it to finish.",
        {
            "argv": {"type": "array", "items": {"type": "string"}},
            "cwd": {"type": "string", "default": "."},
            "timeout": {"type": "integer", "default": 120},
            "intent": {"type": "string"},
        },
        required=["argv", "intent"],
    ),
    function_tool(
        "start_process",
        "Propose starting a background process. Completion becomes an event.",
        {
            "argv": {"type": "array", "items": {"type": "string"}},
            "cwd": {"type": "string", "default": "."},
            "intent": {"type": "string"},
        },
        required=["argv", "intent"],
    ),
    function_tool(
        "process_status",
        "Read the state and captured output of a background process.",
        {"process_id": {"type": "string"}},
        required=["process_id"],
    ),
    function_tool(
        "search_memory",
        "Search durable local memory using hybrid lexical and semantic retrieval.",
        {
            "query": {"type": "string"},
            "scope": {"type": "string", "default": "global"},
            "limit": {"type": "integer", "default": 8},
        },
        required=["query"],
    ),
    function_tool(
        "remember",
        "Store a durable fact, preference, decision, relationship fact, or commitment.",
        {
            "content": {"type": "string"},
            "scope": {"type": "string", "default": "global"},
            "kind": {"type": "string", "default": "fact"},
            "source": {"type": "string", "default": "agent"},
            "confidence": {"type": "number", "default": 1.0},
        },
        required=["content"],
    ),
    function_tool(
        "revise_memory",
        "Correct a durable memory while preserving its revision history.",
        {
            "memory_id": {"type": "string"},
            "content": {"type": "string"},
            "reason": {"type": "string"},
            "kind": {"type": "string"},
            "confidence": {"type": "number"},
        },
        required=["memory_id", "content", "reason"],
    ),
    function_tool(
        "schedule_wake",
        "Schedule an active responsibility to resume after a concrete future dependency.",
        {
            "delay_seconds": {"type": "integer", "minimum": 1},
            "reason": {"type": "string"},
        },
        required=["delay_seconds", "reason"],
    ),
    function_tool(
        "subscribe_event",
        "Subscribe the active responsibility to a durable local event source.",
        {
            "source": {
                "type": "string",
                "enum": ["filesystem", "git", "process", "runtime"],
            },
            "pattern": {"type": "string", "default": "*"},
        },
        required=["source"],
    ),
    function_tool(
        "create_finding",
        "Create a visible finding discovered during proactive read-only observation.",
        {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        required=["title", "summary"],
    ),
    function_tool(
        "browser_navigate",
        "Open a URL in the local governed browser for read-only research.",
        {"url": {"type": "string"}},
        required=["url"],
    ),
    function_tool(
        "browser_snapshot",
        "Read the current browser page as semantic text, ARIA structure, and referenced controls.",
        {},
    ),
    function_tool(
        "browser_click",
        "Propose clicking a referenced browser control.",
        {
            "ref": {"type": "string"},
            "intent": {"type": "string"},
        },
        required=["ref", "intent"],
    ),
    function_tool(
        "browser_fill",
        "Propose filling a referenced browser field.",
        {
            "ref": {"type": "string"},
            "value": {"type": "string"},
            "intent": {"type": "string"},
        },
        required=["ref", "value", "intent"],
    ),
    function_tool(
        "browser_press",
        "Propose sending a key to a referenced browser control.",
        {
            "ref": {"type": "string"},
            "key": {"type": "string"},
            "intent": {"type": "string"},
        },
        required=["ref", "key", "intent"],
    ),
    function_tool(
        "browser_select",
        "Propose selecting an option in a referenced browser control.",
        {
            "ref": {"type": "string"},
            "value": {"type": "string"},
            "intent": {"type": "string"},
        },
        required=["ref", "value", "intent"],
    ),
    function_tool(
        "browser_upload",
        "Propose uploading a workspace file through a referenced browser file input.",
        {
            "ref": {"type": "string"},
            "path": {"type": "string"},
            "intent": {"type": "string"},
        },
        required=["ref", "path", "intent"],
    ),
    function_tool(
        "windows_list",
        "List visible native Windows application windows through UI Automation.",
        {"limit": {"type": "integer", "default": 100}},
    ),
    function_tool(
        "windows_snapshot",
        "Read a Windows UI Automation control tree for a referenced window or control.",
        {
            "ref": {"type": "string"},
            "depth": {"type": "integer", "default": 4},
        },
        required=["ref"],
    ),
    function_tool(
        "windows_focus",
        "Propose focusing a referenced Windows control.",
        {"ref": {"type": "string"}, "intent": {"type": "string"}},
        required=["ref", "intent"],
    ),
    function_tool(
        "windows_invoke",
        "Propose invoking or clicking a referenced Windows control.",
        {"ref": {"type": "string"}, "intent": {"type": "string"}},
        required=["ref", "intent"],
    ),
    function_tool(
        "windows_set_text",
        "Propose replacing text in a referenced Windows control.",
        {
            "ref": {"type": "string"},
            "text": {"type": "string"},
            "intent": {"type": "string"},
        },
        required=["ref", "text", "intent"],
    ),
    function_tool(
        "windows_select",
        "Propose selecting a referenced Windows control.",
        {"ref": {"type": "string"}, "intent": {"type": "string"}},
        required=["ref", "intent"],
    ),
    function_tool(
        "windows_scroll",
        "Propose scrolling a referenced Windows control.",
        {
            "ref": {"type": "string"},
            "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
            "amount": {"type": "string", "default": "page"},
            "count": {"type": "integer", "default": 1},
            "intent": {"type": "string"},
        },
        required=["ref", "direction", "intent"],
    ),
    function_tool(
        "plan_create",
        "Create the durable step-by-step plan for the active responsibility before autonomous mutations.",
        {
            "title": {"type": "string"},
            "goal": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "detail": {"type": "string"},
                            },
                            "required": ["title"],
                        },
                    ]
                },
            },
        },
        required=["title", "goal", "steps"],
    ),
    function_tool(
        "plan_status",
        "Read the current durable plan for the active responsibility.",
        {},
    ),
    function_tool(
        "plan_advance",
        "Mark the active plan step complete and move to the next step.",
        {"summary": {"type": "string"}},
        required=["summary"],
    ),
    function_tool(
        "plan_block",
        "Mark the active plan step blocked with a concrete reason.",
        {"reason": {"type": "string"}},
        required=["reason"],
    ),
    function_tool(
        "plan_resume",
        "Resume a blocked plan.",
        {"plan_id": {"type": "string"}},
        required=["plan_id"],
    ),
    function_tool(
        "plan_fail",
        "Fail the active plan when it cannot safely or correctly continue.",
        {"reason": {"type": "string"}},
        required=["reason"],
    ),
    function_tool(
        "verification_status",
        "Read durable evidence from test, lint, typecheck, and build commands.",
        {},
    ),
    function_tool(
        "skills_list",
        "List installed local declarative skills.",
        {},
    ),
    function_tool(
        "skill_read",
        "Read an installed local skill by name.",
        {"name": {"type": "string"}},
        required=["name"],
    ),
    function_tool(
        "skill_install",
        "Propose installing a reusable local declarative skill.",
        {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "instructions": {"type": "string"},
            "allowed_tools": {
                "type": "array",
                "items": {"type": "string"},
            },
            "intent": {"type": "string"},
        },
        required=["name", "description", "instructions", "intent"],
    ),
]
