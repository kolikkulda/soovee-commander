"""Bonjour/mDNS hints. Discovery never grants access or distributes pairing keys."""
from dataclasses import replace
import ipaddress
import socket
from threading import RLock

from .lan_protocol import TransferError, local_address, send_message, receive_message
from .lan_store import valid_id, valid_name

SERVICE_TYPE = '_soovee._tcp.local.'


def validate_device(identity, name, host, port, kind='desktop'):
    valid_id(identity); name = valid_name(name)
    host = local_address(host)
    if ipaddress.ip_address(host).version != 4 or type(port) is not int or not 1 <= port <= 65535:
        raise TransferError('Invalid discovered device endpoint.')
    return dict(id=identity, name=name, host=host, port=port, kind=kind if kind in ('tv', 'phone', 'desktop') else 'desktop')


def verify_endpoint(service, identity, host, port):
    """Persist a discovery address only after authentication with the saved PSK."""
    peer = service.store.get(identity)
    validate_device(identity, peer.name, host, port)
    with service.files_connection(identity, endpoint=(host, port)) as secure:
        send_message(secure, dict(action='roots'))
        response = receive_message(secure)
        if not isinstance(response.get('roots'), list):
            raise TransferError('Invalid shared-folder list.')
    service.store.add(replace(peer, host=host, port=port))


class Discovery:
    def __init__(self, service, addresses, changed, kind='desktop'):
        from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser, IPVersion
        self.identity, self.changed, self.lock = service.store.id, changed, RLock()
        self.devices, self.names = {}, {}
        self.closed = False
        addresses = [value for value in addresses if ipaddress.ip_address(value).version == 4]
        self.zeroconf = Zeroconf(interfaces=addresses or None, ip_version=IPVersion.V4Only) if addresses else Zeroconf(ip_version=IPVersion.V4Only)
        self.info = ServiceInfo(SERVICE_TYPE, 'soovee-' + self.identity + '.' + SERVICE_TYPE,
            addresses=[socket.inet_aton(value) for value in addresses], port=service.port,
            server='soovee-' + self.identity + '.local.',
            properties={'id':self.identity, 'name':service.store.name.encode('utf-8')[:240].decode('utf-8',errors='ignore'), 'kind':kind, 'v':'1'})
        self.browser = None
        try:
            self.zeroconf.register_service(self.info, allow_name_change=True)
            self.browser = ServiceBrowser(self.zeroconf, SERVICE_TYPE, listener=self)
        except BaseException:
            self.zeroconf.close(); raise

    def snapshot(self):
        with self.lock: return sorted((dict(value) for value in self.devices.values()), key=lambda item:item['name'].casefold())

    def add_service(self, zeroconf, type_, name): self.update_service(zeroconf, type_, name)

    def update_service(self, zeroconf, type_, name):
        if self.closed: return
        info = zeroconf.get_service_info(type_, name, timeout=1200)
        if info is None: return
        try:
            properties = info.properties
            identity = properties.get(b'id', b'').decode('ascii')
            if identity == self.identity or properties.get(b'v') != b'1': return
            addresses = info.parsed_addresses()
            device = next((validate_device(identity, properties.get(b'name', b'').decode('utf-8'), host,
                           info.port, properties.get(b'kind', b'desktop').decode('ascii')) for host in addresses if ':' not in host), None)
            if device is None: return
        except (ValueError, UnicodeError, TransferError): return
        with self.lock:
            if self.closed or len(self.devices) >= 256 and identity not in self.devices: return
            self.devices[identity] = device; self.names[name] = identity
        self.notify()

    def remove_service(self, zeroconf, type_, name):
        with self.lock:
            identity = self.names.pop(name, None)
            if identity is not None: self.devices.pop(identity, None)
        self.notify()

    def notify(self):
        if not self.closed:
            try: self.changed(self.snapshot())
            except RuntimeError: pass  # The owning GUI can finish closing first.

    def close(self):
        self.closed = True
        if self.browser is not None: self.browser.cancel()
        self.zeroconf.unregister_service(self.info)
        self.zeroconf.close()
