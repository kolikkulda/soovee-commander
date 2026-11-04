"""Version, application license, bundled third-party notices and safe diagnostics."""
import json
from pathlib import Path
import platform
import ssl
import sys

from PySide6.QtCore import Qt, QUrl, qVersion
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QListWidget,
                              QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget, QMessageBox)

from . import __version__
from .i18n import current_language, tr

ROOT = Path(__file__).parent


def diagnostics():
    try:
        from libarchive.ffi import version_number
        archive_version = version_number()
    except (ImportError, OSError):
        archive_version = 'unavailable'
    import zlib
    return dict(application='Soovee Commander', version=__version__, platform=platform.platform(),
                architecture=platform.machine(), python=platform.python_version(), qt=qVersion(),
                openssl=ssl.OPENSSL_VERSION, tls_psk=bool(getattr(ssl, 'HAS_PSK', False)),
                libarchive=archive_version, zlib=zlib.ZLIB_RUNTIME_VERSION,
                transfer_protocol=1, language=current_language(), build='packaged' if getattr(sys, 'frozen', False) else 'source')


class AboutDialog(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.setWindowTitle(tr('About Soovee Commander'))
        self.resize(760, 580)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(QPixmap(str(ROOT / 'assets/soovee-commander-icon.png')).scaled(92, 92, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        header.addWidget(icon)
        title = QLabel('Soovee Commander\n' + tr('Version {v0}').format(v0=__version__))
        title.setObjectName('dialogHeading')
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header.addWidget(title, 1)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        description = QLabel(tr('A two-pane file manager for files, archives, servers and Soovee device transfers.'))
        description.setWordWrap(True)
        overview_layout.addWidget(description)
        license_data = json.loads((ROOT / 'licenses/application.json').read_text(encoding='utf-8'))
        self.application_license = QLabel(tr(license_data['status']))
        self.application_license.setWordWrap(True)
        self.application_license.setTextFormat(Qt.TextFormat.PlainText)
        overview_layout.addWidget(QLabel(tr('Application license')))
        overview_layout.addWidget(self.application_license)
        if license_data.get('owner'):
            owner = QLabel(license_data['owner'])
            owner.setTextFormat(Qt.TextFormat.PlainText)
            overview_layout.addWidget(owner)
        overview_layout.addWidget(QLabel(tr('Third-party components retain their own licenses. Full notices are available offline in the Components tab.')))
        if license_data.get('file'):
            license_text = QPlainTextEdit((ROOT / 'licenses' / license_data['file']).read_text(encoding='utf-8'))
            license_text.setReadOnly(True)
            overview_layout.addWidget(license_text, 1)
        overview_layout.addStretch()
        qt_button = QPushButton(tr('About Qt…'))
        qt_button.clicked.connect(lambda: QMessageBox.aboutQt(self, tr('About Qt')))
        overview_layout.addWidget(qt_button)
        self.tabs.addTab(overview, tr('About'))
        components_page = QWidget()
        components_layout = QHBoxLayout(components_page)
        self.components = json.loads((ROOT / 'licenses/components.json').read_text(encoding='utf-8'))
        self.component_list = QListWidget()
        self.component_list.addItems([component['name'] for component in self.components])
        self.component_list.setMaximumWidth(220)
        components_layout.addWidget(self.component_list)
        right = QVBoxLayout()
        self.notice = QPlainTextEdit()
        self.notice.setReadOnly(True)
        right.addWidget(self.notice, 1)
        homepage = QPushButton(tr('Component website'))
        homepage.clicked.connect(self.open_component)
        right.addWidget(homepage)
        components_layout.addLayout(right, 1)
        self.component_list.currentRowChanged.connect(self.show_component)
        self.component_list.setCurrentRow(0)
        self.tabs.addTab(components_page, tr('Components and licenses'))
        archives_page = QWidget()
        archives_layout = QVBoxLayout(archives_page)
        archive_description = QLabel(tr('Archive browsing, extraction and compression use the following open-source libraries. Select a library to read its complete license offline.'))
        archive_description.setWordWrap(True)
        archives_layout.addWidget(archive_description)
        for description, component in [
            ('ZIP: read, extract, create and update · Python zipfile + zlib', 'Python'),
            ('TAR / TAR.GZ / TAR.BZ2 / TAR.XZ: read, extract and create · Python tarfile', 'Python'),
            ('ZIP Deflate / GZIP compression · zlib', 'zlib'),
            ('BZIP2 compression · libbz2', 'bzip2 / libbz2'),
            ('XZ / LZMA compression · liblzma', 'XZ Utils / liblzma'),
            ('RAR: read and extract · 7z: read, extract and create · libarchive', 'libarchive (native backend)'),
            ('Python interface to libarchive · libarchive-c', 'libarchive-c'),
        ]:
            button = QPushButton(tr(description))
            button.clicked.connect(lambda checked=False, name=component: self.open_license(name))
            archives_layout.addWidget(button)
        note = QLabel(tr('RAR creation is not offered by this application. No WinRAR application is bundled. Encryption and split-volume support depend on the format and backend.'))
        note.setWordWrap(True)
        archives_layout.addWidget(note)
        archives_layout.addStretch()
        self.tabs.addTab(archives_page, tr('Archives'))
        diagnostic_page = QWidget()
        diagnostic_layout = QVBoxLayout(diagnostic_page)
        self.system_info = QPlainTextEdit(json.dumps(diagnostics(), indent=2))
        self.system_info.setReadOnly(True)
        diagnostic_layout.addWidget(self.system_info)
        copy = QPushButton(tr('Copy diagnostics'))
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.system_info.toPlainText()))
        diagnostic_layout.addWidget(copy)
        self.tabs.addTab(diagnostic_page, tr('Diagnostics'))
        close = QPushButton(tr('Close'))
        close.clicked.connect(self.accept)
        layout.addWidget(close)

    def open_license(self, name):
        for row, component in enumerate(self.components):
            if component['name'] == name:
                self.component_list.setCurrentRow(row)
                self.tabs.setCurrentIndex(1)
                return

    def show_component(self, row):
        if not 0 <= row < len(self.components):
            return
        component = self.components[row]
        sections = [f"{component['name']} {component['version']}\n{component['license']}\n{component['url']}"]
        for filename in component['files']:
            sections.append(filename + '\n\n' + (ROOT / 'licenses' / filename).read_text(encoding='utf-8', errors='replace'))
        self.notice.setPlainText('\n\n'.join(sections))

    def open_component(self):
        row = self.component_list.currentRow()
        if 0 <= row < len(self.components):
            url = QUrl(self.components[row]['url'])
            if url.scheme() == 'https':
                QDesktopServices.openUrl(url)
