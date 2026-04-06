"""
Desktop application UI scanner (Windows).

Scans a running desktop application's UI Automation tree and writes JSON:
{ "Element label": "XPath-like locator" }

Use this when you want application controls instead of mobile/web DOM elements.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


INTERACTIVE_TYPES = {
    "Button",
    "Edit",
    "ComboBox",
    "List",
    "ListItem",
    "CheckBox",
    "RadioButton",
    "Hyperlink",
    "MenuItem",
    "TabItem",
    "TreeItem",
    "Spinner",
    "Slider",
}


def _slug(s: str) -> str:
    return re.sub(r"[^\w\-.]+", "_", s).strip("_") or "app"


def auto_output_path(app_hint: str) -> Path:
    out_dir = Path(__file__).resolve().parent / "scans"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return out_dir / f"{_slug(app_hint)}_desktop_{ts}.json"


def _to_xpath_literal(value: str) -> str:
    # XPath 1.0 single-quoted literal escaping
    return "'" + value.replace("'", "''") + "'"


def _build_locator(info: Any) -> str:
    """
    Build XPath-like locator for desktop UI element.
    Priority: AutomationId + ControlType, Name + ControlType, then ControlType only.
    """
    control_type = (getattr(info, "control_type", "") or "").strip()
    name = (getattr(info, "name", "") or "").strip()
    auto_id = (getattr(info, "automation_id", "") or "").strip()

    if auto_id and control_type:
        return f"//*[@AutomationId={_to_xpath_literal(auto_id)} and @ControlType={_to_xpath_literal(control_type)}]"
    if name and control_type:
        return f"//*[@Name={_to_xpath_literal(name)} and @ControlType={_to_xpath_literal(control_type)}]"
    if auto_id:
        return f"//*[@AutomationId={_to_xpath_literal(auto_id)}]"
    if name:
        return f"//*[@Name={_to_xpath_literal(name)}]"
    if control_type:
        return f"//*[@ControlType={_to_xpath_literal(control_type)}]"
    return "//*"


def _build_key(info: Any) -> str:
    name = (getattr(info, "name", "") or "").strip()
    auto_id = (getattr(info, "automation_id", "") or "").strip()
    control_type = (getattr(info, "control_type", "") or "").strip() or "Element"
    if name:
        return name
    if auto_id:
        return f"{auto_id} ({control_type})"
    return control_type


def _dedupe_keys(rows: list[dict[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    seen: dict[str, int] = {}
    for row in rows:
        base = re.sub(r"\s+", " ", row["key"]).strip() or "Element"
        n = seen.get(base, 0) + 1
        seen[base] = n
        key = base if n == 1 else f"{base} ({n})"
        out[key] = row["xpath"]
    return out


def scan_desktop_app(
    *,
    title_regex: str,
    depth: int = 8,
) -> dict[str, str]:
    # Lazy import so script can show --help without dependency installed.
    from pywinauto import Desktop

    window = Desktop(backend="uia").window(title_re=title_regex)
    window.wait("exists ready", timeout=20)

    rows: list[dict[str, str]] = []
    elements = window.descendants(depth=depth)
    for el in elements:
        info = el.element_info
        ctype = (getattr(info, "control_type", "") or "").strip()
        if ctype not in INTERACTIVE_TYPES:
            continue
        key = _build_key(info)
        xpath = _build_locator(info)
        rows.append({"key": key, "xpath": xpath})

    return _dedupe_keys(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan a running Windows desktop application and export interactive elements as JSON.",
    )
    parser.add_argument(
        "--title-regex",
        required=True,
        help="Regex to match application window title, e.g. '.*Notepad.*' or '.*Calculator.*'",
    )
    parser.add_argument("--depth", type=int, default=8, help="UI tree depth (default 8)")
    parser.add_argument("--compact", action="store_true", help="Single-line JSON output")
    parser.add_argument("--stdout", action="store_true", help="Also print JSON to stdout")
    parser.add_argument("-o", "--output", metavar="FILE", help="Explicit output file path")
    args = parser.parse_args()

    try:
        data = scan_desktop_app(title_regex=args.title_regex, depth=args.depth)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    payload = (
        json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if args.compact
        else json.dumps(data, ensure_ascii=False, indent=2)
    )
    out_path = Path(args.output) if args.output else auto_output_path(args.title_regex)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload + "\n", encoding="utf-8")
    print(f"Wrote {len(data)} entries to {out_path.resolve()}", file=sys.stderr)

    if args.stdout:
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        print(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

