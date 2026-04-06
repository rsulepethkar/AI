"""
Android .apk XPath agent (Appium/UiAutomator2).

Finds a single UI element by text / content-desc / resource-id and prints XPath.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from appium import webdriver
from appium.options.android import UiAutomator2Options

from android_apk_dom_scanner import _xpath_literal, parse_android_page_source


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


def find_one_in_page_source(xml_source: str, query: str, *, by: str, exact: bool) -> Optional[Match]:
    root = ET.fromstring(xml_source)
    q = _norm(query)
    if not q:
        return None

    attrs_order: list[str]
    if by == "text":
        attrs_order = ["text"]
    elif by == "content-desc":
        attrs_order = ["content-desc"]
    elif by == "resource-id":
        attrs_order = ["resource-id"]
    elif by == "auto":
        attrs_order = ["resource-id", "content-desc", "text"]
    else:
        raise ValueError("by must be one of: auto, text, content-desc, resource-id")

    for el in root.iter():
        attrs = {k: _norm(v) for k, v in el.attrib.items()}
        for a in attrs_order:
            v = attrs.get(a, "")
            if v and _matches(v, q, exact=exact):
                # Return a stable attribute-based xpath
                if a == "resource-id":
                    return Match(key=v, xpath=f\"//*[@resource-id={_xpath_literal(v)}]\")
                if a == "content-desc":
                    return Match(key=v, xpath=f\"//*[@content-desc={_xpath_literal(v)}]\")
                if a == "text":
                    return Match(key=v, xpath=f\"//*[@text={_xpath_literal(v)}]\")
    return None


def _build_options(args: argparse.Namespace) -> UiAutomator2Options:
    opts = UiAutomator2Options()
    opts.platform_name = "Android"
    opts.automation_name = "UiAutomator2"
    opts.device_name = args.device_name
    if args.udid:
        opts.udid = args.udid
    if args.platform_version:
        opts.platform_version = args.platform_version
    opts.app = str(Path(args.apk).resolve())
    if args.app_package:
        opts.app_package = args.app_package
    if args.app_activity:
        opts.app_activity = args.app_activity
    opts.no_reset = args.no_reset
    opts.new_command_timeout = args.new_command_timeout
    opts.auto_grant_permissions = True
    return opts


def run(args: argparse.Namespace) -> Optional[str]:
    driver = webdriver.Remote(args.server_url, options=_build_options(args))
    try:
        if args.wait_seconds > 0:
            time.sleep(args.wait_seconds)
        src = driver.page_source
        m = find_one_in_page_source(src, args.query, by=args.by, exact=args.exact)
        return m.xpath if m else None
    finally:
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve one XPath in an Android .apk app via Appium.")
    parser.add_argument("--server-url", default="http://127.0.0.1:4723", help="Appium server URL")
    parser.add_argument("--apk", required=True, help="Path to the .apk file")
    parser.add_argument("--device-name", default="Android", help="Device name (Appium capability)")
    parser.add_argument("--udid", help="Device UDID (recommended)")
    parser.add_argument("--platform-version", help="Android version, e.g. 14")
    parser.add_argument("--app-package", help="App package (optional but recommended)")
    parser.add_argument("--app-activity", help="App activity (optional but recommended)")
    parser.add_argument("--no-reset", action="store_true", help="Do not reset app state")
    parser.add_argument("--new-command-timeout", type=int, default=120, help="Appium newCommandTimeout")
    parser.add_argument("--wait-seconds", type=int, default=3, help="Wait before reading page source")

    parser.add_argument("--query", "--name", dest="query", required=True, help="String to match")
    parser.add_argument("--by", choices=("auto", "text", "content-desc", "resource-id"), default="auto")
    parser.add_argument("--exact", action="store_true", help="Exact match (default: substring)")
    args = parser.parse_args()

    parsed = urlparse(args.server_url)
    if not parsed.scheme or not parsed.netloc:
        print("Error: --server-url must be a valid URL, e.g. http://127.0.0.1:4723", file=sys.stderr)
        return 2
    if not Path(args.apk).exists():
        print(f"Error: APK not found: {args.apk}", file=sys.stderr)
        return 2

    try:
        xp = run(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if xp:
        print(xp)
        return 0
    print("No matching element found.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

