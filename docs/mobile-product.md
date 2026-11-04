# Mobile and TV product requirements

Mobile clients must be file managers with Soovee transfers integrated into their normal storage browser. A pairing screen is not a substitute for a file manager.

## Reference patterns

- [X-plore](https://play.google.com/store/apps/details?id=com.lonelycatgames.Xplore): source and destination locations, multiple selection, contextual operations and browsing archives as folders.
- [EX File Manager](https://play.google.com/store/apps/details?id=com.ace.ex.file.manager): visible storage locations, filtered search, media previews and file operations.
- [AnExplorer](https://anexplorer.io): storage and network locations adapted to the device, including TV use.

These references guide interaction design. Their marketing feature lists are not evidence of feature parity in Soovee.

## Native library preview (based on 0.18)

The approved overview/library direction is implemented as a native test build, not an embedded mockup. iPhone uses UIKit storage/device cards, native SF Symbols, bottom navigation, persistent list/grid and appearance preferences. Android phones use bottom navigation; Android TV uses a flat navigation rail, storage tiles and a separate device column. File lists offer filename filtering, sorting, multiple selection, destination device/folder selection, rename, folder creation, permanent deletion with confirmation, and local file opening.

The shared `transfer_items` API copies local/device selections without silently overwriting existing targets, reports actual transferred bytes and completed items, and accepts cancellation from a separate native queue. Local moves reuse the established source-preserving move implementation. Moving across devices is deliberately unavailable until source verification and removal are fully integrated. Root/protected-folder guards also apply to the native interface. Empty directories, inaccessible folders and operation failures remain explicit outcomes.

Verified in this change:

- Android debug/release builds and signed universal APK covering armeabi-v7a, arm64-v8a, x86 and x86_64.
- iPhone simulator and signed development-device builds; native startup screenshots reviewed.
- 35 mobile/network integration tests, including multi-item copy, existing-target preservation, cancellation with partial-copy cleanup, encrypted device upload/download, remote rename/delete, and root/self-copy protection.
- Physical iPhone updated in place. Physical TV left untouched to avoid interrupting playback.

Manual traversal with touch/D-pad remains pending: the computer-use tool did not permit opening Finder to expose the simulator window. Startup screenshots and backend tests do not establish that every interaction has passed a manual device test.

Still missing in mobile clients: media thumbnails, aggregate folder-size calculation, archive browsing/extraction/creation, FTP/FTPS/SFTP/SMB/WebDAV screens, document-provider folder bookmarks on iPhone, and the optional Commander presentation. Transfer information currently describes the active/latest operation, not a persistent multi-job queue. Do not describe these as complete or imply feature parity with the reference managers.

Both ends need authenticated rename/delete RPC support. The physical TV remains on 0.17 until its update is scheduled with the owner. Preserve its existing Shared files and pairings; never uninstall or clear application data during an update.

## Design review contract

Review phone overview and Commander flows, plus TV library and Commander flows, before the next mobile/TV deployment. Mark examples as mock data. A prototype action does not establish that the corresponding native feature exists. Do not interrupt TV playback for design previews or updates.

Native implementations should use platform file lists, selection, context menus, document access and media-preview patterns. On iPhone, app-private data from other applications remains inaccessible; user-selected document locations must use the platform permission model.

## Acceptance workflow

Create a folder, copy multiple files, rename an item, inspect aggregate properties, move after verification, cancel an operation, handle an existing destination, delete with explicit confirmation, and reconnect after an address change. Repeat across app Shared, approved device storage and paired devices. Archive and network protocols need their own fixtures and failure tests before being marked supported.
