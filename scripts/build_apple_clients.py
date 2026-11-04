"""Build native iPhone/Apple TV test apps with a pinned Python support package.

Simulator builds use an ad-hoc signature. Device distribution requires the
owner's Apple signing identity and provisioning profile; this script does not
pretend an unsigned device archive is installable.
"""
import argparse
from pathlib import Path
import plistlib
import shutil
import subprocess
import os
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    subprocess.run([str(value) for value in command], check=True, **kwargs)


def build(platform, runtimes, output, profile=None, identity=None):
    device = platform == 'ios-device'
    family = 'iOS' if platform in ('ios','ios-device') else 'tvOS'
    sdk = 'iphoneos' if device else 'iphonesimulator' if platform == 'ios' else 'appletvsimulator'
    slice_name = 'ios-arm64' if device else 'ios-arm64_x86_64-simulator' if platform == 'ios' else 'tvos-arm64_x86_64-simulator'
    version=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    if device and (not profile or not identity): raise SystemExit('A development profile and signing identity are required for a real iPhone.')
    framework = runtimes / family / 'Python.xcframework'
    if not framework.is_dir():
        raise SystemExit(f'Extract the official Python-3.14-{family}-support.b14.tar.gz into {framework.parent}')
    app = output / (f'{family}-device' if device else f'{family}-simulator') / 'SooveeCommander.app'
    if app.exists(): shutil.rmtree(app)
    app.mkdir(parents=True)
    (app / 'Frameworks').mkdir()
    shutil.copytree(framework / slice_name / 'Python.framework', app / 'Frameworks/Python.framework')
    modules = app / 'app'; modules.mkdir()
    ignore = shutil.ignore_patterns('__pycache__', '*.pyc')
    package = modules / 'soovee_commander'; package.mkdir()
    for name in ('__init__', 'lan', 'lan_protocol', 'lan_files', 'lan_store', 'device_files',
                 'providers', 'nativefs', 'operations', 'transfer_status', 'diagnostic_log', 'hkdf', 'openssl_psk', 'discovery'):
        shutil.copyfile(ROOT / f'src/soovee_commander/{name}.py', package / f'{name}.py')
    shutil.copytree(ROOT / 'mobile/shared/python', modules, dirs_exist_ok=True, ignore=ignore)
    import qrcode
    shutil.copytree(Path(qrcode.__file__).parent, modules / 'qrcode', ignore=ignore)
    shutil.copyfile(ROOT / 'mobile/shared/locales/cs.json', app / 'cs.json')
    shutil.copytree(ROOT / 'mobile/shared/licenses', app / 'licenses')
    bundle_id = 'cz.soovee.commander.ios' if family=='iOS' else 'cz.soovee.commander.tvos'
    info = dict(CFBundleIdentifier=bundle_id, CFBundleName='Soovee Commander', CFBundleDisplayName='Soovee Commander',
                CFBundleExecutable='SooveeCommander', CFBundlePackageType='APPL', CFBundleVersion=str(int(''.join(version.split('.')))),
                CFBundleShortVersionString=version, MinimumOSVersion='17.0', CFBundleAllowMixedLocalizations=True, CFBundleLocalizations=['en', 'cs'],
                CFBundleSupportedPlatforms=['iPhoneOS' if device else 'iPhoneSimulator' if platform == 'ios' else 'AppleTVSimulator'],
                UIDeviceFamily=[1, 2] if family=='iOS' else [3],
                UIUserInterfaceStyle='Dark', UILaunchScreen={},
                UIApplicationSceneManifest={'UIApplicationSupportsMultipleScenes':False},
                NSLocalNetworkUsageDescription='Connect paired Soovee devices and transfer files on your local network.')
    info['NSBonjourServices']=['_soovee._tcp']
    if family == 'iOS':
        info.update(UIFileSharingEnabled=True, LSSupportsOpeningDocumentsInPlace=True,
                    NSCameraUsageDescription='Scan the pairing QR shown by your Soovee TV or computer.',
                    UISupportedInterfaceOrientations=['UIInterfaceOrientationPortrait','UIInterfaceOrientationLandscapeLeft','UIInterfaceOrientationLandscapeRight'],
                    **{'UISupportedInterfaceOrientations~ipad':['UIInterfaceOrientationPortrait','UIInterfaceOrientationPortraitUpsideDown','UIInterfaceOrientationLandscapeLeft','UIInterfaceOrientationLandscapeRight']})
        from PIL import Image
        artwork=Image.open(ROOT/'src/soovee_commander/assets/soovee-commander-icon.png').convert('RGB')
        for size in (120,180,152,167):artwork.resize((size,size),Image.Resampling.LANCZOS).save(app/f'Icon{size}.png')
        info['CFBundleIcons']={'CFBundlePrimaryIcon':{'CFBundleIconFiles':['Icon120','Icon180']}}
        info['CFBundleIcons~ipad']={'CFBundlePrimaryIcon':{'CFBundleIconFiles':['Icon152','Icon167']}}
    with (app / 'Info.plist').open('wb') as stream: plistlib.dump(info, stream)
    run(['xcrun', '--sdk', sdk, 'clang', '-arch', 'arm64', '-fobjc-arc', '-fmodules',
         '-miphoneos-version-min=17.0' if device else '-mios-simulator-version-min=17.0' if platform == 'ios' else '-mtvos-simulator-version-min=17.0',
         '-framework', 'UIKit', '-framework', 'Foundation', '-framework', 'CoreImage',
         *(['-framework', 'UniformTypeIdentifiers','-framework','AVFoundation','-framework','QuickLookThumbnailing','-framework','QuickLook'] if family=='iOS' else []),
         '-F', framework / slice_name, '-framework', 'Python',
         '-Wl,-rpath,@executable_path/Frameworks', '-Wl,-export_dynamic',
         ROOT / 'mobile/apple/Soovee.m', '-o', app / 'SooveeCommander'])
    environment = dict(os.environ, PROJECT_DIR=str(framework.parent), CODESIGNING_FOLDER_PATH=str(app),
                       EFFECTIVE_PLATFORM_NAME='-' + sdk, PLATFORM_FAMILY_NAME=family, ARCHS='arm64',
                       PRODUCT_BUNDLE_IDENTIFIER=bundle_id, EXPANDED_CODE_SIGN_IDENTITY=identity if device else '-',
                       EXPANDED_CODE_SIGN_IDENTITY_NAME=identity if device else 'ad-hoc')
    # Use the support package's maintained extension-framework installer.
    run(['bash', '-e', '-c', 'source "$PROJECT_DIR/Python.xcframework/build/utils.sh"; install_python Python.xcframework app'], env=environment)
    # macOS --deep does not reliably discover every nested iOS framework.
    # Sign and verify the runtime explicitly, including Python.framework itself.
    for nested in sorted((app/'Frameworks').glob('*.framework')):
        run(['codesign','--force','--sign',identity if device else '-','--timestamp=none',nested])
        run(['codesign','--verify','--strict',nested])
    signing=[]
    if device:
        decoded=plistlib.loads(subprocess.check_output(['security','cms','-D','-i',str(profile)]))
        entitlements=decoded['Entitlements']
        if not entitlements['application-identifier'].endswith('.'+bundle_id):raise SystemExit('The profile belongs to a different application.')
        shutil.copyfile(profile,app/'embedded.mobileprovision')
        entitlement_file=app.parent/'entitlements.plist';entitlement_file.write_bytes(plistlib.dumps(entitlements))
        signing=['--entitlements',entitlement_file]
    run(['codesign', '--force', '--sign', identity if device else '-', '--timestamp=none',*signing,app])
    run(['codesign', '--verify', '--deep', '--strict', app])
    archive = output / f'SooveeCommander-{version}-{family}-{"device" if device else "simulator"}.zip'
    run(['ditto', '-c', '-k', '--keepParent', '--norsrc', app, archive])
    print(archive, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', choices=['ios', 'ios-device', 'tvos', 'all'], default='all')
    parser.add_argument('--provisioning-profile',type=Path)
    parser.add_argument('--signing-identity')
    parser.add_argument('--runtime-directory', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/apple')
    args = parser.parse_args()
    for platform in ('ios', 'tvos') if args.platform == 'all' else (args.platform,):
        build(platform, args.runtime_directory.resolve(), args.output.resolve(),args.provisioning_profile,args.signing_identity)


if __name__ == '__main__': main()
