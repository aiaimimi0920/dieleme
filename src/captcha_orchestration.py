from __future__ import annotations

from .captcha_context import *  # noqa: F401,F403


class CaptchaOrchestrationMixin:
    def solve(
        self,
        max_attempts=50,
        nc_retry_replay_limit=None,
        slider_find_max_retries=None,
        drag_profile_offset=0,
    ):
        """Main solve method - tries all methods in priority order."""
        with self.lock:
            self.last_failure_reason = None

            def finish(result):
                if not result and self.last_failure_reason == "manual_required":
                    if self.ws:
                        try:
                            self.ws.close()
                        except Exception:
                            pass
                        self.ws = None
                    self._opened_target_ids.clear()
                    return result
                self._close_owned_target_tabs()
                return result

            connected_for_first_attempt = False
            if self._stop_if_cancelled():
                return finish(False)

            preflight = self._preflight_current_challenge()
            local_mock_target = self._is_local_mock_slider_target()
            if preflight.get("manual_required"):
                self.last_failure_reason = "manual_required"
                return finish(False)
            if preflight.get("already_authenticated"):
                return finish(True)
            if preflight.get("connected") and preflight.get("has_slider"):
                connected_for_first_attempt = True
                print("[SOLVER] Active slider challenge detected; using CDP method first.")
            else:
                if not local_mock_target and self._headed_playwright_enabled():
                    # Try ddddocr AI FIRST
                    try:
                        print("[SOLVER] [AI] Attempting ddddocr AI识别...")
                        if self._solve_with_ddddocr():
                            return finish(True)
                    except Exception as e:
                        print(f"[SOLVER] ddddocr error: {e}")

                    # Try Playwright Stealth
                    try:
                        print("[SOLVER] [STAR] Attempting Playwright Stealth...")
                        if self._solve_with_playwright_stealth():
                            return finish(True)
                    except Exception as e:
                        print(f"[SOLVER] Playwright Stealth error: {e}")
                else:
                    if local_mock_target:
                        print("[SOLVER] Local mock target detected; skipping headed solver fallbacks.")
                    else:
                        print("[SOLVER] Skipping headed Playwright solvers because no DISPLAY/WAYLAND_DISPLAY is available.")

                if local_mock_target:
                    print("[SOLVER] Local mock target detected; using CDP solve path directly.")
                else:
                    # Userscript DOM events are isTrusted=false and burn the NC challenge.
                    print("[SOLVER] Skipping userscript fallback on live targets; using CDP drag.")

            # CDP mouse drag (buttons bitmask + slow human path)
            print("[SOLVER] Using CDP method...")
            attempt = 0
            nc_retry_replays = 0
            if nc_retry_replay_limit is None:
                nc_retry_replay_limit = self._nc_retry_replay_limit()
            else:
                nc_retry_replay_limit = max(0, int(nc_retry_replay_limit))
            try:
                drag_profile_offset = int(drag_profile_offset or 0) % max(len(self._os_drag_profiles()), 1)
            except (TypeError, ValueError):
                drag_profile_offset = 0

            while attempt < max_attempts:
                attempt += 1
                if self._stop_if_cancelled():
                    return finish(False)
                print(f"\n[SOLVER] === Attempt {attempt}/{max_attempts} ===")

                # 每一轮都重新连接目标页签，避免 ws 失效后卡死
                if connected_for_first_attempt:
                    connected_for_first_attempt = False
                elif not self.connect_tab():
                    if self.last_failure_reason == "manual_required":
                        return finish(False)
                    print("[SOLVER] [X] connect_tab 失败，5秒后重试...")
                    time.sleep(5)
                    continue

                print("[SOLVER] Connected to browser. Starting solve loop...")
                self._bring_to_front()

                try:
                    # Step 1: Find Slider
                    if slider_find_max_retries is None:
                        slider_info = self._find_slider()
                    else:
                        slider_info = self._find_slider(
                            max_retries=max(1, int(slider_find_max_retries)),
                            retry_delay=0,
                        )
                    if not slider_info:
                        challenge_summary = self._page_challenge_summary()
                        if challenge_summary.get("authenticatedPage"):
                            print("[SOLVER] Auction page became accessible; captcha is already resolved.")
                            self.last_failure_reason = None
                            if self.ws:
                                try:
                                    self.ws.close()
                                except Exception:
                                    pass
                                self.ws = None
                            return finish(True)
                        if challenge_summary.get("hardBlock") and not challenge_summary.get("hasSlider"):
                            print("[SOLVER] Hard block without slider; trying NC retry-click to restore slider.")
                            restored = self._reset_failed_nc_challenge()
                            if restored:
                                print("[SOLVER] NC slider restored after retry-click; continuing loop...")
                                if self.ws:
                                    try:
                                        self.ws.close()
                                    except:
                                        pass
                                    self.ws = None
                                continue
                            print("[SOLVER] [X] Unsupported hard block detected; manual verification required.")
                            self.last_failure_reason = "manual_required"
                            if self.ws:
                                try:
                                    self.ws.close()
                                except:
                                    pass
                            return finish(False)
                        if challenge_summary.get("loginRequired"):
                            print("[SOLVER] Login page detected; manual login is required.")
                            self.last_failure_reason = "manual_required"
                            if self.ws:
                                try:
                                    self.ws.close()
                                except Exception:
                                    pass
                                self.ws = None
                            return finish(False)
                        print("[SOLVER] Slider not found after retries. Reload + continue...")
                        self._reload_page()
                        time.sleep(0.2 if local_mock_target else random.uniform(1, 2))
                        self._close_solver_ws()
                        continue

                    start_x = slider_info["x"] + (slider_info["width"] / 2)
                    start_y = slider_info["y"] + (slider_info["height"] / 2)

                    # Sanity check
                    if start_x < 10 or start_y < 10:
                        print(f"[SOLVER] Invalid coordinates: ({start_x}, {start_y}) -> reload + continue")
                        self._reload_page()
                        time.sleep(0.2 if local_mock_target else random.uniform(1, 2))
                        if self.ws:
                            try:
                                self.ws.close()
                            except:
                                pass
                        continue

                    # Human hesitation before action (NC needs time to bind listeners)
                    time.sleep(0.05 if local_mock_target else random.uniform(1.5, 2.4))

                    print(f"[SOLVER] Slider found at ({start_x:.0f}, {start_y:.0f}) "
                          f"[Selector: {slider_info.get('selector')}, Context: {slider_info.get('context')}]")

                    # Step 2: Get Track Width (dynamic)
                    track_width = self._get_track_width()
                    slider_info["track_width"] = track_width
                    track_rect = self._get_track_rect()

                    # Calculate actual drag distance
                    # NC captcha needs slider to reach nearly the end (95-100%)
                    if local_mock_target:
                        distance = max(1, track_width - slider_info["width"] - 8)
                    else:
                        # The challenge can leave the handle part-way across the
                        # track after a rejected attempt. Calculate the remaining
                        # distance from the live rectangles instead of assuming the
                        # handle is always at the left edge.
                        remaining = None
                        if isinstance(track_rect, dict):
                            track_right = float(track_rect.get("left") or 0) + float(track_rect.get("width") or 0)
                            slider_right = float(slider_info.get("x") or 0) + float(slider_info.get("width") or 0)
                            candidate = track_right - slider_right
                            if 0 < candidate <= track_width + slider_info["width"]:
                                remaining = candidate
                            track_offset_width = float(track_rect.get("offsetWidth") or track_width)
                            handle_offset_width = float(track_rect.get("handleOffsetWidth") or slider_info["width"])
                            current_handle_left = track_rect.get("handleOffsetLeft")
                            if current_handle_left is not None:
                                target_handle_left = track_offset_width - handle_offset_width
                                offset_remaining = target_handle_left - float(current_handle_left)
                                if 0 <= offset_remaining <= track_width + slider_info["width"]:
                                    # NC uses offsetWidth/offsetLeft internally;
                                    # those include the exact 2px border correction
                                    # that getBoundingClientRect() hides.
                                    remaining = offset_remaining
                        if remaining is None:
                            remaining = track_width - slider_info["width"] + 2
                        distance = max(1, min(remaining, 1000))
                    print(
                        f"[SOLVER] Drag distance: {distance:.0f}px "
                        f"(track: {track_width:.0f}px, slider: {slider_info['width']:.0f}px)"
                    )

                    # Step 3: Execute drag
                    self._bring_to_front()
                    time.sleep(0.05 if local_mock_target else random.uniform(0.2, 0.5))
                    if local_mock_target:
                        drag_result = self._do_drag_local_mock(start_x, start_y, distance)
                    elif self._os_mouse_enabled():
                        print("[SOLVER] Using OS-level mouse drag for live NC challenge.")
                        drag_profile_variant = (
                            drag_profile_offset
                            + min(nc_retry_replays, len(self._os_drag_profiles()) - 1)
                        ) % len(self._os_drag_profiles())
                        drag_result = self._do_drag_os(
                            start_x,
                            start_y,
                            distance,
                            slider_info=slider_info,
                            profile_variant_index=drag_profile_variant,
                        )
                        if drag_result is None:
                            os_drag_failure = str(self.last_failure_reason or "")
                            mapping_or_focus_failure = (
                                os_drag_failure == "window_focus_failed"
                                or os_drag_failure.startswith("screen_mapping_")
                                or os_drag_failure == "os_cursor_position_unverified"
                            )
                            if mapping_or_focus_failure:
                                print(
                                    "[SOLVER] OS focus/mapping was not verified; "
                                    "skipping unsafe CDP drag fallback."
                                )
                            else:
                                print("[SOLVER] OS mouse unavailable; falling back to CDP drag.")
                                drag_result = self._do_drag(start_x, start_y, distance)
                    else:
                        drag_result = self._do_drag(start_x, start_y, distance)
                    if drag_result is None:
                        if self.last_failure_reason in {"manual_required", "cancelled"}:
                            if self.ws:
                                try:
                                    self.ws.close()
                                except Exception:
                                    pass
                                self.ws = None
                            return finish(False)
                        print("[SOLVER] Drag did not complete. Reload + continue...")
                        self._reload_page()
                        self._bring_to_front()
                        time.sleep(0.2 if local_mock_target else random.uniform(1, 2))
                        if self.ws:
                            try:
                                self.ws.close()
                            except Exception:
                                pass
                            self.ws = None
                        continue
                    if self.last_failure_reason == "manual_required":
                        if self.ws:
                            try:
                                self.ws.close()
                            except Exception:
                                pass
                            self.ws = None
                        return finish(False)
                    print("[SOLVER] Drag complete. Verifying...")

                    # Step 4: Verify Success
                    time.sleep(0.15 if local_mock_target else random.uniform(1.8, 2.4))

                    if self._wait_for_verification_success():
                        print("\033[92m[SOLVER] [OK] Verified: Captcha solved!\033[0m")
                        self.last_failure_reason = None

                        # Phase 3.1: We DO NOT close the page anymore.
                        # The userscript handles redirecting it back to standby.
                        print("[SOLVER] Leaving worker tab alive for userscript redirect.")

                        self._close_solver_ws()
                        return finish(True)

                    if self.last_failure_reason == "manual_required":
                        return finish(False)

                    print("\033[93m[SOLVER] [X] Verification failed. Reload + unlimited retry...\033[0m")
                    challenge_summary = self._page_challenge_summary()
                    print(
                        "[SOLVER] Challenge diagnostic: "
                        f"{self._challenge_failure_diagnostic(challenge_summary)}"
                    )
                    if challenge_summary.get("authenticatedPage"):
                        print("\033[92m[SOLVER] [OK] Auction page is accessible after drag; treating as solved.\033[0m")
                        self.last_failure_reason = None
                        self._close_solver_ws()
                        return finish(True)
                    if (
                        not local_mock_target
                        and challenge_summary.get("hasSlider")
                        and not challenge_summary.get("explicitFailure")
                        and nc_retry_replays < nc_retry_replay_limit
                    ):
                        # Preserve the live handle position. The next pass uses
                        # the current rectangles to drag only the residual
                        # distance, matching the path that has solved real NC
                        # challenges. Explicit failures are reset below.
                        nc_retry_replays += 1
                        print(
                            "[SOLVER] Slider is still present without an explicit failure; "
                            f"keeping its live position and switching to the next drag profile "
                            "without spending a main attempt "
                            f"({nc_retry_replays}/{nc_retry_replay_limit})."
                        )
                        self._close_solver_ws()
                        attempt = max(attempt - 1, 0)
                        time.sleep(random.uniform(0.4, 0.9))
                        continue
                    if challenge_summary.get("explicitFailure"):
                        if nc_retry_replays < nc_retry_replay_limit:
                            if self._reset_failed_nc_challenge():
                                nc_retry_replays += 1
                                print(
                                    "[SOLVER] Challenge asked to retry; "
                                    f"replaying drag without spending a main attempt "
                                    f"({nc_retry_replays}/{nc_retry_replay_limit})."
                                )
                                self._close_solver_ws()
                                attempt = max(attempt - 1, 0)
                                continue
                        print("[SOLVER] [X] Official challenge explicitly rejected the automated drag; manual verification required.")
                        self.last_failure_reason = "manual_required"
                        self._close_solver_ws()
                        return finish(False)
                    self._reload_page()
                    self._bring_to_front()
                    time.sleep(0.2 if local_mock_target else random.uniform(1, 2))

                except Exception as e:
                    print(f"[SOLVER] Error during steps: {e}")
                    import traceback
                    traceback.print_exc()
                    self._close_solver_ws()
                    print("[SOLVER] Exception branch, 3秒后继续重试...")
                    time.sleep(3)
                    continue

            print(f"[SOLVER] [X] Max attempts ({max_attempts}) reached without success")
            recovered_authenticated_page = bool(
                not local_mock_target and self._recover_authenticated_list_page()
            )
            self._close_solver_ws()
            if recovered_authenticated_page:
                print("\033[92m[SOLVER] [OK] List page is authenticated after challenge attempts; clearing auth lock path.\033[0m")
                return finish(True)
            self.last_failure_reason = "max_attempts_exceeded"
            return finish(False)


__all__ = ["CaptchaOrchestrationMixin"]
