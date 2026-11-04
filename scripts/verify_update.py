"""Exercise a signed release against a real previous .app in a temporary directory."""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from soovee_commander.updates import APP_NAME, APP_NAMES, find_release, launch_update, prepare_update, validate_mac_zip


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("package")
    parser.add_argument("--previous", required=True, help="Previous macOS app ZIP")
    parser.add_argument("--previous-version", default="0.2.0")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="stereo-update-verification-") as temporary:
        root = Path(temporary)
        validate_mac_zip(args.previous)
        subprocess.run(["/usr/bin/ditto", "-x", "-k", str(Path(args.previous).resolve()), str(root)], check=True)
        current = next(root / name for name in APP_NAMES if (root / name).is_dir())
        settings = root / "user-settings.json"
        settings.write_text(json.dumps({"connections": [{"host": "example.com", "username": "test"}],
                                        "left": "/Users/test/Documents"}))
        before = settings.read_bytes()
        release = find_release(args.package, installed_version=args.previous_version)
        prepared = prepare_update(release, current, root / "result.json")
        process = launch_update(prepared, old_pid=999999999, launch=False, verify=True)
        if process.wait(timeout=90) != 0:
            raise RuntimeError((prepared.workspace / "install.log").read_text())
        assert (prepared.workspace / "previous.app" / "Contents" / "MacOS" / "StereoCommander").is_file()
        with (current / "Contents" / "Info.plist").open("rb") as stream:
            assert plistlib.load(stream)["CFBundleShortVersionString"] == release.version
        assert settings.read_bytes() == before
        progress = prepared.workspace / 'progress.json'
        assert json.loads(progress.read_text())['state'] == 'success'
        environment = dict(os.environ, QT_QPA_PLATFORM='offscreen')
        subprocess.run([str(current / 'Contents/MacOS/StereoCommander'), '--update-monitor', str(progress), str(os.getpid())],
                       env=environment, capture_output=True, check=True, timeout=20)
        assert json.loads(prepared.result_path.read_text())["state"] == "success"
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(current)], check=True)
        print(f"OK: actual app {args.previous_version} → {release.version}; signature, startup, backup and settings verified")


if __name__ == "__main__":
    main()
