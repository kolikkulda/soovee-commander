"""Local release signing. Keep .release/update-private.pem backed up and private."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import plistlib
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from soovee_commander import __version__
from soovee_commander.updates import APP_ID, canonical_manifest

KEY = ROOT / ".release" / "update-private.pem"
PUBLIC_MODULE = ROOT / "src" / "soovee_commander" / "update_key.py"


def release_key():
    if not KEY.exists():
        raise RuntimeError("Signing key missing. Run scripts/release.py init-key first.")
    key = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError("Invalid signing key.")
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    from soovee_commander.update_key import PUBLIC_KEY_HEX
    if public != PUBLIC_KEY_HEX:
        raise RuntimeError("The private key does not match the application public key. Never replace the key silently.")
    return key


def init_key():
    if KEY.exists():
        release_key()
        return
    from soovee_commander.update_key import PUBLIC_KEY_HEX
    if PUBLIC_KEY_HEX:
        raise RuntimeError("This project already has a public key. Restore the matching private key from backup.")
    KEY.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    data = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    descriptor = os.open(KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    PUBLIC_MODULE.write_text('"""Public release verification key. Private key is never bundled."""\n'
                             f'PUBLIC_KEY_HEX = "{public}"\n')
    print("Signing key created. The private key exists only in the ignored .release/ folder.")


def stamp_app(path):
    path = Path(path) / "Contents" / "Info.plist"
    with path.open("rb") as stream:
        info = plistlib.load(stream)
    info.update(CFBundleIdentifier=APP_ID, CFBundleShortVersionString=__version__, CFBundleVersion=__version__,
                CFBundleDisplayName="Soovee Commander", CFBundleName="Soovee Commander", NSHighResolutionCapable=True)
    with path.open("wb") as stream:
        plistlib.dump(info, stream)


def changelog_notes(version):
    """The CHANGELOG.md section of a version, shown in the update dialog."""
    path = ROOT / "CHANGELOG.md"
    if not path.is_file():
        return ""
    lines, inside = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line.startswith(f"## [{version}]")
            if inside:
                lines.append(f"Soovee Commander {version}")
            continue
        if inside:
            lines.append(line[4:] if line.startswith("### ") else line)
    return "\n".join(lines).strip()


def package(artifact, target, output):
    key = release_key()
    artifact, output = Path(artifact), Path(output)
    with artifact.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    name = "setup.exe" if target.startswith("windows-") else "application.zip"
    notes = changelog_notes(__version__) or "New Soovee Commander release."
    if len(notes) > 4000:
        raise RuntimeError("Release notes may have at most 4000 characters.")
    manifest = {"schema": 1, "app_id": APP_ID, "version": __version__, "target": target,
                "artifact": name, "sha256": digest, "size": artifact.stat().st_size,
                "notes": notes}
    manifest["signature"] = base64.b64encode(key.sign(canonical_manifest(manifest))).decode("ascii")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("update.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.write(artifact, name)
    print(output)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-key")
    stamp = sub.add_parser("stamp-app")
    stamp.add_argument("app")
    pack = sub.add_parser("package")
    pack.add_argument("--artifact", required=True)
    pack.add_argument("--target", required=True)
    pack.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "init-key":
        init_key()
    elif args.command == "stamp-app":
        stamp_app(args.app)
    else:
        package(args.artifact, args.target, args.output)


if __name__ == "__main__":
    main()
