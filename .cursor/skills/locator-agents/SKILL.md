---
name: locator-agents
description: Run and maintain locator extraction agents for web, mobile web, desktop apps, native iOS apps, and Android APK apps. Use when the user asks to fetch XPaths, scan interactive elements into JSON, run a specific device profile, or troubleshoot no-match issues in this repository.
---

# Locator Agents

Use this skill for this repository's locator tools.

## Scripts

- `xpath_agent.py`: Single XPath from a web URL.
- `qa_dom_scanner.py`: Full web page scan to JSON.
- `mobile_xpath_agent.py`: Single XPath on mobile-emulated web.
- `mobile_dom_scanner.py`: Full mobile-emulated web scan to JSON.
- `application_dom_scanner.py`: Windows desktop app UI scan to JSON.
- `ios_app_xpath_agent.py`: Single XPath in native iOS app via Appium.
- `ios_app_dom_scanner.py`: Full native iOS app UI scan to JSON.
- `android_apk_xpath_agent.py`: Single XPath in Android APK via Appium.
- `android_apk_dom_scanner.py`: Full Android APK UI scan to JSON.

## Default Workflow

1. Detect target type from user request:
   - Web URL -> `xpath_agent.py` or `qa_dom_scanner.py`
   - Mobile web/device profile -> `mobile_*`
   - Windows desktop app -> `application_dom_scanner.py`
   - iOS native app / App Store -> `ios_app_*`
   - Android `.apk` -> `android_apk_*`
2. Prefer scan scripts (`*_dom_scanner.py`) when user asks for "all elements".
3. Prefer xpath scripts (`*_xpath_agent.py`) when user asks for one element.
4. Always save scan output files and report the exact output path.

## Command Templates

### Web

```powershell
python xpath_agent.py --url "<url>" --name "<query>" --by text --stealth
python qa_dom_scanner.py --url "<url>" --stealth
```

### Mobile web (Playwright device emulation)

```powershell
python mobile_xpath_agent.py --url "<url>" --name "<query>" --by text --device "iPhone 14 Pro" --stealth --headed
python mobile_dom_scanner.py --url "<url>" --device "iPhone 14 Pro" --stealth --headed
```

### Windows desktop app

```powershell
python application_dom_scanner.py --title-regex ".*Notepad.*" --stdout
```

### Native iOS app (Appium)

```powershell
python ios_app_xpath_agent.py --server-url "http://127.0.0.1:4723" --bundle-id "com.apple.AppStore" --device-name "iPhone 14 Pro" --query "Search" --by auto
python ios_app_dom_scanner.py --server-url "http://127.0.0.1:4723" --bundle-id "com.apple.AppStore" --device-name "iPhone 14 Pro" --stdout
```

### Android APK (Appium)

```powershell
python android_apk_xpath_agent.py --server-url "http://127.0.0.1:4723" --apk "<path.apk>" --udid "<device-id>" --query "Login" --by auto
python android_apk_dom_scanner.py --server-url "http://127.0.0.1:4723" --apk "<path.apk>" --udid "<device-id>" --stdout
```

## Troubleshooting Rules

- If result is `No matching element found`, retry with:
  - larger `--timeout`
  - `--headed` for Playwright-based scripts
  - alternate match mode (`--by visible-text`, `--by label`, `--by auto`)
- For mobile/web bot walls (empty title/body), use `--stealth` and optionally `--chrome`.
- For Android/iOS Appium flows:
  - verify Appium server URL is reachable
  - verify device/emulator is online
  - verify bundle id / package / activity / APK path
- Keep generated scan artifacts under `scans/`.

## Output Expectations

- For single lookup scripts: print one XPath string on stdout.
- For scanner scripts: write JSON map `key -> xpath` and mention the saved file path.
- Keep key names human-readable and de-duplicated (`Name`, `Name (2)`).

