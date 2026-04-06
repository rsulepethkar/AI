"""
Native iOS app XPath agent (Appium/XCUITest).

Finds a single UI element in an iOS app by label/name/value and prints XPath.
Default app is Apple App Store (bundleId: com.apple.AppStore).
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from appium import webdriver
from appium.options.ios import XCUITestOptions

from ios_app_dom_scanner import (
    INTERACTIVE_TYPES,
    _absolute_xml_xpath,
    _build_attr_locator,
    _xpath_literal,
)


@dataclass(frozen=True)
class Match:
    key: str
    xpath: str


def _norm(s: str) -> str:
    return " ".join((s or "").split()).strip()


def _matches(hay: str, needle: str, *, exact: bool) -> bool:
    if exact:
        return hay == needle
    return needle.lower() in hay.lower()


def find_one_in_page_source(
    xml_source: str,
    query: str,
    *,
    by: str = "auto",
    exact: bool = False,
    interactive_only: bool = True,
) -> Optional[Match]:
    root = ET.fromstring(xml_source)
    q = _norm(query)
    if not q:
        return None

    attrs_order = []
    if by == "label":
        attrs_order = ["label"]
    elif by == "name":
        attrs_order = ["name"]
    elif by == "value":
        attrs_order = ["value"]
    elif by == "auto":
        attrs_order = ["label", "name", "value"]
    else:
        raise ValueError("by must be one of: auto, label, name, value")

    for el in root.iter():
        node_type = el.tag
        if interactive_only and node_type not in INTERACTIVE_TYPES:
            continue
        attrs = {k: _norm(v) for k, v in el.attrib.items()}

        for attr in attrs_order:
            v = attrs.get(attr, "")
            if not v:
                continue
            if _matches(v, q, exact=exact):
                # Prefer attribute locator; fallback to full XML path.
                xp = _build_attr_locator(node_type, attrs)
                if xp in (f"//{node_type}", "//*"):
                    xp = _absolute_xml_xpath(root, el)
                key = v
                return Match(key=key, xpath=xp)

    return None


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


def run(args: argparse.Namespace) -> Optional[str]:
    options = _build_options(args)
    driver = webdriver.Remote(args.server_url, options=options)
    try:
        if args.wait_seconds > 0:
            time.sleep(args.wait_seconds)
        source = driver.page_source
        match = find_one_in_page_source(source, args.query, by=args.by, exact=args.exact)
        return match.xpath if match else None
    finally:
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve a single XPath in a native iOS app via Appium (label/name/value).",
    )
    parser.add_argument("--server-url", default="http://127.0.0.1:4723", help="Appium server URL")
    parser.add_argument("--bundle-id", default="com.apple.AppStore", help="iOS app bundle id")
    parser.add_argument("--device-name", default="iPhone 14 Pro", help="Simulator/real device name")
    parser.add_argument("--platform-version", help="iOS version, e.g. 17.5")
    parser.add_argument("--udid", help="Device UDID (required for real device / specific simulator)")
    parser.add_argument("--no-reset", action="store_true", help="Do not reset app state")
    parser.add_argument("--new-command-timeout", type=int, default=120, help="Appium newCommandTimeout")
    parser.add_argument("--wait-seconds", type=int, default=3, help="Wait before reading page source")

    parser.add_argument("--query", "--name", dest="query", required=True, help="Text to match (label/name/value)")
    parser.add_argument("--by", choices=("auto", "label", "name", "value"), default="auto", help="Match attribute")
    parser.add_argument("--exact", action="store_true", help="Exact match (default: substring)")
    args = parser.parse_args()

    parsed = urlparse(args.server_url)
    if not parsed.scheme or not parsed.netloc:
        print("Error: --server-url must be a valid URL, e.g. http://127.0.0.1:4723", file=sys.stderr)
        return 2

    try:
        xpath = run(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if xpath:
        print(xpath)
        return 0
    print("No matching element found.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

