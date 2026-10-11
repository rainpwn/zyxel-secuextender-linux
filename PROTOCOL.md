# The Zyxel SecuExtender SSL VPN protocol

This document describes how SecuExtender 4.0.5.0 for Windows talks to a Zyxel ZLD firewall. `SecuExtender_core.dll` is a C++/CLI assembly, so most of it decompiles to readable code with ILSpy. Login, tunnel setup and packet exchange were then confirmed against an ATP700 with this client.

Notes marked **from code** were read from the client and not checked separately on the firewall.

## Overview

The client opens three separate TLS connections to the firewall's SSL VPN port:

1. login, which returns a session token,
2. the tunnel, which carries configuration and then IP packets,
3. logout, when the user disconnects.

SecuExtender allows TLS 1.0 to 1.2 and not 1.3 (from code). The firewall presents a self-signed certificate; SecuExtender logs the untrusted root and continues.

## 1. Login

```
POST / HTTP/1.1
Host: <host>:<port>
Referer: https://<host>:<port>
Content-Type: application/x-www-form-urlencoded
Connection: Keep-Alive
Content-Length: <n>

username=<user>&pwd=<password>&password=<password>&loginTosslvpn=true
```

Values are URL-encoded and the password goes in both `pwd` and `password`. No User-Agent is sent.

The firewall answers with a cookie:

```
Set-Cookie: authtok=<token>; ...
```

The client takes the value up to the semicolon. It does not check the HTTP status (from code).

## 2. Tunnel

On a new TLS connection, the client asks the firewall's web server to relay it to an internal service on port 10444:

```
CONNECT 127.0.0.1:10444 HTTP/1.1
User-Agent: WinInet
Host: <host>:<port>
Content-Length: 0
Connection: Keep-Alive
Cache-Control: no-cache
Cookie: authtok=<token>

```

The reply must start with `HTTP/1.0 200 Connection Established`. On `HTTP/1.1 502 Bad Gateway`, SecuExtender tells the user that the SSL VPN service on the firewall is not running and suggests a reboot (from code).

On the same connection the client then sends, with no CRLF and no HTTP version:

```
GET /NetExtInit <token>
```

The firewall answers with raw XML, without HTTP headers, ending in `</configuration>`:

```xml
<configuration>
  <node>
    <ip>client address</ip>
    <mask>client netmask</mask>
    <localip>peer address</localip>
  </node>
  <dns>...</dns>      <!-- up to 8 -->
  <wins>...</wins>    <!-- up to 8 -->
  <area>              <!-- up to 8: networks to route through the tunnel -->
    <ip>network</ip>
    <mask>netmask</mask>
  </area>
</configuration>
```

SecuExtender rejects a configuration shorter than 72 or longer than 1023 bytes (from code). All addresses are IPv4.

The client then sends, again with no CRLF:

```
GET /NetExtDone <token>
```

and does not wait for an answer. From this point the connection carries packets.

## 3. Packets

Each IP packet travels as a 2-byte big-endian length followed by the packet, in both directions:

```
length (2 bytes) | IPv4 packet (length bytes)
```

There is no Ethernet header, no compression and no other framing. A TLS record can hold part of a packet or several packets, so the receiver reassembles by length.

On Windows, SecuExtender uses a renamed OpenVPN TAP adapter in point-to-point mode with MTU 1370. On Linux a `tun` interface without packet information headers does the same job.

There is no keepalive in the client (from code). The tunnel ends when either side closes the connection.

## 4. Logout (from code)

On a third TLS connection:

```
POST /setuser.cgi HTTP/1.1
Host: <host>:<port>
Referer: https://<host>:<port>
Cookie: authtok=<token>;
Content-Type: application/x-www-form-urlencoded
Connection: Keep-Alive
Content-Length: 14

perform=logout
```

## Open questions

- Whether the firewall closes idle tunnels, and after how long.
- How two-factor authentication changes the login. The client contains code for selecting a certificate, which I have not traced.
