#!/bin/zsh
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$PROJECT_DIR"
SOOVEE_BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/soovee-build.XXXXXX")"
trap 'rm -rf "$SOOVEE_BUILD_ROOT"' EXIT
export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
export PYINSTALLER_CONFIG_DIR="$SOOVEE_BUILD_ROOT/cache"
SOOVEE_PYTHON="${SOOVEE_PYTHON:-${STEREO_PYTHON:-$PROJECT_DIR/.venv/bin/python}}"
SOOVEE_VERSION="$("$SOOVEE_PYTHON" -c 'from soovee_commander import __version__; print(__version__)')"
SOOVEE_ARCH="$(uname -m)"
"$SOOVEE_PYTHON" scripts/collect_licenses.py
"$SOOVEE_PYTHON" -m PyInstaller --noconfirm --windowed --name SooveeCommander --collect-submodules zeroconf \
    --add-data "$PROJECT_DIR/src/soovee_commander/licenses:soovee_commander/licenses" \
    --icon "$PROJECT_DIR/packaging/SooveeCommander.icns" \
    --add-data "$PROJECT_DIR/src/soovee_commander/assets:soovee_commander/assets" \
    --add-data "$PROJECT_DIR/src/soovee_commander/locales:soovee_commander/locales" \
    --osx-bundle-identifier cz.stereocommander.desktop \
    --paths "$PROJECT_DIR/src" --workpath "$SOOVEE_BUILD_ROOT/work" \
    --distpath "$SOOVEE_BUILD_ROOT/dist" --specpath "$SOOVEE_BUILD_ROOT/spec" \
    "$PROJECT_DIR/launcher.py"
SOOVEE_APP="$SOOVEE_BUILD_ROOT/dist/SooveeCommander.app"
ln -s SooveeCommander "$SOOVEE_APP/Contents/MacOS/StereoCommander"
"$SOOVEE_PYTHON" scripts/release.py stamp-app "$SOOVEE_APP"
chflags -R nohidden "$SOOVEE_APP"
xattr -cr "$SOOVEE_APP"
codesign --force --deep --sign - --timestamp=none "$SOOVEE_APP"
codesign --verify --deep --strict "$SOOVEE_APP"
QT_QPA_PLATFORM=offscreen "$SOOVEE_APP/Contents/MacOS/SooveeCommander" --smoke-test
mkdir -p "$PROJECT_DIR/dist"
# Older installed updaters require this payload root and executable name.
SOOVEE_UPDATE_ZIP="$SOOVEE_BUILD_ROOT/StereoCommander-$SOOVEE_VERSION-macOS-$SOOVEE_ARCH.zip"
mkdir -p "$SOOVEE_BUILD_ROOT/update"
ditto "$SOOVEE_APP" "$SOOVEE_BUILD_ROOT/update/StereoCommander.app"
ditto -c -k --keepParent --norsrc "$SOOVEE_BUILD_ROOT/update/StereoCommander.app" "$SOOVEE_UPDATE_ZIP"
if [[ -f "$PROJECT_DIR/.release/update-private.pem" ]]; then
    "$SOOVEE_PYTHON" scripts/release.py package --artifact "$SOOVEE_UPDATE_ZIP" --target "macos-$SOOVEE_ARCH" \
        --output "$PROJECT_DIR/dist/SooveeCommander-$SOOVEE_VERSION-macos-$SOOVEE_ARCH.stereoupdate"
fi
SOOVEE_DMG_ROOT="$SOOVEE_BUILD_ROOT/image"
mkdir -p "$SOOVEE_DMG_ROOT"
ditto "$SOOVEE_APP" "$SOOVEE_DMG_ROOT/SooveeCommander.app"
SOOVEE_ZIP="$PROJECT_DIR/dist/SooveeCommander-$SOOVEE_VERSION-macOS-$SOOVEE_ARCH.zip"
ditto -c -k --keepParent --norsrc "$SOOVEE_DMG_ROOT/SooveeCommander.app" "$SOOVEE_ZIP"
cp "$SOOVEE_ZIP" "$PROJECT_DIR/dist/SooveeCommander-macOS-$SOOVEE_ARCH.zip"
ln -s /Applications "$SOOVEE_DMG_ROOT/Applications"
cat > "$SOOVEE_DMG_ROOT/INSTALL.txt" <<'TEXT'
Soovee Commander

1. Drag SooveeCommander into Applications.
2. Start it from Applications (or find it with Spotlight).
3. You may eject this installer disk.

Future versions: choose Update → Select update folder in the application.
Keep the downloaded .stereoupdate file packed in that folder.
Your settings and connections will be preserved.

This application currently uses an ad-hoc signature without Apple notarization.
If macOS blocks the first launch, allow it once in System Settings → Privacy & Security.
TEXT
hdiutil create -quiet -ov -volname "Soovee Commander" -srcfolder "$SOOVEE_DMG_ROOT" \
    -format UDZO "$PROJECT_DIR/dist/SooveeCommander-$SOOVEE_VERSION-macOS-$SOOVEE_ARCH.dmg"
echo "$SOOVEE_ZIP"
