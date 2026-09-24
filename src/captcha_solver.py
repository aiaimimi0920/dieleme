from __future__ import annotations

import sys
import types
import os
import random
import time

import requests
import websocket

from . import captcha_dom

from .captcha_context import DEFAULT_CDP_PAGE_TARGET_LIMIT, LOCAL_MOCK_VERIFY_MODES
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
    SLIDER_SELECTORS = list(captcha_dom.SLIDER_SELECTORS)
    TRACK_SELECTORS = list(captcha_dom.TRACK_SELECTORS)


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
