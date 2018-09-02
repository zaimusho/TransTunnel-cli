import select
import socket
import pytun
import errno
import time
#  import base64

from htun.tools import dump, add_route, is_running, print_stats
from htun.args import args


class TunnelServer(object):
    def __init__(self, sock, addr, dstaddr, create_socket=None):
        self._tun = pytun.TunTapDevice(
            name="htun",
            flags=pytun.IFF_TUN | pytun.IFF_NO_PI
        )
        self._tun.addr = addr
        self._tun.dstaddr = dstaddr
        self._tun.netmask = args.tmask
        self._tun.mtu = args.tmtu
        self._tun.up()
        if args.rsubnet:
            add_route(args.rsubnet, args.saddr, self._tun.name)
        self._sock = sock
        self._create_socket = create_socket
        self.r = [self._tun, self._sock]
        self.w = []
        self.to_tun = self.to_sock = b''

    def reconnect(self):
        if self._create_socket:
            self._sock.close()
            self._sock = self._create_socket()
            self.r = [self._tun, self._sock]
            self.w = []
            self.to_tun = self.to_sock = b''

    def exchange_messages(self):
        self.r, self.w, _ = select.select(self.r, self.w, [])

        if self._tun in self.r:
            data = self._tun.read(self._tun.mtu)
            self.to_sock += data
            dump("from_sock <<<", data)
        if self._sock in self.r:
            data = self._sock.recv(65535)
            if data:
                self.to_tun += data
                dump("from_sock <<<", data)
            else:
                print("Connection closed")
                return False

        if self._tun in self.w and self.to_tun:
            try:
                write_len = self._tun.write(self.to_tun)
                self.count_in += write_len
                dump("to_tun <<<", self.to_tun[:write_len])
                self.to_tun = self.to_tun[write_len:]
            except OSError as e:
                if e.errno == errno.EINVAL:
                    # this is a transmission error. just drop it
                    dump("Illegal argument", self.to_tun)
                    self.to_tun = b''
                    self.count_err += 1
                else:
                    raise e
        if self._sock in self.w and self.to_sock:
            sent_len = self._sock.send(self.to_sock)
            self.count_out += sent_len
            dump("to_sock >>>", self.to_sock)
            self.to_sock = self.to_sock[sent_len:]

        self.r = [self._tun, self._sock]
        self.w = []
        # only put in the object we really want to write to, or
        # else we cause high CPU load
        if self.to_tun:
            self.w.append(self._tun)
        if self.to_sock:
            self.w.append(self._sock)
        return True

    def run(self):
        self.count_in = self.count_out = self.count_err = 0
        while is_running():
            try:
                if not self.exchange_messages():
                    self.reconnect()
                else:
                    print_stats(self.count_in, self.count_out, self.count_err)
            except (select.error, socket.error, pytun.Error) as e:
                #  if e.errno == errno.EINTR:
                #      continue
                #  if args.debug:
                print(str(e))
                time.sleep(1)
                #  stop_running()
        self._sock.close()