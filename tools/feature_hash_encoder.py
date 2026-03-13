"""Categorical feature hashing utilities for AVM style data.

需求要点：
- 对 community_name/city/district/housing_type/floor_level 做稳定哈希编码；
- 缺失值统一填充为 UNK；
- 显式输出缺失标记特征。
"""

from __future__ import annotations

import hashlib
from typing import Iterable

import pandas as pd

CATEGORICAL_COLUMNS = [
    "community_name",
    "city",
    "district",
    "housing_type",
    "floor_level",
]

UNK_TOKEN = "UNK"


def stable_hash(value: str, digest_size: int = 8) -> int:
    """Return a deterministic integer hash for a string value.

    Uses BLAKE2b for deterministic cross-run hashing (unlike Python built-in hash).
    """
    payload = value.encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=digest_size).digest()
    return int.from_bytes(digest, byteorder="big", signed=False)


def _normalize_with_missing_flag(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Normalize missing values to UNK and return missing flag.

    Missing is defined as NaN/None or empty string after stripping.
    """
    text = series.astype("string")
    is_missing = text.isna() | (text.str.strip() == "")
    normalized = text.where(~is_missing, UNK_TOKEN)
    return normalized, is_missing.astype("int8")


def encode_categorical_features(
    df: pd.DataFrame,
    columns: Iterable[str] = CATEGORICAL_COLUMNS,
) -> pd.DataFrame:
    """Encode selected categorical columns using stable hash + missing indicators.

    For each column `col`:
    - fill missing/blank with `UNK`
    - add `col_is_missing` (0/1)
    - add `col_hash` (uint64-like int)
    - overwrite `col` with normalized text
    """
    encoded = df.copy()

    for col in columns:
        if col not in encoded.columns:
            encoded[col] = UNK_TOKEN

        normalized, is_missing = _normalize_with_missing_flag(encoded[col])
        encoded[col] = normalized
        encoded[f"{col}_is_missing"] = is_missing
        encoded[f"{col}_hash"] = normalized.map(stable_hash)

    return encoded
