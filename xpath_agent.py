"""
Agent: open a URL and resolve XPath for an element.
Match by name/id/attributes, label, exact text, or visible text (substring).
With --by text, XPath is //tag[text()='...'] (tag from the matched node).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Optional, TextIO

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Playwright,
    sync_playwright,
    Page,
    Locator,
)


# Reduce empty-HTML bot walls on retail sites (Amazon, etc.).
STEALTH_INIT_SCRIPT = """
(() => {
  try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  } catch (e) {}
})();
"""

CHROME_WIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

GET_XPATH_JS = """
(el) => {
  const q = (s) => "'" + String(s).replace(/'/g, "''") + "'";
  if (!el || el.nodeType !== 1) return null;
  if (el.id) return '//*[@id=' + q(el.id) + ']';

  function relPathFrom(ancestor, e) {
    if (!ancestor || !e || ancestor === e) return null;
    const parts = [];
    let cur = e;
    while (cur && cur.nodeType === 1 && cur !== ancestor) {
      const p = cur.parentNode;
      if (!p || p.nodeType !== 1) return null;
      const tag = cur.tagName.toLowerCase();
      const same = Array.from(p.children).filter((n) => n.tagName === cur.tagName);
      const idx = same.indexOf(cur) + 1;
      parts.unshift(tag + '[' + idx + ']');
      cur = p;
    }
    return cur === ancestor ? parts.join('/') : null;
  }

  function xpathViaFollowingSiblingOfPrecedingId(e) {
    const tag = e.tagName.toLowerCase();
    let sib = e.previousElementSibling;
    while (sib) {
      if (sib.id) {
        let k = 0;
        let cur = sib.nextElementSibling;
        while (cur) {
          if (cur.tagName.toLowerCase() === tag) {
            k++;
            if (cur === e) return '//*[@id=' + q(sib.id) + ']/following-sibling::' + tag + '[' + k + ']';
          }
          cur = cur.nextElementSibling;
        }
        return null;
      }
      sib = sib.previousElementSibling;
    }
    return null;
  }

  function xpathViaPrecedingSiblingOfFollowingId(e) {
    const tag = e.tagName.toLowerCase();
    let sib = e.nextElementSibling;
    while (sib) {
      if (sib.id) {
        let k = 0;
        let cur = sib.previousElementSibling;
        while (cur) {
          if (cur.tagName.toLowerCase() === tag) {
            k++;
            if (cur === e) return '//*[@id=' + q(sib.id) + ']/preceding-sibling::' + tag + '[' + k + ']';
          }
          cur = cur.previousElementSibling;
        }
        return null;
      }
      sib = sib.nextElementSibling;
    }
    return null;
  }

  function findAnchor(e) {
    let a = e.parentElement;
    while (a && a !== document.documentElement) {
      if (a.id) return { kind: 'id', val: a.id, node: a };
      const dt = a.getAttribute && a.getAttribute('data-testid');
      if (dt) return { kind: 'testid', val: dt, node: a };
      a = a.parentElement;
    }
    return null;
  }

  let xp = xpathViaFollowingSiblingOfPrecedingId(el);
  if (xp) return xp;
  xp = xpathViaPrecedingSiblingOfFollowingId(el);
  if (xp) return xp;
  const anchor = findAnchor(el);
  if (anchor) {
    const rel = relPathFrom(anchor.node, el);
    if (rel) {
      if (anchor.kind === 'id') return '//*[@id=' + q(anchor.val) + ']/' + rel;
      return '//*[@data-testid=' + q(anchor.val) + ']/' + rel;
    }
  }
  const relBody = relPathFrom(document.body, el);
  if (relBody) return '//body/' + relBody;
  return '//' + el.tagName.toLowerCase();
}
"""

GET_TAG_JS = "(el) => el && el.tagName ? el.tagName.toLowerCase() : null"


def xpath_string_literal(value: str) -> str:
    """XPath 1.0 string in single quotes; apostrophe doubled."""
    return "'" + value.replace("'", "''") + "'"


def compute_xpath_text_predicate(page: Page, locator: Locator, exact_text: str) -> Optional[str]:
    """//tag[text()='exact_text'] using the matched element's tag name."""
    handle = locator.element_handle()
    if not handle:
        return None
    try:
        tag = page.evaluate(GET_TAG_JS, handle)
        if not tag:
            return None
        lit = xpath_string_literal(exact_text)
        return f"//{tag}[text()={lit}]"
    finally:
        handle.dispose()


def compute_xpath(page: Page, locator: Locator) -> Optional[str]:
    handle = locator.element_handle()
    if not handle:
        return None
    try:
        return page.evaluate(GET_XPATH_JS, handle)
    finally:
        handle.dispose()


def css_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _first_css(page: Page, selector: str) -> Optional[Locator]:
    loc = page.locator(selector)
    try:
        if loc.count() >= 1:
            return loc.first
    except Exception:
        pass
    return None


def _first_get_by_text(page: Page, text: str, *, exact: bool) -> Optional[Locator]:
    try:
        loc = page.get_by_text(text, exact=exact)
        if loc.count() >= 1:
            return loc.first
    except Exception:
        pass
    return None


def _first_link_by_name(page: Page, name: str, *, exact: bool) -> Optional[Locator]:
    """Prefer <a> via accessible name so --by text yields //a[text()='...'] for nav links."""
    try:
        loc = page.get_by_role("link", name=name, exact=exact)
        if loc.count() >= 1:
            return loc.first
    except Exception:
        pass
    return None


def _first_anchor_href_contains(page: Page, needle: str) -> Optional[Locator]:
    """Match <a href*='needle'> (Amazon gift-card URLs, etc.)."""
    n = needle.replace("\\", "\\\\").replace('"', '\\"')
    try:
        loc = page.locator(f'a[href*="{n}" i]')
        if loc.count() >= 1:
            return loc.first
    except Exception:
        pass
    try:
        loc = page.locator(f'a[href*="{n}"]')
        if loc.count() >= 1:
            return loc.first
    except Exception:
        pass
    return None


def _amazon_gift_cards_anchor(page: Page) -> Optional[Locator]:
    """amazon.in / amazon.com often use gift-card in href even when link text is wrapped."""
    if "amazon." not in page.url.lower():
        return None
    for frag in ("gift-card", "gift_card", "gc_redirect", "/gp/gc", "nav_cs_gc"):
        hit = _first_anchor_href_contains(page, frag)
        if hit is not None:
            return hit
    return None


def _first_get_by_label(page: Page, label: str, *, exact: bool) -> Optional[Locator]:
    try:
        loc = page.get_by_label(label, exact=exact)
        if loc.count() >= 1:
            return loc.first
    except Exception:
        pass
    return None


StrategyFn = Callable[[], Optional[Locator]]


def find_locator(
    page: Page,
    query: str,
    *,
    by: str = "auto",
    exact: bool = False,
) -> Optional[Locator]:
    """Resolve a locator. ``by`` selects strategy; ``auto`` tries several in order."""
    esc = css_escape(query)

    if by == "name":
        return _first_css(page, f'[name="{esc}"]')
    if by == "id":
        return _first_css(page, f'[id="{esc}"]')
    if by == "placeholder":
        return _first_css(page, f'[placeholder="{esc}"]')
    if by == "aria-label":
        return _first_css(page, f'[aria-label="{esc}"]')
    if by == "label":
        return _first_get_by_label(page, query, exact=exact)
    if by == "text":
        hit = _first_link_by_name(page, query, exact=True)
        if hit is not None:
            return hit
        ql = query.strip().lower()
        if "gift card" in ql:
            hit = _amazon_gift_cards_anchor(page)
            if hit is not None:
                return hit
        hit = _first_link_by_name(page, query, exact=False)
        if hit is not None:
            return hit
        return _first_get_by_text(page, query, exact=True)
    if by == "visible-text":
        return _first_get_by_text(page, query, exact=False)

    if by != "auto":
        return None

    strategies: list[StrategyFn] = [
        lambda: _first_css(page, f'[name="{esc}"]'),
        lambda: _first_css(page, f'[id="{esc}"]'),
        lambda: _first_css(page, f'[placeholder="{esc}"]'),
        lambda: _first_css(page, f'[aria-label="{esc}"]'),
        lambda: _first_get_by_label(page, query, exact=exact),
        lambda: _first_link_by_name(page, query, exact=True)
        or _first_get_by_text(page, query, exact=True),
        lambda: _first_get_by_text(page, query, exact=False),
    ]

    for fn in strategies:
        hit = fn()
        if hit is not None:
            return hit
    return None


def write_debug(
    page: Page,
    query: str,
    *,
    by: str,
    exact: bool,
    out: TextIO,
) -> None:
    """Print why a match might fail (blocked page, wrong --by, exact vs partial)."""
    print("[debug] After navigation:", file=out)
    try:
        print(f"  URL: {page.url}", file=out)
        print(f"  Title: {page.title()!r}", file=out)
        n = page.evaluate("() => document.body ? document.body.innerText.length : 0")
        print(f"  Body innerText length: {n} (0 often means blank / CAPTCHA / bot wall)", file=out)
    except Exception as e:
        print(f"  (could not read page: {e})", file=out)

    esc = css_escape(query)
    name_sel = f'[name="{esc}"]'
    id_sel = f'[id="{esc}"]'
    print(f"[debug] Counts for query {query!r} (by={by}):", file=out)
    try:
        print(f"  [name]: {page.locator(name_sel).count()}", file=out)
        print(f"  [id]: {page.locator(id_sel).count()}", file=out)
        print(f"  link role exact: {page.get_by_role('link', name=query, exact=True).count()}", file=out)
        print(f"  get_by_text exact: {page.get_by_text(query, exact=True).count()}", file=out)
        print(f"  get_by_text partial: {page.get_by_text(query, exact=False).count()}", file=out)
    except Exception as e:
        print(f"  (count error: {e})", file=out)

    here = Path(__file__).resolve().parent
    sample = (here / "fixtures" / "test_page.html").as_uri()
    print(f"[debug] Offline test (no Amazon needed):", file=out)
    print(f"  python xpath_agent.py --url \"{sample}\" --name \"Gift Cards\" --by text", file=out)


def _launch_browser(p: Playwright, *, headless: bool, stealth: bool, use_chrome: bool) -> Browser:
    launch_kwargs = {"headless": headless}
    if stealth:
        launch_kwargs["ignore_default_args"] = ["--enable-automation"]
        launch_kwargs["args"] = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
    if use_chrome:
        launch_kwargs["channel"] = "chrome"
    try:
        return p.chromium.launch(**launch_kwargs)
    except Exception:
        if use_chrome:
            launch_kwargs.pop("channel", None)
            return p.chromium.launch(**launch_kwargs)
        raise


def _new_context(browser: Browser, *, stealth: bool) -> BrowserContext:
    if not stealth:
        return browser.new_context()
    return browser.new_context(
        user_agent=CHROME_WIN_UA,
        viewport={"width": 1365, "height": 900},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        extra_http_headers={
            "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
        },
    )


def _post_goto_wait(page: Page, timeout_ms: int) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except Exception:
        pass
    if "amazon." in page.url.lower():
        try:
            page.locator(
                "#nav-main, #navbar, #nav-belt, nav[role='navigation'], div#navFooter"
            ).first.wait_for(state="attached", timeout=min(timeout_ms, 25000))
        except Exception:
            pass


def run(
    url: str,
    query: str,
    *,
    by: str = "auto",
    exact: bool = False,
    timeout_ms: int = 15000,
    headless: bool = True,
    debug: bool = False,
    debug_out: Optional[TextIO] = None,
    stealth: bool = False,
    use_chrome: bool = False,
) -> Optional[str]:
    dbg = debug_out if debug_out is not None else sys.stderr
    with sync_playwright() as p:
        browser = _launch_browser(p, headless=headless, stealth=stealth, use_chrome=use_chrome)
        context = _new_context(browser, stealth=stealth)
        page = context.new_page()
        if stealth:
            page.add_init_script(STEALTH_INIT_SCRIPT)
        page.set_default_timeout(timeout_ms)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            _post_goto_wait(page, timeout_ms)
        except Exception:
            page.close()
            context.close()
            browser.close()
            raise

        try:
            if debug:
                write_debug(page, query, by=by, exact=exact, out=dbg)
            locator = find_locator(page, query, by=by, exact=exact)
            if not locator:
                if debug:
                    print("[debug] No locator matched your --by strategy.", file=dbg)
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
        description="Resolve XPath for an element (name, label, text, visible text, or attributes).",
    )
    parser.add_argument("--url", required=True, help="Page URL to open")
    parser.add_argument(
        "--name",
        "--query",
        dest="query",
        required=True,
        metavar="STRING",
        help="String to match (meaning depends on --by)",
    )
    parser.add_argument(
        "--by",
        choices=by_choices,
        default="auto",
        help="Match mode: auto tries name, id, placeholder, aria-label, label, exact text, then substring text",
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help="For --by label (or auto label step): require full label string match",
    )
    parser.add_argument("--timeout", type=int, default=15000, help="Timeout ms (default 15000)")
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print URL, title, body size, match counts, and a local file:// test command (stderr)",
    )
    parser.add_argument(
        "--stealth",
        action="store_true",
        help="Harder bot detection: realistic Chrome context, hide webdriver, en-IN (good for Amazon)",
    )
    parser.add_argument(
        "--chrome",
        action="store_true",
        help="Use installed Google Chrome (channel=chrome); falls back to bundled Chromium if unavailable",
    )
    args = parser.parse_args()

    try:
        xpath = run(
            args.url,
            args.query,
            by=args.by,
            exact=args.exact,
            timeout_ms=args.timeout,
            headless=not args.headed,
            debug=args.debug,
            stealth=args.stealth,
            use_chrome=args.chrome,
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
