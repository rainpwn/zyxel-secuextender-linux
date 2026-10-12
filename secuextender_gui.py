#!/usr/bin/env python3
"""secuextender_gui.py - graphical front end for zyxel_sslvpn.py. It runs as your user and starts the client
as root through pkexec, so the system asks for your password at every connection.

  ./secuextender_gui.py

Servers that connect successfully are saved, with the username, in ~/SecuExtender.xml.
Needs Tkinter (Debian/Ubuntu: python3-tk, Fedora: python3-tkinter) and pkexec (polkit).
"""
import hashlib, json, os, queue, re, subprocess, sys, threading, urllib.request, webbrowser
import tkinter as tk
import xml.etree.ElementTree as ET
from tkinter import font, ttk
from types import SimpleNamespace
from xml.sax.saxutils import escape

import zyxel_sslvpn
from zyxel_sslvpn import __version__

NAME = "SecuExtender for Linux"
CONFIG = os.path.expanduser("~/SecuExtender.xml")
CLIENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zyxel_sslvpn.py")
REPO = "https://github.com/rainpwn/zyxel-secuextender-linux"
COFFEE = "https://buymeacoffee.com/rainpwn"
C = dict(bg="#f3f4f6", surface="#ffffff", line="#d8dce2", ink="#1d2329", muted="#5b6672", off="#a3acb6",
         accent="#1565c0", accent_hover="#0f4f99", accent_off="#a7bfe0", select="#dce8f8", hover="#eceff3",
         press="#e1e5ea", danger="#b42318", danger_hover="#fbeae8", ok="#1a7f37")


def load_servers():
    try:
        root = ET.parse(CONFIG).getroot()
    except (OSError, ET.ParseError):
        return []
    return [(s.findtext("host", "").strip(), s.findtext("user", "").strip()) for s in root.iter("server")]


def save_servers(servers):
    body = "".join(f"  <server>\n    <host>{escape(h)}</host>\n    <user>{escape(u)}</user>\n  </server>\n"
                   for h, u in servers)
    with open(CONFIG, "w", encoding="utf-8") as f:
        f.write(f'<?xml version="1.0" standalone="yes"?>\n<SecuExtender>\n{body}</SecuExtender>\n')


def split_server(server):
    host, sep, port = server.rpartition(":")
    return (host, int(port)) if sep and port.isdigit() else (server, 443)


def fingerprint(host, port):
    with zyxel_sslvpn.tls_connect(SimpleNamespace(host=host, port=port, insecure=True)) as s:
        return hashlib.sha256(s.getpeercert(binary_form=True)).hexdigest()


def latest_release():
    """Tag of the latest GitHub release, e.g. "v0.2.0", or None when GitHub cannot be reached."""
    try:
        api = REPO.replace("github.com", "api.github.com/repos") + "/releases/latest"
        with urllib.request.urlopen(api, timeout=5) as r:
            return json.load(r)["tag_name"]
    except (OSError, ValueError, KeyError):
        return None


def newer(tag):
    v = lambda s: tuple(int(x) for x in re.findall(r"\d+", s)[:3])
    return v(tag) > v(__version__)


def theme(root, px):
    base = font.nametofont("TkDefaultFont")
    title = base.copy(); title.configure(size=int(base.cget("size") * 1.35), weight="bold")
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=C["bg"], foreground=C["ink"], bordercolor=C["line"], lightcolor=C["bg"],
                darkcolor=C["bg"], troughcolor=C["bg"], focuscolor=C["accent"], fieldbackground=C["surface"],
                selectbackground=C["select"], selectforeground=C["ink"], insertcolor=C["ink"])
    s.configure("Panel.TFrame", background=C["surface"])
    s.configure("Panel.TLabel", background=C["surface"])
    s.configure("Title.TLabel", background=C["surface"], font=title)
    s.configure("Muted.TLabel", foreground=C["muted"])
    s.configure("Online.TLabel", foreground=C["ok"])
    s.configure("Error.TLabel", foreground=C["danger"])
    s.configure("PanelMuted.TLabel", background=C["surface"], foreground=C["muted"])
    link = base.copy(); link.configure(underline=True)
    s.configure("Link.TLabel", foreground=C["accent"], font=link)
    s.configure("PanelLink.TLabel", background=C["surface"], foreground=C["accent"], font=link)
    s.configure("TSeparator", background=C["line"])

    for name, bg, fg, hover, press, off_bg, off_fg in [
            ("TButton", C["surface"], C["ink"], C["hover"], C["press"], C["surface"], C["off"]),
            ("Accent.TButton", C["accent"], "#ffffff", C["accent_hover"], C["accent_hover"], C["accent_off"], "#ffffff"),
            ("Danger.TButton", C["surface"], C["danger"], C["danger_hover"], C["danger_hover"], C["surface"], C["off"])]:
        s.configure(name, background=bg, foreground=fg, lightcolor=bg, darkcolor=bg, padding=(px(12), px(6)),
                    bordercolor=C["accent"] if name == "Accent.TButton" else C["line"], focuscolor=bg)
        state = [("disabled", off_bg), ("pressed", press), ("active", hover)]
        s.map(name, background=state, lightcolor=state, darkcolor=state, foreground=[("disabled", off_fg)],
              bordercolor=[("focus", C["ink"] if name == "Accent.TButton" else C["accent"])])

    s.configure("TEntry", padding=px(6), bordercolor=C["line"], lightcolor=C["surface"], darkcolor=C["surface"])
    s.map("TEntry", bordercolor=[("disabled", C["line"]), ("focus", C["accent"])],
          lightcolor=[("disabled", C["bg"]), ("focus", C["accent"])],
          fieldbackground=[("disabled", C["bg"])], foreground=[("disabled", C["muted"])])
    s.configure("TCombobox", padding=px(5), arrowcolor=C["muted"], background=C["surface"],
                lightcolor=C["surface"], darkcolor=C["surface"])
    s.map("TCombobox", bordercolor=[("disabled", C["line"]), ("focus", C["accent"])], background=[("active", C["hover"])],
          fieldbackground=[("disabled", C["bg"])], foreground=[("disabled", C["muted"])])
    root.option_add("*TCombobox*Listbox.selectBackground", C["select"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["ink"])
    s.configure("TScrollbar", background=C["line"], bordercolor=C["bg"], lightcolor=C["line"],
                darkcolor=C["line"], arrowcolor=C["muted"], troughcolor=C["bg"], gripcount=0)
    s.map("TScrollbar", background=[("active", C["off"])])
    s.configure("TProgressbar", background=C["accent"], lightcolor=C["accent"], darkcolor=C["accent"],
                troughcolor=C["line"], bordercolor=C["line"], thickness=px(4))
    return title, link  # the caller keeps them: Tk deletes a named font when its Python object goes away


class App:
    def __init__(self, root):
        self.root, self.proc, self.closing, self.events, self.images = root, None, False, queue.Queue(), []
        self.servers, self.latest, self.state = load_servers(), None, "idle"
        self.online = self.stopping = False
        scale = float(root.tk.call("tk", "scaling")) / (96 / 72)  # 1.0 at 96 dpi
        self.px = lambda n: max(1, round(n * scale))
        self.icon_size = 36 if scale >= 1.5 else 18
        px = self.px
        self.fonts = theme(root, px)
        root.title(f"{NAME} {__version__}")
        root.configure(background=C["bg"])
        root.geometry(f"{px(620)}x{px(560)}")
        root.minsize(px(480), px(460))
        root.iconphoto(True, tk.PhotoImage(data=ICONS["app@64"]))

        # status bar
        bar = ttk.Frame(root, padding=(px(14), px(12), px(14), px(10)))
        bar.pack(fill="x")
        self.status = ttk.Label(bar)
        self.status.pack(side="left")
        self.button(bar, "About", "about", self.about, "TButton").pack(side="right")
        self.update_link = ttk.Label(bar, style="Link.TLabel", cursor="hand2")
        self.update_link.bind("<Button-1>", lambda e: webbrowser.open(REPO + "/releases/latest"))

        body = ttk.Frame(root, padding=(px(14), 0, px(14), px(14)))
        body.pack(fill="both", expand=True)

        # connection card
        card = ttk.Frame(body, style="Panel.TFrame", padding=px(16))
        card.pack(fill="x")
        card.columnconfigure(1, weight=1)
        self.server, self.user, self.password = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.combo = ttk.Combobox(card, textvariable=self.server, values=[h for h, _ in self.servers])
        self.combo.bind("<<ComboboxSelected>>", lambda e: self.user.set(dict(self.servers)[self.server.get()]))
        self.fields = [self.combo, ttk.Entry(card, textvariable=self.user),
                       ttk.Entry(card, textvariable=self.password, show="•")]
        for row, (label, w) in enumerate(zip(["Server", "Username", "Password"], self.fields)):
            ttk.Label(card, text=label, style="PanelMuted.TLabel").grid(row=row, column=0, sticky="w",
                                                                        padx=(0, px(12)), pady=px(3))
            w.grid(row=row, column=1, sticky="ew", pady=px(3))
        actions = ttk.Frame(card, style="Panel.TFrame")
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(px(14), 0))
        ttk.Label(actions, text="Server is host:port, the port defaults to 443.",
                  style="PanelMuted.TLabel").pack(side="left")
        self.icons = {k: self.icon(k) for k in ("connect", "disconnect")}
        self.action = ttk.Button(actions, compound="left", command=self.toggle)
        self.action.pack(side="right")
        self.minimize = ttk.Button(actions, text="Minimize", command=root.iconify)
        self.spinner = ttk.Progressbar(actions, mode="indeterminate", length=px(90))

        # client output
        log = ttk.Frame(body, style="Panel.TFrame")
        log.pack(fill="both", expand=True, pady=(px(12), 0))
        self.text = tk.Text(log, font="TkFixedFont", height=8, wrap="word", state="disabled", relief="flat",
                            background=C["surface"], foreground=C["ink"], selectbackground=C["select"],
                            selectforeground=C["ink"], inactiveselectbackground=C["select"],
                            highlightthickness=0, padx=px(12), pady=px(10))
        self.text.tag_configure("muted", foreground=C["muted"])
        sb = ttk.Scrollbar(log, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)

        if self.servers:
            self.server.set(self.servers[0][0])
            self.user.set(self.servers[0][1])
        self.set_state("idle", "Not connected")
        self.write("Choose a server, enter your password and press Connect. "
                   "The client output appears here.\n", "muted")
        root.bind("<Return>", lambda e: self.state == "idle" and self.toggle())
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.poll()
        self.check_update()
        (self.fields[2] if self.servers else self.combo).focus_set()

    def icon(self, key):
        """(normal, disabled) images, with room on the right so the label does not touch the icon."""
        pair = []
        for tag in ("", "_off"):
            data = ICONS.get(f"{key}{tag}@{self.icon_size}")
            if data is None:
                pair.append(pair[0]); continue
            src = tk.PhotoImage(data=data)
            img = tk.PhotoImage(width=src.width() + self.px(8), height=src.height())
            img.tk.call(img, "copy", src)
            self.images += [src, img]
            pair.append(img)
        return pair

    def button(self, parent, text, key, fn, style):
        on, off = self.icon(key)
        return ttk.Button(parent, text=text, image=(on, "disabled", off), compound="left", command=fn, style=style)

    def poll(self):  # worker threads hand callbacks to the Tk thread through this queue
        while not self.events.empty():
            self.events.get()()
        self.root.after(100, self.poll)

    def set_state(self, state, msg, style="Muted.TLabel"):
        """idle: form editable, Connect. busy: everything locked, spinner. connected: Disconnect."""
        self.state = state
        for w in self.fields:
            w.state(["!disabled"] if state == "idle" else ["disabled"])
        key, text, bstyle = (("disconnect", "Disconnect", "Danger.TButton") if state == "connected" or self.stopping
                             else ("connect", "Connect", "Accent.TButton"))
        on, off = self.icons[key]
        self.action.configure(text=text, image=(on, "disabled", off), style=bstyle)
        self.action.state(["disabled"] if state == "busy" else ["!disabled"])
        if state == "connected":  # not every desktop puts a minimize button on the title bar
            self.minimize.pack(side="right", padx=(0, self.px(8)))
        else:
            self.minimize.pack_forget()
        if state == "busy":
            self.spinner.pack(side="right", padx=(0, self.px(12)))
            self.spinner.start(12)
        else:
            self.spinner.stop()
            self.spinner.pack_forget()
        self.root.config(cursor="watch" if state == "busy" else "")
        self.status.config(text=msg, style=style)

    def write(self, text, tag=()):
        self.text.configure(state="normal")
        self.text.insert("end", text, tag)
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    # ---- connection ----

    def toggle(self):
        if self.proc:
            self.stop()
            return
        server, user = self.server.get().strip(), self.user.get().strip()
        if not server or not user:
            self.set_state("idle", "Enter the server and the username.", "Error.TLabel")
            return
        self.clear()
        self.set_state("busy", f"Contacting {server}...")
        threading.Thread(target=self.check_certificate, args=(server, user), daemon=True).start()

    def check_certificate(self, server, user):
        host, port = split_server(server)
        try:
            fp = fingerprint(host, port)
        except (OSError, ValueError) as e:
            self.events.put(lambda: (self.write(f"{server}: {e}\n"),
                                     self.set_state("idle", f"Cannot reach {server}", "Error.TLabel")))
            return
        self.events.put(lambda: self.start(server, user, fp))

    def start(self, server, user, fp):
        if not self.confirm_certificate(server, fp):
            self.set_state("idle", "Not connected")
            return
        host, port = split_server(server)
        cmd = [sys.executable, "-u", CLIENT, host, str(port), user, "--pin", fp, "--password-stdin"]
        if os.geteuid():
            cmd.insert(0, "pkexec")
            self.write("Waiting for authorization: the client needs root for the tun interface and the routes.\n",
                       "muted")
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True)
            self.proc.stdin.write(self.password.get() + "\n")
            self.proc.stdin.flush()
        except OSError as e:
            self.proc = None
            self.write(f"Cannot start the client: {e}\n")
            self.set_state("idle", "pkexec not found" if isinstance(e, FileNotFoundError) else "Not connected",
                           "Error.TLabel")
            return
        self.set_state("busy", f"Connecting to {server}...")
        threading.Thread(target=self.read_output, args=(self.proc, server, user), daemon=True).start()

    def read_output(self, proc, server, user):
        ip = ""
        for line in proc.stdout:
            self.events.put(lambda line=line: self.write(line))
            if m := re.match(r"tunnel: ip (\S+)", line):
                ip = m.group(1)
            if m := re.match(r"connected on (\S+?),", line):
                self.events.put(lambda dev=m.group(1), ip=ip: self.connected(server, user, f"{dev}  ·  {ip}"))
        code = proc.wait()
        self.events.put(lambda: self.finished(code))

    def connected(self, server, user, detail):
        self.online = True
        self.set_state("connected", f"●  Connected to {server}  ·  {detail}", "Online.TLabel")
        self.servers = [(server, user)] + [s for s in self.servers if s[0] != server]
        self.combo["values"] = [h for h, _ in self.servers]
        try:
            save_servers(self.servers)
        except OSError as e:
            self.write(f"Cannot save {CONFIG}: {e}\n")
        self.root.title(f"Connected to {server} - {NAME}")  # what the taskbar shows while minimized

    def stop(self):
        if not self.stopping:
            self.stopping = True
            self.set_state("busy", "Disconnecting...")
            self.proc.stdin.close()  # the client logs out and exits when its stdin closes

    def finished(self, code):
        was_online, asked, self.proc, self.online, self.stopping = self.online, self.stopping, None, False, False
        self.root.title(f"{NAME} {__version__}")
        if was_online and not asked:  # the tunnel dropped while the window may be minimized: show it
            self.set_state("idle", "Connection lost. The output below says why.", "Error.TLabel")
            self.root.deiconify()
        elif was_online:
            self.set_state("idle", "Disconnected")
        elif code in (126, 127) and os.geteuid():
            self.set_state("idle", "Authorization was refused or cancelled.", "Error.TLabel")
        else:
            self.set_state("idle", "Connection failed. The output below says why.", "Error.TLabel")
        if self.closing:
            self.root.destroy()

    def quit(self):
        if not self.proc:
            self.root.destroy()
        else:
            self.closing = True
            self.stop()

    # ---- updates ----

    def check_update(self, done=None):
        """Ask GitHub for the latest release in the background; done() runs on the Tk thread afterwards."""
        def work():
            tag = latest_release()
            self.events.put(lambda: self.checked(tag, done))
        threading.Thread(target=work, daemon=True).start()

    def checked(self, tag, done):
        self.latest = tag
        if tag and newer(tag):
            self.update_link.config(text=f"Update available: {tag}")
            self.update_link.pack(side="right", padx=(0, self.px(14)))
        if done:
            done()

    def update_text(self):
        if self.latest is None:
            return "Could not reach GitHub to check for updates."
        if newer(self.latest):
            return f"Version {self.latest} is available."
        return "You have the latest version."

    # ---- dialogs ----

    def dialog(self, title):
        win = tk.Toplevel(self.root, background=C["bg"])
        win.title(title)
        win.transient(self.root)
        win.resizable(False, False)
        win.bind("<Escape>", lambda e: win.destroy())
        frm = ttk.Frame(win, padding=self.px(18))
        frm.pack(fill="both", expand=True)
        return win, frm

    def modal(self, win, focus):
        """Center win on the main window and keep the input until it closes."""
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_reqheight()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.wait_visibility()
        win.grab_set()
        focus.focus_set()
        self.root.wait_window(win)

    def confirm_certificate(self, server, fp):
        px, ok = self.px, []
        win, frm = self.dialog("Check the certificate")
        ttk.Label(frm, wraplength=px(420), justify="left",
                  text=f"{server} presented the certificate below. Connect only if its SHA-256 fingerprint "
                       "matches the one of your firewall's certificate.").pack(anchor="w")
        pairs = ":".join(fp[i:i + 2] for i in range(0, len(fp), 2)).upper()
        t = tk.Text(frm, font="TkFixedFont", height=2, width=47, wrap="none", relief="flat", background=C["surface"],
                    foreground=C["ink"], selectbackground=C["select"], highlightthickness=0, padx=px(12), pady=px(10))
        t.insert("1.0", pairs[:47] + "\n" + pairs[48:])  # 16 bytes per line
        t.configure(state="disabled")
        t.pack(fill="x", pady=(px(12), 0))

        def accept():
            ok.append(True)
            win.destroy()
        btns = ttk.Frame(frm)
        btns.pack(anchor="e", pady=(px(16), 0))
        cancel = ttk.Button(btns, text="Cancel", command=win.destroy)
        cancel.pack(side="left")
        ttk.Button(btns, text="Trust and connect", command=accept, style="Accent.TButton").pack(
            side="left", padx=(px(8), 0))
        self.modal(win, cancel)  # no Enter binding: trusting a certificate must be a deliberate click
        return bool(ok)

    def about(self):
        px = self.px
        win, frm = self.dialog(f"About {NAME}")
        card = ttk.Frame(frm, style="Panel.TFrame", padding=px(16))
        card.pack(fill="x")
        logo = tk.PhotoImage(data=ICONS["app@64"])
        self.images.append(logo)
        ttk.Label(card, image=logo, style="Panel.TLabel").grid(row=0, column=0, rowspan=2, padx=(0, px(14)))
        ttk.Label(card, text=NAME, style="Title.TLabel").grid(row=0, column=1, sticky="sw")
        ttk.Label(card, text=f"Version {__version__}", style="PanelMuted.TLabel").grid(row=1, column=1, sticky="nw")
        ttk.Label(frm, wraplength=px(400), justify="left",
                  text="SSL VPN client for Zyxel firewalls (USG FLEX, ATP and VPN series) on Linux. "
                       "It speaks the same protocol as Zyxel SecuExtender.").pack(anchor="w", pady=(px(14), 0))

        row = ttk.Frame(frm)
        row.pack(fill="x", pady=(px(14), 0))
        status = ttk.Label(row, text=self.update_text(), style="Muted.TLabel")
        status.pack(side="left")
        check = ttk.Button(row, text="Check for updates")
        check.pack(side="right", padx=(px(12), 0))

        def checked():
            if status.winfo_exists():
                status.config(text=self.update_text())
                check.state(["!disabled"])

        def recheck():
            status.config(text="Checking...")
            check.state(["disabled"])
            self.check_update(checked)
        check.config(command=recheck)

        ttk.Separator(frm).pack(fill="x", pady=px(14))
        for line in ["Made by Alessandro Sgreccia (rainpwn). MIT License.",
                     "Icons: Lucide (lucide.dev), ISC License.",
                     "Independent project, not affiliated with or endorsed by Zyxel."]:
            ttk.Label(frm, text=line, style="Muted.TLabel").pack(anchor="w")
        links = ttk.Frame(frm, style="Panel.TFrame", padding=(px(12), px(8)))
        links.pack(fill="x", pady=(px(14), 0))
        for i, (text, url) in enumerate([("Source code", REPO), ("Report a problem", REPO + "/issues"),
                                         ("Buy me a coffee", COFFEE)]):
            lbl = ttk.Label(links, text=text, style="PanelLink.TLabel", cursor="hand2")
            lbl.bind("<Button-1>", lambda e, url=url: webbrowser.open(url))
            lbl.pack(side="left", padx=(0 if i == 0 else px(16), 0))
        close = ttk.Button(frm, text="Close", command=win.destroy, style="Accent.TButton")
        close.pack(anchor="e", pady=(px(16), 0))
        win.bind("<Return>", lambda e: win.destroy())
        self.modal(win, close)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


# Icons: Lucide (lucide.dev, ISC license), rendered to PNG with 16 alpha levels; key@pixels, _off = disabled.
ICONS = {
    'connect@18': 'iVBORw0KGgoAAAANSUhEUgAAABIAAAASBAMAAACk4JNkAAAAMFBMVEX///////////////////////////////////////////////////////////////9Or7hAAAAAEHRSTlMAESIzRFVmd4iZqrvM3e7/dpUBFQAAAHFJREFUeNpdzbEJAkEYROFvfyzgxCtgMTewAjmwBysxtjGxAQ8DY0uQu4s0cw0WBZ3oDbxhYG0BpKdDQyBpVKoJSjFNEMdXP56zEN3Jrc1mPLZskiCh+d2WQJ7g0s3bO1iVoVyrsRv2H7n3/8v4rUt4A3CMGYLIsb7XAAAAAElFTkSuQmCC',
    'connect@36': 'iVBORw0KGgoAAAANSUhEUgAAACQAAAAkBAMAAAATLoWrAAAAMFBMVEX///////////////////////////////////////////////////////////////9Or7hAAAAAEHRSTlMAESIzRFVmd4iZqrvM3e7/dpUBFQAAAOZJREFUeNqtkbFqAkEYhL89JWdhyG26NEErW19DfAhTpgypQopgIaT0MSxtLOx9gcMXEKt0d9sEQkAmxe6tp0aIkL/ZYXb/+Wf+hXPV60DyfEBtcrjeeZwAYDIL1mQ16qD+nxIChwOgCfCY0Xq5SXnXa3h5pVgPoTFRJeM6oVFmmTvANCYu3KV6qgM/0YfD1EyE97rY/YmW9lRloqGtB/fqx81/+3O+i4IjLbrW3g71GamWVBRFIY33c9/8Hj68NACr9p1Jy/XA1f3Z6Zc9cl86lceBMnOS0ekv//hLYx7DNCswM5yvH8aMTBIVLC9WAAAAAElFTkSuQmCC',
    'connect_off@18': 'iVBORw0KGgoAAAANSUhEUgAAABIAAAASBAMAAACk4JNkAAAAMFBMVEWjrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLaXNI5fAAAAEHRSTlMAESIzRFVmd4iZqrvM3e7/dpUBFQAAAHFJREFUeNpdzbEJAkEYROFvfyzgxCtgMTewAjmwBysxtjGxAQ8DY0uQu4s0cw0WBZ3oDbxhYG0BpKdDQyBpVKoJSjFNEMdXP56zEN3Jrc1mPLZskiCh+d2WQJ7g0s3bO1iVoVyrsRv2H7n3/8v4rUt4A3CMGYLIsb7XAAAAAElFTkSuQmCC',
    'connect_off@36': 'iVBORw0KGgoAAAANSUhEUgAAACQAAAAkBAMAAAATLoWrAAAAMFBMVEWjrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLaXNI5fAAAAEHRSTlMAESIzRFVmd4iZqrvM3e7/dpUBFQAAAOZJREFUeNqtkbFqAkEYhL89JWdhyG26NEErW19DfAhTpgypQopgIaT0MSxtLOx9gcMXEKt0d9sEQkAmxe6tp0aIkL/ZYXb/+Wf+hXPV60DyfEBtcrjeeZwAYDIL1mQ16qD+nxIChwOgCfCY0Xq5SXnXa3h5pVgPoTFRJeM6oVFmmTvANCYu3KV6qgM/0YfD1EyE97rY/YmW9lRloqGtB/fqx81/+3O+i4IjLbrW3g71GamWVBRFIY33c9/8Hj68NACr9p1Jy/XA1f3Z6Zc9cl86lceBMnOS0ekv//hLYx7DNCswM5yvH8aMTBIVLC9WAAAAAElFTkSuQmCC',
    'disconnect@18': 'iVBORw0KGgoAAAANSUhEUgAAABIAAAASBAMAAACk4JNkAAAAMFBMVEW0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0IxjrKE+QAAAAEHRSTlMAESIzRFVmd4iZqrvM3e7/dpUBFQAAAJRJREFUeNo1jrsKwkAURM/uFUwlW1lZbG0haSUk+iU+Klu/Sez9BAWxTBMLEUQJauejWCyiYCw2TjPDGQYGKoXemuPAKQC5NWY5APE2KXy56OuD8SyjN9UAm5atlqZzvRuQ+TLUzzOQlC8xbQvqOMiHI4C6k8fH+ETsAFCprb0BdJmtu3sAguL0tQASXSa7FQDyv/oDkqsm6ivbiW4AAAAASUVORK5CYII=',
    'disconnect@36': 'iVBORw0KGgoAAAANSUhEUgAAACQAAAAkBAMAAAATLoWrAAAAMFBMVEW0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0Ixi0IxjrKE+QAAAAEHRSTlMAESIzRFVmd4iZqrvM3e7/dpUBFQAAAQlJREFUeNqFkrFOwzAQhv8kSoQFSFlZUDbUrU/QZ8hTZIVHMRVC6nTte4DEiMQAO0Ko4gHM1NZF9c+Q1LG99DZ//u98d7+B09GhCE5ZvYN6XecjKZ/eWjz+hilC7q6cDYiiM/ymDkVmPiFjkQWEHwG6pR54HjW1XVZtkgjFl6i8BjKzDus726Ox1na10Tir35HIhL588dUAYhZ+ng4z3gGKPM6j+GBcA0D8PELyp7/zIvIwxU0DdL7HBfcozDhxSQuhngVLuKCG4t64qUfXrgZkeCBAihxFOKcGIOHSy2FRmyPI8besdGr5ZW+Eji2dTxJLD3QmsfReYksrZ1E+f7YhogayOvljp+MfQeqRL4kjiO8AAAAASUVORK5CYII=',
    'disconnect_off@18': 'iVBORw0KGgoAAAANSUhEUgAAABIAAAASBAMAAACk4JNkAAAAMFBMVEWjrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLaXNI5fAAAAEHRSTlMAESIzRFVmd4iZqrvM3e7/dpUBFQAAAJJJREFUeNo1jjsKwkAYhL/dXzCVbGVjsyeQtBoSPYmPytYzib1HUBDs0mghgihB7XwUi0UUjMUm08zwDQMDpUJvzXHgFIDcG7MMgHiX5L5c9PXRlIzeVANsWtXStG8PAzJfhvK6AEnxFtO1oE6DbDgCqDt5fo1PxA4AldraB0AX23XnAECQn38WQKLrZL8CQKqrf5/GJwysL6CZAAAAAElFTkSuQmCC',
    'disconnect_off@36': 'iVBORw0KGgoAAAANSUhEUgAAACQAAAAkBAMAAAATLoWrAAAAMFBMVEWjrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLajrLaXNI5fAAAAEHRSTlMAESIzRFVmd4iZqrvM3e7/dpUBFQAAAQlJREFUeNqFkrFOwzAQhv8kSoQFSFlZUDbUrU/QZ8hTZIVHMRVC6nTte4DEiMQAO0Ko4gHM1NZF9c+Q1LG99DZ//u98d7+B09GhCE5ZvYN6XecjKZ/eWjz+hilC7q6cDYiiM/ymDkVmPiFjkQWEHwG6pR54HjW1XVZtkgjFl6i8BjKzDus726Ox1na10Tir35HIhL588dUAYhZ+ng4z3gGKPM6j+GBcA0D8PELyp7/zIvIwxU0DdL7HBfcozDhxSQuhngVLuKCG4t64qUfXrgZkeCBAihxFOKcGIOHSy2FRmyPI8besdGr5ZW+Eji2dTxJLD3QmsfReYksrZ1E+f7YhogayOvljp+MfQeqRL4kjiO8AAAAASUVORK5CYII=',
    'about@18': 'iVBORw0KGgoAAAANSUhEUgAAABIAAAASBAMAAACk4JNkAAAAMFBMVEU7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlJ0E5tEAAAAEHRSTlMAESIzRFVmd4iZqrvM3e7/dpUBFQAAAHlJREFUeNpNzrERwQAYQOHPn5O0VNpswARSSOvOCKk0GqqsYCKdDZRa4c4AnNRCoZDmle+9BLHonmBy/bx3kFwP5eY9w/yM5Z3BZeTHrGVPsY30CE6VaQXSV+Q3aroIWEPcch5EF82KMcNG1lJTbHvmf6138L8iyhxfrUIoRvW6jHMAAAAASUVORK5CYII=',
    'about@36': 'iVBORw0KGgoAAAANSUhEUgAAACQAAAAkBAMAAAATLoWrAAAAMFBMVEU7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlI7RlJ0E5tEAAAAEHRSTlMAESIzRFVmd4iZqrvM3e7/dpUBFQAAAR9JREFUeNp1kj1LA0EURc++YAIJ4mKZakR/QLC1sEiljTbWprXyH5haENKIWEawN2CtthYW9hbZzjbgRyTBuRabyY5s8poZzrw7cO97UKrK7Nw6ateG/x4uJOm5FZE7SZImbo7OpLfr8wfpPZCmdJtCsi/d5CR50n1+29E0BaCun9DfUx+ArjoBVTUGsKIJenJAXQOAagegoT6wKwdw+p1LPjAOJ1kh9IMVYPhJIeTgF0yvsdtVOTOyGHkKNBN6nCWMADi5AkCkFhRufjOROx0pz4CReVz8vZGZZyNG62Tms80YbfvMGFQBSBMAOtPC9vFXsL0wnEo5wjjoWh40jfI4FgyNpnSZQrI3Hy10wwKMy2vSWrJMSVi59trLI8vqD/THi9bfzdt1AAAAAElFTkSuQmCC',
    'app@64': 'iVBORw0KGgoAAAANSUhEUgAAAEAAAABABAMAAABYR2ztAAAAMFBMVEUVZcAVZcAVZcAVZcAVZcAVZcAVZcAVZcAVZcAVZcAVZcAVZcAVZcAVZcAVZcAVZcC+ZqBeAAAAEHRSTlMAESIzRFVmd4iZqrvM3e7/dpUBFQAAAjBJREFUeNrNlT9oFEEYxd/t5aInFlscFlZbWCiIpNAiKIiIhSDJ+qeyMNurKHaKKCJYGsGQxiIiaJvCxkoUxU5PhBgQ4YIoYrUBSdC72/1Z7Nzu7GZ306Rwum/e2zdv55t5I231OHSmHj8Mz+vwVgixX0OYBfhTjR8BgDdV+D7MuFOO7w2B71NAdK0Eds6HwNBzukA85+bRxonrL0fi2wH4cu+czbllFn8rSadMsZzhbTP1OSkvm/JBSpgxuBFtXErqtZTQBYieZpInewCD1GJI/PXFMdt158b7kNjNCOvuhv++khCcpGJ1A8HMOJsdkP+V0NiMcHO5+EVobbvUBl/STG6j7DEv+XVLtAPpYx1hXooflxMmHxqBpdVSk03wpQWIPGUmLUIb1tQGPskijOW0dvjTUjxlT1mEvqRHHWlppWIno0DqFAUSgjH9TFJRQI4kTH8GgSwBV1jHPsmEVvoLkmYZWkskVgaB5cCzFAxZGvvwxJL9a189r3hWHFhPl1hJG5yptqQoLXbCq2JTR3OOJA2lg0XCcSn7qMnIpewb72XVIgR5fBz6VnkUvuUJB+C33WaIcgHQ6NkJlNSvbcJ+svMkSZqGoeWp2SN3VaRtwI+svABczZtasCN6N1iNyKIyMvvd6pG3KEm6DQx8SWp1Sx+N8RAYnpZ2dYE4KH2uILo7GULFwzVKdOBnedgsjvC+Vx5HTcPoT1QG1n2AXxPVkda4GPLOrU29PWe3/LX/B6PQbjqetoazAAAAAElFTkSuQmCC',
}

if __name__ == "__main__":
    main()
