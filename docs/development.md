# Development

The desktop app is in `src/soovee_commander` (Python, PySide6). Code and command names are in English; Czech user-interface texts are in `src/soovee_commander/locales/cs.json`.

```sh
python -m pip install -e '.[dev]'
python -m soovee_commander
python -m pytest -q
```

Tests run Qt offscreen (`tests/conftest.py`) and use local FTP, FTPS and SFTP servers and two instances of the transfer protocol.

## Building

- macOS: `SOOVEE_PYTHON=/path/to/python ./scripts/build_macos.sh`
- Windows: set `LIBARCHIVE` to the vcpkg `archive.dll` and run `./scripts/build_windows.ps1`
- Output goes to `dist/` (ignored by Git).
- CI (`.github/workflows/build.yml`) runs the tests, builds the macOS and Windows apps, and tests Windows installation and removal.
- `scripts/collect_licenses.py` records the bundled libraries and their license texts.

## Update packages

Official `.stereoupdate` packages are signed with a private key that is not part of the repository. They are created with `scripts/release.py package`; the update notes come from the version's section in `CHANGELOG.md`. A modified build runs without this key; it only does not accept unofficial update packages.

## Compatibility

Some internal identifiers (settings keys, the `.stereoupdate` format and the `stereo_commander` module alias) keep an earlier project name so existing installations keep their settings and can update.
