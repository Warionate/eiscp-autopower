"""eiscp-autopower: switch an Onkyo / Pioneer / Integra receiver on and off
together with a Windows PC, over the network (eISCP).

Rules:
  wake  (unlock / logon / resume by the user / sound starts):
        receiver in standby -> power on, select the PC input, optionally set the volume.
        already on          -> do nothing (never steal an input someone else is using).
  off   (sleep / shutdown / silence for N minutes):
        only when the receiver is on AND its input is the PC input.
        Before sleep there is no time for a round trip, so the decision uses the
        state remembered by a background poll and the standby command is sent
        without waiting for a reply.
  pc    (manual): power on + PC input + volume, even if another input is in use.

Usage: python eiscp_autopower.py [run|wake|off|pc|status] [--config PATH]
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import json
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time

import eiscp

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = {
    "host": None,                # receiver host name or IP (required)
    "pc_input": "optical",       # input the PC is connected to (onkyo-eiscp name)
    "wake_volume": None,         # volume to set when powering on; null = leave as is
    "wake_on_unlock": True,      # power on at logon / unlock / resume by the user
    "wake_on_sound": True,       # power on when the PC starts playing sound
    "off_on_sleep": True,        # standby before sleep / shutdown
    "silence_minutes": 10,       # standby after this many silent minutes; 0 = never
    "audio_threshold": 1e-5,     # peak level that counts as sound
    "poll_seconds": 2.0,         # audio meter interval
    "state_refresh_seconds": 60, # how often to remember the receiver state
    "boot_wait_seconds": 15,     # max wait for the receiver to report "on"
    "log_file": "eiscp-autopower.log",
}

log = logging.getLogger("eiscp-autopower")
lock = threading.Lock()
cfg = {}
# Last known receiver state, so the sleep handler can decide without a round trip.
known = {"t": 0.0, "power": None, "input": set()}
target = {"ip": None}


def load_config(path):
    with open(path, encoding="utf-8") as f:
        user = json.load(f)
    unknown = set(user) - set(DEFAULTS)
    if unknown:
        raise SystemExit("unknown config keys: %s" % ", ".join(sorted(unknown)))
    c = dict(DEFAULTS, **user)
    if not c["host"]:
        raise SystemExit("config: 'host' is required")
    return c


def setup_logging():
    path = cfg["log_file"]
    if not os.path.isabs(path):
        path = os.path.join(HERE, path)
    h = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    if sys.stdout is not None:
        log.addHandler(logging.StreamHandler(sys.stdout))


def receiver_addr():
    # Resolve once and keep the IP: right after resume DNS is often not back yet.
    try:
        target["ip"] = socket.gethostbyname(cfg["host"])
    except OSError:
        if not target["ip"]:
            raise
    return target["ip"]


def remember(power, inp):
    known.update(t=time.time(), power=power, input=inp)


def _value(v):
    # onkyo-eiscp returns a name or a tuple of aliases, e.g. ('video2', 'cbl', 'sat')
    return set(v) if isinstance(v, tuple) else {v}


def query(r, name):
    return _value(r.command(name + "=query")[1])


def _power_on_and_select(r):
    if "on" not in query(r, "system-power"):
        r.command("system-power=on")
        deadline = time.time() + cfg["boot_wait_seconds"]
        while time.time() < deadline and "on" not in query(r, "system-power"):
            time.sleep(1)
        time.sleep(2)
    r.command("input-selector=" + cfg["pc_input"])
    if cfg["wake_volume"] is not None:
        r.command("master-volume=%d" % cfg["wake_volume"])
    remember(True, {cfg["pc_input"]})


def wake(reason):
    with lock:
        r = eiscp.eISCP(receiver_addr())
        try:
            if "on" in query(r, "system-power"):
                inp = query(r, "input-selector")
                remember(True, inp)
                log.info("wake(%s): already on, input %s - leave it", reason, sorted(inp))
                return
            _power_on_and_select(r)
            log.info("wake(%s): powered on, input %s", reason, cfg["pc_input"])
        finally:
            r.disconnect()


def pc(reason):
    with lock:
        r = eiscp.eISCP(receiver_addr())
        try:
            _power_on_and_select(r)
            log.info("pc(%s): input %s", reason, cfg["pc_input"])
        finally:
            r.disconnect()


def off(reason):
    with lock:
        r = eiscp.eISCP(receiver_addr())
        try:
            if "on" not in query(r, "system-power"):
                remember(False, set())
                log.info("off(%s): already standby", reason)
                return
            inp = query(r, "input-selector")
            if cfg["pc_input"] not in inp:
                remember(True, inp)
                log.info("off(%s): input %s is not the PC - leave it", reason, sorted(inp))
                return
            r.command("system-power=standby")
            remember(False, set())
            log.info("off(%s): standby", reason)
        finally:
            r.disconnect()


def off_fast(reason):
    """Sleep / shutdown path: decide from the remembered state, send PWR00 without waiting."""
    age = time.time() - known["t"]
    if known["power"] is False:
        log.info("off(%s): known standby", reason)
        return
    if known["power"] and cfg["pc_input"] not in known["input"]:
        log.info("off(%s): known input %s is not the PC - leave it", reason, sorted(known["input"]))
        return
    if known["power"] is None or age > 10 * cfg["state_refresh_seconds"]:
        log.info("off(%s): state unknown (age %ds) - leave it", reason, age)
        return
    r = eiscp.eISCP(target["ip"] or cfg["host"])
    r.CONNECT_TIMEOUT = 1.0
    try:
        r.send("PWR00")  # send() does not wait for an answer
        remember(False, set())
        log.info("off(%s): standby sent", reason)
    finally:
        r.disconnect()


def refresh_state():
    with lock:
        r = eiscp.eISCP(receiver_addr())
        try:
            power = "on" in query(r, "system-power")
            remember(power, query(r, "input-selector") if power else set())
        finally:
            r.disconnect()


def state_loop():
    first = True
    while True:
        try:
            refresh_state()
            if first:
                log.info("state: power=%s input=%s ip=%s", known["power"], sorted(known["input"]), target["ip"])
                first = False
        except Exception as e:
            log.debug("refresh failed: %r", e)
        time.sleep(cfg["state_refresh_seconds"])


def wake_retry(reason, tries=6, delay=5):
    # Right after resume the network may not be back yet.
    for i in range(tries):
        try:
            wake(reason)
            return
        except Exception as e:
            if i == tries - 1:
                log.warning("wake(%s) failed after %d tries: %r", reason, tries, e)
            time.sleep(delay)


def safe(fn, reason):
    try:
        fn(reason)
    except Exception as e:
        log.warning("%s(%s) failed: %r", fn.__name__, reason, e)


def bg(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


# ---- audio watcher -------------------------------------------------------

def audio_peak():
    from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
    from comtypes import CLSCTX_ALL
    dev = AudioUtilities.GetSpeakers()
    dev = getattr(dev, "_dev", dev)
    meter = dev.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None)
    return meter.QueryInterface(IAudioMeterInformation).GetPeakValue()


def audio_loop():
    import comtypes
    comtypes.CoInitialize()
    playing = False
    last_sound = time.time()
    errors = 0
    silence = cfg["silence_minutes"] * 60
    while True:
        try:
            peak = audio_peak()
            errors = 0
        except Exception as e:
            errors += 1
            if errors in (1, 100):
                log.warning("audio meter failed: %r", e)
            peak = 0.0
        now = time.time()
        if peak > cfg["audio_threshold"]:
            last_sound = now
            if not playing:
                playing = True
                log.info("sound started")
                if cfg["wake_on_sound"]:
                    safe(wake, "sound")
        elif playing and silence and now - last_sound > silence:
            playing = False
            log.info("silent for %d min", cfg["silence_minutes"])
            safe(off, "silence")
        time.sleep(cfg["poll_seconds"])


# ---- hidden window for session / power notifications ----------------------

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOGON = 5
WTS_SESSION_UNLOCK = 8
PBT_APMSUSPEND = 4
PBT_APMRESUMESUSPEND = 7  # resume caused by the user (not by Wake-on-LAN or a timer)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR)]


def wndproc(hwnd, msg, wparam, lparam):
    if msg == WM_WTSSESSION_CHANGE and wparam in (WTS_SESSION_UNLOCK, WTS_SESSION_LOGON):
        if cfg["wake_on_unlock"]:
            bg(safe, wake, "unlock")
    elif msg == WM_POWERBROADCAST:
        if wparam == PBT_APMSUSPEND and cfg["off_on_sleep"]:
            safe(off_fast, "sleep")  # synchronous and quick: the system waits only a moment
        elif wparam == PBT_APMRESUMESUSPEND and cfg["wake_on_unlock"]:
            bg(wake_retry, "resume")
        return 1
    elif msg == WM_QUERYENDSESSION:
        if cfg["off_on_sleep"]:
            safe(off_fast, "shutdown")
        return 1
    elif msg == WM_ENDSESSION:
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def idle_seconds():
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]
    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    user32.GetLastInputInfo(ctypes.byref(li))
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0


def run():
    log.info("start (pid %d, receiver %s)", os.getpid(), cfg["host"])
    proc = WNDPROC(wndproc)
    hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
    name = "EiscpAutopower"
    wc = WNDCLASSW(lpfnWndProc=proc, hInstance=hinst, lpszClassName=name)
    if not user32.RegisterClassW(ctypes.byref(wc)):
        raise OSError(ctypes.get_last_error(), "RegisterClassW")
    hwnd = user32.CreateWindowExW(0, name, name, 0, 0, 0, 0, 0, None, None, hinst, None)
    if not hwnd:
        raise OSError(ctypes.get_last_error(), "CreateWindowExW")
    if not ctypes.windll.wtsapi32.WTSRegisterSessionNotification(hwnd, 0):
        log.warning("WTSRegisterSessionNotification failed: %d", ctypes.get_last_error())
    bg(audio_loop)
    bg(state_loop)
    # Logon counts as "the user is here", but a restart after a crash at night must not.
    if cfg["wake_on_unlock"] and idle_seconds() < 120:
        bg(safe, wake, "logon")
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def main():
    ap = argparse.ArgumentParser(description="Switch an eISCP receiver together with this PC.")
    ap.add_argument("command", nargs="?", default="run", choices=["run", "wake", "off", "pc", "status"])
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    args = ap.parse_args()
    cfg.update(load_config(args.config))
    socket.setdefaulttimeout(3)
    setup_logging()
    if args.command == "run":
        run()
    elif args.command == "status":
        r = eiscp.eISCP(receiver_addr())
        try:
            for q in ("system-power", "input-selector", "master-volume"):
                print(q, r.command(q + "=query")[1])
        finally:
            r.disconnect()
    else:
        {"wake": wake, "off": off, "pc": pc}[args.command]("cli")


if __name__ == "__main__":
    main()
