#!/usr/bin/env python3
"""geocoding 服务商适配与坐标系转换。

国内 geocoding 返回的都不是 WGS-84：

- 高德 GCJ-02（国测局偏移）
- 百度 BD-09（在 GCJ-02 上再叠一层）
- `property_listing.geom` 是 SRID 4326，即 WGS-84

直接把 GCJ-02 当 WGS-84 入库会有 50-500 米系统偏移。同小区比价受影响有限
（同区域点位整体同向平移），但参与距离计算、半径筛选或与其他来源坐标比对时
就会出错。所以这里统一在入库前转成 WGS-84，并保留原始值便于回查。
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from typing import Any, Callable

# GCJ-02 偏移算法常量
_A = 6378245.0  # 克拉索夫斯基椭球长半轴
_EE = 0.00669342162296594323  # 偏心率平方

# 高德 level 里精度不足的类型。返回“市”“省”等于没有小区信息，
# 存进去会把整个城市的房源压到同一个点上，污染同小区比价。
_REJECTED_LEVELS = {"", "国家", "省", "市", "区县", "区", "县"}

# 中国大陆及港澳台的粗略经纬度包围盒，用于挡掉明显错误的结果
_CHINA_LAT_RANGE = (3.5, 53.6)
_CHINA_LON_RANGE = (73.5, 135.1)


class GeocodeProviderError(RuntimeError):
    """服务商返回了错误状态（key 无效、参数错误等）。"""


class GeocodeQuotaExceeded(GeocodeProviderError):
    """额度耗尽。必须与“查不到”区分，否则会把整批目标误标成无坐标。"""


# ---------- 坐标系转换 ----------


def _out_of_china(lat: float, lon: float) -> bool:
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def _delta(lat: float, lon: float) -> tuple[float, float]:
    d_lat = _transform_lat(lon - 105.0, lat - 35.0)
    d_lon = _transform_lon(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    d_lon = (d_lon * 180.0) / (_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return d_lat, d_lon


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    if _out_of_china(lat, lon):
        return lat, lon
    d_lat, d_lon = _delta(lat, lon)
    return lat + d_lat, lon + d_lon


def gcj02_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    """GCJ-02 -> WGS-84。偏移无解析逆函数，用一次减法近似（误差 < 1 米级）。"""
    if _out_of_china(lat, lon):
        return lat, lon
    d_lat, d_lon = _delta(lat, lon)
    return lat - d_lat, lon - d_lon


def bd09_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    x_pi = math.pi * 3000.0 / 180.0
    x = lon - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * x_pi)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * x_pi)
    return z * math.sin(theta), z * math.cos(theta)


def bd09_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    gcj_lat, gcj_lon = bd09_to_gcj02(lat, lon)
    return gcj02_to_wgs84(gcj_lat, gcj_lon)


# ---------- 结果可信度 ----------


def is_acceptable_level(level: Any) -> bool:
    return str(level or "").strip() not in _REJECTED_LEVELS


def is_plausible_china_coordinate(lat: Any, lon: Any) -> bool:
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return False
    return (
        _CHINA_LAT_RANGE[0] <= lat_f <= _CHINA_LAT_RANGE[1]
        and _CHINA_LON_RANGE[0] <= lon_f <= _CHINA_LON_RANGE[1]
    )


# ---------- 高德 ----------

_AMAP_QUOTA_INFOCODES = {"10003", "10004", "10019", "10020", "10021", "10044", "10045"}
_AMAP_QUOTA_KEYWORDS = ("OVER_LIMIT", "QUOTA", "TOO_FREQUENT", "CUQPS")


def parse_amap_response(body: str) -> dict[str, Any] | None:
    """解析高德 geo 接口响应，返回已转成 WGS-84 的结果，查不到返回 None。"""
    try:
        payload = json.loads(body)
    except (TypeError, ValueError) as error:
        raise GeocodeProviderError(f"amap response is not JSON: {error}") from error
    if not isinstance(payload, dict):
        raise GeocodeProviderError("amap response is not an object")

    if str(payload.get("status")) != "1":
        info = str(payload.get("info") or "UNKNOWN")
        infocode = str(payload.get("infocode") or "")
        if infocode in _AMAP_QUOTA_INFOCODES or any(k in info.upper() for k in _AMAP_QUOTA_KEYWORDS):
            raise GeocodeQuotaExceeded(f"amap quota exceeded: info={info} infocode={infocode}")
        raise GeocodeProviderError(f"amap error: info={info} infocode={infocode}")

    geocodes = payload.get("geocodes")
    if not isinstance(geocodes, list) or not geocodes:
        return None
    first = geocodes[0]
    if not isinstance(first, dict):
        return None

    location = str(first.get("location") or "")
    parts = location.split(",")
    if len(parts) != 2:
        return None
    try:
        raw_lon = float(parts[0])
        raw_lat = float(parts[1])
    except ValueError:
        return None

    if not is_plausible_china_coordinate(raw_lat, raw_lon):
        return None

    level = str(first.get("level") or "")
    lat, lon = gcj02_to_wgs84(raw_lat, raw_lon)
    return {
        "provider": "amap",
        "source_crs": "GCJ-02",
        "latitude": lat,
        "longitude": lon,
        "raw_latitude": raw_lat,
        "raw_longitude": raw_lon,
        "level": level,
        "formatted_address": str(first.get("formatted_address") or ""),
    }


def _default_fetch(url: str, *, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


class AmapGeocoder:
    """高德地理编码客户端。

    结果缓存包括查不到的情况：重跑时不该为同一个地址重复烧额度，而
    「查不到」往往是地址本身的问题，重试也不会变。
    """

    ENDPOINT = "https://restapi.amap.com/v3/geocode/geo"

    def __init__(
        self,
        *,
        api_key: str,
        fetch: Callable[..., str] = _default_fetch,
        timeout: float = 10.0,
    ) -> None:
        if not str(api_key or "").strip():
            raise ValueError("AmapGeocoder requires a non-empty api_key")
        self.api_key = str(api_key).strip()
        self._fetch = fetch
        self.timeout = timeout
        self._cache: dict[str, dict[str, Any] | None] = {}
        self.call_count = 0

    def geocode(self, query: str) -> dict[str, Any] | None:
        key = str(query or "").strip()
        if not key:
            return None
        if key in self._cache:
            return self._cache[key]

        params = urllib.parse.urlencode({"key": self.api_key, "address": key, "output": "JSON"})
        url = f"{self.ENDPOINT}?{params}"
        self.call_count += 1
        body = self._fetch(url, timeout=self.timeout)
        result = parse_amap_response(body)
        if result is not None and not is_acceptable_level(result.get("level")):
            result = None
        self._cache[key] = result
        return result
