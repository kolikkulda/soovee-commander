"""Real loopback mDNS, authenticated address changes and storage metadata."""
import json
from pathlib import Path
import socket
from threading import Event
import time

import pytest

from soovee_commander.discovery import Discovery, validate_device, verify_endpoint
from soovee_commander.lan import TransferService
from soovee_commander.device_files import DeviceProvider
from soovee_commander.lan_protocol import TransferError


def test_invalid_discovery_data_cannot_become_a_device():
    for host, port, name in [('8.8.8.8',12000,'TV'),('127.0.0.1',True,'TV'),('192.168.1.2',0,'TV'),('192.168.1.2',80,'TV\nforged')]:
        with pytest.raises((TransferError,ValueError)):
            validate_device('a'*32,name,host,port)


def test_real_mdns_does_not_publish_a_code_or_secret(tmp_path):
    a,b=TransferService(tmp_path/'a','Test desktop'),TransferService(tmp_path/'b','Test TV')
    a.start();b.start();code=b.begin_pairing()
    discoveries=[];found=[]
    try:
        first=Discovery(a,['127.0.0.1'],lambda values:found.append(values));discoveries.append(first)
        second=Discovery(b,['127.0.0.1'],lambda values:None,'tv');discoveries.append(second)
        deadline=time.monotonic()+8
        while not any(value['id']==b.store.id for value in first.snapshot()) and time.monotonic()<deadline:time.sleep(.03)
        devices=first.snapshot();device=next(value for value in devices if value['id']==b.store.id)
        assert device['name']=='Test TV' and device['port']==b.port and device['kind']=='tv'
        advertised=repr(second.info.properties)
        assert code not in advertised and 'secret' not in advertised and 'code' not in advertised
        assert set(second.info.properties)=={b'id',b'name',b'kind',b'v'}
    finally:
        for discovery in discoveries:discovery.close()
        a.stop();b.stop()


def test_capacity_and_authenticated_endpoint_update(tmp_path):
    root=tmp_path/'shared';root.mkdir()
    a=TransferService(tmp_path/'a','Controller')
    b=TransferService(tmp_path/'b','TV',approve_pair=lambda peer:True)
    a.start();b.start()
    try:
        peer=a.pair('127.0.0.1',b.port,b.begin_pairing(),approve=lambda peer:True)
        b.shares.add(root,'Internal storage',a.store.id,writable=True)
        provider=DeviceProvider(a,peer.id)
        value=provider.space('/')
        assert 0<value['total'] and 0<=value['available']<=value['free']<=value['total']
        assert value['path']==str(root) and not value['readonly']
        b.stop();b.start('127.0.0.1',0)
        verify_endpoint(a,peer.id,'127.0.0.1',b.port)
        assert a.store.get(peer.id).port==b.port
        assert provider.space('/Internal storage')['total']==value['total']
        before=a.store.get(peer.id)
        with socket.socket() as unavailable:
            unavailable.bind(('127.0.0.1',0));port=unavailable.getsockname()[1]
            with pytest.raises(OSError):verify_endpoint(a,peer.id,'127.0.0.1',port)
        assert a.store.get(peer.id)==before
    finally:a.stop();b.stop()
