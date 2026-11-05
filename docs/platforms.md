# Platforms

| Platform | Status |
| --- | --- |
| macOS (Apple Silicon) | Desktop app, DMG and signed updates. |
| Windows x64 | Desktop app, installer, portable ZIP and signed updates. Installation and removal are tested in CI. |
| macOS Intel, Windows ARM64 | No dedicated build yet. |
| Android phone and tablet | One APK for ARM and x86, 32 and 64 bit, Android 7 or newer. |
| Android TV, Google TV | Same APK with a remote-control interface. |
| iPhone and iPad | Native app; development builds only, not distributed yet. |

All clients use the same encrypted transfer protocol (TLS 1.3 with a pre-shared key set up by code or QR pairing) and the same file core. A paired device sees only the folders that were explicitly shared with it.

Phones and TVs must keep Soovee open during transfers; Android continues running copies in the background with a notification. Device discovery uses Bonjour/mDNS on the local network.

See [mobile.md](mobile.md) for building the mobile clients.
