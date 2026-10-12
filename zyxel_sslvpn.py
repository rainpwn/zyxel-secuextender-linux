#!/usr/bin/env python3
"""zyxel_sslvpn.py - SSL VPN client for Zyxel ZLD firewalls (USG FLEX, ATP, VPN series),
speaking the same protocol as Zyxel SecuExtender 4.x.

  sudo ./zyxel_sslvpn.py vpn.example.com 443 user --pin <certificate sha256>

The protocol is documented in PROTOCOL.md.
"""
import argparse, getpass, hashlib, os, re, select, shutil, signal, socket, ssl, struct, subprocess, sys, threading, fcntl
from urllib.parse import quote

__version__ = "0.1.0"

PROXY_PORT = 10444      # hard-coded in SecuExtender (SetConnCTX)
MTU = 1370              # MTU of the SecuExtender TAP adapter
IFF_TUN, IFF_NO_PI, TUNSETIFF = 0x0001, 0x1000, 0x400454CA


def tls_connect(a):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # firewalls ship self-signed certificates: checked against --pin below
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2  # same as the Windows client
    s = ctx.wrap_socket(socket.create_connection((a.host, a.port), timeout=30), server_hostname=a.host)
    fp = hashlib.sha256(s.getpeercert(binary_form=True)).hexdigest()
    if not a.insecure and fp != a.pin.replace(":", "").lower():
        sys.exit(f"Unexpected certificate, sha256={fp}\n(if this is your firewall, run again with --pin {fp})")
    return s


def recv_until(s, marker, limit=65536):
    buf = b""
    while marker not in buf:
        d = s.recv(4096)
        if not d or len(buf) > limit:
            raise ConnectionError(f"connection closed before {marker!r}: {buf[:300]!r}")
        buf += d
    return buf


def login(a, password):
    body = f"username={quote(a.user, safe='')}&pwd={quote(password, safe='')}&password={quote(password, safe='')}&loginTosslvpn=true"
    hp = f"{a.host}:{a.port}"
    req = (f"POST / HTTP/1.1\r\nHost: {hp}\r\nReferer: https://{hp}\r\n"
           f"Content-Type: application/x-www-form-urlencoded\r\nConnection: Keep-Alive\r\n"
           f"Content-Length: {len(body)}\r\n\r\n{body}")
    with tls_connect(a) as s:
        s.sendall(req.encode())
        resp = recv_until(s, b"\r\n\r\n").decode("latin1")
    m = re.search(r"Set-Cookie: authtok=([^;\r\n]*);", resp, re.I)
    if not m:
        sys.exit("Login failed, no authtok cookie. Response headers:\n" + resp.split("\r\n\r\n")[0])
    return m.group(1)


def logout(a, tok):
    hp = f"{a.host}:{a.port}"
    body = "perform=logout"
    req = (f"POST /setuser.cgi HTTP/1.1\r\nHost: {hp}\r\nReferer: https://{hp}\r\nCookie: authtok={tok};\r\n"
           f"Content-Type: application/x-www-form-urlencoded\r\nConnection: Keep-Alive\r\n"
           f"Content-Length: {len(body)}\r\n\r\n{body}")
    try:
        with tls_connect(a) as s:
            s.sendall(req.encode())
    except OSError as e:
        print("logout not sent:", e, file=sys.stderr)


def negotiate(a, tok):
    s = tls_connect(a)
    s.sendall((f"CONNECT 127.0.0.1:{PROXY_PORT} HTTP/1.1\r\nUser-Agent: WinInet\r\nHost: {a.host}:{a.port}\r\n"
               f"Content-Length: 0\r\nConnection: Keep-Alive\r\nCache-Control: no-cache\r\n"
               f"Cookie: authtok={tok}\r\n\r\n").encode())
    head, _, rest = recv_until(s, b"\r\n\r\n").partition(b"\r\n\r\n")
    if not head.startswith(b"HTTP/1.0 200 Connection Established"):
        hint = " (the firewall's SSL VPN daemon is down; Zyxel's client suggests a reboot)" if b"502" in head else ""
        sys.exit(f"CONNECT refused{hint}: {head[:200]!r}")
    s.sendall(f"GET /NetExtInit {tok}".encode())
    buf = rest
    while b"</configuration>" not in buf:
        d = s.recv(4096)
        if not d:
            sys.exit(f"incomplete configuration: {buf[:300]!r}")
        buf += d
    xml, _, extra = buf.partition(b"</configuration>")
    xml = xml.decode("latin1") + "</configuration>"
    if a.verbose:
        print(xml, file=sys.stderr)
    s.sendall(f"GET /NetExtDone {tok}".encode())
    return s, parse_config(xml), extra


def parse_config(xml):
    tag = lambda name, text: re.findall(rf"<{name}>\s*([^<]*?)\s*</{name}>", text, re.I)
    node = re.search(r"<node>(.*?)</node>", xml, re.I | re.S)
    if not node:
        sys.exit("XML without <node>:\n" + xml)
    n = node.group(1)
    areas = [(tag("ip", x)[0], tag("mask", x)[0]) for x in re.findall(r"<area>(.*?)</area>", xml, re.I | re.S)
             if tag("ip", x) and tag("mask", x)]
    return {"ip": tag("ip", n)[0], "mask": (tag("mask", n) or ["255.255.255.255"])[0],
            "peer": tag("localip", n)[0], "dns": tag("dns", xml)[:8], "areas": areas[:8]}


def sh(*cmd, check=True):
    print("+", " ".join(cmd), file=sys.stderr)
    return subprocess.run(cmd, check=check)


def setup_tun(name, cfg, no_dns):
    fd = os.open("/dev/net/tun", os.O_RDWR)
    ifr = fcntl.ioctl(fd, TUNSETIFF, struct.pack("16sH", name.encode(), IFF_TUN | IFF_NO_PI))
    name = ifr[:16].rstrip(b"\0").decode()
    sh("ip", "link", "set", name, "mtu", str(MTU), "up")
    sh("ip", "addr", "add", cfg["ip"], "peer", cfg["peer"], "dev", name)
    for net, mask in cfg["areas"]:
        sh("ip", "route", "replace", f"{net}/{mask}", "dev", name)
    if cfg["dns"] and not no_dns:
        if shutil.which("resolvectl"):
            sh("resolvectl", "dns", name, *cfg["dns"], check=False)
        else:
            print("resolvectl not found, DNS servers not set:", cfg["dns"], file=sys.stderr)
    return fd, name  # non-persistent tun: closing fd removes the interface, its routes and DNS


def pump(s, fd, extra, verbose):
    buf, first = extra, True
    while True:
        r = [s] if s.pending() else select.select([s, fd], [], [])[0]
        if fd in r:
            pkt = os.read(fd, 65535)
            s.sendall(struct.pack(">H", len(pkt)) + pkt)
        if s in r:
            d = s.recv(65536)
            if not d:
                print("tunnel closed by the firewall", file=sys.stderr)
                return
            buf += d
            while len(buf) >= 2 and len(buf) >= 2 + (n := struct.unpack(">H", buf[:2])[0]):
                pkt, buf = buf[2:2 + n], buf[2 + n:]
                if first:
                    first = False
                    if verbose or pkt[:1] and pkt[0] >> 4 not in (4, 6):
                        print("first packet from the firewall:", pkt[:32].hex(), file=sys.stderr)
                os.write(fd, pkt)


def main():
    p = argparse.ArgumentParser(description="Zyxel SSL VPN client (SecuExtender protocol)")
    p.add_argument("host"); p.add_argument("port", type=int); p.add_argument("user")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--pin", help="sha256 of the firewall certificate (hex)")
    g.add_argument("--insecure", action="store_true", help="do not check the certificate")
    p.add_argument("--dev", default="zyvpn%d", help="tun interface name")
    p.add_argument("--no-dns", action="store_true", help="ignore the DNS servers pushed by the firewall")
    p.add_argument("--password-stdin", action="store_true",
                   help="read the password from the first line of stdin; disconnect when stdin is closed")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    a = p.parse_args()
    if os.geteuid() != 0:
        sys.exit("run as root (tun device, routes)")
    if a.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = os.environ.get("ZYXEL_VPN_PASSWORD") or getpass.getpass("Password: ")
    for sig in (signal.SIGINT, signal.SIGTERM):  # kill and systemd stop must log out too
        signal.signal(sig, signal.default_int_handler)
    if a.password_stdin:  # the GUI runs us as root through pkexec and cannot signal us: it closes stdin instead
        threading.Thread(target=lambda: (sys.stdin.read(), os.kill(os.getpid(), signal.SIGTERM)), daemon=True).start()

    tok = login(a, password)
    print("login ok", file=sys.stderr)
    try:
        s, cfg, extra = negotiate(a, tok)
        s.settimeout(None)
        print(f"tunnel: ip {cfg['ip']} peer {cfg['peer']} dns {cfg['dns']} routes {cfg['areas']}", file=sys.stderr)
        fd, name = setup_tun(a.dev, cfg, a.no_dns)
        print(f"connected on {name}, Ctrl+C to disconnect", file=sys.stderr)
        try:
            pump(s, fd, extra, a.verbose)
        finally:
            os.close(fd)
            s.close()
    except KeyboardInterrupt:
        pass
    finally:
        logout(a, tok)
        print("logged out", file=sys.stderr)


if __name__ == "__main__":
    main()
