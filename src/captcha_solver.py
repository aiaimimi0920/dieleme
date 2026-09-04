from __future__ import annotations

import sys
import types

from .captcha_context import *  # noqa: F401,F403
from .captcha_target import CaptchaTargetMixin
from .captcha_cdp import CaptchaCDPMixin
from .captcha_slider import CaptchaSliderMixin
from .captcha_os_windows import CaptchaOSWindowsMixin
from .captcha_os_mapping import CaptchaOSMappingMixin
from .captcha_os_input import CaptchaOSInputMixin
from .captcha_nc_retry import CaptchaNCRetryMixin
from .captcha_preflight import CaptchaPreflightMixin
from .captcha_orchestration import CaptchaOrchestrationMixin
from .captcha_fallbacks import CaptchaFallbacksMixin


class CaptchaSolver(
    CaptchaTargetMixin,
    CaptchaCDPMixin,
    CaptchaSliderMixin,
    CaptchaOSWindowsMixin,
    CaptchaOSMappingMixin,
    CaptchaOSInputMixin,
    CaptchaNCRetryMixin,
    CaptchaPreflightMixin,
    CaptchaOrchestrationMixin,
    CaptchaFallbacksMixin,
):
    # Multiple selectors for different captcha variants
    SLIDER_SELECTORS = [
        '#nc_1_n1z', '#nc_2_n1z', '[id^="nc_"][id$="_n1z"]',
        '#nc_1_n1t', '#nc_2_n1t', '[id^="nc_"][id$="_n1t"]',  # NC captcha uses _n1t for button
        '.btn_slide', '.nc_iconfont.btn_slide', '.nc_scale .btn_slide', '.nc_wrapper .btn_slide',
        '.nc-slider-btn', '.slider-btn', '.nc-lang-cnt .btn_ok', '.btn_ok',
        '.icon-slide-arrow', '.nc-iconfont.icon-slide-arrow',  # NC specific
        '#mock-slider-handle'  # For testing with mock page
    ]
    TRACK_SELECTORS = [
        '#nc_1_n1t', '#nc_2_n1t', '[id^="nc_"][id$="_n1t"]',
        '.nc_scale', '.nc-lang-cnt', '.scale_text', '.slidetounlock', '.nc_wrapper',
        '.nc_scale_text', '[id^="nc_"][id*="scale_text"]',
        '.slider', '.nc-container .slider',  # NC track
        '#mock-slider-track'  # For testing with mock page
    ]


_MIXIN_MODULES = (
    "captcha_target",
    "captcha_cdp",
    "captcha_slider",
    "captcha_os_windows",
    "captcha_os_mapping",
    "captcha_os_input",
    "captcha_nc_retry",
    "captcha_preflight",
    "captcha_orchestration",
    "captcha_fallbacks",
)


class _CaptchaFacadeModule(types.ModuleType):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        context = sys.modules.get(f"{__package__}.captcha_context")
        if context is None or not hasattr(context, name):
            return
        setattr(context, name, value)
        for suffix in _MIXIN_MODULES:
            module = sys.modules.get(f"{__package__}.{suffix}")
            if module is not None and hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _CaptchaFacadeModule

__all__ = ["CaptchaSolver", "DEFAULT_CDP_PAGE_TARGET_LIMIT", "LOCAL_MOCK_VERIFY_MODES"]

if __name__ == "__main__":
    s = CaptchaSolver()
    if s.solve():
        print("Done.")
    else:
        print("Failed.")
