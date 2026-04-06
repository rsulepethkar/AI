"""
QA automation helper: load a URL, scan the DOM for interactive elements,
and save a JSON map of { visible label/text (or fallback) : best XPath }.

By default each run writes a new UTF-8 file under ./scans/ (host + timestamp).
Use -o to choose an explicit path; use --stdout to also print JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, unquote

from playwright.sync_api import sync_playwright

from xpath_agent import STEALTH_INIT_SCRIPT, _launch_browser, _new_context, _post_goto_wait

# In-page: collect interactive nodes; XPath prefers @id, @name, @aria-label, text(), @href, else relative paths.
SCAN_INTERACTIVE_JS = """
() => {
  const q = (s) => "'" + String(s).replace(/'/g, "''") + "'";

  /** First non-empty direct text-node value (for //tag[text()='...'], not normalize-space). */
  function firstDirectText(el) {
    if (!el || el.nodeType !== 1) return '';
    for (let i = 0; i < el.childNodes.length; i++) {
      const n = el.childNodes[i];
      if (n.nodeType === 3) {
        const v = n.textContent.replace(/^\\s+|\\s+$/g, '');
        if (v.length > 0) return v;
      }
    }
    return '';
  }

  /** Child-axis steps from ancestor (exclusive) down to el: div[1]/span[2]/a[1] */
  function relPathFrom(ancestor, el) {
    if (!ancestor || !el || ancestor === el) return null;
    const parts = [];
    let cur = el;
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

  /** //*[@id='prev']/following-sibling::tag[k] */
  function xpathViaFollowingSiblingOfPrecedingId(el) {
    const tag = el.tagName.toLowerCase();
    let sib = el.previousElementSibling;
    while (sib) {
      if (sib.id) {
        let k = 0;
        let cur = sib.nextElementSibling;
        while (cur) {
          if (cur.tagName.toLowerCase() === tag) {
            k++;
            if (cur === el) return '//*[@id=' + q(sib.id) + ']/following-sibling::' + tag + '[' + k + ']';
          }
          cur = cur.nextElementSibling;
        }
        return null;
      }
      sib = sib.previousElementSibling;
    }
    return null;
  }

  /** //*[@id='next']/preceding-sibling::tag[k] */
  function xpathViaPrecedingSiblingOfFollowingId(el) {
    const tag = el.tagName.toLowerCase();
    let sib = el.nextElementSibling;
    while (sib) {
      if (sib.id) {
        let k = 0;
        let cur = sib.previousElementSibling;
        while (cur) {
          if (cur.tagName.toLowerCase() === tag) {
            k++;
            if (cur === el) return '//*[@id=' + q(sib.id) + ']/preceding-sibling::' + tag + '[' + k + ']';
          }
          cur = cur.previousElementSibling;
        }
        return null;
      }
      sib = sib.nextElementSibling;
    }
    return null;
  }

  /** Nearest ancestor (not self) with id or data-testid, below html. */
  function findAnchor(el) {
    let a = el.parentElement;
    while (a && a !== document.documentElement) {
      if (a.id) return { kind: 'id', val: a.id, node: a };
      const dt = a.getAttribute && a.getAttribute('data-testid');
      if (dt) return { kind: 'testid', val: dt, node: a };
      a = a.parentElement;
    }
    return null;
  }

  /** Relative XPath only (no /html[1]/body[1]/...). */
  function relativeOptimizedXPath(el) {
    if (!el || el.nodeType !== 1) return null;
    if (el.id) return '//*[@id=' + q(el.id) + ']';

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

    const tag = el.tagName.toLowerCase();
    const t = firstDirectText(el);
    if (t) return '//' + tag + '[text()=' + q(t) + ']';
    return '//' + tag;
  }

  function normText(el) {
    if (!el) return '';
    const s = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (s.length > 120) return s.slice(0, 117) + '...';
    return s;
  }

  function labelForControl(el) {
    const tag = el.tagName;
    if (tag !== 'INPUT' && tag !== 'SELECT' && tag !== 'TEXTAREA') return '';
    const id = el.id;
    if (id) {
      const labels = document.getElementsByTagName('label');
      for (let i = 0; i < labels.length; i++) {
        if (labels[i].htmlFor === id) return normText(labels[i]);
      }
    }
    let p = el.parentElement;
    if (p && p.tagName === 'LABEL') return normText(p);
    return '';
  }

  function displayKey(el) {
    const tag = el.tagName.toLowerCase();
    let key = labelForControl(el);
    if (key && (tag === 'input' || tag === 'select' || tag === 'textarea')) {
      const t = (el.getAttribute('type') || '').toLowerCase();
      if (t !== 'submit' && t !== 'button' && t !== 'reset' && t !== 'image')
        key = key + ' field';
    }
    if (!key) key = normText(el);
    if (!key) key = (el.getAttribute('aria-label') || '').trim();
    if (!key) key = (el.getAttribute('placeholder') || '').trim();
    if (!key) key = (el.getAttribute('title') || '').trim();
    if (!key) key = (el.getAttribute('name') || '').trim();
    if (!key) key = (el.getAttribute('alt') || '').trim();
    if (!key) key = (el.getAttribute('value') || '').trim();
    if (!key) {
      const r = el.getAttribute('role');
      key = r ? tag + '[role=' + r + ']' : tag;
      const typ = el.getAttribute('type');
      if (typ && tag === 'input') key += '[' + typ + ']';
    }
    return key || tag;
  }

  function smartXPath(el) {
    const tag = el.tagName.toLowerCase();
    if (el.id) return '//*[@id=' + q(el.id) + ']';
    const name = el.getAttribute('name');
    const aria = el.getAttribute('aria-label');
    const typ = (el.getAttribute('type') || '').toLowerCase();

    if (name && (tag === 'input' || tag === 'select' || tag === 'textarea' || tag === 'button')) {
      if (tag === 'input' && typ)
        return '//input[@type=' + q(typ) + ' and @name=' + q(name) + ']';
      return '//' + tag + '[@name=' + q(name) + ']';
    }
    if (aria)
      return '//' + tag + '[@aria-label=' + q(aria) + ']';
    if (tag === 'input' && typ)
      return '//input[@type=' + q(typ) + ']';

    const txt = firstDirectText(el);
    if (txt && (tag === 'a' || tag === 'button' || tag === 'label'))
      return '//' + tag + '[text()=' + q(txt) + ']';

    if (tag === 'a') {
      const href = el.getAttribute('href');
      if (href && href.length < 200)
        return '//a[@href=' + q(href) + ']';
    }

    return relativeOptimizedXPath(el);
  }

  const sel = [
    'a[href]',
    'button',
    'input:not([type="hidden"])',
    'select',
    'textarea',
    '[role="button"]',
    '[role="link"]',
    '[role="checkbox"]',
    '[role="radio"]',
    '[role="switch"]',
    '[role="textbox"]',
    '[role="searchbox"]',
    '[role="combobox"]',
    '[role="listbox"]',
    '[role="menuitem"]',
    '[role="tab"]',
    '[contenteditable="true"]',
    'label',
  ].join(',');

  const nodes = Array.from(document.querySelectorAll(sel));
  const rows = [];
  const seen = new Set();

  for (let i = 0; i < nodes.length; i++) {
    const el = nodes[i];
    if (!(el instanceof Element)) continue;
    const xp = smartXPath(el);
    if (!xp) continue;
    const key = displayKey(el).trim() || el.tagName.toLowerCase();
    const dedupe = key + '|' + xp;
    if (seen.has(dedupe)) continue;
    seen.add(dedupe);
    rows.push({ key, xpath: xp });
  }

  return rows;
}
"""


def auto_output_path(url: str) -> Path:
    """New file per run: scans/<host_or_file_stem>_<YYYYMMDD_HHMMSS>.json"""
    out_dir = Path(__file__).resolve().parent / "scans"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    parsed = urlparse(url.strip())
    if parsed.scheme == "file":
        raw_path = unquote(parsed.path).replace("\\", "/")
        stem = Path(raw_path).stem or "local_page"
        slug = re.sub(r"[^\w\-.]+", "_", stem).strip("_") or "local_page"
    else:
        host = (parsed.hostname or "site").lower()
        slug = re.sub(r"[^\w\-.]+", "_", host).strip("_") or "site"
    return out_dir / f"{slug}_{ts}.json"


def _unique_keys(rows: list[dict[str, str]]) -> dict[str, str]:
    """Build ordered dict: human-readable keys, suffix (2), (3) on collision."""
    out: dict[str, str] = {}
    counts: dict[str, int] = {}
    for row in rows:
        base = row.get("key") or "element"
        base = re.sub(r"\s+", " ", str(base)).strip() or "element"
        n = counts.get(base, 0) + 1
        counts[base] = n
        key = base if n == 1 else f"{base} ({n})"
        out[key] = row["xpath"]
    return out


def scan_page(url: str, *, stealth: bool, use_chrome: bool, headless: bool, timeout_ms: int) -> dict[str, str]:
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
        finally:
            pass

        try:
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
        description="Scan a page for interactive elements; output JSON map label/text -> XPath.",
    )
    parser.add_argument("--url", required=True, help="Page URL (https://... or file:///...)")
    parser.add_argument("--timeout", type=int, default=30000, help="Navigation timeout ms (default 30000)")
    parser.add_argument("--headed", action="store_true", help="Show browser")
    parser.add_argument("--stealth", action="store_true", help="Use stealth context (recommended for Amazon, etc.)")
    parser.add_argument("--chrome", action="store_true", help="Use installed Google Chrome if available")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Single-line JSON (default: indented, readable)",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="Explicit output path (default: scans/<host>_<timestamp>.json)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Also print JSON to stdout (default: file only)",
    )
    args = parser.parse_args()

    try:
        data = scan_page(
            args.url,
            stealth=args.stealth,
            use_chrome=args.chrome,
            headless=not args.headed,
            timeout_ms=args.timeout,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    payload = (
        json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if args.compact
        else json.dumps(data, ensure_ascii=False, indent=2)
    )
    out_path = Path(args.output) if args.output else auto_output_path(args.url)
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
