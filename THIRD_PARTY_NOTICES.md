# Third-party software and distribution status

Soovee Commander's original application code is licensed under the [MIT License](LICENSE). Third-party code and test fixtures retain their own licenses. The MIT grant does not replace those licenses.

The runtime package inventory and offline license texts are in [src/soovee_commander/licenses](src/soovee_commander/licenses). About → Components and licenses displays that inventory; About → Archives explains which archive libraries the application uses. The RAR test fixtures retain their upstream notice in [tests/fixtures/rarfile-LICENSE](tests/fixtures/rarfile-LICENSE).

Archive functionality uses Python zipfile/tarfile, zlib, libbz2, liblzma and native libarchive through libarchive-c. Their notices must remain with redistributed copies. The application does not bundle WinRAR or use Salamander's source code.

Desktop local-network discovery uses python-zeroconf (LGPL-2.1-or-later) and ifaddr (MIT). Their license texts are included in the generated component inventory. Android discovery uses the platform NsdManager API. Discovery announces only device identity, display name, device kind and protocol version; pairing codes and keys are never advertised.

## Public source repository

Keep LICENSE, this notice, upstream notices, build scripts and test-fixture licenses in the repository. Do not publish the private update-signing key in `.release/`, paired-device keys, user connection settings or a development environment. `.release/`, `.venv/`, `build/` and `dist/` are currently ignored by Git. Copying the entire working directory into an upload can bypass those exclusions.

## LGPL components in the binary releases

The macOS, Windows and Android packages of releases 0.20.0 and 0.21.0 contain these components under the GNU Lesser General Public License. Versions were read from the component inventory inside the built packages (About › Components and licenses shows the same list).

| Component | Version | License | Corresponding source |
| --- | --- | --- | --- |
| Qt (libraries used by PySide6, including Qt PDF) | 6.12.0 | LGPL-3.0-only | [qt-everywhere-src-6.12.0.tar.xz](https://download.qt.io/official_releases/qt/6.12/6.12.0/single/qt-everywhere-src-6.12.0.tar.xz) |
| PySide6 (Essentials, Pdf) and Shiboken6 | 6.12.0 | LGPL-3.0-only | [pyside-setup-everywhere-src-6.12.0.tar.xz](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/pyside-setup-everywhere-src-6.12.0.tar.xz) |
| Paramiko | 4.0.0 | LGPL-2.1 | [paramiko 4.0.0 source](https://pypi.org/project/paramiko/4.0.0/#files) |
| python-zeroconf | 0.153.0 | LGPL-2.1-or-later | [zeroconf 0.153.0 source](https://pypi.org/project/zeroconf/0.153.0/#files) |

The libraries are used unmodified. Soovee Commander's own source code, build scripts and build instructions are in this repository ([docs/development.md](docs/development.md)).

**Source offer.** For at least three years after a release, the corresponding source of the LGPL components listed for that release is available on request: open an issue in this repository. The sources are linked from the official Qt and PyPI servers above.

### Replacing or modifying the LGPL libraries

- **Rebuild from source:** install your modified PySide6, Shiboken6, Paramiko or zeroconf into the build environment, then run `scripts/build_macos.sh` (macOS) or `scripts/build_windows.ps1` (Windows). The result runs without any key held by the project.
- **macOS, without rebuilding:** the Qt, PySide6 and Shiboken6 libraries are separate files in `SooveeCommander.app/Contents/Frameworks` (Qt frameworks in `PySide6/Qt/lib`, `PySide6/libpyside6.abi3.*.dylib`, `shiboken6/libshiboken6.abi3.*.dylib`, `PySide6/*.so`). Replace them with interface-compatible builds of the same minor version, then re-sign the app locally: `codesign --force --deep --sign - SooveeCommander.app`.
- **Windows, without rebuilding:** the same libraries are separate DLLs in `_internal\PySide6` and `_internal\shiboken6` of the installed or portable app; replace them with interface-compatible builds.
- Paramiko and zeroconf are bundled as Python modules inside the application archive; to change them, rebuild as described above.
- The private key that signs official update packages is not needed to run a modified build. A modified installation simply does not accept unofficial update packages through Help › Install update.

## Other notices

- Qt PDF contains PDFium and the libraries it bundles (for example FreeType, libjpeg-turbo, OpenJPEG, Little CMS, libpng and zlib). The PDFium license is included; the complete list for Qt 6 is in [Licenses used in Qt](https://doc.qt.io/qt-6/licenses-used-in-qt.html) (Qt PDF section).
- The Windows package includes the copyright notices of its native libraries (libarchive and its compression libraries, built with vcpkg) as `windows-native-*-COPYRIGHT.txt` in the component license folder.
- Android packages contain the Python runtime (PSF License), Chaquopy runtime notices and the libraries listed in [mobile/shared/licenses](mobile/shared/licenses).

Status date: 2026-11-04. This records how the project meets the license conditions of the components it ships; it is not an independent legal opinion.
