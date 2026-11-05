# Mobile and TV clients

The clients share the transfer and file core with the desktop app (`mobile/shared/python`). Android uses a native Java interface, iPhone and iPad a native UIKit interface.

## Android and Android TV

One APK for ARMv7, ARM64, x86 and x86_64, Android 7 or newer. The interface adapts to phones, tablets and TVs. Python 3.11 runs through Chaquopy; TLS 1.3 with pre-shared keys is provided through the public OpenSSL API.

Requirements: Java 17, Gradle 8.9, Android SDK 35 and Python 3.11 on the build machine.

```sh
export ANDROID_HOME=/path/to/Android/sdk
export SOOVEE_BUILD_PYTHON=/path/to/python3.11
gradle --no-daemon -p mobile/android :app:assembleRelease
python scripts/sign_android.py mobile/android/app/build/outputs/apk/release/app-release-unsigned.apk --output dist/SooveeCommander-android-universal.apk
```

The signing script creates a private key in the ignored `.release` folder on first use. Keep a backup: later versions must be signed with the same key to install over earlier ones.

## iPhone and iPad

`scripts/build_apple_clients.py` builds the UIKit app with the official Python-Apple-support runtime (`--runtime-directory` points to a folder with `iOS/Python.xcframework`).

- Simulator: `--platform ios`
- Device: `--platform ios-device` with a provisioning profile and signing identity. `scripts/prepare_apple_signing.py` asks Xcode for a development profile.

iOS gives the app access to its own folder and to folders the user chooses in the Files app; other apps' data stays private.

## Pairing

1. Open Soovee on both devices on the same local network.
2. Select the other device in Devices. It shows an eight-digit code and a QR code; type the code or scan the QR code.
3. Confirm the pairing and choose which folders to share.

Codes and keys are never announced on the network. After an address change, a paired device is found again and verified with its key.
