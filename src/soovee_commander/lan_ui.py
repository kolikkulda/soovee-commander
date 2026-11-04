"""Desktop device pairing and explicit receive approvals for Soovee Transfers."""
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event, Lock, Thread
import time
import socket
import ipaddress

from PySide6.QtCore import QObject, Qt, QTimer, Signal, QStandardPaths, QSignalBlocker, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtNetwork import QNetworkInterface
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                              QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                              QPlainTextEdit, QProgressBar, QPushButton, QStackedWidget, QTabWidget, QVBoxLayout, QWidget, QGroupBox)
import qrcode

from .filemodel import size_text
from .i18n import tr
from .lan import TransferService
from .lan_protocol import TransferError, key_fingerprint, parse_invitation
from .providers import LocalProvider
from .discovery import Discovery, verify_endpoint
from . import dialog_kit


def qr_image(text):
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    code.add_data(text)
    code.make(fit=True)
    matrix = code.get_matrix()
    scale = max(3, 280 // len(matrix))
    image = QImage(len(matrix) * scale, len(matrix) * scale, QImage.Format.Format_RGB32)
    image.fill(QColor('white'))
    painter = QPainter(image)
    for row, values in enumerate(matrix):
        for column, dark in enumerate(values):
            if dark:
                painter.fillRect(column * scale, row * scale, scale, scale, QColor('black'))
    painter.end()
    return image


def read_qr(filename):
    import zxingcpp
    from PIL import Image
    path = Path(filename)
    if path.stat().st_size > 20 * 1024 * 1024:
        raise TransferError('Choose a QR image smaller than 20 MB.')
    with Image.open(path) as image:
        if image.width * image.height > 16 * 1024 * 1024:
            raise TransferError('The QR image dimensions are too large.')
        values = zxingcpp.read_barcodes(image)
    invitations = []
    for value in values:
        try:
            parse_invitation(value.text)
            invitations.append(value.text)
        except (ValueError, TransferError):
            pass
    if len(invitations) != 1:
        raise TransferError('The image must contain exactly one Soovee pairing QR code.')
    return invitations[0]


@dataclass(eq=False)
class Approval:
    kind: str
    peer: object
    manifest: dict | None = None
    cancel: Event = field(default_factory=Event)
    done: Event = field(default_factory=Event)
    value: object = None
    lock: Lock = field(default_factory=Lock)

    def resolve(self, value):
        with self.lock:
            if not self.done.is_set():
                self.value = value
                self.done.set()


class Bridge(QObject):
    requested = Signal(object)
    activity = Signal(object)
    discovered = Signal(object)
    discovery_ready = Signal(object)
    discovery_failed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.stopping = Event()
        self.pending = set()
        self.lock = Lock()

    def ask(self, kind, peer, manifest=None, cancel=None):
        request = Approval(kind, peer, manifest, cancel if cancel is not None else Event())
        with self.lock:
            self.pending.add(request)
        self.requested.emit(request)
        deadline = time.monotonic() + 120
        try:
            while not request.done.wait(.1):
                if self.stopping.is_set() or request.cancel.is_set() or time.monotonic() > deadline:
                    request.resolve(None)
            return request.value
        finally:
            with self.lock:
                self.pending.discard(request)

    def stop(self):
        self.stopping.set()
        with self.lock:
            requests = list(self.pending)
        for request in requests:
            request.resolve(None)


def placeholder(widget, text):
    """Explain an empty list instead of showing a blank box; the row cannot be selected."""
    item = QListWidgetItem(text)
    item.setFlags(Qt.ItemFlag.NoItemFlags)
    widget.addItem(item)


def muted(text):
    label = QLabel(text)
    label.setObjectName('muted')
    label.setWordWrap(True)
    return label


class SectionView(QWidget):
    """Left list of sections and the selected page, with the tab API the dialog uses."""

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.list = QListWidget()
        self.list.setObjectName('settingsCategories')
        self.list.setFixedWidth(210)
        self.list.setSpacing(2)
        self.stack = QStackedWidget()
        layout.addWidget(self.list)
        layout.addWidget(self.stack, 1)
        self.list.currentRowChanged.connect(self.stack.setCurrentIndex)

    def addTab(self, widget, title):
        self.stack.addWidget(widget)
        self.list.addItem(title)
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        return self.stack.count() - 1

    def setCurrentIndex(self, index):
        self.list.setCurrentRow(index)

    def currentIndex(self):
        return self.stack.currentIndex()

    def tabText(self, index):
        return self.list.item(index).text()

    def count(self):
        return self.stack.count()


class DevicesDialog(QDialog):
    def __init__(self, host, state_directory=None, device_kind="desktop"):
        super().__init__(host)
        self.host = host
        self.device_kind = device_kind
        self.state_directory = state_directory or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)) / 'StereoCommander' / 'transfers'
        self.service = None
        self.discovery = None
        self.found_devices = {}
        self.bridge = None
        self.approvals = set()
        self.receive_cancels = {}
        self._auto_started = False
        self.setWindowTitle(tr('Soovee Transfers · Devices'))
        self.resize(980, 740)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        # Header: what this is, whether it is running, and the one switch.
        header = QHBoxLayout()
        header.setSpacing(14)
        badge = QLabel()
        badge.setObjectName('dialogIcon')
        badge.setFixedSize(42, 42)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        from .toolbar_icons import toolbar_icon
        from .themes import THEMES
        badge.setPixmap(toolbar_icon('devices', THEMES[getattr(host, 'theme_key', 'soovee')]['accent']).pixmap(QSize(30, 30)))
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        heading = QLabel(tr('Soovee Transfers'))
        heading.setObjectName('dialogHeading')
        texts.addWidget(heading)
        self.status = QLabel()
        self.status.setObjectName('dialogSubtitle')
        self.status.setWordWrap(True)
        texts.addWidget(self.status)
        header.addLayout(texts, 1)
        self.enable = QPushButton(tr('Enable local transfers'))
        self.enable.setObjectName('primary')
        self.enable.clicked.connect(self.start)
        self.stop_button = QPushButton(tr('Stop local transfers'))
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(lambda: self.shutdown(remember=True))
        header.addWidget(self.enable, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.stop_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        # Connection settings ------------------------------------------------
        self.name = QLineEdit(str(host.settings.value('lan_name', socket.gethostname()[:80])))
        self.address = QComboBox()
        addresses = set()
        for address in QNetworkInterface.allAddresses():
            try:
                parsed = ipaddress.ip_address(address.toString())
                if parsed.version == 4 and parsed.is_private and not (parsed.is_loopback or parsed.is_unspecified or parsed.is_multicast):
                    addresses.add(str(parsed))
            except ValueError:
                pass
        addresses = sorted(addresses, key=lambda value: (ipaddress.ip_address(value).is_link_local, value))
        self.address.addItems(addresses + ['127.0.0.1'])
        self.address.currentTextChanged.connect(lambda _: self.update_invitation())
        self.destination = QLineEdit(str(host.settings.value('lan_destination', str(Path.home() / 'Downloads' if (Path.home() / 'Downloads').is_dir() else Path.home()))))
        self.destination.setProperty('userContent', True)
        choose = QPushButton(tr('Browse…'))
        choose.clicked.connect(self.choose_destination)
        destination_row = QHBoxLayout()
        destination_row.addWidget(self.destination)
        destination_row.addWidget(choose)
        self.role = QComboBox()
        self.role.setProperty('translatedItems', True)
        self.role.setEnabled(False)
        for label, value in [('Both devices can control', 'both'), ('Controlled device (TV default)', 'controlled'), ('Controller only', 'controller')]:
            self.role.addItem(tr(label), value)
        self.role.setCurrentIndex(1 if device_kind == 'tv' else 0)
        self.role.currentIndexChanged.connect(self.change_role)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow(tr('Device name'), self.name)
        form.addRow(tr('Device role'), self.role)
        form.addRow(tr('Local address for pairing'), self.address)
        form.addRow(tr('Receive into'), destination_row)
        self.connection_settings = QGroupBox(tr('Connection settings'))
        self.connection_settings.setObjectName('toolCard')
        self.connection_settings.setLayout(form)
        self.renew = QPushButton(tr('Generate pairing code'))
        self.renew.setEnabled(True)
        self.renew.clicked.connect(self.new_code)

        self.tabs = SectionView()
        root.addWidget(self.tabs, 1)

        # 1 · Nearby devices ---------------------------------------------------
        nearby_page = QWidget()
        nearby_layout = QVBoxLayout(nearby_page)
        nearby_layout.setContentsMargins(0, 0, 0, 0)
        nearby_layout.addWidget(muted(tr('Choose a device and click Ask for a code: it shows a code that you type here. A paired device opens as a disk.')))
        self.discovery_status = QLabel(tr('Looking for Soovee devices on your network…')); self.discovery_status.setWordWrap(True)
        nearby_layout.addWidget(self.discovery_status)
        self.nearby = QListWidget(); self.nearby.currentItemChanged.connect(self.select_nearby)
        self.nearby.itemDoubleClicked.connect(lambda *args: self.connect_nearby())
        nearby_layout.addWidget(self.nearby, 1)
        self.remote_host = QLineEdit()
        self.remote_host.setPlaceholderText(tr('Other device IP address'))
        self.remote_port = QLineEdit()
        self.remote_port.setPlaceholderText(tr('Port'))
        self.remote_port.setMaximumWidth(85)
        self.remote_code = QLineEdit()
        self.remote_code.setPlaceholderText(tr('Eight-digit code'))
        self.remote_code.textChanged.connect(self.update_pair_button)
        self.remote_code.setMaximumWidth(160)
        join = QHBoxLayout()
        join.addWidget(QLabel(tr('Code shown on the other device:')))
        join.addWidget(self.remote_code)
        self.pair_button = QPushButton(tr('Pair device'))
        self.pair_button.setObjectName('primary')
        self.pair_button.clicked.connect(self.connect_nearby)
        self.pair_button.setEnabled(False)
        join.addWidget(self.pair_button)
        join.addStretch()
        nearby_layout.addLayout(join)
        manual = QGroupBox(tr('Connect by address')); manual.setObjectName('toolCard'); manual_layout = QHBoxLayout(manual)
        manual_layout.addWidget(self.remote_host, 1); manual_layout.addWidget(self.remote_port)
        manual.hide()
        other = QHBoxLayout()
        manual_button = QPushButton(tr('Connect by address…')); manual_button.setCheckable(True)
        manual_button.toggled.connect(manual.setVisible)
        def manual_mode(checked):
            if checked:
                self.nearby.setCurrentRow(-1); self.remote_code.setEnabled(True); self.pair_button.setText(tr('Pair device'))
        manual_button.toggled.connect(manual_mode)
        own_code = QPushButton(tr('Show my pairing code…'))
        own_code.clicked.connect(lambda: self.show_pairing_code())
        other.addWidget(own_code)
        paste = QPushButton(tr('Paste pairing invitation'))
        paste.clicked.connect(lambda: self.use_invitation(QApplication.clipboard().text()))
        load = QPushButton(tr('Read QR image…'))
        load.clicked.connect(self.load_qr)
        for button in (manual_button, paste, load):
            other.addWidget(button)
        other.addStretch()
        nearby_layout.addLayout(other)
        nearby_layout.addWidget(manual)
        self.tabs.addTab(nearby_page, tr('Nearby devices'))

        # 2 · Paired devices ---------------------------------------------------
        devices_page = QWidget()
        devices_layout = QVBoxLayout(devices_page)
        devices_layout.setContentsMargins(0, 0, 0, 0)
        devices_layout.addWidget(muted(tr('Paired devices · Open a device or share folders with it')))
        self.devices = QListWidget()
        self.devices.itemDoubleClicked.connect(self.open_selected_device)
        devices_layout.addWidget(self.devices, 1)
        actions = QHBoxLayout()
        open_device = self.open_device_button = QPushButton(tr('Open device as a disk'))
        open_device.setObjectName('primary')
        open_device.clicked.connect(self.open_selected_device)
        send = QPushButton(tr('Send with confirmation…'))
        send.clicked.connect(self.send_selection)
        endpoint = QPushButton(tr('Update device address…'))
        endpoint.clicked.connect(self.update_address)
        remove = QPushButton(tr('Remove pairing'))
        remove.clicked.connect(self.remove_pairing)
        for button in (open_device, send, endpoint):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(remove)
        devices_layout.addLayout(actions)
        self.tabs.addTab(devices_page, tr('Paired devices'))

        # 3 · Shared folders ---------------------------------------------------
        shares_page = QWidget()
        shares_layout = QVBoxLayout(shares_page)
        shares_layout.setContentsMargins(0, 0, 0, 0)
        shares_layout.addWidget(muted(tr('Pairing does not share your disk. Add folders for the selected paired device.')))
        self.share_peer = QComboBox()
        self.share_peer.currentIndexChanged.connect(self.refresh_shares)
        peer_row = QFormLayout()
        peer_row.addRow(tr('Device:'), self.share_peer)
        shares_layout.addLayout(peer_row)
        self.shared_folders = QListWidget()
        shares_layout.addWidget(self.shared_folders, 1)
        self.share_write = QCheckBox(tr('Allow copying files into the next shared folder'))
        shares_layout.addWidget(self.share_write)
        share_buttons = QHBoxLayout()
        add_share = QPushButton(tr('Share folder…'))
        add_share.setObjectName('primary')
        add_share.clicked.connect(self.add_share)
        remove_share = QPushButton(tr('Stop sharing this folder'))
        remove_share.clicked.connect(self.remove_share)
        share_buttons.addWidget(add_share)
        share_buttons.addStretch()
        share_buttons.addWidget(remove_share)
        shares_layout.addLayout(share_buttons)
        self.tabs.addTab(shares_page, tr('Shared folders'))

        # Pairing code window: appears when another device asks, or on demand.
        self.pairing_window = dialog_kit.StandardDialog(self, tr('Pairing code'), tr('Pairing code of this computer'),
                                                        icon="devices", close_only=True, width=620)
        self.pairing_window.setModal(False)
        pair_layout = self.pairing_window.body
        pairing = QHBoxLayout()
        pairing.setSpacing(20)
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setMinimumSize(248, 248)
        self.qr.setStyleSheet('background: white; border: 8px solid white; border-radius: 8px;')
        pairing.addWidget(self.qr, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.addWidget(muted(tr('Pairing code')))
        self.code = QLabel(tr('Transfers are disabled'))
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.code.setStyleSheet('font-size: 36px; font-weight: 700; font-family: Menlo, Consolas, monospace;')
        self.code.setTextFormat(Qt.TextFormat.PlainText)
        text.addWidget(self.code)
        self.expiry = QLabel()
        self.expiry.setWordWrap(True)
        self.expiry.setObjectName('muted')
        text.addWidget(self.expiry)
        copy_code = QPushButton(tr('Copy code'))
        copy_code.clicked.connect(lambda: QApplication.clipboard().setText(self.service.pairing['code']) if self.service and self.service.pairing else None)
        copy_link = QPushButton(tr('Copy pairing invitation'))
        copy_link.clicked.connect(self.copy_invitation)
        save_qr = QPushButton(tr('Save pairing QR…'))
        save_qr.clicked.connect(self.save_qr)
        for button in (copy_code, self.renew, copy_link, save_qr):
            button.setMaximumWidth(300)
            text.addWidget(button)
        text.addStretch()
        pairing.addLayout(text, 1)
        pair_layout.addLayout(pairing, 1)
        self.pending_shares = {}

        # 5 · Connection settings -----------------------------------------------
        settings_page = QWidget()
        settings_layout = QVBoxLayout(settings_page)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.addWidget(self.connection_settings)
        settings_layout.addWidget(muted(tr('The device name is shown to other devices. A controlled device (such as a TV) can be browsed but does not browse others. Received files are placed in a new Soovee-… folder inside Receive into.')))
        settings_layout.addStretch()
        self.tabs.addTab(settings_page, tr('Connection settings'))

        # Activity ---------------------------------------------------------------
        activity = QGroupBox(tr('Activity'))
        activity.setObjectName('toolCard')
        activity_layout = QVBoxLayout(activity)
        self.receiving = QLabel(tr('No incoming transfer'))
        self.receiving.setWordWrap(True)
        activity_layout.addWidget(self.receiving)
        self.receive_progress = QProgressBar()
        self.receive_progress.setRange(0, 1000)
        self.receive_progress.setValue(0)
        self.receive_progress.setTextVisible(False)
        self.receive_progress.setFixedHeight(10)
        activity_layout.addWidget(self.receive_progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(90)
        self.log.setMaximumBlockCount(10000)
        activity_layout.addWidget(self.log)
        root.addWidget(activity)
        footer = QHBoxLayout()
        footer.addStretch()
        close = QPushButton(tr('Close'))
        close.clicked.connect(self.close)
        footer.addWidget(close)
        root.addLayout(footer)
        self.refresh_devices()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_expiry)
        self.timer.start()

    def share_after_pairing(self, identity):
        """Apply the folder chosen in the pairing approval, so the device sees files at once."""
        choice = self.pending_shares.pop(identity, None)
        if choice is None or self.service is None:
            return
        path, writable = choice
        base = Path(path).name or 'Shared'
        for number in range(1, 20):
            try:
                self.service.shares.add(path, base if number == 1 else f'{base} {number}', identity, writable)
                self.append_log(tr('Shared folder {v0} with the new device.').format(v0=path))
                break
            except TransferError as exc:
                if 'already has this name' not in str(exc):
                    self.append_log(tr('Incomplete: {v0}').format(v0=tr(str(exc))))
                    break
            except OSError as exc:
                self.append_log(tr('Incomplete: {v0}').format(v0=str(exc)))
                break
        self.refresh_shares()

    def update_status(self):
        if self.service is None:
            self.status.setText(tr('Off · Other devices cannot find or pair with this computer.'))
        else:
            self.status.setText(tr('On · Visible as “{v0}” at {v1}:{v2} · Paired devices: {v3}').format(
                v0=self.service.store.name, v1=self.address.currentText(), v2=self.service.port, v3=len(self.service.store.peers())))
        self.enable.setVisible(self.service is None)
        self.stop_button.setVisible(self.service is not None)

    def found(self, devices):
        if self.service is None: return
        self.found_devices = {value['id']:value for value in devices}
        current = self.nearby.currentItem()
        identity = current.data(Qt.ItemDataRole.UserRole) if current else None
        paired = {peer.id for peer in self.service.store.peers()}
        with QSignalBlocker(self.nearby):
            self.nearby.clear()
            for device in devices:
                status = tr('Paired · ready to open') if device['id'] in paired else tr('Click Ask for a code')
                kind = tr({'tv':'TV', 'phone':'Phone', 'desktop':'Computer'}[device['kind']])
                item = QListWidgetItem(device['name'] + '\n' + kind + ' · ' + status)
                item.setData(Qt.ItemDataRole.UserRole, device['id']); item.setSizeHint(QSize(0, 66))
                self.nearby.addItem(item)
                if device['id'] == identity: self.nearby.setCurrentItem(item)
        self.discovery_status.setText(tr('Choose a device. No IP address is needed.') if devices else tr('No Soovee devices found yet. Keep the app open on the other device, or use a QR invitation.'))
        if self.nearby.currentItem() is None and devices and not self.remote_host.text(): self.nearby.setCurrentRow(0)

    def select_nearby(self, item, previous=None):
        if item is None or self.service is None: return
        device = self.found_devices.get(item.data(Qt.ItemDataRole.UserRole))
        if device is None: return
        self.remote_host.setText(device['host']); self.remote_port.setText(str(device['port']))
        paired = device['id'] in {peer.id for peer in self.service.store.peers()}
        self.remote_code.clear(); self.remote_code.setEnabled(not paired)
        self.update_pair_button()
        if not paired: self.remote_code.setFocus()

    def update_pair_button(self, *args):
        item = self.nearby.currentItem()
        identity = item.data(Qt.ItemDataRole.UserRole) if item else None
        paired = self.service is not None and identity in {peer.id for peer in self.service.store.peers()}
        if paired:
            self.pair_button.setText(tr('Open device as a disk'))
        elif identity and not self.remote_code.text().strip():
            self.pair_button.setText(tr('Ask for a code'))  # The other device shows its code.
        else:
            self.pair_button.setText(tr('Pair device'))

    def request_code(self, name):
        service = self.service
        host, port = self.remote_host.text().strip(), int(self.remote_port.text())
        self.pair_button.setEnabled(False)
        def done(_):
            self.pair_button.setEnabled(self.service is not None)
            self.discovery_status.setText(tr('{v0} now shows a pairing code. Type it here and click Pair device.').format(v0=name))
            self.remote_code.setFocus()
        def failed(message):
            self.pair_button.setEnabled(self.service is not None)
            self.discovery_status.setText(tr('{v0} did not answer. Keep Soovee open there, or enter the code it shows.').format(v0=name))
            self.append_log(tr('Incomplete: {v0}').format(v0=tr(message)))
        self.host.run_task(lambda _: service.request_pairing(host, port), done, failed)

    def show_pairing_code(self, name=None):
        """Show this computer's QR and code; with name, because that device asked for it."""
        if self.service is None:
            self.start()
            if self.service is None:
                return
        session = self.service.pairing
        if session is None or session['expires'] <= time.monotonic() or session['attempts'] >= 5:
            self.service.begin_pairing()
        self.update_invitation()
        window = self.pairing_window
        window.heading.setText(tr('{v0} wants to pair').format(v0=name) if name else tr('Pairing code of this computer'))
        window.subtitle.setText(tr('Type this code on {v0}, or scan the QR in Soovee there. Then confirm the same verification on both devices.').format(v0=name)
                                if name else tr('On the phone or TV, open Soovee, choose this computer or Scan pairing QR, and scan this code or type it.'))
        window.subtitle.setVisible(True)
        window.show(); window.raise_(); window.activateWindow()
        QApplication.alert(window)

    def connect_nearby(self):
        item = self.nearby.currentItem()
        identity = item.data(Qt.ItemDataRole.UserRole) if item else None
        if self.service is not None and identity in {peer.id for peer in self.service.store.peers()}:
            for row in range(self.devices.count()):
                if self.devices.item(row).data(Qt.ItemDataRole.UserRole) == identity:
                    self.devices.setCurrentRow(row); self.open_selected_device(); return
        if identity and not self.remote_code.text().strip() and self.service is not None:
            return self.request_code(self.found_devices.get(identity, {}).get('name', ''))
        self._auto_open_after_pair = True
        self.pair_device()

    def start_discovery(self):
        service, bridge = self.service, self.bridge
        addresses = [self.address.itemText(row) for row in range(self.address.count()) if self.address.itemText(row) != '127.0.0.1']
        if not addresses: return
        def ready(discovery):
            if discovery is None: return
            if self.service is not service:
                Thread(target=discovery.close, daemon=True).start(); return
            self.discovery = discovery
        def failed(message):
            if self.service is not service: return
            self.discovery_status.setText(tr('Automatic discovery is unavailable. Use a QR invitation or connect by address.'))
            self.append_log(message)
        bridge.discovery_ready.connect(ready); bridge.discovery_failed.connect(failed)
        def build():
            try:
                discovery = Discovery(service, addresses, bridge.discovered.emit, self.device_kind)
                if bridge.stopping.is_set(): discovery.close(); return
                try: bridge.discovery_ready.emit(discovery)
                except RuntimeError: discovery.close()
            except Exception as exc:
                if not bridge.stopping.is_set():
                    try: bridge.discovery_failed.emit(str(exc))
                    except RuntimeError: pass
        Thread(target=build,daemon=True,name='Soovee discovery startup').start()

    def choose_destination(self):
        path = QFileDialog.getExistingDirectory(self, tr('Receive into'), self.destination.text())
        if path:
            self.destination.setText(path)
            self.host.settings.setValue('lan_destination', path)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._auto_started:
            QTimer.singleShot(0, self, self.auto_start)

    def auto_start(self):
        if self.isVisible() and not self._auto_started:
            self._auto_started = True
            self.start()

    def start(self):
        if self.service is not None:
            return
        try:
            if not Path(self.destination.text()).is_dir():
                raise TransferError('Choose an existing receiving folder.')
            self.bridge = Bridge(self)
            self.bridge.requested.connect(self.approve)
            self.bridge.activity.connect(self.activity)
            self.bridge.discovered.connect(self.found)
            bridge = self.bridge
            service = TransferService(self.state_directory, self.name.text(),
                                      approve_pair=lambda peer: bool(bridge.ask('pair', peer)),
                                      approve_offer=lambda peer, manifest, cancel: bridge.ask('offer', peer, manifest, cancel),
                                      event=bridge.activity.emit, device_kind=self.device_kind)
            try:
                service.start('0.0.0.0', int(self.host.settings.value('lan_port', 0)))
            except OSError:
                service.start('0.0.0.0', 0)
            self.service = service
            from PySide6.QtCore import QSignalBlocker
            with QSignalBlocker(self.role):
                self.role.setCurrentIndex(self.role.findData(service.shares.mode))
            self.open_device_button.setEnabled(service.shares.mode != "controlled")
            self.role.setEnabled(True)
            self.host.settings.setValue('lan_port', service.port)
            self.host.settings.setValue('lan_enabled', True)
            self.host.settings.setValue('lan_name', service.store.name)
            self.host.settings.setValue('lan_destination', self.destination.text())
            self.enable.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.renew.setEnabled(True)
            self.pair_button.setEnabled(True)
            self.name.setEnabled(False)
            self.refresh_devices()
            self.new_code()
            self.start_discovery()
            self.append_log(tr('Local transfers enabled on port {v0}.').format(v0=service.port))
            self.update_status()
        except Exception as exc:
            self.host.error(tr(str(exc)))

    def change_role(self, *args):
        if self.service is not None:
            self.service.shares.set_mode(self.role.currentData())
            self.open_device_button.setEnabled(self.service.shares.mode != 'controlled')
            self.refresh_shares()

    def open_selected_device(self, *args):
        peer = self.selected_peer()
        if peer is None:
            return self.host.error(tr('Select a paired device.'))
        if self.service.shares.mode == 'controlled':
            return self.host.error(tr('Change the device role to browse another device.'))
        from .device_files import DeviceProvider
        service = self.service
        def mount(_=None):
            if self.service is not service: return
            self.host.other().new_tab(DeviceProvider(service, peer.id), '/')
            self.hide()
        found = self.found_devices.get(peer.id)
        if found is not None and (found['host'], found['port']) != (peer.host, peer.port):
            self.host.run_task(lambda _: verify_endpoint(service, peer.id, found['host'], found['port']), mount)
        else: mount()

    def refresh_shares(self, *args):
        self.shared_folders.clear()
        if self.service is not None:
            for value in self.service.shares.value['shares']:
                if self.share_peer.currentData() not in value['peers']:
                    continue
                label = tr('Read and copy in') if value['writable'] else tr('Read only')
                item = QListWidgetItem(f"{value['name']} · {label} · {value['path']}")
                item.setData(Qt.ItemDataRole.UserRole, value['id'])
                self.shared_folders.addItem(item)
        if not self.shared_folders.count():
            placeholder(self.shared_folders, tr('Turn on transfers first.') if self.service is None else
                        tr('Pair a device first.') if not self.share_peer.count() else
                        tr('Nothing is shared with this device yet. Choose Share folder…'))

    def add_share(self):
        identity = self.share_peer.currentData()
        if self.service is None or not identity:
            return self.host.error(tr('Select a paired device first on the Paired devices tab.'))
        peer = self.service.store.get(identity)
        path = QFileDialog.getExistingDirectory(self, tr('Share folder…'))
        if not path:
            return
        name = dialog_kit.ask_text(self, tr('Shared folder name'), tr('Share “{v0}”').format(v0=Path(path).name or path),
                                   tr('Name shown on {v0}:').format(v0=peer.name), Path(path).name or 'Files',
                                   subtitle=path, action=tr('Share folder'), icon="mkdir")
        if name is not None:
            try:
                self.service.shares.add(path, name, peer.id, self.share_write.isChecked())
                self.refresh_shares()
            except (TransferError, OSError) as exc:
                self.host.error(tr(str(exc)))

    def remove_share(self):
        item = self.shared_folders.currentItem()
        if item is not None and item.data(Qt.ItemDataRole.UserRole) and self.service is not None:
            self.service.shares.remove(item.data(Qt.ItemDataRole.UserRole))
            self.refresh_shares()

    def new_code(self):
        if self.service is None:
            self.start()
        else:
            self.service.begin_pairing()
            self.update_invitation()

    def update_invitation(self):
        if self.service is None:
            return
        try:
            link = self.service.pairing_link(self.address.currentText())
            number = self.service.pairing['code']
            self.code.setText(number[:4] + ' ' + number[4:])
            self.qr.setPixmap(QPixmap.fromImage(qr_image(link)).scaled(220, 220, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
            self.update_expiry()
        except TransferError:
            self.qr.clear()
            self.code.setText(tr('Generate a new pairing code'))

    def update_expiry(self):
        if self.service is None:
            return
        session = self.service.pairing
        if session is None or session['expires'] <= time.monotonic() or session['attempts'] >= 5:
            self.qr.clear()
            self.code.setText(tr('Generate a new pairing code'))
            self.expiry.setText(tr('Codes expire after five minutes or five attempts.'))
        else:
            self.expiry.setText(tr('Address: {v0}:{v1} · Code valid for {v2}s').format(v0=self.address.currentText(), v1=self.service.port, v2=int(session['expires'] - time.monotonic())))

    def copy_invitation(self):
        try:
            if self.service is None:
                raise TransferError('Enable Soovee Transfers first.')
            QApplication.clipboard().setText(self.service.pairing_link(self.address.currentText()))
        except TransferError as exc:
            self.host.error(tr(str(exc)))

    def save_qr(self):
        try:
            if self.service is None:
                raise TransferError('Enable Soovee Transfers first.')
            image = qr_image(self.service.pairing_link(self.address.currentText()))
            filename, _ = QFileDialog.getSaveFileName(self, tr('Save pairing QR…'), 'soovee-pairing.png', 'PNG (*.png)')
            if filename and not image.save(filename):
                raise TransferError('The QR image could not be saved.')
        except TransferError as exc:
            self.host.error(tr(str(exc)))

    def use_invitation(self, text):
        try:
            host, port, code = parse_invitation(text)
            self.nearby.setCurrentRow(-1); self.remote_code.setEnabled(True)
            self.pair_button.setText(tr('Pair device')); self.tabs.setCurrentIndex(0)
            self.remote_host.setText(host)
            self.remote_port.setText(str(port))
            self.remote_code.setText(code)
        except (TransferError, ValueError) as exc:
            self.host.error(tr(str(exc)))

    def load_qr(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Read QR image…'), '', 'Images (*.png *.jpg *.jpeg *.webp)')
        if path:
            self.host.run_task(lambda _: read_qr(path), self.use_invitation, read_only=True)

    def pair_device(self):
        if self.service is None:
            return
        try:
            port = int(self.remote_port.text())
            if not 1 <= port <= 65535:
                raise ValueError()
        except ValueError:
            return self.host.error(tr('Port must be between 1 and 65535.'))
        service, bridge = self.service, self.bridge
        host, code = self.remote_host.text().strip(), self.remote_code.text().strip()
        self.pair_button.setEnabled(False)
        def done(peer):
            self.remote_code.clear()
            self.pair_button.setEnabled(self.service is not None)
            self.refresh_devices()
            if getattr(self, '_auto_open_after_pair', False):
                self._auto_open_after_pair = False
                for row in range(self.devices.count()):
                    if self.devices.item(row).data(Qt.ItemDataRole.UserRole) == peer.id:
                        self.devices.setCurrentRow(row); self.open_selected_device(); break
        def failed(message):
            self.pair_button.setEnabled(self.service is not None)
            self.host.error(message)
        self.host.run_task(lambda _: service.pair(host, port, code, approve=lambda peer: bool(bridge.ask('pair', peer))), done, failed)

    def approve(self, request):
        if request.done.is_set() or self.service is None or self.bridge.stopping.is_set():
            request.resolve(None)
            return
        if request.kind == 'pair':
            box = dialog_kit.StandardDialog(self, tr('Confirm device pairing'), tr('Pair with {v0}?').format(v0=request.peer.name),
                                            tr('Address: {v0}').format(v0=request.peer.host), icon="devices", action=tr('Pair device'))
            box.note(tr('Check that the other device shows the same verification code:'))
            code = QLabel(key_fingerprint(request.peer.secret))
            code.setStyleSheet('font-size: 22px; font-weight: 700; font-family: Menlo, Consolas, monospace;')
            code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.add(code)
            share = QCheckBox(tr('Share a folder with this device'))
            share.setChecked(True)
            folder = QLineEdit(self.destination.text())
            folder.setProperty('userContent', True)
            browse = QPushButton(tr('Browse…'))
            browse.clicked.connect(lambda: folder.setText(QFileDialog.getExistingDirectory(box, tr('Share folder…'), folder.text()) or folder.text()))
            writable = QCheckBox(tr('Allow copying files into this folder'))
            writable.setChecked(True)
            row = QHBoxLayout(); row.addWidget(folder, 1); row.addWidget(browse)
            box.add(share); box.body.addLayout(row); box.add(writable)
            share.toggled.connect(folder.setEnabled); share.toggled.connect(browse.setEnabled); share.toggled.connect(writable.setEnabled)
            box.share_choice = (request.peer.id, share, folder, writable)
            box.note(tr('Nothing else on this computer is shared. You can change shared folders later in Shared folders.'))
            destination = True
        else:
            import hashlib
            from .lan_protocol import canonical
            identity = hashlib.sha256(canonical(request.manifest)).hexdigest()
            destination = Path(self.destination.text())
            self.receive_cancels[identity] = request.cancel
            self.host.cancel_events.add(request.cancel)
            self.host.cancel_button.setEnabled(True)
            items = request.manifest['items']
            box = dialog_kit.StandardDialog(self, tr('Accept incoming files'),
                                            tr('Receive files from {v0}?').format(v0=request.peer.name),
                                            tr('{v0} items · {v1}').format(v0=len(items), v1=size_text(sum(item['size'] for item in items))),
                                            icon="extract", action=tr('Receive'))
            box.add(dialog_kit.item_list((item['path'] for item in items), total=len(items)))
            box.note(tr('Saved to: {v0}').format(v0=str(destination / ('Soovee-' + identity[:12]))))
        box.cancel.setText(tr('Decline'))
        box.ok.setAutoDefault(False)
        box.cancel.setDefault(True)  # Incoming requests are never accepted by a stray Enter.
        self.approvals.add((box, request))
        def finished(_):
            self.approvals.discard((box, request))
            choice = getattr(box, 'share_choice', None)
            if choice and box.result() == QDialog.DialogCode.Accepted and choice[1].isChecked() and choice[2].text().strip():
                self.pending_shares[choice[0]] = (choice[2].text().strip(), choice[3].isChecked())
            request.resolve(destination if box.result() == QDialog.DialogCode.Accepted else None)
            box.deleteLater()
        box.finished.connect(finished)
        timer = QTimer(box)
        timer.setInterval(250)
        timer.timeout.connect(lambda: box.reject() if request.done.is_set() or request.cancel.is_set() else None)
        timer.start()
        box.open()

    def refresh_devices(self):
        self.devices.clear()
        identity = self.share_peer.currentData()
        self.share_peer.clear()
        if self.service is not None:
            for peer in self.service.store.peers():
                self.share_peer.addItem(peer.name, peer.id)
                item = QListWidgetItem(f'{peer.name}   ·   {peer.host}:{peer.port}')
                item.setData(Qt.ItemDataRole.UserRole, peer.id)
                self.devices.addItem(item)
            if self.devices.count():
                self.devices.setCurrentRow(0)
        if not self.devices.count():
            placeholder(self.devices, tr('Turn on transfers first.') if self.service is None else
                        tr('No paired devices yet. Choose a device in Nearby devices and click Ask for a code.'))
            index = self.share_peer.findData(identity)
            if index >= 0:
                self.share_peer.setCurrentIndex(index)
        self.refresh_shares()
        if self.found_devices: self.found(list(self.found_devices.values()))
        if hasattr(self, 'status'):
            self.update_status()

    def selected_peer(self):
        item = self.devices.currentItem()
        identity = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return self.service.store.get(identity) if identity and self.service is not None else None

    def send_selection(self):
        peer = self.selected_peer()
        if peer is None:
            return self.host.error(tr('Select a paired device.'))
        panel = self.host.active
        if not isinstance(panel.provider, LocalProvider):
            return self.host.error(tr('Copy files from archives or servers to disk before sending.'))
        paths = [panel.provider.join(panel.path, entry.name) for entry in panel.action_entries()]
        if not paths:
            return self.host.error(tr('Choose at least one file or folder.'))
        service = self.service
        self.host.enqueue(tr('Send to {v0}').format(v0=peer.name), lambda cancel, report: service.send(peer.id, paths, cancel, report),
                          on_done=lambda result: self.append_log(tr('Received bundle: {v0}').format(v0=result)))

    def update_address(self):
        peer = self.selected_peer()
        if peer is None:
            return
        value = dialog_kit.ask_text(self, tr('Update device address…'), tr('Address of {v0}').format(v0=peer.name),
                                    tr('Local IPv4 address:port'), f'{peer.host}:{peer.port}', action=tr('Save'), icon="devices",
                                    subtitle=tr('Needed only when the device changed its address and was not found automatically.'))
        if value is not None:
            try:
                host, port = value.strip().rsplit(':', 1)
                self.service.store.add(replace(peer, host=host, port=int(port)))
                self.refresh_devices()
            except (TransferError, ValueError) as exc:
                self.host.error(tr(str(exc)))

    def remove_pairing(self):
        peer = self.selected_peer()
        if peer is not None and dialog_kit.confirm(self, tr('Remove pairing'), tr('Remove {v0} and stop its active connections?').format(v0=peer.name),
                                                   f'{peer.host}:{peer.port}', action=tr('Remove pairing'), destructive=True, icon="devices",
                                                   note=tr('Files on both devices stay. To connect again, pair the devices with a new code.')):
            self.service.remove_peer(peer.id)
            self.refresh_devices()

    def append_log(self, message):
        line = time.strftime('%H:%M:%S') + '  ' + message
        self.log.appendPlainText(line)
        self.host.log.appendPlainText(line)

    def activity(self, event):
        kind = event['kind']
        if kind in ('completed', 'declined', 'interrupted'):
            cancel = self.receive_cancels.pop(event['transfer'], None)
            if cancel is not None:
                self.host.cancel_events.discard(cancel)
                self.host.cancel_button.setEnabled(bool(self.host.cancel_events))
        if kind == 'progress':
            self.receiving.setText(tr('Receiving {v0}: {v1} / {v2}').format(v0=event['path'], v1=size_text(event['done']), v2=size_text(event['total'])))
            self.receive_progress.setValue(int(1000 * event['done'] / event['total']) if event['total'] else 0)
        elif kind == 'pair-request':
            self.append_log(tr('{v0} asked for a pairing code.').format(v0=event['name']))
            self.show_pairing_code(event['name'])
        elif kind == 'paired':
            self.pairing_window.hide()
            self.share_after_pairing(event['device'])
            self.tabs.setCurrentIndex(1)
            self.refresh_devices()
            self.update_invitation()
            self.append_log(tr('Paired device: {v0}').format(v0=event['name']))
        elif kind == 'file':
            self.append_log(tr('Receiving file: {v0} · {v1}').format(v0=event['path'], v1=size_text(event['size'])))
        elif kind == 'completed':
            self.receive_progress.setValue(1000)
            self.receiving.setText(tr('Received bundle: {v0}').format(v0=event['destination']))
            self.append_log(tr('Received bundle: {v0}').format(v0=event['destination']))
            self.host.left.refresh()
            self.host.right.refresh()
        elif kind == 'error':
            self.append_log(tr('Incomplete: {v0}').format(v0=tr(event['message'])))
        elif kind in ('declined', 'interrupted', 'verifying'):
            message = tr({'declined': 'Transfer declined', 'interrupted': 'Transfer interrupted; partial data kept', 'verifying': 'Verifying received files…'}[kind])
            self.receiving.setText(message)
            self.append_log(message)
        if not self.host.pending_jobs and kind in ('progress', 'completed', 'interrupted', 'verifying'):
            self.host.progress.setRange(0, 1000)
            self.host.progress.setValue(self.receive_progress.value())
            self.host.queue_label.setText(self.receiving.text())

    def shutdown(self, *, remember=False):
        if remember:
            self.host.settings.setValue('lan_enabled', False)
        if self.discovery is not None:
            discovery, self.discovery = self.discovery, None
            Thread(target=discovery.close, daemon=True, name='Soovee discovery shutdown').start()
        self.found_devices.clear(); self.nearby.clear()
        for cancel in self.receive_cancels.values():
            cancel.set()
            self.host.cancel_events.discard(cancel)
        self.receive_cancels.clear()
        self.host.cancel_button.setEnabled(bool(self.host.cancel_events))
        if self.bridge is not None:
            self.bridge.stop()
        for box, request in list(self.approvals):
            request.resolve(None)
            box.reject()
        if self.service is not None:
            self.service.stop()
            self.service = None
        self.qr.clear()
        self.code.setText(tr('Transfers are disabled'))
        self.expiry.clear()
        self.enable.setEnabled(True)
        self.name.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.renew.setEnabled(True)
        self.pair_button.setEnabled(False)
        self.role.setEnabled(False)
        self.open_device_button.setEnabled(False)
        self.refresh_devices()
        self.update_status()

    def closeEvent(self, event):
        self.hide()
        event.accept()
