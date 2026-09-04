from __future__ import annotations

import requests
import websocket
import json
import time
import random
import threading
import math
import os
import re
import subprocess
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(_sys.stderr, "reconfigure"):
    try:
        _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.parse import quote

from tools.cdp_browser_identity import browser_identity_init_script, build_user_agent_override

# Reconfigure stdout/stderr for safe encoding on Windows (GBK) consoles
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(_sys.stderr, "reconfigure"):
    try:
        _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_CDP_PAGE_TARGET_LIMIT = 12
LOCAL_MOCK_VERIFY_MODES = {"strict_success_text", "teardown_only", "explicit_fail", "near_miss", "retry_then_success"}

__all__ = [name for name in globals() if not name.startswith("__")]
