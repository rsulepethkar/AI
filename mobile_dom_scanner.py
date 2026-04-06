"""
Mobile QA DOM scanner: run the same interactive-element scan as qa_dom_scanner,
but inside a mobile-emulated browser (Playwright device profile).

Outputs JSON: { "Element label/text": "xpath" }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from playwright.sync_api import sync_playwright

from qa_dom_scanner import SCAN_INTERACTIVE_JS, _unique_keys
from xpath_agent import STEALTH_INIT_SCRIPT, _launch_browser, _post_goto_wait


def auto_output_path(url: str, device: str) -> Path:
    out_dir = Path(__file__).resolve().parent / "scans"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    parsed = urlparse(url.strip())
    if parsed.scheme == "file":
        raw_path = unquote(parsed.path).replace("\\", "/")
        stem = Path(raw_path).stem or "local_page"
        host_slug = re.sub(r"[^\w\-.]+", "_", stem).strip("_") or "local_page"
    else:
        host = (parsed.hostname or "site").lower()
        host_slug = re.sub(r"[^\w\-.]+", "_", host).strip("_") or "site"
    dev_slug = re.sub(r"[^\w\-.]+", "_", device).strip("_") or "device"
    return out_dir / f"{host_slug}_{dev_slug}_{ts}.json"


def scan_page_mobile(
    url: str,
    *,
    device_name: str,
    stealth: bool,
    use_chrome: bool,
    headless: bool,
    timeout_ms: int,
) -> dict[str, str]:
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
            _post_goto_wait(page, timeout_ms)
            raw: Any = page.evaluate(SCAN_INTERACTIVE_JS)
            if not isinstance(raw, list):
                return {}
            rows = [r for r in raw if isinstance(r, dict) and "key" in r and "xpath" in r]
            return _unique_keys(rows)
        finally:
            context.close()
            browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan a page on mobile emulation; output JSON map label/text -> XPath.",
    )
    parser.add_argument("--url", required=True, help="Page URL (https://... or file:///...)")
    parser.add_argument("--device", default="iPhone 13 Pro", help="Playwright device profile (default: iPhone 13 Pro)")
    parser.add_argument("--timeout", type=int, default=60000, help="Timeout ms (default 60000)")
    parser.add_argument("--headed", action="store_true", help="Show browser")
    parser.add_argument("--stealth", action="store_true", help="Use stealth script/flags (recommended for real sites)")
    parser.add_argument("--chrome", action="store_true", help="Use installed Google Chrome if available")
    parser.add_argument("--compact", action="store_true", help="Single-line JSON")
    parser.add_argument("--stdout", action="store_true", help="Also print JSON to stdout")
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="Explicit output path (default: scans/<host>_<device>_<timestamp>.json)",
    )
    args = parser.parse_args()

    try:
        data = scan_page_mobile(
            args.url,
            device_name=args.device,
            stealth=args.stealth,
            use_chrome=args.chrome,
            headless=not args.headed,
            timeout_ms=args.timeout,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    payload = (
        json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if args.compact
        else json.dumps(data, ensure_ascii=False, indent=2)
    )
    out_path = Path(args.output) if args.output else auto_output_path(args.url, args.device)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload + "\n", encoding="utf-8")
    print(f"Wrote {len(data)} entries to {out_path.resolve()}", file=sys.stderr)

    if args.stdout:
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        try:
            print(payload)
        except UnicodeEncodeError:
            sys.stdout.buffer.write((payload + "\n").encode("utf-8", errors="replace"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

