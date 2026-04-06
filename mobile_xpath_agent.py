"""
Mobile XPath agent: open a URL with mobile emulation and resolve XPath.
Reuses locator strategies from xpath_agent.py.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from playwright.sync_api import sync_playwright

from xpath_agent import (
    STEALTH_INIT_SCRIPT,
    _launch_browser,
    compute_xpath,
    compute_xpath_text_predicate,
    find_locator,
)


def run_mobile(
    url: str,
    query: str,
    *,
    by: str = "auto",
    exact: bool = False,
    timeout_ms: int = 20000,
    headless: bool = True,
    stealth: bool = True,
    use_chrome: bool = False,
    device_name: str = "Pixel 7",
) -> Optional[str]:
    with sync_playwright() as p:
        browser = _launch_browser(p, headless=headless, stealth=stealth, use_chrome=use_chrome)
        if device_name not in p.devices:
            browser.close()
            raise ValueError(f"Unsupported device: {device_name}")

        context = browser.new_context(**p.devices[device_name])
        page = context.new_page()
        if stealth:
            page.add_init_script(STEALTH_INIT_SCRIPT)
        page.set_default_timeout(timeout_ms)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            locator = find_locator(page, query, by=by, exact=exact)
            if not locator:
                return None
            locator.wait_for(state="attached", timeout=timeout_ms)
            if by == "text":
                xp = compute_xpath_text_predicate(page, locator, query)
                if xp:
                    return xp
            return compute_xpath(page, locator)
        finally:
            context.close()
            browser.close()


def main() -> int:
    by_choices = (
        "auto",
        "name",
        "id",
        "label",
        "text",
        "visible-text",
        "placeholder",
        "aria-label",
    )
    parser = argparse.ArgumentParser(
        description="Resolve XPath on a mobile-emulated browser (e.g., Pixel/iPhone).",
    )
    parser.add_argument("--url", required=True, help="Page URL to open")
    parser.add_argument("--name", "--query", dest="query", required=True, help="Text/value to match")
    parser.add_argument("--by", choices=by_choices, default="auto", help="How to match target element")
    parser.add_argument("--exact", action="store_true", help="Exact match for label mode")
    parser.add_argument("--device", default="Pixel 7", help="Playwright device profile (default: Pixel 7)")
    parser.add_argument("--timeout", type=int, default=20000, help="Timeout ms (default 20000)")
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument("--stealth", action="store_true", help="Use stealth flags (recommended)")
    parser.add_argument("--chrome", action="store_true", help="Use installed Chrome if available")
    args = parser.parse_args()

    try:
        xpath = run_mobile(
            args.url,
            args.query,
            by=args.by,
            exact=args.exact,
            timeout_ms=args.timeout,
            headless=not args.headed,
            stealth=args.stealth,
            use_chrome=args.chrome,
            device_name=args.device,
        )
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

