"""Sign Android releases locally with a stable key; never upload the private key."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('apk', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--android-sdk', type=Path, default=Path(os.environ.get('ANDROID_HOME', Path.home() / 'Library/Android/sdk')))
    parser.add_argument('--java-home', type=Path, default=Path(os.environ.get('JAVA_HOME', '/Applications/Android Studio.app/Contents/jbr/Contents/Home')))
    args = parser.parse_args()
    private = ROOT / '.release'; private.mkdir(mode=0o700, exist_ok=True)
    key, password = private / 'android-signing.p12', private / 'android-signing-password.txt'
    if not key.exists():
        if password.exists():
            raise SystemExit('Signing key missing. Restore it from backup; do not silently change application identity.')
        descriptor = os.open(password, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream: stream.write(secrets.token_urlsafe(40))
        subprocess.run([str(args.java_home / 'bin/keytool'), '-genkeypair', '-keystore', str(key), '-storetype', 'PKCS12',
                        '-storepass:file', str(password), '-keyalg', 'RSA', '-keysize', '3072', '-validity', '10000',
                        '-alias', 'soovee-commander', '-dname', 'CN=Soovee Commander,O=Soovee'], check=True)
        key.chmod(0o600)
    if not password.is_file(): raise SystemExit('The Android signing password file is missing.')
    tools = sorted((args.android_sdk / 'build-tools').glob('*/apksigner'), key=lambda p: tuple(int(s) for s in p.parent.name.split('.') if s.isdigit()))
    if not tools: raise SystemExit('Android SDK build-tools with apksigner are required.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, JAVA_HOME=str(args.java_home))
    subprocess.run([str(tools[-1]), 'sign', '--ks', str(key), '--ks-pass', 'file:' + str(password),
                    '--ks-key-alias', 'soovee-commander', '--v4-signing-enabled', 'false',
                    '--out', str(args.output), str(args.apk)], env=environment, check=True)
    subprocess.run([str(tools[-1]), 'verify', '--verbose', '--print-certs', str(args.output)], env=environment, check=True)
    print(args.output)


if __name__ == '__main__': main()
