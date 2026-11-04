"""Freeze the installed runtime dependency inventory and upstream license texts for About."""
from importlib.metadata import distribution
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import sys
import sysconfig
import tomllib
import zlib

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'src/soovee_commander/licenses'
TARGET.mkdir(exist_ok=True)
project = tomllib.loads((ROOT / 'pyproject.toml').read_text())
pending = [Requirement(value).name for value in project['project']['dependencies']]
seen, records = set(), []
while pending:
    name = pending.pop()
    normalized = re.sub('[-_.]+', '-', name).lower()
    if normalized in seen:
        continue
    seen.add(normalized)
    installed = distribution(name)
    metadata = installed.metadata
    for value in metadata.get_all('Requires-Dist') or []:
        dependency = Requirement(value)
        if dependency.marker is None or dependency.marker.evaluate({'extra': ''}):
            pending.append(dependency.name)
    files = []
    for item in installed.files or []:
        lowered = str(item).lower()
        if '.dist-info/' not in lowered or not any(token in item.name.lower() for token in ('license', 'copying', 'notice')):
            continue
        source = installed.locate_file(item)
        if not source.is_file() or source.stat().st_size > 500000:
            continue
        filename = normalized + '-' + re.sub('[^a-zA-Z0-9._-]', '_', item.name) + '.txt'
        # Read before replacing the existing notice. Cloud-backed filesystems
        # may time out in fcopyfile and leave a truncated destination behind.
        text = source.read_bytes()
        if not text.strip():
            raise RuntimeError('Empty third-party notice: ' + str(source))
        temporary = TARGET / (filename + '.tmp')
        temporary.write_bytes(text)
        temporary.replace(TARGET / filename)
        files.append(filename)
    if normalized in ('pyside6-essentials', 'pyside6-pdf', 'shiboken6'):
        files.extend(['LGPL-3.0-only.txt', 'GPL-3.0-only.txt', 'GPL-2.0-only.txt'])
    urls = metadata.get_all('Project-URL') or []
    url = next((value.split(',', 1)[1].strip() for value in urls if ',' in value and value.lower().startswith(('source', 'homepage', 'home', 'repository'))), metadata.get('Home-Page', ''))
    records.append(dict(name=metadata['Name'], version=metadata['Version'], license=metadata.get('License-Expression') or metadata.get('License') or 'See upstream notices', url=url, files=sorted(set(files))))
stdlib = Path(sysconfig.get_paths()['stdlib'])
python_license = next((path for path in [stdlib / 'LICENSE.txt', stdlib.parent / 'LICENSE.txt', Path(sys.base_prefix) / 'LICENSE.txt', Path(sys.base_prefix) / 'LICENSE'] if path.is_file()), None)
if python_license is None:
    raise RuntimeError('The Python runtime license is missing.')
shutil.copyfile(python_license, TARGET / 'Python-LICENSE.txt')
records.extend([
    dict(name='Python', version=sys.version.split()[0], license='PSF License and included notices', url='https://www.python.org/', files=['Python-LICENSE.txt']),
    dict(name='OpenSSL (TLS runtime)', version=ssl.OPENSSL_VERSION, license='Apache-2.0', url='https://www.openssl.org/', files=['OpenSSL-LICENSE.txt']),
    dict(name='libarchive (native backend)', version='Platform library; see runtime diagnostics', license='BSD-style; see individual notices', url='https://www.libarchive.org/', files=['libarchive-COPYING.txt']),
    dict(name='zlib', version=zlib.ZLIB_RUNTIME_VERSION, license='Zlib', url='https://zlib.net/', files=['zlib-LICENSE.txt']),
    dict(name='bzip2 / libbz2', version='Runtime library', license='bzip2-1.0.6 (BSD-style)', url='https://sourceware.org/bzip2/', files=['bzip2-LICENSE.txt']),
    dict(name='PDFium (inside Qt PDF)', version='Bundled with PySide6-Pdf', license='BSD-3-Clause; bundled third-party notices see Qt PDF attributions',
         url='https://doc.qt.io/qt-6/licenses-used-in-qt.html', files=['PDFium-LICENSE.txt']),
    dict(name='XZ Utils / liblzma', version='Runtime library', license='0BSD / public domain for older versions; see notices', url='https://tukaani.org/xz/', files=['xz-COPYING.txt', 'xz-0BSD.txt']),
])
if sys.platform == 'win32':
    native = Path(os.environ['LIBARCHIVE']).parent.parent / 'share'
    if not native.is_dir():
        raise RuntimeError('Native dependency notices are missing. Use archive.dll from a vcpkg installation.')
    notices = []
    for package in sorted(native.iterdir()):
        source = package / 'copyright'
        if source.is_file():
            data = source.read_bytes()
            if not data.strip():
                raise RuntimeError('Empty native dependency notice: ' + str(source))
            filename = 'windows-native-' + package.name + '-COPYRIGHT.txt'
            (TARGET / filename).write_bytes(data)
            notices.append(filename)
    if not notices:
        raise RuntimeError('No native Windows dependency notices were found.')
    records.append(dict(name='Windows native dependency notices (vcpkg)',
                        version='See included package notices', license='Per-package licenses; see notices',
                        url='https://github.com/microsoft/vcpkg', files=notices))
for record in records:
    for filename in record['files']:
        if not (TARGET / filename).is_file() or not (TARGET / filename).stat().st_size:
            raise RuntimeError('Missing third-party notice: ' + filename)
(TARGET / 'components.json').write_text(json.dumps(sorted(records, key=lambda record: record['name'].lower()), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Collected licenses for', len(records), 'runtime components.')
