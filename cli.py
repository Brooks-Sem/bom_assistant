#!/usr/bin/env python3
"""CLI entry point for bom-assistant — called by OpenClaw agent."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

USAGE = (
    "Usage:\n"
    '  cli.py to-excel <file_paths> [output_name] [instruction]\n'
    '  cli.py edit     <instruction> [task_id]\n'
    '  cli.py lookup   <query>'
)


def _fail(message: str) -> None:
    print(json.dumps({"status": "failed", "error": message}, ensure_ascii=False))
    sys.exit(1)


def _load():
    try:
        from server import bom_to_excel, bom_edit, bom_lookup
    except Exception as exc:
        _fail(f"Backend load error: {exc}")
    return bom_to_excel, bom_edit, bom_lookup


def _compact(result: dict) -> dict:
    """Strip full row data for concise agent output."""
    out = {k: v for k, v in result.items() if k != "rows"}
    rows = result.get("rows", [])
    out["row_count"] = len(rows)
    if rows:
        out["preview_rows"] = rows[:3]
        if len(rows) > 3:
            out["truncated_rows"] = len(rows) - 3
    return out


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(USAGE, file=sys.stderr)
        sys.exit(0 if args else 1)

    cmd, rest = args[0], args[1:]
    bom_to_excel, bom_edit, bom_lookup = _load()

    try:
        if cmd == "to-excel":
            if not rest:
                _fail("to-excel requires <file_paths>")
            result = bom_to_excel(
                file_paths=rest[0],
                output_name=rest[1] if len(rest) > 1 else "",
                user_instruction=rest[2] if len(rest) > 2 else "",
            )
        elif cmd == "edit":
            if not rest:
                _fail("edit requires <instruction>")
            result = bom_edit(
                edit_instruction=rest[0],
                task_id=rest[1] if len(rest) > 1 else "",
            )
        elif cmd == "lookup":
            if not rest:
                _fail("lookup requires <query>")
            result = bom_lookup(query=" ".join(rest))
        else:
            _fail(f"Unknown command: {cmd}")
    except Exception as e:
        _fail(str(e))

    output = _compact(result) if cmd != "lookup" else result
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
