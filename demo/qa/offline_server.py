"""Start the real launcher with outbound non-loopback sockets denied.

Used with Playwright's external-request block. Does not change host networking.
"""
import ipaddress
import runpy
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex
original_sendto = socket.socket.sendto


def check(address):
    if not isinstance(address, tuple):
        return
    host = address[0]
    if host == 'localhost':
        return
    try:
        allowed = ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise OSError('QA offline: external network blocked')


def connect(sock, address):
    check(address)
    return original_connect(sock, address)


def connect_ex(sock, address):
    check(address)
    return original_connect_ex(sock, address)


def sendto(sock, data, *args):
    check(args[-1])
    return original_sendto(sock, data, *args)


socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
socket.socket.sendto = sendto
sys.path.insert(0, str(ROOT))
sys.argv = [str(ROOT / 'run.py'), '--no-browser']
runpy.run_path(str(ROOT / 'run.py'), run_name='__main__')
