"""Fixed desktop write actions shared by the helper and same-host TLS proxy."""

RUNTIME_ACTIONS = frozenset({"start", "pause", "resume"})
ITEM_ACTION_PATHS = {
    "manual_update": "/api/collection/item/manual_update",
    "reanalyze": "/api/collection/item/reanalyze",
    "reset_links": "/api/collection/region/reset_links",
}
OPERATOR_ACTION_PATHS = {
    **{action: "/api/collection/control/" + action for action in RUNTIME_ACTIONS},
    **ITEM_ACTION_PATHS,
}


def _text(value: object, limit: int = 128) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= limit
        and not any(ord(char) < 32 for char in value)
    )


def validate_operator_body(action: str, body: object) -> None:
    if not isinstance(body, dict):
        raise ValueError("invalid_operator_body")
    if action in RUNTIME_ACTIONS:
        valid = not body
    elif action == "reset_links":
        valid = set(body) == {"location_code"} and _text(body["location_code"])
    elif action == "reanalyze":
        valid = (
            set(body) in ({"item_id"}, {"item_id", "reason"})
            and _text(body.get("item_id"))
            and ("reason" not in body or _text(body["reason"], 256))
        )
    elif action == "manual_update":
        updates = body.get("updates")
        valid = (
            set(body) == {"item_id", "updates"}
            and _text(body["item_id"])
            and isinstance(updates, dict)
            and 0 < len(updates) <= 256
            and all(_text(key) for key in updates)
        )
    else:
        valid = False
    if not valid:
        raise ValueError("invalid_operator_body")
