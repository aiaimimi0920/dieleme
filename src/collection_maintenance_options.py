"""Normalize bounded maintenance inputs before invoking collection services."""


def nonnegative_integer(
    value: object, default: int, *, negative: int | None = None
) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return default
    try:
        number = int(value)
    except ValueError:
        return default
    if number < 0:
        return default if negative is None else negative
    return number
