"""Verify X11 button release and recover a stale Xwayland relative pointer."""
from __future__ import annotations

import ctypes as c
import time


class _AnyClass(c.Structure):
    _fields_ = [("type", c.c_int), ("sourceid", c.c_int)]


class _ButtonState(c.Structure):
    _fields_ = [("mask_len", c.c_int), ("mask", c.POINTER(c.c_ubyte))]


class _ButtonClass(c.Structure):
    _fields_ = [
        ("type", c.c_int), ("sourceid", c.c_int), ("num_buttons", c.c_int),
        ("labels", c.POINTER(c.c_ulong)), ("state", _ButtonState),
    ]


class _Device(c.Structure):
    _fields_ = [
        ("deviceid", c.c_int), ("name", c.c_char_p), ("use", c.c_int),
        ("attachment", c.c_int), ("enabled", c.c_int), ("num_classes", c.c_int),
        ("classes", c.POINTER(c.POINTER(_AnyClass))),
    ]


class _X11Pointer:
    def __init__(self):
        self.x11 = c.CDLL("libX11.so.6")
        self.xi = c.CDLL("libXi.so.6")
        self.xtst = c.CDLL("libXtst.so.6")
        self.x11.XOpenDisplay.argtypes = [c.c_char_p]
        self.x11.XOpenDisplay.restype = c.c_void_p
        self.x11.XSync.argtypes = [c.c_void_p, c.c_int]
        self.x11.XCloseDisplay.argtypes = [c.c_void_p]
        self.x11.XSetErrorHandler.argtypes = [c.c_void_p]
        self.x11.XSetErrorHandler.restype = c.c_void_p
        self.xi.XIQueryDevice.argtypes = [c.c_void_p, c.c_int, c.POINTER(c.c_int)]
        self.xi.XIQueryDevice.restype = c.POINTER(_Device)
        self.xi.XIFreeDeviceInfo.argtypes = [c.POINTER(_Device)]
        self.xi.XOpenDevice.argtypes = [c.c_void_p, c.c_ulong]
        self.xi.XOpenDevice.restype = c.c_void_p
        self.xi.XCloseDevice.argtypes = [c.c_void_p, c.c_void_p]
        self.xtst.XTestFakeDeviceButtonEvent.argtypes = [
            c.c_void_p, c.c_void_p, c.c_uint, c.c_int, c.POINTER(c.c_int), c.c_int, c.c_ulong,
        ]
        self.display = self.x11.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("X11 display unavailable")
        self.errors = []
        callback = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_void_p)
        self.error_handler = callback(lambda *_args: self.errors.append(True) or 0)
        self.previous_handler = self.x11.XSetErrorHandler(c.cast(self.error_handler, c.c_void_p))

    def _check_errors(self):
        self.x11.XSync(self.display, 0)
        if self.errors:
            raise RuntimeError("X11 pointer request failed")

    def states(self):
        count = c.c_int()
        devices = self.xi.XIQueryDevice(self.display, 0, c.byref(count))
        rows = []
        try:
            self._check_errors()
            if not devices:
                raise RuntimeError("X11 pointer inventory unavailable")
            for index in range(count.value):
                device = devices[index]
                if device.use not in (1, 3, 5):
                    continue
                pressed = False
                for class_index in range(device.num_classes):
                    info = device.classes[class_index]
                    if info.contents.type != 1:
                        continue
                    button = c.cast(info, c.POINTER(_ButtonClass)).contents
                    if button.state.mask_len:
                        pressed = pressed or bool(button.state.mask[0] & 2)
                rows.append({
                    "id": device.deviceid, "name": device.name.decode(errors="replace"),
                    "use": device.use, "attachment": device.attachment,
                    "enabled": bool(device.enabled), "left_pressed": pressed,
                })
        finally:
            if devices:
                self.xi.XIFreeDeviceInfo(devices)
        return rows

    def release(self, device_id):
        device = self.xi.XOpenDevice(self.display, device_id)
        try:
            self._check_errors()
            if not device:
                raise RuntimeError("Xwayland relative pointer disappeared")
            sent = self.xtst.XTestFakeDeviceButtonEvent(self.display, device, 1, 0, None, 0, 0)
            self._check_errors()
            if not sent:
                raise RuntimeError("Xwayland button release was not sent")
        finally:
            if device:
                self.xi.XCloseDevice(self.display, device)

    def close(self):
        self.x11.XSync(self.display, 0)
        self.x11.XCloseDisplay(self.display)
        self.x11.XSetErrorHandler(self.previous_handler)


def _pressed_owner_ids(rows):
    masters = [row for row in rows if row["use"] == 1 and row["name"] == "Virtual core pointer"]
    if len(masters) != 1:
        return None
    master = masters[0]
    if not master["left_pressed"]:
        return []
    owners = [row for row in rows if row["use"] == 3 and row["enabled"]
              and row["attachment"] == master["id"] and row["left_pressed"]]
    if not owners or any(not row["name"].startswith("xwayland-relative-pointer:") for row in owners):
        return None
    return sorted(row["id"] for row in owners)


def recover_xwayland_left_button():
    """Called only after exact target focus/mapping; never release XTEST or physical input."""
    pointer = None
    released = []
    try:
        pointer = _X11Pointer()
        owners = _pressed_owner_ids(pointer.states())
        if owners is None:
            return {"verified": False, "released": [], "reason": "button_owner_busy_or_unknown"}
        if owners:
            # A pending release can arrive asynchronously; do not recover a changing owner.
            time.sleep(0.05)
            current = _pressed_owner_ids(pointer.states())
            if current == []:
                return {"verified": True, "released": []}
            if current != owners:
                return {"verified": False, "released": [], "reason": "button_owner_changed"}
            for device_id in owners:
                pointer.release(device_id)
                released.append(device_id)
            if _pressed_owner_ids(pointer.states()) != []:
                return {"verified": False, "released": released, "reason": "button_release_unconfirmed"}
        return {"verified": True, "released": released}
    except (OSError, RuntimeError, ValueError) as error:
        return {"verified": False, "released": released, "reason": type(error).__name__}
    finally:
        if pointer is not None:
            pointer.close()
