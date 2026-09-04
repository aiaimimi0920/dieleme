from __future__ import annotations

import ast
import re
from pathlib import Path

import src.server as server_module


SERVER_PATHS = sorted(Path("src").glob("server*.py"))
CONTRACT_TEST_PATHS = sorted(
    set(Path("tools/test").glob("avm_http_contract*.py"))
    | set(Path("tools/test").rglob("test_*.py"))
    | set(Path("tests").rglob("test_*.py"))
)
AUTHENTICATED_OBJECT_JSON_ROUTES = {
    "/api/collection/auth/recovery/claim",
    "/api/collection/auth/recovery/pc2_restarting",
    "/api/collection/auth/recovery/result",
    "/api/collection/auth/recovery/snapshot_ready",
}


def _read(paths: list[Path]) -> str:
    return "\n".join(path.read_text(encoding="utf-8-sig") for path in paths)


def _function_sources() -> dict[str, str]:
    functions: dict[str, str] = {}
    for path in SERVER_PATHS:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[node.name] = ast.get_source_segment(source, node) or ""
            elif isinstance(node, ast.ClassDef) and node.name == "DataHandler":
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        functions[child.name] = ast.get_source_segment(source, child) or ""
    return functions


FUNCTION_SOURCES = _function_sources()


def _data_handler_method(method_name: str) -> ast.FunctionDef:
    tree = ast.parse(Path(server_module.__file__).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "DataHandler":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return child
    raise AssertionError(f"DataHandler.{method_name} not found")


def _condition_routes(condition: ast.expr) -> list[str]:
    routes: set[str] = set()
    for node in ast.walk(condition):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("/api/"):
                routes.add(node.value)
        elif isinstance(node, ast.Name):
            value = getattr(server_module, node.id, ())
            if isinstance(value, str) and value.startswith("/api/"):
                routes.add(value)
            elif isinstance(value, (tuple, list, set)):
                routes.update(item for item in value if isinstance(item, str) and item.startswith("/api/"))
    return sorted(routes)


def _dispatches(method_name: str) -> list[tuple[list[str], str]]:
    method = _data_handler_method(method_name)
    branch = next((node for node in method.body if isinstance(node, ast.If)), None)
    dispatches: list[tuple[list[str], str]] = []
    while branch is not None:
        helper_name = None
        for statement in branch.body:
            if not isinstance(statement, ast.Return) or not isinstance(statement.value, ast.Call):
                continue
            function = statement.value.func
            if isinstance(function, ast.Attribute):
                helper_name = function.attr
                break
        if helper_name is not None:
            dispatches.append((_condition_routes(branch.test), helper_name))
        branch = branch.orelse[0] if len(branch.orelse) == 1 and isinstance(branch.orelse[0], ast.If) else None
    return dispatches


def _route_sources(method_name: str) -> list[tuple[list[str], str]]:
    return [
        (routes, FUNCTION_SOURCES[helper_name])
        for routes, helper_name in _dispatches(method_name)
        if helper_name in FUNCTION_SOURCES
    ]


def _catches_value_error(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        exception_names = {
            child.id for child in ast.walk(node.type) if isinstance(child, ast.Name)
        }
        if "ValueError" in exception_names:
            return True
    return False


def _has_negative_compare(source: str, *, variable: str | None = None) -> bool:
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Compare) or not any(isinstance(op, ast.Lt) for op in node.ops):
            continue
        if variable is not None and not (isinstance(node.left, ast.Name) and node.left.id == variable):
            continue
        if any(isinstance(item, ast.Constant) and item.value == 0 for item in node.comparators):
            return True
    return False


def _get_invalid_numeric_query_route_paths() -> list[str]:
    return sorted([
        "/api/analysis/drift_status",
        "/api/analysis/release_gate",
        "/api/analysis/manual_review_control_plane_backup_repairs",
        "/api/analysis/manual_review_control_plane_integrity_history",
        "/api/analysis/manual_review_receipt_operations",
        "/api/avm/archive_detail_replay",
        "/api/avm/drift_status",
        "/api/avm/fetch_missing_detail_archives",
        "/api/avm/recent_detail_replay",
        "/api/avm/recent_gap_audit",
        "/api/avm/release_gate",
        "/api/avm/manual_review_control_plane_backup_repairs",
        "/api/avm/manual_review_control_plane_integrity_history",
        "/api/avm/manual_review_receipt_operations",
        "/api/collection/details/fetch_missing",
        "/api/collection/details/prepare_replay",
    ])


def _get_negative_limit_clamp_route_paths() -> list[str]:
    return sorted([
        "/api/analysis/manual_review_control_plane_backup_repairs",
        "/api/analysis/manual_review_control_plane_integrity_history",
        "/api/analysis/manual_review_receipt_operations",
        "/api/avm/archive_detail_replay",
        "/api/avm/fetch_missing_detail_archives",
        "/api/avm/manual_review_control_plane_backup_repairs",
        "/api/avm/manual_review_control_plane_integrity_history",
        "/api/avm/manual_review_receipt_operations",
        "/api/avm/recent_detail_replay",
        "/api/collection/details/fetch_missing",
        "/api/collection/details/prepare_replay",
    ])


def _get_negative_numeric_query_route_paths() -> list[str]:
    return sorted([
        "/api/analysis/drift_status",
        "/api/analysis/manual_review_control_plane_backup_repairs",
        "/api/analysis/manual_review_control_plane_integrity_history",
        "/api/analysis/manual_review_receipt_operations",
        "/api/analysis/release_gate",
        "/api/avm/archive_detail_replay",
        "/api/avm/drift_status",
        "/api/avm/fetch_missing_detail_archives",
        "/api/avm/manual_review_control_plane_backup_repairs",
        "/api/avm/manual_review_control_plane_integrity_history",
        "/api/avm/manual_review_receipt_operations",
        "/api/avm/recent_detail_replay",
        "/api/avm/recent_gap_audit",
        "/api/avm/release_gate",
        "/api/collection/details/fetch_missing",
        "/api/collection/details/prepare_replay",
    ])


def _source_routes_matching(predicate) -> list[str]:
    routes: set[str] = set()
    for branch_routes, source in _route_sources("do_GET"):
        if predicate(source):
            routes.update(branch_routes)
    return sorted(routes)


def _asserted_error_codes() -> set[str]:
    asserted: set[str] = set()
    for path in CONTRACT_TEST_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for assertion in (node for node in ast.walk(tree) if isinstance(node, ast.Assert)):
            for child in ast.walk(assertion.test):
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    if re.fullmatch(r"[A-Z][A-Z0-9_]+", child.value):
                        asserted.add(child.value)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if function_name not in {"assertEqual", "_assert_http_error_code"}:
                continue
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    if re.fullmatch(r"[A-Z][A-Z0-9_]+", argument.value):
                        asserted.add(argument.value)
    return asserted


def test_server_api_route_literals_are_referenced_by_http_contract_suite():
    routes = sorted(set(re.findall(r"['\"](/api/[^'\"\s]+)['\"]", _read(SERVER_PATHS))))
    suite_text = _read(CONTRACT_TEST_PATHS)
    assert [route for route in routes if route not in suite_text] == []


def test_server_structured_error_codes_are_referenced_by_http_contract_suite():
    codes = sorted(set(re.findall(r"code\s*=\s*['\"]([A-Z0-9_]+)['\"]", _read(SERVER_PATHS))))
    suite_text = _read(CONTRACT_TEST_PATHS)
    assert [code for code in codes if code not in suite_text] == []


def test_server_structured_error_codes_are_asserted_by_http_contract_suite():
    codes = set(re.findall(r"code\s*=\s*['\"]([A-Z0-9_]+)['\"]", _read(SERVER_PATHS)))
    assert sorted(codes - _asserted_error_codes()) == []


def test_public_route_json_loads_have_invalid_json_guardrails():
    route_sources = _route_sources("do_POST") + [
        (list(server_module.MANUAL_REVIEW_RECEIPT_ENDPOINTS), FUNCTION_SOURCES["do_DELETE"])
    ]
    missing = [routes for routes, source in route_sources if "json.loads" in source and "AVM_INVALID_JSON" not in source]
    assert missing == []


def test_public_route_object_json_sites_have_non_object_guardrails():
    route_sources = _route_sources("do_POST") + [
        (list(server_module.MANUAL_REVIEW_RECEIPT_ENDPOINTS), FUNCTION_SOURCES["do_DELETE"])
    ]
    missing = [
        routes
        for routes, source in route_sources
        if "json.loads" in source
        and "send_invalid_request_body" not in source
        and "AVM_INVALID_REQUEST_BODY" not in source
    ]
    assert missing == []


def test_live_sweep_object_json_route_inventory_matches_source():
    actual: set[tuple[str, str]] = set()
    for routes, source in _route_sources("do_POST"):
        if "json.loads" in source:
            actual.update((route, "POST") for route in routes)
    if "json.loads" in FUNCTION_SOURCES["do_DELETE"]:
        actual.update((route, "DELETE") for route in server_module.MANUAL_REVIEW_RECEIPT_ENDPOINTS)
    from tools.test.avm_http_contract_base import AVMHttpContractBase

    expected = set(AVMHttpContractBase._object_json_route_methods(None))
    expected.update((route, "POST") for route in AUTHENTICATED_OBJECT_JSON_ROUTES)
    assert sorted(actual) == sorted(expected)


def test_invalid_numeric_query_route_inventory_matches_source():
    assert _source_routes_matching(_catches_value_error) == _get_invalid_numeric_query_route_paths()


def test_negative_limit_clamp_route_inventory_matches_source():
    actual = _source_routes_matching(lambda source: _has_negative_compare(source, variable="limit"))
    assert actual == _get_negative_limit_clamp_route_paths()


def test_negative_numeric_query_route_inventory_matches_source():
    assert _source_routes_matching(_has_negative_compare) == _get_negative_numeric_query_route_paths()


def test_server_has_no_legacy_send_error_calls_in_public_handler():
    assert "self.send_error(" not in _read(SERVER_PATHS)


def test_server_bare_404s_are_only_non_api_fallbacks():
    bare_404_functions = {
        name for name, source in FUNCTION_SOURCES.items() if "self.send_response(404)" in source
    }
    assert bare_404_functions == {"do_DELETE", "_server_get_fallback", "_server_post_fallback"}
    assert "AVM_ENDPOINT_NOT_FOUND" in FUNCTION_SOURCES["do_DELETE"]
    assert "AVM_ENDPOINT_NOT_FOUND" in FUNCTION_SOURCES["_server_post_fallback"]
    get_source = FUNCTION_SOURCES["do_GET"]
    assert "request_path.startswith('/api/')" in get_source
    assert "self._server_get_fallback" in get_source
