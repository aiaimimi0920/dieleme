from __future__ import annotations

from .captcha_context import *  # noqa: F401,F403


class CaptchaOSMappingMixin:
    def _css_to_cdp_window_screen(self, start_x, start_y, distance):
        """Map CSS coordinates to physical screen via CDP Browser.getWindowForTarget + dpr.
        Avoids OS window enumeration unreliability (wrong hwnd selection)."""
        metrics = self._window_metrics()
        bounds = self._browser_window_bounds()
        if not bounds or not isinstance(bounds, dict):
            return None
        inner_w = max(float(metrics.get("innerWidth") or 0), 1.0)
        inner_h = max(float(metrics.get("innerHeight") or 0), 1.0)
        dpr = float(metrics.get("dpr") or 1) or 1.0
        outer_w = float(metrics.get("outerWidth") or 0)
        outer_h = float(metrics.get("outerHeight") or 0)
        if outer_w <= 0 or outer_h <= 0:
            return None
        chrome_left = max(0.0, (outer_w - inner_w) / 2.0)
        chrome_top = max(0.0, outer_h - inner_h)
        return {
            "x": (float(bounds.get("left") or 0) + chrome_left + float(start_x)) * dpr,
            "y": (float(bounds.get("top") or 0) + chrome_top + float(start_y)) * dpr,
            "distance": float(distance) * dpr,
            "source": "cdp_window_bounds",
        }

    def _css_to_client_screen(self, start_x, start_y, distance):
        metrics = self._window_metrics()
        inner_w = max(float(metrics.get("innerWidth") or 0), 1.0)
        inner_h = max(float(metrics.get("innerHeight") or 0), 1.0)
        dpr = float(metrics.get("dpr") or 1) or 1.0
        client = self._win32_client_origin()
        if client:
            scale_x = client["width"] / inner_w
            if client.get("uses_render_widget"):
                toolbar_phys = 0.0
            else:
                page_phys_h = inner_h * scale_x
                toolbar_phys = max(0.0, client["height"] - page_phys_h)
            return {
                "x": client["left"] + float(start_x) * scale_x,
                "y": client["top"] + toolbar_phys + float(start_y) * scale_x,
                "distance": float(distance) * scale_x,
                "source": "win32_render" if client.get("uses_render_widget") else "win32_client",
                "uses_render_widget": bool(client.get("uses_render_widget")),
                "region": (
                    int(client["left"]),
                    int(client["top"]),
                    int(client["width"]),
                    int(client["height"]),
                ),
            }
        inner_h_css = float(metrics.get("innerHeight") or 0)
        outer_h = float(metrics.get("outerHeight") or 0)
        inner_w_css = float(metrics.get("innerWidth") or 0)
        outer_w = float(metrics.get("outerWidth") or 0)
        chrome_top = max(0.0, outer_h - (inner_h_css / dpr if dpr else inner_h_css))
        border = max(0.0, (outer_w - (inner_w_css / dpr if dpr else inner_w_css)) / 2)
        return {
            "x": (float(metrics.get("screenX") or 0) + border + float(start_x)) * dpr,
            "y": (float(metrics.get("screenY") or 0) + chrome_top + float(start_y)) * dpr,
            "distance": float(distance) * dpr,
            "source": "dpr_fallback",
            "region": None,
        }

    def _located_point_from_screenshot(self, located, start_x, start_y, distance):
        clip_w = max(float(located.get("clip_w") or located.get("width") or 1), 1.0)
        clip_h = max(float(located.get("clip_h") or located.get("height") or 1), 1.0)
        scale_x = located["width"] / clip_w
        scale_y = located["height"] / clip_h
        clip_x = float(located.get("clip_x") or 0)
        clip_y = float(located.get("clip_y") or 0)
        return {
            "x": located["left"] + (float(start_x) - clip_x) * scale_x,
            "y": located["top"] + (float(start_y) - clip_y) * scale_y,
            "distance": float(distance) * scale_x,
            "source": "screenshot_handle" if located.get("clipped") else "screenshot_viewport",
        }

    def _clamp_search_region(self, search_region, screen_size):
        if not search_region or len(search_region) != 4:
            return None
        try:
            left, top, width, height = (int(search_region[0]), int(search_region[1]), int(search_region[2]), int(search_region[3]))
            screen_width, screen_height = (int(screen_size[0]), int(screen_size[1]))
        except (TypeError, ValueError, IndexError):
            return None
        if width <= 0 or height <= 0 or screen_width <= 0 or screen_height <= 0:
            return None
        right = min(left + width, screen_width)
        bottom = min(top + height, screen_height)
        left = max(left, 0)
        top = max(top, 0)
        if right <= left or bottom <= top:
            return None
        return (left, top, right - left, bottom - top)

    def _slider_search_region(self, expected, distance, slider_info=None):
        """Bound template matching around the expected live slider position."""
        if not isinstance(expected, dict):
            return None
        try:
            start_x = float(expected["x"])
            start_y = float(expected["y"])
            mapped_distance = abs(float(expected.get("distance", distance) or 0))
            handle_width = float((slider_info or {}).get("width") or 42)
            handle_height = float((slider_info or {}).get("height") or 34)
        except (KeyError, TypeError, ValueError):
            return expected.get("region")
        horizontal_margin = 96.0
        vertical_margin = 80.0
        return (
            int(start_x - horizontal_margin),
            int(start_y - vertical_margin),
            int(max(mapped_distance + handle_width + horizontal_margin * 2, 240.0)),
            int(max(handle_height + vertical_margin * 2, 160.0)),
        )

    def _viewport_origin_on_screen(self, slider_info=None, search_region=None, drag_distance=0):
        """Locate the page viewport (or slider/track) on the physical screen via screenshot."""
        try:
            import base64
            import io
            import tempfile
            from pathlib import Path
            import pyautogui
            from PIL import Image
        except ImportError:
            return None

        clip = None
        if isinstance(slider_info, dict):
            track_w = float(slider_info.get("track_width") or 0)
            if track_w <= 0:
                track_w = float(slider_info.get("width") or 0) + float(drag_distance or 0) + 8
            clip = {
                "x": max(0, float(slider_info.get("x") or 0) - 2),
                "y": max(0, float(slider_info.get("y") or 0) - 4),
                "width": max(float(slider_info.get("width") or 0) + 4, track_w + 4),
                "height": max(float(slider_info.get("height") or 0) + 8, 36),
                "scale": 1,
            }
        params = {"format": "png", "fromSurface": True}
        if clip:
            params["clip"] = clip
        shot = self._send_cdp("Page.captureScreenshot", params)
        data = shot.get("data") if isinstance(shot, dict) else None
        if not data:
            return None
        raw = base64.b64decode(data)
        try:
            shot_w, shot_h = Image.open(io.BytesIO(raw)).size
        except Exception:
            shot_w = shot_h = 0
        tmp = Path(tempfile.gettempdir()) / ("fapai_nc_track.png" if clip else "fapai_nc_viewport.png")
        tmp.write_bytes(raw)
        locate_kwargs = {}
        clamped_region = self._clamp_search_region(search_region, pyautogui.size())
        if clamped_region:
            locate_kwargs["region"] = clamped_region

        def locate_on_screen(kwargs):
            last_error = None
            try:
                box = pyautogui.locateOnScreen(str(tmp), confidence=0.82, **kwargs)
                if box is not None:
                    return box, None
            except Exception as error:
                last_error = error
            try:
                box = pyautogui.locateOnScreen(str(tmp), **kwargs)
                if box is not None:
                    return box, None
            except Exception as error:
                last_error = error
            return None, last_error

        box, locate_error = locate_on_screen(locate_kwargs)
        if box is None and clamped_region:
            print("[SOLVER] Regional screenshot locate missed; retrying on the full screen.")
            box, full_screen_error = locate_on_screen({})
            locate_error = full_screen_error or locate_error
        if box is None:
            if locate_error is not None:
                print(f"[SOLVER] Screenshot locate failed: {locate_error}")
            return None
        return {
            "left": float(box.left),
            "top": float(box.top),
            "width": float(box.width),
            "height": float(box.height),
            "shot_w": float(shot_w or box.width),
            "shot_h": float(shot_h or box.height),
            "clipped": bool(clip),
            "clip_x": float(clip["x"]) if clip else 0.0,
            "clip_y": float(clip["y"]) if clip else 0.0,
            "clip_w": float(clip["width"]) if clip else float(shot_w or box.width),
            "clip_h": float(clip["height"]) if clip else float(shot_h or box.height),
        }

    def _map_css_to_screen(
        self,
        start_x,
        start_y,
        distance,
        slider_info=None,
        *,
        allow_zero_distance=False,
    ):
        """Map CSS viewport coordinates to physical screen pixels for OS mouse input."""
        expected = self._css_to_client_screen(start_x, start_y, distance)
        cdp_expected = self._css_to_cdp_window_screen(start_x, start_y, distance)
        if expected and cdp_expected:
            dx = abs(float(expected["x"]) - float(cdp_expected["x"]))
            dy = abs(float(expected["y"]) - float(cdp_expected["y"]))
            # win32 enumeration can pick the wrong top-level window when multiple Edge
            # windows exist on different monitors. CDP window bounds are authoritative.
            if dx > 200.0 or dy > 200.0:
                print(
                    f"[SOLVER] Screen map win32=({expected['x']:.0f},{expected['y']:.0f}) "
                    f"cdp=({cdp_expected['x']:.0f},{cdp_expected['y']:.0f}) "
                    f"delta=({dx:.0f},{dy:.0f}); using CDP window bounds"
                )
                expected = cdp_expected
            else:
                expected.setdefault("uses_render_widget", False)
        elif not expected and cdp_expected:
            expected = cdp_expected
        x11_expected = self._css_to_x11_window_screen(start_x, start_y, distance)
        if x11_expected:
            expected = x11_expected
        activation_verified = bool(
            self._target_activation_verified
            and expected
            and expected.get("source") in {
                "win32_render",
                "cdp_window_bounds",
                "dpr_fallback",
                "x11_window_geometry",
            }
        )
        screenshot_search_region = self._slider_search_region(
            expected,
            distance,
            slider_info=slider_info,
        )
        if x11_expected:
            # Hardware-accelerated Chrome on Xwayland can render as black to
            # XGetImage/scrot. Matching the exact activated target's CDP bounds
            # to its physical X11 window is the stronger available proof.
            located = None
            print("[SOLVER] X11/CDP window geometry verified for physical slider mapping.")
        elif activation_verified:
            # Activation proves the tab identity, not that the render widget is
            # still at the same physical origin. Take a screenshot-backed sample
            # while the exact target is foregrounded and use it when it disagrees.
            located = self._viewport_origin_on_screen(
                slider_info,
                search_region=screenshot_search_region,
                drag_distance=distance,
            )
            if located is None:
                print(
                    "[SOLVER] Exact CDP target activation verified; "
                    f"screenshot mapping unavailable, falling back to {expected.get('source')}."
                )
        else:
            located = self._viewport_origin_on_screen(
                slider_info,
                search_region=screenshot_search_region,
                drag_distance=distance,
            )
        screenshot_point = None
        delta = None
        if located:
            screenshot_point = self._located_point_from_screenshot(
                located, start_x, start_y, distance
            )
        if screenshot_point and expected:
            delta = (
                (screenshot_point["x"] - expected["x"]) ** 2
                + (screenshot_point["y"] - expected["y"]) ** 2
            ) ** 0.5
        screenshot_delta_limit = max(64.0, abs(float(distance or 0)) * 0.35)
        physical_mapping_required = os.name != "nt" and isinstance(slider_info, dict)
        if (
            physical_mapping_required
            and located
            and located.get("clipped")
            and expected
            and delta is not None
            and delta > screenshot_delta_limit
        ):
            # A narrow NC track is visually repetitive and can produce a high-
            # confidence false match elsewhere on the desktop. Verify the whole
            # foregrounded viewport before trusting a large coordinate jump.
            print(
                f"[SOLVER] Clipped screenshot map drifted {delta:.0f}px; "
                "retrying with the full viewport."
            )
            viewport_located = self._viewport_origin_on_screen(
                None,
                search_region=None,
                drag_distance=distance,
            )
            if viewport_located:
                located = viewport_located
                screenshot_point = self._located_point_from_screenshot(
                    located, start_x, start_y, distance
                )
                delta = (
                    (screenshot_point["x"] - expected["x"]) ** 2
                    + (screenshot_point["y"] - expected["y"]) ** 2
                ) ** 0.5
            else:
                located = None
                screenshot_point = None
                delta = None
        chosen = expected
        if screenshot_point and not expected:
            chosen = screenshot_point
        elif screenshot_point and expected.get("source") == "dpr_fallback":
            # On Linux the DPR calculation does not prove which tab is physically
            # visible. A matching CDP template on the desktop is authoritative.
            chosen = screenshot_point
        elif (
            screenshot_point
            and not expected.get("uses_render_widget")
            and delta is not None
            and delta <= screenshot_delta_limit
        ):
            chosen = screenshot_point
        elif (
            screenshot_point
            and expected.get("uses_render_widget")
            and delta is not None
            and delta <= max(48.0, abs(float(distance or 0)) * 0.15)
        ):
            chosen = expected
        elif screenshot_point and delta is not None and delta > screenshot_delta_limit:
            print(
                f"[SOLVER] Rejecting screenshot map with implausible {delta:.0f}px drift; "
                f"using {expected.get('source')}."
            )
        if screenshot_point and expected:
            print(
                f"[SOLVER] Screen map expected=({expected['x']:.0f},{expected['y']:.0f}) "
                f"screenshot=({screenshot_point['x']:.0f},{screenshot_point['y']:.0f}) "
                f"delta={delta:.0f}px source={chosen.get('source')} "
                f"render={bool(expected.get('uses_render_widget'))}"
            )
        if not chosen:
            self.last_failure_reason = "screen_mapping_unavailable"
            print("[SOLVER] Screen mapping unavailable; skipping OS drag.")
            return None
        try:
            mapped_values = (float(chosen["x"]), float(chosen["y"]), float(chosen["distance"]))
        except (KeyError, TypeError, ValueError):
            self.last_failure_reason = "screen_mapping_invalid"
            print("[SOLVER] Screen mapping is invalid; skipping OS drag.")
            return None
        invalid_distance = mapped_values[2] < 0 if allow_zero_distance else mapped_values[2] <= 0
        if not all(math.isfinite(value) for value in mapped_values) or invalid_distance:
            self.last_failure_reason = "screen_mapping_invalid"
            print("[SOLVER] Screen mapping contains non-finite coordinates; skipping OS drag.")
            return None
        if physical_mapping_required and not located and not x11_expected:
            self.last_failure_reason = "screen_mapping_unverified"
            print("[SOLVER] Linux slider mapping requires screenshot or X11 geometry verification.")
            return None
        return {
            "x": mapped_values[0],
            "y": mapped_values[1],
            "distance": mapped_values[2],
            "source": chosen.get("source") or (expected.get("source") if expected else None),
            "located": bool(located or x11_expected or (activation_verified and not physical_mapping_required)),
            "clipped": bool(located and located.get("clipped")),
            "activation_verified": activation_verified,
        }


__all__ = ["CaptchaOSMappingMixin"]
