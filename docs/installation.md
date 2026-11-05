# Installation and updates

## macOS

Open the DMG and drag `SooveeCommander.app` to Applications. The app is not notarized yet: the first time, right-click it in Applications and choose Open.

Settings, saved connections and paired devices are stored outside the app and are kept when the app is replaced or updated.

## Windows

The installer is for x64 Windows and installs for the current user, with a Start menu shortcut and an uninstaller. The portable ZIP runs without installation: unpack the whole archive, including the `_internal` folder, and start `SooveeCommander.exe`. Both use the same user settings.

The installer is not signed with a publisher certificate yet, so Windows SmartScreen may ask for confirmation.

## Android and Android TV

Install `SooveeCommander-…-android-universal.apk` (Android 7 or newer). Android asks to allow installing apps from the browser or file manager you use. Later versions install over the existing one and keep its files and pairings.

## Updates

Download the `.stereoupdate` file for your system from the release and choose **Help › Install update** (keep the file packed). The app checks the signature, platform and version before it replaces itself, and keeps a backup of the previous version.

## Diagnostic log

**Help › Diagnostic log** shows recent events and errors and can export them. The log stays on your computer; nothing is sent automatically. Exports may contain file paths and server addresses.

- macOS: `~/Library/Logs/SooveeCommander/application.jsonl`
- Windows: `%LOCALAPPDATA%\SooveeCommander\logs`
