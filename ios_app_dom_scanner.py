"""
Native iOS app scanner (Appium/XCUITest).

Scans interactive elements from iOS app page_source XML and writes:
{ "Element label/text": "XPath" }

Default target app is Apple App Store (bundleId: com.apple.AppStore).
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
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from appium import webdriver
from appium.options.ios import XCUITestOptions


INTERACTIVE_TYPES = {
    "XCUIElementTypeButton",
    "XCUIElementTypeTextField",
    "XCUIElementTypeSecureTextField",
    "XCUIElementTypeSearchField",
    "XCUIElementTypeSwitch",
    "XCUIElementTypeSegmentedControl",
    "XCUIElementTypeSlider",
    "XCUIElementTypeCell",
    "XCUIElementTypeLink",
    "XCUIElementTypeTabBar",
    "XCUIElementTypeTextView",
    "XCUIElementTypeStaticText",
}


def _slug(s: str) -> str:
    return re.sub(r"[^\w\-.]+", "_", s).strip("_") or "ios_app"


def _xpath_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def auto_output_path(bundle_id: str, device_name: str) -> Path:
    out_dir = Path(__file__).resolve().parent / "scans"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return out_dir / f"{_slug(bundle_id)}_{_slug(device_name)}_{ts}.json"


def _build_key(attrs: dict[str, str], node_type: str) -> str:
    for k in ("label", "name", "value"):
        v = (attrs.get(k) or "").strip()
        if v:
            return v
    return node_type


def _build_attr_locator(node_type: str, attrs: dict[str, str]) -> str:
    """Prefer stable attribute-based XPath for iOS."""
    name = (attrs.get("name") or "").strip()
    label = (attrs.get("label") or "").strip()
    value = (attrs.get("value") or "").strip()

    if name and node_type:
        return f"//{node_type}[@name={_xpath_literal(name)}]"
    if label and node_type:
        return f"//{node_type}[@label={_xpath_literal(label)}]"
    if value and node_type:
        return f"//{node_type}[@value={_xpath_literal(value)}]"
    if node_type:
        return f"//{node_type}"
    return "//*"


def _absolute_xml_xpath(root: ET.Element, target: ET.Element) -> str:
    """
    Build XML absolute path with sibling indexes from app source tree.
    Used as fallback when attribute locator is weak.
    """
    parent_map: dict[ET.Element, ET.Element] = {child: p for p in root.iter() for child in p}
    parts: list[str] = []
    cur = target
    while cur is not None:
        parent = parent_map.get(cur)
        tag = cur.tag
        if parent is None:
            parts.append(tag)
            break
        same = [c for c in list(parent) if c.tag == tag]
        idx = same.index(cur) + 1
        parts.append(f"{tag}[{idx}]")
        cur = parent
    return "/" + "/".join(reversed(parts))


def _dedupe_keys(rows: list[dict[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    seen: dict[str, int] = defaultdict(int)
    for row in rows:
        base = re.sub(r"\s+", " ", row["key"]).strip() or "element"
        seen[base] += 1
        key = base if seen[base] == 1 else f"{base} ({seen[base]})"
        out[key] = row["xpath"]
    return out


def parse_ios_page_source(xml_source: str) -> dict[str, str]:
    root = ET.fromstring(xml_source)
    rows: list[dict[str, str]] = []

    for el in root.iter():
        node_type = el.tag
        if node_type not in INTERACTIVE_TYPES:
            continue
        attrs = {k: str(v) for k, v in el.attrib.items()}
        key = _build_key(attrs, node_type)

        # Prefer attribute-based locator; fallback to full XML path.
        attr_xpath = _build_attr_locator(node_type, attrs)
        if attr_xpath in (f"//{node_type}", "//*"):
            xpath = _absolute_xml_xpath(root, el)
        else:
            xpath = attr_xpath

        rows.append({"key": key, "xpath": xpath})

    return _dedupe_keys(rows)


def _build_options(args: argparse.Namespace) -> XCUITestOptions:
    opts = XCUITestOptions()
    opts.platform_name = "iOS"
    opts.automation_name = "XCUITest"
    opts.device_name = args.device_name
    if args.platform_version:
        opts.platform_version = args.platform_version
    if args.udid:
        opts.udid = args.udid
    opts.bundle_id = args.bundle_id
    opts.no_reset = args.no_reset
    opts.new_command_timeout = args.new_command_timeout
    return opts


def scan_ios_app(args: argparse.Namespace) -> dict[str, str]:
    options = _build_options(args)
    driver = webdriver.Remote(args.server_url, options=options)
    try:
        if args.wait_seconds > 0:
            time.sleep(args.wait_seconds)
        source = driver.page_source
        if args.source_out:
            Path(args.source_out).write_text(source, encoding="utf-8")
        return parse_ios_page_source(source)
    finally:
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan native iOS app UI tree via Appium and export key->XPath JSON.",
    )
    parser.add_argument("--server-url", default="http://127.0.0.1:4723", help="Appium server URL")
    parser.add_argument("--bundle-id", default="com.apple.AppStore", help="iOS app bundle id")
    parser.add_argument("--device-name", default="iPhone 14 Pro", help="Simulator/real device name")
    parser.add_argument("--platform-version", help="iOS version, e.g. 17.5")
    parser.add_argument("--udid", help="Device UDID (required for real device / specific simulator)")
    parser.add_argument("--no-reset", action="store_true", help="Do not reset app state")
    parser.add_argument("--new-command-timeout", type=int, default=120, help="Appium newCommandTimeout")
    parser.add_argument("--wait-seconds", type=int, default=3, help="Wait before reading page source")
    parser.add_argument("--source-out", metavar="FILE", help="Optional: save raw page_source XML")
    parser.add_argument("--compact", action="store_true", help="Single-line JSON")
    parser.add_argument("--stdout", action="store_true", help="Also print JSON to stdout")
    parser.add_argument("-o", "--output", metavar="FILE", help="Explicit output file path")
    args = parser.parse_args()

    # basic validation for URL
    parsed = urlparse(args.server_url)
    if not parsed.scheme or not parsed.netloc:
        print("Error: --server-url must be a valid URL, e.g. http://127.0.0.1:4723", file=sys.stderr)
        return 2

    try:
        data = scan_ios_app(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    payload = (
        json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if args.compact
        else json.dumps(data, ensure_ascii=False, indent=2)
    )

    out_path = Path(args.output) if args.output else auto_output_path(args.bundle_id, args.device_name)
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

