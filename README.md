1. One-time setup
cd "c:\Project\New folder\Web Automation"
pip install -r requirements.txt
python -m playwright install chromium
(Optional: use your installed Chrome with --chrome on some commands.)

2. XPath agent (xpath_agent.py) — one element, one XPath
cd "c:\Project\New folder\Web Automation"
# Example: match by visible / link text
python xpath_agent.py --url "https://www.amazon.in/" --name "Gift Cards" --by text --stealth
# Local test page (no network)
python xpath_agent.py --url "file:///C:/Project/New%20folder/Web%20Automation/fixtures/test_page.html" --name "Gift Cards" --by text
Useful flags: --headed (show browser), --debug, --timeout 30000, --chrome.

3. DOM scanner (qa_dom_scanner.py) — full page → JSON file
cd "c:\Project\New folder\Web Automation"
python qa_dom_scanner.py --url "https://example.com" --stealth
By default it writes under scans\ (new file each run). Check the last line on stderr for the exact path.

Explicit file:

python qa_dom_scanner.py --url "https://example.com" -o my_scan.json --stealth
Useful flags: --headed, --chrome, --stdout (also print JSON), --compact.

