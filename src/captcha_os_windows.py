from __future__ import annotations

from .captcha_context import *  # noqa: F401,F403


class CaptchaOSWindowsMixin:
    def _os_mouse_enabled(self):
        if self._is_local_mock_slider_target():
            return False
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return False
        raw = os.getenv("FAPAI_SOLVER_OS_MOUSE")
        if raw is not None:
            return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
        return os.name == "nt"

    def _window_metrics(self):
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": """({
                screenX: window.screenX, screenY: window.screenY,
                outerWidth: window.outerWidth, outerHeight: window.outerHeight,
                innerWidth: window.innerWidth, innerHeight: window.innerHeight,
                dpr: window.devicePixelRatio || 1,
                title: document.title || ''
            })""",
            "returnByValue": True,
        })
        if ret and "result" in ret and ret["result"].get("value"):
            return ret["result"]["value"]
        return {}

    def _enable_process_dpi_awareness(self):
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    def _force_foreground_hwnd(self, hwnd):
        if not hwnd:
            return False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            target_hwnd = int(hwnd)
            user32.ShowWindowAsync(target_hwnd, 9)  # SW_RESTORE
            foreground = user32.GetForegroundWindow()
            current_thread = kernel32.GetCurrentThreadId()
            pid = ctypes.c_ulong(0)
            foreground_thread = user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid))
            target_pid = ctypes.c_ulong(0)
            target_thread = user32.GetWindowThreadProcessId(target_hwnd, ctypes.byref(target_pid))
            if foreground_thread and foreground_thread != current_thread:
                user32.AttachThreadInput(current_thread, foreground_thread, True)
            if target_thread and target_thread != current_thread:
                user32.AttachThreadInput(current_thread, target_thread, True)
            try:
                user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass
            user32.keybd_event(0x12, 0, 0, 0)  # ALT down, allows SetForegroundWindow
            user32.BringWindowToTop(target_hwnd)
            user32.SetForegroundWindow(target_hwnd)
            try:
                user32.SwitchToThisWindow(target_hwnd, True)
            except Exception:
                pass
            user32.keybd_event(0x12, 0, 2, 0)  # ALT up
            if foreground_thread and foreground_thread != current_thread:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
            if target_thread and target_thread != current_thread:
                user32.AttachThreadInput(current_thread, target_thread, False)
            time.sleep(0.12)
            focused = int(user32.GetForegroundWindow()) == target_hwnd
            if not focused:
                for _ in range(3):
                    user32.SetForegroundWindow(target_hwnd)
                    time.sleep(0.08)
                    if int(user32.GetForegroundWindow()) == target_hwnd:
                        focused = True
                        break
            return focused
        except Exception as error:
            print(f"[SOLVER] SetForegroundWindow failed: {error}")
            return False

    def _iter_top_level_windows(self):
        if os.name != "nt":
            return []
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError:
            return []
        user32 = ctypes.windll.user32
        handles = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value or ""
            class_buff = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buff, 256)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            handles.append({
                "hwnd": int(hwnd),
                "title": title,
                "class_name": class_buff.value or "",
                "left": int(rect.left),
                "top": int(rect.top),
                "right": int(rect.right),
                "bottom": int(rect.bottom),
            })
            return True

        proc = WNDENUMPROC(callback)
        user32.EnumWindows(proc, 0)
        return handles

    def _browser_window_bounds(self):
        params = {}
        if self.target_id:
            params["targetId"] = self.target_id
        result = self._send_cdp("Browser.getWindowForTarget", params)
        if not isinstance(result, dict):
            return None
        bounds = result.get("bounds")
        if not isinstance(bounds, dict):
            return None
        return {
            "left": float(bounds.get("left") or 0),
            "top": float(bounds.get("top") or 0),
            "width": float(bounds.get("width") or 0),
            "height": float(bounds.get("height") or 0),
            "window_state": str(bounds.get("windowState") or ""),
        }

    def _edge_hwnd(self):
        windows = self._iter_top_level_windows()
        if not windows:
            return None
        metrics = self._window_metrics()
        tab_title = str(metrics.get("title") or "").strip()
        bounds = self._browser_window_bounds()
        chrome_windows = [
            item for item in windows
            if "Chrome_WidgetWin_1" in str(item.get("class_name") or "")
            and (item.get("right") or 0) - (item.get("left") or 0) > 200
            and (item.get("bottom") or 0) - (item.get("top") or 0) > 200
        ]
        candidates = chrome_windows or windows

        def score(item):
            title = str(item.get("title") or "")
            value = 0
            if tab_title and tab_title in title:
                value += 50
            lowered = title.lower()
            if "edge" in lowered or "microsoft edge" in lowered:
                value += 10
            if any(token in title for token in ("验证", "淘宝", "拍卖", "司法")):
                value += 8
            if bounds:
                delta = abs(float(item.get("left") or 0) - bounds["left"]) + abs(
                    float(item.get("top") or 0) - bounds["top"]
                )
                value += max(0, 20 - delta / 20.0)
            return value

        ranked = sorted(candidates, key=score, reverse=True)
        if not ranked:
            return None
        best = ranked[0]
        if score(best) <= 0 and not chrome_windows:
            return None
        return best.get("hwnd")

    def _find_child_windows_by_class(self, parent_hwnd, class_name):
        if os.name != "nt" or not parent_hwnd:
            return []
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError:
            return []
        user32 = ctypes.windll.user32
        matches = []

        def walk(current):
            child = user32.FindWindowExW(int(current), 0, None, None)
            while child:
                class_buff = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(child, class_buff, 256)
                if (class_buff.value or "") == class_name:
                    rect = wintypes.RECT()
                    user32.GetClientRect(child, ctypes.byref(rect))
                    width = int(rect.right - rect.left)
                    height = int(rect.bottom - rect.top)
                    if width > 200 and height > 200:
                        matches.append({"hwnd": int(child), "width": width, "height": height})
                walk(child)
                child = user32.FindWindowExW(int(current), child, None, None)

        walk(parent_hwnd)
        matches.sort(key=lambda item: item["width"] * item["height"], reverse=True)
        return matches

    def _win32_client_origin(self):
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError:
            return None
        top_hwnd = self._edge_hwnd()
        if not top_hwnd:
            return None
        render_windows = self._find_child_windows_by_class(top_hwnd, "Chrome_RenderWidgetHostHWND")
        hwnd = int(render_windows[0]["hwnd"]) if render_windows else int(top_hwnd)
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        point = wintypes.POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
            return None
        width = float(rect.right - rect.left)
        height = float(rect.bottom - rect.top)
        if width < 50 or height < 50:
            return None
        return {
            "hwnd": int(top_hwnd),
            "render_hwnd": hwnd,
            "left": float(point.x),
            "top": float(point.y),
            "width": width,
            "height": height,
            "uses_render_widget": bool(render_windows),
        }

    def _focus_linux_window(self):
        """Focus the visible Chromium window that owns the active CDP tab."""
        if not str(os.environ.get("DISPLAY") or "").strip():
            print("[SOLVER] DISPLAY is not set; cannot focus the Linux browser window.")
            return False
        if not self._activate_target_tab():
            print("[SOLVER] Exact CDP target activation failed before Linux window focus.")
            return False
        window_ids = []
        for window_class in ("chromium", "google-chrome", "microsoft-edge"):
            try:
                result = subprocess.run(
                    ["xdotool", "search", "--onlyvisible", "--class", window_class],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
            except (FileNotFoundError, subprocess.SubprocessError) as error:
                print(f"[SOLVER] Linux window search failed: {error}")
                return False
            for raw_window_id in result.stdout.splitlines():
                window_id = raw_window_id.strip()
                if window_id.isdigit() and window_id not in window_ids:
                    window_ids.append(window_id)
        for window_id in reversed(window_ids):
            try:
                activated = subprocess.run(
                    ["xdotool", "windowactivate", "--sync", window_id],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
            except subprocess.SubprocessError:
                continue
            if activated.returncode == 0:
                # Focusing an outer Chromium window can leave a different tab active.
                # Re-activate the exact CDP target after the OS focus transition.
                if not self._activate_target_tab():
                    print(
                        "[SOLVER] Exact CDP target activation failed after "
                        f"focusing Linux window id={window_id}"
                    )
                    continue
                time.sleep(0.35)
                self._linux_window_id = window_id
                print(f"[SOLVER] Linux browser window focused id={window_id}")
                return True
        print("[SOLVER] No focusable Linux Chromium window was found.")
        return False

    def _focus_os_window(self):
        if os.name != "nt":
            return self._focus_linux_window()
        self._bring_to_front()
        hwnd = None
        client = self._win32_client_origin()
        if client:
            hwnd = client.get("hwnd")
        if not hwnd:
            hwnd = self._edge_hwnd()
        focused = self._force_foreground_hwnd(hwnd) if hwnd else False
        print(f"[SOLVER] OS window focus hwnd={hwnd} focused={focused}")
        return focused

    def _linux_window_geometry(self):
        if os.name == "nt" or not str(self._linux_window_id or "").isdigit():
            return None
        try:
            result = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", str(self._linux_window_id)],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        values = {}
        for line in result.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator and key in {"X", "Y", "WIDTH", "HEIGHT"}:
                try:
                    values[key.lower()] = float(value)
                except ValueError:
                    return None
        if values.get("width", 0) < 200 or values.get("height", 0) < 200:
            return None
        return values

    def _linux_window_frame_extents(self):
        """Return compositor frame extents in physical pixels for the focused X11 window."""
        if os.name == "nt" or not str(self._linux_window_id or "").isdigit():
            return None
        try:
            result = subprocess.run(
                [
                    "xprop",
                    "-id",
                    str(self._linux_window_id),
                    "_NET_FRAME_EXTENTS",
                    "_GTK_FRAME_EXTENTS",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        properties = {}
        for line in result.stdout.splitlines():
            property_name, separator, raw_values = line.partition("=")
            property_name = property_name.split("(", 1)[0].strip()
            if not separator or property_name not in {"_NET_FRAME_EXTENTS", "_GTK_FRAME_EXTENTS"}:
                continue
            values = re.findall(r"-?\d+(?:\.\d+)?", raw_values)
            if len(values) >= 4:
                properties[property_name] = {
                    key: max(float(value), 0.0)
                    for key, value in zip(("left", "right", "top", "bottom"), values[:4])
                }
        return properties.get("_NET_FRAME_EXTENTS") or properties.get("_GTK_FRAME_EXTENTS")

    def _css_to_x11_window_screen(self, start_x, start_y, distance):
        """Map CSS through the exact focused X11 window when GPU screenshots are opaque."""
        if os.name == "nt" or not self._target_activation_verified:
            return None
        geometry = self._linux_window_geometry()
        frame_extents = self._linux_window_frame_extents()
        metrics = self._window_metrics()
        bounds = self._browser_window_bounds()
        if not geometry or not isinstance(metrics, dict) or not isinstance(bounds, dict):
            return None
        try:
            dpr = float(metrics.get("dpr") or 1) or 1.0
            inner_w = float(metrics.get("innerWidth") or 0)
            inner_h = float(metrics.get("innerHeight") or 0)
            outer_w = float(metrics.get("outerWidth") or 0)
            outer_h = float(metrics.get("outerHeight") or 0)
            bound_left = float(bounds.get("left") or 0) * dpr
            bound_top = float(bounds.get("top") or 0) * dpr
            bound_width = float(bounds.get("width") or 0) * dpr
            bound_height = float(bounds.get("height") or 0) * dpr
        except (TypeError, ValueError):
            return None
        if min(inner_w, inner_h, outer_w, outer_h, bound_width, bound_height) <= 0:
            return None
        position_delta = math.hypot(geometry["x"] - bound_left, geometry["y"] - bound_top)
        size_delta = max(
            abs(geometry["width"] - bound_width),
            abs(geometry["height"] - bound_height),
        )
        if position_delta > 48.0 or size_delta > 64.0:
            print(
                f"[SOLVER] X11/CDP window geometry mismatch "
                f"position_delta={position_delta:.0f}px size_delta={size_delta:.0f}px."
            )
            return None
        scale_x = geometry["width"] / outer_w
        scale_y = geometry["height"] / outer_h
        if abs(scale_x - scale_y) > 0.08:
            return None
        chrome_left = max(0.0, (outer_w - inner_w) * scale_x / 2.0)
        # outerHeight-innerHeight includes the bottom client-side decoration on
        # GNOME/Xwayland. Only the top frame and browser UI precede clientY=0.
        frame_bottom = float((frame_extents or {}).get("bottom") or 0.0)
        chrome_top = max(0.0, (outer_h - inner_h) * scale_y - frame_bottom)
        return {
            "x": geometry["x"] + chrome_left + float(start_x) * scale_x,
            "y": geometry["y"] + chrome_top + float(start_y) * scale_y,
            "distance": float(distance) * scale_x,
            "source": "x11_window_geometry",
            "frame_bottom": frame_bottom,
            "region": (
                int(geometry["x"]),
                int(geometry["y"]),
                int(geometry["width"]),
                int(geometry["height"]),
            ),
        }


__all__ = ["CaptchaOSWindowsMixin"]
