# Changelog

All notable changes to Soovee Commander are listed here. Versions before 1.0 are test builds.

## [0.22.0] - 2026-11-11

### Security
- File operations from paired devices can no longer reach outside a shared folder when a folder is swapped for a link during the operation.
- Renaming from a paired device never replaces an existing item.
- Capacity requests no longer reveal the full path of a shared folder.
- Pairing requests are limited per address and can be turned off on desktop and Android.
- Plain FTP connections are marked as not secure and ask for confirmation.
- Android hands only shared storage, the Shared folder and preview copies to other apps.

### Desktop
- Enter confirms dialogs on macOS, including New folder, Rename and Delete.
- New folder (F7) can prefill the name under the cursor; this can be turned off or limited to folders.
- Archives are created next to the selected items, with a changeable location.
- Open with and Properties show program icons; Use saves a file association without opening the file, optionally for related file types.

### Fixed
- Copying and renaming on SMB network shares (for example a NAS) no longer fails.

## [0.21.0] - 2026-11-05

### Android and Android TV
- Redesigned interface matching the iPhone and iPad app, with light and dark appearance.
- Faster file list for large folders, with thumbnails, list and grid views, natural sorting, filtering and search in subfolders.
- File actions in a menu, multi-selection, favorites, recent folders, a text editor and ZIP/TAR archive support.
- Copy and move progress with speed and time remaining; operations continue in the background.
- Android TV navigation optimized for the remote control.

### Fixed
- Copying on Android no longer fails when the system refuses extended file attributes.

## [0.20.0] - 2026-11-04

### iPhone and iPad
- Works as a standalone file manager for the app folder and folders chosen in Files.
- Faster file list with thumbnails, search in subfolders, file actions, multi-selection, previews, a text editor and ZIP/TAR archive support.
- Two-panel layout on iPad and in landscape, with drag and drop and keyboard shortcuts.
- Copy progress with speed and time remaining.
- Redesigned Devices and Settings screens.

### Device pairing
- Clearer recovery when a paired device no longer recognizes this one.

### Fixed
- Connection errors on Windows are reported correctly.

## [0.19.1] - 2026-11-04

### Device pairing
- Pairing by selecting a nearby device, which then shows its code and QR code.
- Removing a paired device also revokes its access to shared folders.
- Paired devices are found again after a network address change.

## [0.19.0] - 2026-11-04

### Desktop
- Folders refresh automatically when their contents change.
- New columns for date added and last opened, and sorting options.
- New file creation with built-in types and custom templates.
- Built-in previews for images, PDF, Markdown, CSV and office documents.
- Reorganized menus, a single Settings window and redesigned dialogs.

## Earlier versions

Versions 0.15 to 0.18 introduced the Windows build, disk usage in panel headers, multi-rename with masks and counters, panel view options, device transfers and the first Android and Android TV clients.
