"""Package the generated Soovee artwork into macOS and Windows icon containers."""
from pathlib import Path
import struct

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

ROOT = Path(__file__).resolve().parents[1]
source = QImage(str(ROOT / 'src/soovee_commander/assets/soovee-commander-icon.png'))
if source.isNull():
    raise RuntimeError('The Soovee Commander artwork is missing.')


def png(size):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).save(buffer, 'PNG'):
        raise RuntimeError('Could not encode the icon.')
    return bytes(data)


chunks = []
for kind, size in [('icp4', 16), ('icp5', 32), ('icp6', 64), ('ic07', 128), ('ic08', 256), ('ic09', 512), ('ic10', 1024), ('ic11', 32), ('ic12', 64), ('ic13', 256), ('ic14', 512)]:
    data = png(size)
    chunks.append(kind.encode('ascii') + struct.pack('>I', len(data) + 8) + data)
body = b''.join(chunks)
(ROOT / 'packaging/SooveeCommander.icns').write_bytes(b'icns' + struct.pack('>I', len(body) + 8) + body)
images = [(size, png(size)) for size in [16, 32, 48, 64, 128, 256]]
entries, payload, offset = [], [], 6 + 16 * len(images)
for size, data in images:
    entries.append(struct.pack('<BBBBHHII', size if size < 256 else 0, size if size < 256 else 0, 0, 0, 1, 32, len(data), offset))
    payload.append(data)
    offset += len(data)
(ROOT / 'packaging/SooveeCommander.ico').write_bytes(struct.pack('<HHH', 0, 1, len(images)) + b''.join(entries) + b''.join(payload))
print('Created Soovee Commander macOS and Windows icons.')
