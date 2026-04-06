"""
Android .apk UI scanner (Appium/UiAutomator2).

Scans interactive elements from Android page_source XML and writes:
{ "Element text/label": "XPath" }

Target is an APK under test (not a webview).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from appium import webdriver
from appium.options.android import UiAutomator2Options


# Common interactive-ish widget classes in Android view hierarchy dumps
INTERACTIVE_CLASSES_PREFIXES = (
    "android.widget.Button",
    "android.widget.EditText",
    "android.widget.ImageButton",
    "android.widget.CheckBox",
    "android.widget.RadioButton",
    "android.widget.Switch",
    "android.widget.Spinner",
    "android.widget.SeekBar",
    "android.widget.ListView",
    "android.widget.RecyclerView",
    "android.widget.TextView",  # many apps use clickable text views
)


def _slug(s: str) -> str:
    return re.sub(r"[^\w\-.]+", "_", s).strip("_") or "android_app"


def _xpath_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def auto_output_path(app_package: str, device_name: str) -> Path:
    out_dir = Path(__file__).resolve().parent / "scans"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return out_dir / f"{_slug(app_package)}_{_slug(device_name)}_{ts}.json"


def _build_key(attrs: dict[str, str]) -> str:
    for k in ("text", "content-desc", "resource-id"):
        v = (attrs.get(k) or "").strip()
        if v:
            return v
    cls = (attrs.get("class") or "").strip()
    return cls or "element"


def _best_xpath_for_node(attrs: dict[str, str]) -> str:
    """
    Prefer stable attributes:
      - resource-id
      - content-desc
      - exact text()
    Fallback to class only.
    """
    cls = (attrs.get("class") or "").strip()
    rid = (attrs.get("resource-id") or "").strip()
    desc = (attrs.get("content-desc") or "").strip()
    txt = (attrs.get("text") or "").strip()

    if rid:
        return f\"//*[@resource-id={_xpath_literal(rid)}]\"
    if desc and cls:
        return f\"//*[@class={_xpath_literal(cls)} and @content-desc={_xpath_literal(desc)}]\"
    if desc:
        return f\"//*[@content-desc={_xpath_literal(desc)}]\"
    if txt and cls:
        return f\"//*[@class={_xpath_literal(cls)} and @text={_xpath_literal(txt)}]\"
    if txt:
        return f\"//*[@text={_xpath_literal(txt)}]\"
    if cls:
        return f\"//*[@class={_xpath_literal(cls)}]\"
    return \"//*\"


def _is_interactive(attrs: dict[str, str]) -> bool:
    cls = (attrs.get("class") or "").strip()
    if any(cls.startswith(p) for p in INTERACTIVE_CLASSES_PREFIXES):
        return True
    clickable = (attrs.get("clickable") or "").strip().lower()
    focusable = (attrs.get("focusable") or "").strip().lower()
    return clickable == "true" or focusable == "true"


def _dedupe_keys(rows: list[dict[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    seen: dict[str, int] = defaultdict(int)
    for row in rows:
        base = re.sub(r\"\\s+\", \" \", row[\"key\"]).strip() or \"element\"
        seen[base] += 1
        key = base if seen[base] == 1 else f\"{base} ({seen[base]})\"
        out[key] = row[\"xpath\"]
    return out


def parse_android_page_source(xml_source: str) -> dict[str, str]:
    root = ET.fromstring(xml_source)
    rows: list[dict[str, str]] = []

    for el in root.iter():
        attrs = {k: str(v) for k, v in el.attrib.items()}
        if not _is_interactive(attrs):
            continue
        key = _build_key(attrs)
        xpath = _best_xpath_for_node(attrs)
        rows.append({\"key\": key, \"xpath\": xpath})

    return _dedupe_keys(rows)


def _build_options(args: argparse.Namespace) -> UiAutomator2Options:
    opts = UiAutomator2Options()
    opts.platform_name = \"Android\"
    opts.automation_name = \"UiAutomator2\"
    opts.device_name = args.device_name
    if args.udid:
        opts.udid = args.udid
    if args.platform_version:
        opts.platform_version = args.platform_version

    # App under test
    opts.app = str(Path(args.apk).resolve())
    if args.app_package:
        opts.app_package = args.app_package
    if args.app_activity:
        opts.app_activity = args.app_activity

    # Session behavior
    opts.no_reset = args.no_reset
    opts.new_command_timeout = args.new_command_timeout

    # Helpful defaults
    opts.auto_grant_permissions = True
    return opts


def scan_android_app(args: argparse.Namespace) -> dict[str, str]:
    options = _build_options(args)
    driver = webdriver.Remote(args.server_url, options=options)
    try:
        if args.wait_seconds > 0:
            time.sleep(args.wait_seconds)
        source = driver.page_source
        if args.source_out:
            Path(args.source_out).write_text(source, encoding=\"utf-8\")
        return parse_android_page_source(source)
    finally:
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=\"Scan an Android .apk app UI tree via Appium and export key->XPath JSON.\",
    )
    parser.add_argument(\"--server-url\", default=\"http://127.0.0.1:4723\", help=\"Appium server URL\")
    parser.add_argument(\"--apk\", required=True, help=\"Path to the .apk file\")
    parser.add_argument(\"--device-name\", default=\"Android\", help=\"Device name (Appium capability)\")
    parser.add_argument(\"--udid\", help=\"Device UDID (recommended)\")
    parser.add_argument(\"--platform-version\", help=\"Android version, e.g. 14\")
    parser.add_argument(\"--app-package\", help=\"App package (optional but recommended)\")
    parser.add_argument(\"--app-activity\", help=\"App activity (optional but recommended)\")
    parser.add_argument(\"--no-reset\", action=\"store_true\", help=\"Do not reset app state\")
    parser.add_argument(\"--new-command-timeout\", type=int, default=120, help=\"Appium newCommandTimeout\")
    parser.add_argument(\"--wait-seconds\", type=int, default=3, help=\"Wait before reading page source\")
    parser.add_argument(\"--source-out\", metavar=\"FILE\", help=\"Optional: save raw page_source XML\")
    parser.add_argument(\"--compact\", action=\"store_true\", help=\"Single-line JSON\")
    parser.add_argument(\"--stdout\", action=\"store_true\", help=\"Also print JSON to stdout\")
    parser.add_argument(\"-o\", \"--output\", metavar=\"FILE\", help=\"Explicit output file path\")
    args = parser.parse_args()

    parsed = urlparse(args.server_url)
    if not parsed.scheme or not parsed.netloc:
        print(\"Error: --server-url must be a valid URL, e.g. http://127.0.0.1:4723\", file=sys.stderr)
        return 2
    if not Path(args.apk).exists():
        print(f\"Error: APK not found: {args.apk}\", file=sys.stderr)
        return 2

    try:
        data = scan_android_app(args)
    except Exception as e:
        print(f\"Error: {e}\", file=sys.stderr)
        return 2

    payload = (
        json.dumps(data, ensure_ascii=False, separators=(\",\", \":\"))
        if args.compact
        else json.dumps(data, ensure_ascii=False, indent=2)
    )
    out_path = Path(args.output) if args.output else auto_output_path(args.app_package or \"apk\", args.device_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload + \"\\n\", encoding=\"utf-8\")
    print(f\"Wrote {len(data)} entries to {out_path.resolve()}\", file=sys.stderr)

    if args.stdout:
        if hasattr(sys.stdout, \"reconfigure\"):\n            try:\n                sys.stdout.reconfigure(encoding=\"utf-8\", errors=\"replace\")\n            except Exception:\n                pass\n        try:\n            print(payload)\n        except UnicodeEncodeError:\n            sys.stdout.buffer.write((payload + \"\\n\").encode(\"utf-8\", errors=\"replace\"))\n
    return 0


if __name__ == \"__main__\":
    raise SystemExit(main())

