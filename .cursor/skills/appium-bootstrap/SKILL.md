---
name: appium-bootstrap
description: Bootstrap and verify Appium environments for Android and iOS automation in this repository. Use when users need help starting emulators/simulators, validating connected devices, checking Appium server readiness, resolving package/activity or bundle-id setup issues, or running first-time preflight commands before locator agents.
---

# Appium Bootstrap

Use this skill before running `ios_app_*` or `android_apk_*` agents.

## Goal

Confirm Appium + device + app target are ready, then run one known-good smoke command.

## Preflight Checklist

1. **Appium server**
   - Default URL: `http://127.0.0.1:4723`
   - Verify endpoint responds before running scripts.
2. **Device availability**
   - Android: `adb devices` has at least one `device`.
   - iOS: simulator/real device visible to Appium/Xcode.
3. **Target app info**
   - Android APK mode: valid `--apk` path.
   - Android installed-app mode: package/activity known.
   - iOS: valid `--bundle-id` (default `com.apple.AppStore`).
4. **Dependencies**
   - Python packages from `requirements.txt` installed.

## Android Bootstrap

### Start emulator (Windows example)

```powershell
"$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" -list-avds
"$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" -avd "Pixel_7_API_34"
```

### Verify device is ready

```powershell
"$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" devices
"$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" -s emulator-5554 shell getprop dev.bootcomplete
```

Expected: device state `device` and `dev.bootcomplete = 1`.

### Package/activity discovery

```powershell
"$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" shell dumpsys window | findstr /i "mCurrentFocus"
"$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" shell dumpsys activity activities | findstr /i "mResumedActivity"
```

### Android smoke run

```powershell
python android_apk_dom_scanner.py --server-url "http://127.0.0.1:4723" --apk "<path.apk>" --udid "<device-id>" --stdout
```

## iOS Bootstrap

### Requirements

- Appium server running with XCUITest driver.
- Xcode + WebDriverAgent configured.
- Simulator or real device available.

### iOS smoke run (App Store)

```powershell
python ios_app_dom_scanner.py --server-url "http://127.0.0.1:4723" --bundle-id "com.apple.AppStore" --device-name "iPhone 14 Pro" --stdout
```

## Failure Triage

- **Connection refused / cannot reach server**
  - Appium server not running at `--server-url`.
- **No such device / offline**
  - Start emulator/simulator and wait for boot completion.
- **App launch failure**
  - Wrong APK path, package/activity, or bundle id.
- **Session not created**
  - Driver mismatch (`UiAutomator2` for Android, `XCUITest` for iOS), or missing platform tooling.

## Output Rules

- Report exact command run.
- Report pass/fail with concise root cause.
- If scanner succeeds, report output JSON path.

