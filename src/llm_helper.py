"""Compatibility facade for Crow LLM backends and extraction helpers."""

from __future__ import annotations

import _thread as thread
import base64
import datetime
from datetime import datetime
import functools as _functools
from html import unescape
import hashlib
import hmac
import importlib as _importlib
import json
import json as _json
import os
import os as _os
import queue
import random
import re
import ssl
import threading
import time
from time import mktime
import types as _types
from urllib.parse import urlparse
from wsgiref.handlers import format_date_time

from bs4 import BeautifulSoup
import requests
import websocket


_IMPLEMENTATION_MODULES = (
    "src.llm_config",
    "src.llm_metrics",
    "src.llm_model_selector",
    "src.llm_websocket",
    "src.llm_openai_compatible",
    "src.llm_text_extraction",
    "src.llm_product_extraction",
    "src.llm_auction_extraction",
    "src.llm_avm_risk",
)


def _clone_function(
    function: _types.FunctionType,
    *,
    qualname: str | None = None,
) -> _types.FunctionType:
    clone = _types.FunctionType(
        function.__code__,
        globals(),
        function.__name__,
        function.__defaults__,
        function.__closure__,
    )
    _functools.update_wrapper(clone, function)
    clone.__kwdefaults__ = dict(function.__kwdefaults__ or {})
    clone.__module__ = __name__
    clone.__qualname__ = qualname or function.__name__
    return clone


for _module_name in _IMPLEMENTATION_MODULES:
    _module = _importlib.import_module(_module_name)
    for _name in _module.__all__:
        _value = getattr(_module, _name)
        if isinstance(_value, _types.FunctionType) and _value.__module__ == _module.__name__:
            globals()[_name] = _clone_function(_value)
        else:
            globals()[_name] = _value


if __name__ == "__main__":
    print("Testing GLM-4.7 (WebSocket)...")
    response = chat_with_glm(
        '你好，请做一个简单的自我介绍，并返回JSON格式: {"name": "AI", "role": "Assistant"}'
    )
    print(f"Response: {response}")
