import json
import os
import py_compile
import re
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

import src.server as server_module
from src.avm.service import AVMService


class TestAVMHttpContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name + "\\datas"

        import os

        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.data_dir + "\\2026-01-01.json", "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "id": "3001",
                        "url": "https://x/3001",
                        "成交价格": "100万",
                        "起拍价格": "80万",
                        "建筑面积": "100㎡",
                        "交易时间": "2026-01-01 10:00:00",
                        "城市": "上海市",
                        "区": "浦东新区",
                        "所属小区": "测试小区",
                        "纬度": 31.2,
                        "经度": 121.5,
                    },
                    {
                        "id": "3002",
                        "url": "https://x/3002",
                        "成交价格": "110万",
                        "起拍价格": "90万",
                        "建筑面积": "100㎡",
                        "交易时间": "2026-02-01 10:00:00",
                        "城市": "上海市",
                        "区": "浦东新区",
                        "所属小区": "测试小区",
                        "纬度": 31.2001,
                        "经度": 121.5001,
                    },
                ],
                f,
                ensure_ascii=False,
            )

        self.original_service = server_module.AVM_SERVICE
        self.original_start_time = server_module.AVM_SERVICE_START_TIME
        self.original_solver_pending_token = server_module.SOLVER_PENDING_TOKEN
        server_module.SOLVER_PENDING_TOKEN = None
        for manager in server_module.MANUAL_REVIEW_MAINTENANCE_MANAGERS.values():
            manager.shutdown(timeout=1.0)
        server_module.MANUAL_REVIEW_MAINTENANCE_MANAGERS.clear()
        server_module.AVM_SERVICE = AVMService(data_dir=self.data_dir)
        server_module.AVM_SERVICE_START_TIME = time.time() - 5

        self.httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for manager in server_module.MANUAL_REVIEW_MAINTENANCE_MANAGERS.values():
            manager.shutdown(timeout=1.0)
        server_module.MANUAL_REVIEW_MAINTENANCE_MANAGERS.clear()
        server_module.AVM_SERVICE = self.original_service
        server_module.AVM_SERVICE_START_TIME = self.original_start_time
        server_module.SOLVER_PENDING_TOKEN = self.original_solver_pending_token
        self.tmp.cleanup()

    def _get_json(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _post_json(self, path, payload, headers=None):
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _delete_json(self, path, payload, headers=None):
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
            method="DELETE",
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _assert_non_object_json_body_rejected(self, path, payload=None, method="POST"):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps([] if payload is None else payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_REQUEST_BODY")
        self.assertEqual(body["error"]["details"]["expected_type"], "object")
        self.assertEqual(body["error"]["details"]["received_type"], "list")

    def _assert_invalid_json_body_rejected(self, path, method="POST"):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def _assert_http_error_code(self, path, expected_status, expected_code, *, method="GET", payload=None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=None if payload is None else json.dumps(payload).encode("utf-8"),
            headers={} if payload is None else {"Content-Type": "application/json"},
            method=method,
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request)

        self.assertEqual(ctx.exception.code, expected_status)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], expected_code)
        return body

    def _contract_source_texts(self):
        return (
            Path(server_module.__file__).read_text(encoding="utf-8"),
            Path(__file__).read_text(encoding="utf-8"),
        )

    def _server_method_line_range(self, method_name):
        server_text, _ = self._contract_source_texts()
        lines = server_text.splitlines()
        start = None
        for idx, line in enumerate(lines, start=1):
            if line.strip().startswith(f"def {method_name}"):
                start = idx
                break
        self.assertIsNotNone(start, f"server method not found: {method_name}")
        end = len(lines) + 1
        for idx in range(start + 1, len(lines) + 1):
            if re.match(r"^\s{4}def\s+", lines[idx - 1]):
                end = idx
                break
        return start, end

    def _server_method_lines(self, method_name):
        server_text, _ = self._contract_source_texts()
        lines = server_text.splitlines()
        start, end = self._server_method_line_range(method_name)
        return [(idx, lines[idx - 1]) for idx in range(start, end)]

    def _object_json_route_methods(self):
        return [
            ("/api/report_sniff_status", "POST"),
            ("/api/collection/seeds/report_progress", "POST"),
            ("/api/avm/manual_review_receipts", "POST"),
            ("/api/analysis/manual_review_receipts", "POST"),
            ("/api/avm/manual_review_receipts", "DELETE"),
            ("/api/analysis/manual_review_receipts", "DELETE"),
            ("/api/avm/run", "POST"),
            ("/api/analysis/pipeline/run", "POST"),
            ("/api/avm/evaluate", "POST"),
            ("/api/analysis/evaluate", "POST"),
            ("/api/avm/recent_enrich_maintenance", "POST"),
            ("/api/collection/details/maintenance", "POST"),
            ("/api/avm/fetch_missing_detail_archives", "POST"),
            ("/api/collection/details/fetch_missing", "POST"),
            ("/api/avm/archive_detail_replay", "POST"),
            ("/api/collection/details/prepare_replay", "POST"),
            ("/api/collection/region/reset_links", "POST"),
            ("/api/collection/item/reanalyze", "POST"),
            ("/api/collection/item/manual_update", "POST"),
            ("/api/collection/auth/complete", "POST"),
            ("/api/collection/auth/resume_after_cooldown", "POST"),
            ("/api/save_locations", "POST"),
            ("/api/area_result", "POST"),
            ("/api/collection/details/area_result", "POST"),
            ("/api/infer_location", "POST"),
            ("/api/collection/details/infer_location", "POST"),
            ("/api/approve_area", "POST"),
            ("/api/collection/details/approve_area", "POST"),
            ("/api/save", "POST"),
            ("/api/collection/seeds/batch", "POST"),
            ("/api/avm/screen", "POST"),
            ("/api/report_captcha", "POST"),
            ("/api/report_manual_captcha", "POST"),
            ("/api/log", "POST"),
            ("/api/update_item", "POST"),
            ("/api/collection/details/update_item", "POST"),
            ("/api/analyze_html", "POST"),
            ("/api/collection/details/html", "POST"),
        ]

    def _source_object_json_route_methods(self):
        route_methods = set()
        route_pattern = re.compile(r"""['"](/api/[^'"\s]+)['"]""")
        branch_pattern = re.compile(r"^\s*(if|elif)\s+self\.path")
        for method_name, http_method in (("do_POST", "POST"), ("do_DELETE", "DELETE")):
            method_lines = self._server_method_lines(method_name)
            method_line_by_number = dict(method_lines)
            method_start = method_lines[0][0]
            for idx, line in method_lines:
                if "json.loads" not in line:
                    continue

                branch_idx = idx - 1
                branch_line = None
                while branch_idx >= method_start:
                    candidate = method_line_by_number[branch_idx]
                    if branch_pattern.match(candidate) or "if self.path in MANUAL_REVIEW_RECEIPT_ENDPOINTS" in candidate:
                        branch_line = candidate
                        break
                    branch_idx -= 1

                if not branch_line:
                    continue

                if "MANUAL_REVIEW_RECEIPT_ENDPOINTS" in branch_line:
                    routes = list(server_module.MANUAL_REVIEW_RECEIPT_ENDPOINTS)
                else:
                    routes = route_pattern.findall(branch_line)
                for route in routes:
                    route_methods.add((route, http_method))
        return sorted(route_methods)

    def _get_invalid_numeric_query_route_paths(self):
        return sorted(
            [
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
            ]
        )

    def _source_get_invalid_numeric_query_route_paths(self):
        method_lines = self._server_method_lines("do_GET")
        method_line_by_number = dict(method_lines)
        method_start = method_lines[0][0]
        route_paths = set()
        route_pattern = re.compile(r"""['"](/api/[^'"\s]+)['"]""")
        branch_pattern = re.compile(r"^\s*(if|elif)\s+(request_path|self\.path)")
        constant_route_map = {
            "MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS": list(server_module.MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS),
            "MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS": list(server_module.MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS),
            "MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS": list(server_module.MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS),
        }
        for idx, line in method_lines:
            if not ("except ValueError:" in line or "except (TypeError, ValueError):" in line):
                continue
            branch_idx = idx - 1
            branch_line = None
            while branch_idx >= method_start:
                candidate = method_line_by_number[branch_idx]
                if branch_pattern.match(candidate):
                    branch_line = candidate
                    break
                branch_idx -= 1
            if not branch_line:
                continue
            matched_constant = next((name for name in constant_route_map if name in branch_line), None)
            if matched_constant:
                routes = constant_route_map[matched_constant]
            else:
                routes = route_pattern.findall(branch_line)
            for route in routes:
                route_paths.add(route)
        return sorted(route_paths)

    def _get_negative_limit_clamp_route_paths(self):
        return sorted(
            [
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
            ]
        )

    def _source_negative_limit_clamp_route_paths(self):
        method_lines = self._server_method_lines("do_GET")
        method_line_by_number = dict(method_lines)
        method_start = method_lines[0][0]
        route_paths = set()
        route_pattern = re.compile(r"""['"](/api/[^'"\s]+)['"]""")
        branch_pattern = re.compile(r"^\s*(if|elif)\s+(request_path|self\.path)")
        constant_route_map = {
            "MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS": list(server_module.MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS),
            "MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS": list(server_module.MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS),
            "MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS": list(server_module.MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS),
        }
        for idx, line in method_lines:
            if "if limit < 0:" not in line:
                continue
            branch_idx = idx - 1
            branch_line = None
            while branch_idx >= method_start:
                candidate = method_line_by_number[branch_idx]
                if branch_pattern.match(candidate):
                    branch_line = candidate
                    break
                branch_idx -= 1
            if not branch_line:
                continue
            matched_constant = next((name for name in constant_route_map if name in branch_line), None)
            if matched_constant:
                routes = constant_route_map[matched_constant]
            else:
                routes = route_pattern.findall(branch_line)
            for route in routes:
                route_paths.add(route)
        return sorted(route_paths)

    def _get_negative_numeric_query_route_paths(self):
        return sorted(
            [
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
            ]
        )

    def _source_negative_numeric_query_route_paths(self):
        method_lines = self._server_method_lines("do_GET")
        method_line_by_number = dict(method_lines)
        method_start = method_lines[0][0]
        route_paths = set()
        route_pattern = re.compile(r"""['"](/api/[^'"\s]+)['"]""")
        branch_pattern = re.compile(r"^\s*(if|elif)\s+(request_path|self\.path)")
        constant_route_map = {
            "MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS": list(server_module.MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS),
            "MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS": list(server_module.MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS),
            "MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS": list(server_module.MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS),
        }
        for idx, line in method_lines:
            if "< 0" not in line:
                continue
            branch_idx = idx - 1
            branch_line = None
            while branch_idx >= method_start:
                candidate = method_line_by_number[branch_idx]
                if branch_pattern.match(candidate):
                    branch_line = candidate
                    break
                branch_idx -= 1
            if not branch_line:
                continue
            matched_constant = next((name for name in constant_route_map if name in branch_line), None)
            if matched_constant:
                routes = constant_route_map[matched_constant]
            else:
                routes = route_pattern.findall(branch_line)
            for route in routes:
                route_paths.add(route)
        return sorted(route_paths)

    def _repo_owned_python_files(self):
        files = []
        for root in (Path("src"), Path("tools"), Path("tests")):
            if not root.exists():
                continue
            files.extend(sorted(root.rglob("*.py")))
        return files

    def _repo_owned_python_test_files(self):
        files = []
        excluded_parts = {"venv", "node_modules", "__pycache__", ".codex-temp"}
        for path in Path(".").rglob("test_*.py"):
            if any(part in excluded_parts for part in path.parts):
                continue
            files.append(path)
        return sorted(files)

    def _primary_repo_test_files(self):
        files = []
        for root in (Path("tests"), Path("tools/test")):
            if not root.exists():
                continue
            files.extend(sorted(root.rglob("test_*.py")))
        return sorted(files)

    def test_server_api_route_literals_are_referenced_by_http_contract_suite(self):
        server_text, suite_text = self._contract_source_texts()
        routes = sorted(set(re.findall(r"""['"](/api/[^'"\s]+)['"]""", server_text)))
        missing = [route for route in routes if route not in suite_text]
        self.assertEqual(missing, [], f"Missing /api route references in suite: {missing}")

    def test_server_structured_error_codes_are_referenced_by_http_contract_suite(self):
        server_text, suite_text = self._contract_source_texts()
        codes = sorted(set(re.findall(r'code="([A-Z0-9_]+)"', server_text)))
        missing = [code for code in codes if code not in suite_text]
        self.assertEqual(missing, [], f"Missing structured error code references in suite: {missing}")

    def test_server_structured_error_codes_are_asserted_by_http_contract_suite(self):
        server_text, suite_text = self._contract_source_texts()
        codes = sorted(set(re.findall(r'code="([A-Z0-9_]+)"', server_text)))
        missing = []
        for code in codes:
            if (
                f'["error"]["code"], "{code}"' not in suite_text
                and f"['error']['code'], '{code}'" not in suite_text
                and not re.search(
                    rf"_assert_http_error_code\([\s\S]{{0,300}}\"{re.escape(code)}\"",
                    suite_text,
                )
            ):
                missing.append(code)
        self.assertEqual(missing, [], f"Missing structured error code assertions in suite: {missing}")

    def test_public_route_json_loads_have_invalid_json_guardrails(self):
        server_text, _ = self._contract_source_texts()
        lines = server_text.splitlines()
        missing = []
        for method_name in ("do_POST", "do_DELETE"):
            for line_no, line in self._server_method_lines(method_name):
                if "json.loads" not in line:
                    continue
                window = "\n".join(lines[line_no - 1 : min(line_no + 13, len(lines))])
                if "AVM_INVALID_JSON" not in window:
                    missing.append(line_no)
        self.assertEqual(missing, [], f"json.loads sites missing AVM_INVALID_JSON guardrails: {missing}")

    def test_public_route_object_json_sites_have_non_object_guardrails(self):
        server_text, _ = self._contract_source_texts()
        lines = server_text.splitlines()
        missing = []
        for method_name in ("do_POST", "do_DELETE"):
            for line_no, line in self._server_method_lines(method_name):
                if "json.loads" not in line:
                    continue
                window = "\n".join(lines[line_no - 1 : min(line_no + 13, len(lines))])
                if "send_invalid_request_body" not in window and "AVM_INVALID_REQUEST_BODY" not in window:
                    missing.append(line_no)
        self.assertEqual(missing, [], f"json.loads object-body sites missing non-object guardrails: {missing}")

    def test_live_sweep_object_json_route_inventory_matches_source(self):
        expected = sorted(self._object_json_route_methods())
        actual = self._source_object_json_route_methods()
        self.assertEqual(actual, expected)

    def test_invalid_numeric_query_route_inventory_matches_source(self):
        expected = self._get_invalid_numeric_query_route_paths()
        actual = self._source_get_invalid_numeric_query_route_paths()
        self.assertEqual(actual, expected)

    def test_negative_limit_clamp_route_inventory_matches_source(self):
        expected = self._get_negative_limit_clamp_route_paths()
        actual = self._source_negative_limit_clamp_route_paths()
        self.assertEqual(actual, expected)

    def test_negative_numeric_query_route_inventory_matches_source(self):
        expected = self._get_negative_numeric_query_route_paths()
        actual = self._source_negative_numeric_query_route_paths()
        self.assertEqual(actual, expected)

    def test_repo_owned_python_files_compile(self):
        files = self._repo_owned_python_files()
        self.assertGreater(len(files), 0)
        for path in files:
            with self.subTest(path=str(path)):
                py_compile.compile(str(path), doraise=True)

    def test_repo_owned_python_test_inventory_is_covered_by_primary_test_dirs(self):
        self.assertEqual(self._repo_owned_python_test_files(), self._primary_repo_test_files())

    def test_server_has_no_legacy_send_error_calls_in_public_handler(self):
        server_text, _ = self._contract_source_texts()
        self.assertNotIn("self.send_error(", server_text)

    def test_server_bare_404s_are_only_non_api_fallbacks(self):
        server_text, _ = self._contract_source_texts()
        lines = server_text.splitlines()
        failures = []
        for line_no, line in enumerate(lines, start=1):
            if "self.send_response(404)" not in line:
                continue
            start = max(0, line_no - 10)
            end = min(len(lines), line_no + 4)
            window = "\n".join(lines[start:end])
            if "request_path.startswith('/api/')" not in window or 'code="AVM_ENDPOINT_NOT_FOUND"' not in window:
                failures.append(line_no)
        self.assertEqual(failures, [], f"bare 404s outside non-api fallback pattern: {failures}")

    def test_unknown_api_get_returns_json_404_error(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/does-not-exist")

        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_ENDPOINT_NOT_FOUND")
        self.assertEqual(body["error"]["details"]["path"], "/api/does-not-exist")

    def test_unknown_api_post_returns_json_404_error(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/does-not-exist",
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_ENDPOINT_NOT_FOUND")
        self.assertEqual(body["error"]["details"]["path"], "/api/does-not-exist")

    def test_unknown_api_delete_returns_json_404_error(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/does-not-exist",
            data=b"",
            headers={"Content-Type": "application/json"},
            method="DELETE",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_ENDPOINT_NOT_FOUND")
        self.assertEqual(body["error"]["details"]["path"], "/api/does-not-exist")

    def _wait_for_job(self, job_id, timeout=3.0):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            status, payload = self._get_json(f"/api/avm/manual_review_receipt_jobs?job_id={urllib.parse.quote(job_id)}")
            self.assertEqual(status, 200)
            last = payload
            if payload["job"]["status"] in {"completed", "failed"}:
                return payload
            time.sleep(0.05)
        self.fail(f"job {job_id} did not finish in time; last payload={last}")

    def test_health_endpoint(self):
        self._get_json("/api/avm/predict?id=3001")
        status, payload = self._get_json("/api/avm/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "avm")
        self.assertGreaterEqual(payload["dataset_size"], 2)
        self.assertIn("feature_cache_hit_rate", payload)
        self.assertIn("strategy_counts", payload)
        self.assertIn("avg_predict_time_ms", payload)
        self.assertIn("db_mode", payload)
        self.assertIn("db_total_ids", payload)
        self.assertIn("db_pending_ids", payload)
        self.assertIn("collection_stage", payload)
        self.assertIn("analysis_blockers", payload["collection_stage"])
        self.assertIn("recommended_actions", payload["collection_stage"])
        self.assertIn("operator_action_summary", payload["collection_stage"])
        self.assertIn("recoverability_summary", payload["collection_stage"])
        self.assertIn("scheduler_feedback_summary", payload["collection_stage"])
        self.assertIn("manual_review_backlog_summary", payload["collection_stage"])
        self.assertIn("operator_overview", payload["collection_stage"])
        self.assertIn("calibration_guidance", payload)
        self.assertIn("coordinate_strategy_watchlist", payload)
        if payload["db_mode"]:
            self.assertIn("stage_transition_recent", payload["data_supply_recent_24h"])

    def test_health_endpoint_returns_json_error_on_health_snapshot_failure(self):
        with mock.patch.object(server_module.AVM_SERVICE, "health_snapshot", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/health")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_HEALTH_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_status_endpoint_surfaces_calibration_guidance_and_coordinate_watchlist(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "risk_factor_targets": [
                        {
                            "target_type": "risk_flag",
                            "name": "is_occupied",
                            "suggested_next_factor": 0.5
                        }
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 1.05
                        }
                    ],
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72
                        }
                    ],
                    "strategy_targets": [],
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 1.05,
                        "risk_factor_overrides": {"is_occupied": 0.5}
                    },
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "runbook_refs": ["tools/evaluate_avm.py"],
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "suggested_commands": ["python tools/evaluate_avm.py"],
                        "suggested_bundle_commands": [
                            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal"
                        ],
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk",
                            "target_types": ["global_risk", "temporal"],
                            "target_names": None
                        },
                    },
                    "guidance": {
                        "status": "fix_coordinate_quality",
                        "priority": "high",
                        "recommended_actions": ["review_coordinate_strategy_cohorts"],
                        "top_reason": "district_centroid",
                    }
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "evaluation": {
                        "top_coordinate_strategy_group": "district_centroid",
                        "coordinate_strategy_watchlist": ["district_centroid"],
                    }
                },
                f,
                ensure_ascii=False,
            )

        status, payload = self._get_json("/api/status")
        self.assertEqual(status, 200)
        self.assertIn("avm", payload)
        self.assertEqual(payload["avm"]["calibration_guidance"]["status"], "fix_coordinate_quality")
        self.assertEqual(payload["avm"]["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(payload["avm"]["top_calibration_target_hint"]["target_name"], "time_decay")
        self.assertEqual(payload["avm"]["top_calibration_target_hint"]["playbook_id"], "tune-temporal-decay")
        self.assertIn("tools/evaluate_avm.py", payload["avm"]["top_calibration_target_hint"]["runbook_refs"])
        self.assertIn("python tools/evaluate_avm.py", payload["avm"]["top_calibration_target_hint"]["suggested_commands"])
        self.assertIn("python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal", payload["avm"]["top_calibration_target_hint"]["suggested_bundle_commands"])
        self.assertTrue(payload["avm"]["calibration_patch_preview"]["patch_ready"])
        self.assertEqual(payload["avm"]["calibration_patch_preview"]["changed_paths"]["weighting.time_decay"]["after"], 0.72)
        self.assertEqual(payload["avm"]["calibration_patch_preview"]["rollback_patch"]["weighting"]["time_decay"], 0.85)
        self.assertEqual(payload["avm"]["calibration_target_counts"]["global_risk"], 1)
        self.assertEqual(payload["avm"]["top_calibration_patch_preview"]["applied_filter"], {"target_type": "temporal", "target_name": "time_decay"})
        self.assertEqual(payload["avm"]["top_calibration_patch_preview"]["changed_keys"], ["weighting.time_decay"])
        self.assertEqual(payload["avm"]["recommended_bundle_patch_preview"]["bundle_id"], "temporal-global-risk")
        self.assertEqual(payload["avm"]["recommended_bundle_patch_preview"]["applied_filter"], {"target_types": ["global_risk", "temporal"], "target_names": None})
        self.assertEqual(payload["avm"]["recommended_bundle_patch_preview"]["changed_keys"], ["risk_discount_factor", "weighting.time_decay"])
        self.assertEqual(
            payload["avm"]["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        )
        self.assertEqual(
            payload["avm"]["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        )
        self.assertEqual(
            payload["avm"]["recommended_bundle_verify_command"],
            "python tools/evaluate_avm.py",
        )
        self.assertEqual(
            payload["avm"]["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(payload["avm"]["recommended_bundle_risk_level"], "medium")
        self.assertIn("multiple_changed_keys", payload["avm"]["recommended_bundle_risk_reasons"])
        self.assertEqual(payload["avm"]["recommended_bundle_next_action"], "preview_only_first")
        self.assertIn("medium_risk_bundle", payload["avm"]["recommended_bundle_next_action_reasons"])
        self.assertEqual(payload["avm"]["recommended_bundle_next_action_command"], "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal")
        self.assertEqual(payload["avm"]["recommended_bundle_next_action_command_kind"], "preview")
        self.assertEqual(payload["avm"]["recommended_bundle_follow_up_command"], "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write")
        self.assertEqual(payload["avm"]["recommended_bundle_follow_up_command_kind"], "write")
        command_chain = payload["avm"]["recommended_bundle_command_chain"]
        self.assertEqual(
            [item["kind"] for item in command_chain],
            ["preview", "write", "verify", "gate"],
        )
        preview_step, write_step, verify_step, gate_step = command_chain
        self.assertEqual(
            preview_step["step_ready_action_command"],
            payload["avm"]["recommended_bundle_preview_command"],
        )
        self.assertEqual(
            preview_step["step_ready_follow_up_command"],
            payload["avm"]["recommended_bundle_write_command"],
        )
        self.assertEqual(preview_step["step_ready_stage_span"], "write_then_evaluate")
        self.assertEqual(preview_step["artifact_state_reason"], "config_not_written_yet")
        self.assertEqual(
            write_step["step_ready_action_command"],
            payload["avm"]["recommended_bundle_write_command"],
        )
        self.assertEqual(
            write_step["step_ready_follow_up_command"],
            payload["avm"]["recommended_bundle_verify_command"],
        )
        self.assertEqual(write_step["step_ready_stage_span"], "write_then_evaluate")
        self.assertEqual(
            verify_step["step_ready_action_command"],
            payload["avm"]["recommended_bundle_verify_command"],
        )
        self.assertEqual(
            verify_step["step_ready_follow_up_command"],
            payload["avm"]["recommended_bundle_gate_command"],
        )
        self.assertEqual(verify_step["step_ready_stage_span"], "evaluate_then_gate")
        self.assertEqual(verify_step["artifact_state_reason"], "eval_not_rerun_yet")
        self.assertEqual(
            gate_step["step_ready_action_command"],
            payload["avm"]["recommended_bundle_gate_command"],
        )
        self.assertEqual(gate_step["step_ready_stage_span"], "gate_only")
        self.assertEqual(gate_step["artifact_state_reason"], "pre_bundle_gate_report")
        self.assertEqual(payload["avm"]["coordinate_strategy_watchlist"], ["district_centroid"])
        self.assertEqual(payload["avm"]["top_coordinate_strategy_group"], "district_centroid")

    def test_status_endpoint_returns_json_error_on_health_snapshot_failure(self):
        with mock.patch.object(server_module.AVM_SERVICE, "health_snapshot", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/status")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_STATUS_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_status_endpoint_stops_high_risk_bundle_chain_at_preview(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {"is_occupied": 0.8},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 0.99,
                        }
                    ],
                    "risk_factor_targets": [
                        {
                            "target_type": "risk_flag",
                            "name": "is_occupied",
                            "suggested_next_factor": 0.5,
                        }
                    ],
                    "strategy_targets": [],
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 0.99,
                        "risk_factor_overrides": {"is_occupied": 0.5},
                    },
                    "top_calibration_target": {
                        "target_type": "risk_flag",
                        "name": "is_occupied",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_risk_factors",
                        "target_type": "risk_flag",
                        "target_name": "is_occupied",
                        "playbook_id": "split-bundle-or-single-target-first",
                        "runbook_refs": ["tools/apply_avm_calibration_patch.py"],
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "suggested_commands": ["python tools/apply_avm_calibration_patch.py --target-type risk_flag --target-name is_occupied"],
                        "suggested_bundle_commands": [
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied",
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write",
                            "python tools/evaluate_avm.py",
                            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
                        ],
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk-risk-flag",
                            "target_types": ["temporal", "global_risk", "risk_flag"],
                            "target_names": ["time_decay", "risk_discount_factor", "is_occupied"],
                        },
                    },
                    "guidance": {
                        "status": "tune_risk_factors",
                        "priority": "high",
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "top_reason": "multi_flag_bundle",
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["avm"]["recommended_bundle_risk_level"], "high")
        self.assertIn("high_risk_bundle", payload["avm"]["recommended_bundle_next_action_reasons"])
        self.assertEqual(payload["avm"]["recommended_bundle_next_action"], "split_bundle_or_single_target_first")
        self.assertEqual(
            payload["avm"]["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied",
        )
        self.assertEqual(payload["avm"]["recommended_bundle_next_action_command_kind"], "preview")
        self.assertEqual(payload["avm"]["recommended_bundle_follow_up_command"], "")
        self.assertEqual(payload["avm"]["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(len(payload["avm"]["recommended_bundle_command_chain"]), 1)
        preview_step = payload["avm"]["recommended_bundle_command_chain"][0]
        self.assertEqual(preview_step["kind"], "preview")
        self.assertEqual(preview_step["step_ready_follow_up_command"], "")
        self.assertEqual(preview_step["step_ready_follow_up_expected_signal"], "")
        self.assertEqual(preview_step["step_ready_follow_up_success_criterion"], "")
        self.assertEqual(preview_step["step_ready_terminal_outcome"], "ready_for_write_decision")
        self.assertEqual(preview_step["step_ready_stage_span"], "preview_then_split")
        self.assertEqual(preview_step["step_ready_badge"], "now-preview-then-split")
        self.assertEqual(preview_step["step_ready_group_id"], "preview-and-split")
        self.assertEqual(preview_step["step_ready_display_order"], 0)

    def test_status_endpoint_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [],
                    "risk_factor_targets": [],
                    "strategy_targets": [],
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                    },
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "runbook_refs": ["tools/evaluate_avm.py"],
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "suggested_commands": ["python tools/evaluate_avm.py"],
                        "recommended_bundle": {
                            "bundle_id": "temporal-only",
                            "target_types": ["temporal"],
                            "target_names": ["time_decay"],
                        },
                    },
                    "guidance": {
                        "status": "tune_temporal_decay",
                        "priority": "medium",
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "top_reason": "time_decay",
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/status")

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["avm"]["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            payload["avm"]["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(payload["avm"]["recommended_bundle_verify_command"], "python tools/evaluate_avm.py")
        self.assertEqual(
            payload["avm"]["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(payload["avm"]["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            payload["avm"]["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(payload["avm"]["recommended_bundle_follow_up_command"], "python tools/evaluate_avm.py")
        self.assertEqual(payload["avm"]["recommended_bundle_follow_up_command_kind"], "verify")
        self.assertEqual(
            [item["kind"] for item in payload["avm"]["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )

    def test_status_endpoint_normalizes_malformed_calibration_target_lists(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": {
                        "target_type": "temporal",
                        "name": "time_decay",
                        "suggested_next_value": 0.72,
                    },
                    "global_risk_targets": {},
                    "risk_factor_targets": "bad-shape",
                    "strategy_targets": None,
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "recommended_bundle": {
                            "bundle_id": "temporal-only",
                            "target_types": ["temporal"],
                            "target_names": ["time_decay"],
                        },
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/status")

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["avm"]["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["avm"]["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["avm"]["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            payload["avm"]["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )

    def test_status_endpoint_tolerates_non_object_calibration_targets_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["avm"]["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["avm"]["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["avm"]["recommended_bundle_next_action"], "no_action_required")

    def test_status_endpoint_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["avm"]["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["avm"]["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["avm"]["recommended_bundle_next_action"], "no_action_required")

    def test_status_endpoint_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            f.write("{")
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["avm"]["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["avm"]["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["avm"]["recommended_bundle_next_action"], "no_action_required")

    def test_status_endpoint_tolerates_invalid_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": [],
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["avm"]["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["avm"]["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["avm"]["recommended_bundle_next_action"], "no_action_required")

    def test_status_endpoint_uses_gate_embedded_calibration_targets_when_file_is_missing(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "evaluation": {
                        "coordinate_strategy_watchlist": [],
                        "calibration_targets": {
                            "config_patch": {"weighting": {"time_decay": 0.72}},
                            "temporal_targets": [
                                {
                                    "target_type": "temporal",
                                    "name": "time_decay",
                                    "suggested_next_value": 0.72,
                                }
                            ],
                            "global_risk_targets": [],
                            "risk_factor_targets": [],
                            "strategy_targets": [],
                            "top_calibration_target": {
                                "target_type": "temporal",
                                "name": "time_decay",
                            },
                            "top_calibration_target_hint": {
                                "status": "tune_temporal_decay",
                                "target_type": "temporal",
                                "target_name": "time_decay",
                                "playbook_id": "tune-temporal-decay",
                                "recommended_bundle": {
                                    "bundle_id": "temporal-only",
                                    "target_types": ["temporal"],
                                    "target_names": ["time_decay"],
                                },
                            },
                            "guidance": {
                                "status": "tune_temporal_decay",
                                "priority": "medium",
                                "recommended_actions": ["adjust_weighting_time_decay"],
                                "top_reason": "time_decay",
                            },
                        },
                    }
                },
                f,
                ensure_ascii=False,
            )

        status, payload = self._get_json("/api/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["avm"]["calibration_guidance"]["status"], "tune_temporal_decay")
        self.assertEqual(
            payload["avm"]["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 1,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["avm"]["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(
            payload["avm"]["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            payload["avm"]["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(
            payload["avm"]["recommended_bundle_patch_preview"]["changed_keys"],
            ["weighting.time_decay"],
        )

    def test_status_endpoint_merges_partial_embedded_calibration_targets_with_file_context(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {"is_occupied": 0.8},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 0.99,
                        "risk_factor_overrides": {"is_occupied": 0.5},
                    },
                    "temporal_targets": [
                        {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 0.99,
                        }
                    ],
                    "risk_factor_targets": [
                        {
                            "target_type": "risk_flag",
                            "name": "is_occupied",
                            "suggested_next_factor": 0.5,
                        }
                    ],
                    "strategy_targets": [],
                    "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                    "top_calibration_target_hint": {
                        "status": "tune_risk_factors",
                        "playbook_id": "split-bundle-or-single-target-first",
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk-risk-flag",
                            "target_types": ["temporal", "global_risk", "risk_flag"],
                            "target_names": ["time_decay", "risk_discount_factor", "is_occupied"],
                        },
                        "suggested_bundle_commands": [
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied",
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write",
                            "python tools/evaluate_avm.py",
                            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
                        ],
                    },
                    "guidance": {
                        "status": "tune_risk_factors",
                        "priority": "high",
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "top_reason": "multi_flag_bundle",
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "evaluation": {
                        "calibration_targets": {
                            "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                        }
                    }
                },
                f,
                ensure_ascii=False,
            )

        status, payload = self._get_json("/api/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["avm"]["recommended_bundle_risk_level"], "high")
        self.assertEqual(payload["avm"]["recommended_bundle_next_action"], "split_bundle_or_single_target_first")
        self.assertEqual(payload["avm"]["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(
            [item["kind"] for item in payload["avm"]["recommended_bundle_command_chain"]],
            ["preview"],
        )

    def test_health_endpoint_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [],
                    "risk_factor_targets": [],
                    "strategy_targets": [],
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                    },
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "runbook_refs": ["tools/evaluate_avm.py"],
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "suggested_commands": ["python tools/evaluate_avm.py"],
                        "recommended_bundle": {
                            "bundle_id": "temporal-only",
                            "target_types": ["temporal"],
                            "target_names": ["time_decay"],
                        },
                    },
                    "guidance": {
                        "status": "tune_temporal_decay",
                        "priority": "medium",
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "top_reason": "time_decay",
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/avm/health")

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            payload["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(payload["recommended_bundle_verify_command"], "python tools/evaluate_avm.py")
        self.assertEqual(
            payload["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            payload["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(payload["recommended_bundle_follow_up_command"], "python tools/evaluate_avm.py")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "verify")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )

    def test_analysis_release_gate_endpoint_returns_json_error_on_operator_summary_failure(self):
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
            "analysis_readiness": {"manual_review_receipt_summary": {"receipt_count": 1}},
        }
        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload), \
             mock.patch.object(server_module, "_avm_operator_eval_summary", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_RELEASE_GATE_SUMMARY_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_health_endpoint_tolerates_non_object_calibration_targets_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/avm/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_health_endpoint_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/avm/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_health_endpoint_tolerates_invalid_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": -1,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/avm/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_health_endpoint_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            f.write("{")
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/avm/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_health_endpoint_uses_gate_embedded_calibration_targets_when_file_is_missing(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "evaluation": {
                        "coordinate_strategy_watchlist": [],
                        "calibration_targets": {
                            "config_patch": {"weighting": {"time_decay": 0.72}},
                            "temporal_targets": [
                                {
                                    "target_type": "temporal",
                                    "name": "time_decay",
                                    "suggested_next_value": 0.72,
                                }
                            ],
                            "global_risk_targets": [],
                            "risk_factor_targets": [],
                            "strategy_targets": [],
                            "top_calibration_target": {
                                "target_type": "temporal",
                                "name": "time_decay",
                            },
                            "top_calibration_target_hint": {
                                "status": "tune_temporal_decay",
                                "target_type": "temporal",
                                "target_name": "time_decay",
                                "playbook_id": "tune-temporal-decay",
                                "recommended_bundle": {
                                    "bundle_id": "temporal-only",
                                    "target_types": ["temporal"],
                                    "target_names": ["time_decay"],
                                },
                            },
                            "guidance": {
                                "status": "tune_temporal_decay",
                                "priority": "medium",
                                "recommended_actions": ["adjust_weighting_time_decay"],
                                "top_reason": "time_decay",
                            },
                        },
                    }
                },
                f,
                ensure_ascii=False,
            )

        status, payload = self._get_json("/api/avm/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "tune_temporal_decay")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 1,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(
            payload["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            payload["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(
            payload["recommended_bundle_patch_preview"]["changed_keys"],
            ["weighting.time_decay"],
        )

    def test_health_endpoint_merges_partial_embedded_calibration_targets_with_file_context(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {"is_occupied": 0.8},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 0.99,
                        "risk_factor_overrides": {"is_occupied": 0.5},
                    },
                    "temporal_targets": [
                        {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 0.99,
                        }
                    ],
                    "risk_factor_targets": [
                        {
                            "target_type": "risk_flag",
                            "name": "is_occupied",
                            "suggested_next_factor": 0.5,
                        }
                    ],
                    "strategy_targets": [],
                    "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                    "top_calibration_target_hint": {
                        "status": "tune_risk_factors",
                        "playbook_id": "split-bundle-or-single-target-first",
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk-risk-flag",
                            "target_types": ["temporal", "global_risk", "risk_flag"],
                            "target_names": ["time_decay", "risk_discount_factor", "is_occupied"],
                        },
                        "suggested_bundle_commands": [
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied",
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write",
                            "python tools/evaluate_avm.py",
                            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
                        ],
                    },
                    "guidance": {
                        "status": "tune_risk_factors",
                        "priority": "high",
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "top_reason": "multi_flag_bundle",
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "evaluation": {
                        "calibration_targets": {
                            "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                        }
                    }
                },
                f,
                ensure_ascii=False,
            )

        status, payload = self._get_json("/api/avm/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["recommended_bundle_risk_level"], "high")
        self.assertEqual(payload["recommended_bundle_next_action"], "split_bundle_or_single_target_first")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["preview"],
        )

    def test_analysis_health_alias_endpoint(self):
        status, payload = self._get_json("/api/analysis/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("collection_stage", payload)
        self.assertIn("operator_action_summary", payload["collection_stage"])
        self.assertIn("scheduler_feedback_summary", payload["collection_stage"])
        self.assertIn("operator_overview", payload["collection_stage"])
        self.assertIn("manual_review_backlog_summary", payload["collection_stage"])

    def test_analysis_health_alias_returns_json_error_on_health_snapshot_failure(self):
        with mock.patch.object(server_module.AVM_SERVICE, "health_snapshot", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/health")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_HEALTH_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_health_alias_surfaces_risk_validation_summary(self):
        status, payload = self._get_json("/api/analysis/health")
        self.assertEqual(status, 200)
        self.assertIn("risk_validation_counts", payload)
        self.assertIn("risk_feature_completeness_avg", payload)
        self.assertIn("active_weighting", payload)
        self.assertIn("active_risk_discount_factor", payload)
        self.assertIn("active_risk_factor_override_count", payload)
        self.assertIn("active_risk_factor_overrides", payload)
        self.assertIn("coordinate_strategy_counts", payload)
        self.assertIn("calibration_guidance", payload)
        self.assertIn("calibration_target_counts", payload)
        self.assertIn("top_calibration_target", payload)
        self.assertIn("top_calibration_target_hint", payload)
        self.assertIn("calibration_patch_preview", payload)
        self.assertIn("top_calibration_patch_preview", payload)
        self.assertIn("recommended_bundle_patch_preview", payload)
        self.assertIn("recommended_bundle_risk_level", payload)
        self.assertIn("recommended_bundle_risk_reasons", payload)
        self.assertIn("recommended_bundle_next_action", payload)
        self.assertIn("recommended_bundle_next_action_reasons", payload)
        self.assertIn("recommended_bundle_next_action_command", payload)
        self.assertIn("recommended_bundle_next_action_command_kind", payload)
        self.assertIn("recommended_bundle_follow_up_command", payload)
        self.assertIn("recommended_bundle_follow_up_command_kind", payload)
        self.assertIn("recommended_bundle_command_chain", payload)
        self.assertIn("coordinate_strategy_watchlist", payload)

    def test_analysis_health_alias_surfaces_calibration_guidance_and_coordinate_watchlist(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "risk_factor_targets": [
                        {
                            "target_type": "risk_flag",
                            "name": "is_occupied",
                            "suggested_next_factor": 0.5
                        }
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 1.05
                        }
                    ],
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72
                        }
                    ],
                    "strategy_targets": [],
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 1.05,
                        "risk_factor_overrides": {"is_occupied": 0.5}
                    },
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "runbook_refs": ["tools/evaluate_avm.py"],
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "suggested_commands": ["python tools/evaluate_avm.py"],
                        "suggested_bundle_commands": [
                            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal"
                        ],
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk",
                            "target_types": ["global_risk", "temporal"],
                            "target_names": None
                        },
                    },
                    "guidance": {
                        "status": "fix_coordinate_quality",
                        "priority": "high",
                        "recommended_actions": ["review_coordinate_strategy_cohorts"],
                        "top_reason": "district_centroid",
                    }
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "evaluation": {
                        "top_coordinate_strategy_group": "district_centroid",
                        "coordinate_strategy_watchlist": ["district_centroid"],
                    }
                },
                f,
                ensure_ascii=False,
            )

        status, payload = self._get_json("/api/analysis/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "fix_coordinate_quality")
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(payload["top_calibration_target_hint"]["target_name"], "time_decay")
        self.assertEqual(payload["top_calibration_target_hint"]["playbook_id"], "tune-temporal-decay")
        self.assertIn("tools/evaluate_avm.py", payload["top_calibration_target_hint"]["runbook_refs"])
        self.assertIn("python tools/evaluate_avm.py", payload["top_calibration_target_hint"]["suggested_commands"])
        self.assertIn("python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal", payload["top_calibration_target_hint"]["suggested_bundle_commands"])
        self.assertTrue(payload["calibration_patch_preview"]["patch_ready"])
        self.assertEqual(payload["calibration_patch_preview"]["changed_paths"]["weighting.time_decay"]["after"], 0.72)
        self.assertEqual(payload["calibration_patch_preview"]["rollback_patch"]["weighting"]["time_decay"], 0.85)
        self.assertEqual(payload["calibration_target_counts"]["global_risk"], 1)
        self.assertEqual(payload["top_calibration_patch_preview"]["applied_filter"], {"target_type": "temporal", "target_name": "time_decay"})
        self.assertEqual(payload["top_calibration_patch_preview"]["changed_keys"], ["weighting.time_decay"])
        self.assertEqual(payload["recommended_bundle_patch_preview"]["bundle_id"], "temporal-global-risk")
        self.assertEqual(payload["recommended_bundle_patch_preview"]["applied_filter"], {"target_types": ["global_risk", "temporal"], "target_names": None})
        self.assertEqual(payload["recommended_bundle_patch_preview"]["changed_keys"], ["risk_discount_factor", "weighting.time_decay"])
        self.assertEqual(
            payload["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        )
        self.assertEqual(
            payload["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        )
        self.assertEqual(payload["recommended_bundle_verify_command"], "python tools/evaluate_avm.py")
        self.assertEqual(
            payload["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(payload["recommended_bundle_risk_level"], "medium")
        self.assertIn("multiple_changed_keys", payload["recommended_bundle_risk_reasons"])
        self.assertEqual(payload["recommended_bundle_next_action"], "preview_only_first")
        self.assertIn("medium_risk_bundle", payload["recommended_bundle_next_action_reasons"])
        self.assertEqual(payload["recommended_bundle_next_action_command"], "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal")
        self.assertEqual(payload["recommended_bundle_next_action_command_kind"], "preview")
        self.assertEqual(payload["recommended_bundle_follow_up_command"], "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "write")
        command_chain = payload["recommended_bundle_command_chain"]
        self.assertEqual(
            [item["kind"] for item in command_chain],
            ["preview", "write", "verify", "gate"],
        )
        self.assertEqual(payload["coordinate_strategy_watchlist"], ["district_centroid"])
        self.assertEqual(payload["top_coordinate_strategy_group"], "district_centroid")

    def test_analysis_status_alias_endpoint(self):
        status, payload = self._get_json("/api/analysis/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("collection_stage", payload)
        self.assertIn("operator_action_summary", payload["collection_stage"])
        self.assertIn("scheduler_feedback_summary", payload["collection_stage"])
        self.assertIn("operator_overview", payload["collection_stage"])
        self.assertIn("manual_review_backlog_summary", payload["collection_stage"])
        self.assertIn("calibration_guidance", payload)
        self.assertIn("calibration_target_counts", payload)
        self.assertIn("top_calibration_target", payload)
        self.assertIn("coordinate_strategy_watchlist", payload)

    def test_analysis_status_alias_returns_json_error_on_health_snapshot_failure(self):
        with mock.patch.object(server_module.AVM_SERVICE, "health_snapshot", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/status")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_HEALTH_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_status_alias_surfaces_risk_validation_summary(self):
        status, payload = self._get_json("/api/analysis/status")
        self.assertEqual(status, 200)
        self.assertIn("risk_validation_counts", payload)
        self.assertIn("risk_feature_completeness_avg", payload)
        self.assertIn("active_weighting", payload)
        self.assertIn("active_risk_discount_factor", payload)
        self.assertIn("active_risk_factor_override_count", payload)
        self.assertIn("active_risk_factor_overrides", payload)
        self.assertIn("coordinate_strategy_counts", payload)
        self.assertIn("calibration_guidance", payload)
        self.assertIn("calibration_target_counts", payload)
        self.assertIn("top_calibration_target", payload)
        self.assertIn("top_calibration_target_hint", payload)
        self.assertIn("calibration_patch_preview", payload)
        self.assertIn("top_calibration_patch_preview", payload)
        self.assertIn("recommended_bundle_patch_preview", payload)
        self.assertIn("recommended_bundle_risk_level", payload)
        self.assertIn("recommended_bundle_risk_reasons", payload)
        self.assertIn("recommended_bundle_next_action", payload)
        self.assertIn("recommended_bundle_next_action_reasons", payload)
        self.assertIn("recommended_bundle_next_action_command", payload)
        self.assertIn("recommended_bundle_next_action_command_kind", payload)
        self.assertIn("recommended_bundle_follow_up_command", payload)
        self.assertIn("recommended_bundle_follow_up_command_kind", payload)
        self.assertIn("recommended_bundle_command_chain", payload)
        self.assertIn("coordinate_strategy_watchlist", payload)

    def test_analysis_status_alias_surfaces_calibration_guidance_and_coordinate_watchlist(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "risk_factor_targets": [
                        {
                            "target_type": "risk_flag",
                            "name": "is_occupied",
                            "suggested_next_factor": 0.5
                        }
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 1.05
                        }
                    ],
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72
                        }
                    ],
                    "strategy_targets": [],
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 1.05,
                        "risk_factor_overrides": {"is_occupied": 0.5}
                    },
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "runbook_refs": ["tools/evaluate_avm.py"],
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "suggested_commands": ["python tools/evaluate_avm.py"],
                        "suggested_bundle_commands": [
                            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal"
                        ],
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk",
                            "target_types": ["global_risk", "temporal"],
                            "target_names": None
                        },
                    },
                    "guidance": {
                        "status": "fix_coordinate_quality",
                        "priority": "high",
                        "recommended_actions": ["review_coordinate_strategy_cohorts"],
                        "top_reason": "district_centroid",
                    }
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "evaluation": {
                        "top_coordinate_strategy_group": "district_centroid",
                        "coordinate_strategy_watchlist": ["district_centroid"],
                    }
                },
                f,
                ensure_ascii=False,
            )

        status, payload = self._get_json("/api/analysis/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "fix_coordinate_quality")
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(payload["top_calibration_target_hint"]["target_name"], "time_decay")
        self.assertEqual(payload["top_calibration_target_hint"]["playbook_id"], "tune-temporal-decay")
        self.assertIn("tools/evaluate_avm.py", payload["top_calibration_target_hint"]["runbook_refs"])
        self.assertIn("python tools/evaluate_avm.py", payload["top_calibration_target_hint"]["suggested_commands"])
        self.assertIn("python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal", payload["top_calibration_target_hint"]["suggested_bundle_commands"])
        self.assertTrue(payload["calibration_patch_preview"]["patch_ready"])
        self.assertEqual(payload["calibration_patch_preview"]["changed_paths"]["weighting.time_decay"]["after"], 0.72)
        self.assertEqual(payload["calibration_patch_preview"]["rollback_patch"]["weighting"]["time_decay"], 0.85)
        self.assertEqual(payload["calibration_target_counts"]["global_risk"], 1)
        self.assertEqual(payload["top_calibration_patch_preview"]["applied_filter"], {"target_type": "temporal", "target_name": "time_decay"})
        self.assertEqual(payload["top_calibration_patch_preview"]["changed_keys"], ["weighting.time_decay"])
        self.assertEqual(payload["recommended_bundle_patch_preview"]["bundle_id"], "temporal-global-risk")
        self.assertEqual(payload["recommended_bundle_patch_preview"]["applied_filter"], {"target_types": ["global_risk", "temporal"], "target_names": None})
        self.assertEqual(payload["recommended_bundle_patch_preview"]["changed_keys"], ["risk_discount_factor", "weighting.time_decay"])
        self.assertEqual(
            payload["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        )
        self.assertEqual(
            payload["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        )
        self.assertEqual(
            payload["recommended_bundle_verify_command"],
            "python tools/evaluate_avm.py",
        )
        self.assertEqual(
            payload["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(payload["recommended_bundle_risk_level"], "medium")
        self.assertIn("multiple_changed_keys", payload["recommended_bundle_risk_reasons"])
        self.assertEqual(payload["recommended_bundle_next_action"], "preview_only_first")
        self.assertIn("medium_risk_bundle", payload["recommended_bundle_next_action_reasons"])
        self.assertEqual(payload["recommended_bundle_next_action_command_kind"], "preview")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "write")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["preview", "write", "verify", "gate"],
        )
        self.assertEqual(payload["coordinate_strategy_watchlist"], ["district_centroid"])
        self.assertEqual(payload["top_coordinate_strategy_group"], "district_centroid")

    def test_analysis_health_alias_uses_gate_embedded_calibration_targets_when_file_is_missing(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "evaluation": {
                        "coordinate_strategy_watchlist": ["district_centroid"],
                        "top_coordinate_strategy_group": "district_centroid",
                        "calibration_targets": {
                            "config_patch": {"weighting": {"time_decay": 0.72}},
                            "temporal_targets": [
                                {
                                    "target_type": "temporal",
                                    "name": "time_decay",
                                    "suggested_next_value": 0.72,
                                }
                            ],
                            "global_risk_targets": [],
                            "risk_factor_targets": [],
                            "strategy_targets": [],
                            "top_calibration_target": {
                                "target_type": "temporal",
                                "name": "time_decay",
                            },
                            "top_calibration_target_hint": {
                                "status": "tune_temporal_decay",
                                "target_type": "temporal",
                                "target_name": "time_decay",
                                "playbook_id": "tune-temporal-decay",
                                "recommended_bundle": {
                                    "bundle_id": "temporal-only",
                                    "target_types": ["temporal"],
                                    "target_names": ["time_decay"],
                                },
                            },
                            "guidance": {
                                "status": "tune_temporal_decay",
                                "priority": "medium",
                                "recommended_actions": ["adjust_weighting_time_decay"],
                                "top_reason": "time_decay",
                            },
                        },
                    }
                },
                f,
                ensure_ascii=False,
            )

        status, payload = self._get_json("/api/analysis/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "tune_temporal_decay")
        self.assertEqual(payload["calibration_target_counts"]["temporal"], 1)
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(payload["recommended_bundle_risk_level"], "low")
        self.assertEqual(payload["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )

    def test_analysis_health_alias_merges_partial_embedded_calibration_targets_with_file_context(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {"is_occupied": 0.8},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 0.99,
                        "risk_factor_overrides": {"is_occupied": 0.5},
                    },
                    "temporal_targets": [
                        {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 0.99,
                        }
                    ],
                    "risk_factor_targets": [
                        {
                            "target_type": "risk_flag",
                            "name": "is_occupied",
                            "suggested_next_factor": 0.5,
                        }
                    ],
                    "strategy_targets": [],
                    "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                    "top_calibration_target_hint": {
                        "status": "tune_risk_factors",
                        "playbook_id": "split-bundle-or-single-target-first",
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk-risk-flag",
                            "target_types": ["temporal", "global_risk", "risk_flag"],
                            "target_names": ["time_decay", "risk_discount_factor", "is_occupied"],
                        },
                        "suggested_bundle_commands": [
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied",
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write",
                            "python tools/evaluate_avm.py",
                            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
                        ],
                    },
                    "guidance": {
                        "status": "tune_risk_factors",
                        "priority": "high",
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "top_reason": "multi_flag_bundle",
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "evaluation": {
                        "calibration_targets": {
                            "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                        }
                    }
                },
                f,
                ensure_ascii=False,
            )

        status, payload = self._get_json("/api/analysis/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "tune_risk_factors")
        self.assertEqual(payload["recommended_bundle_risk_level"], "high")
        self.assertEqual(payload["recommended_bundle_next_action"], "split_bundle_or_single_target_first")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["preview"],
        )

    def test_analysis_health_alias_stops_high_risk_bundle_chain_at_preview(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {"is_occupied": 0.8},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 0.99,
                        }
                    ],
                    "risk_factor_targets": [
                        {
                            "target_type": "risk_flag",
                            "name": "is_occupied",
                            "suggested_next_factor": 0.5,
                        }
                    ],
                    "strategy_targets": [],
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 0.99,
                        "risk_factor_overrides": {"is_occupied": 0.5},
                    },
                    "top_calibration_target": {
                        "target_type": "risk_flag",
                        "name": "is_occupied",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_risk_factors",
                        "target_type": "risk_flag",
                        "target_name": "is_occupied",
                        "playbook_id": "split-bundle-or-single-target-first",
                        "runbook_refs": ["tools/apply_avm_calibration_patch.py"],
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "suggested_commands": ["python tools/apply_avm_calibration_patch.py --target-type risk_flag --target-name is_occupied"],
                        "suggested_bundle_commands": [
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied",
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write",
                            "python tools/evaluate_avm.py",
                            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
                        ],
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk-risk-flag",
                            "target_types": ["temporal", "global_risk", "risk_flag"],
                            "target_names": ["time_decay", "risk_discount_factor", "is_occupied"],
                        },
                    },
                    "guidance": {
                        "status": "tune_risk_factors",
                        "priority": "high",
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "top_reason": "multi_flag_bundle",
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["recommended_bundle_risk_level"], "high")
        self.assertIn("high_risk_bundle", payload["recommended_bundle_next_action_reasons"])
        self.assertEqual(payload["recommended_bundle_next_action"], "split_bundle_or_single_target_first")
        self.assertEqual(
            payload["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied",
        )
        self.assertEqual(payload["recommended_bundle_next_action_command_kind"], "preview")
        self.assertEqual(payload["recommended_bundle_follow_up_command"], "")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(len(payload["recommended_bundle_command_chain"]), 1)
        preview_step = payload["recommended_bundle_command_chain"][0]
        self.assertEqual(preview_step["kind"], "preview")
        self.assertEqual(preview_step["step_ready_follow_up_command"], "")
        self.assertEqual(preview_step["step_ready_follow_up_expected_signal"], "")
        self.assertEqual(preview_step["step_ready_follow_up_success_criterion"], "")
        self.assertEqual(preview_step["step_ready_terminal_outcome"], "ready_for_write_decision")
        self.assertEqual(preview_step["step_ready_stage_span"], "preview_then_split")
        self.assertEqual(preview_step["step_ready_badge"], "now-preview-then-split")
        self.assertEqual(preview_step["step_ready_group_id"], "preview-and-split")
        self.assertEqual(preview_step["step_ready_display_order"], 0)

    def test_analysis_health_alias_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [],
                    "risk_factor_targets": [],
                    "strategy_targets": [],
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                    },
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "runbook_refs": ["tools/evaluate_avm.py"],
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "suggested_commands": ["python tools/evaluate_avm.py"],
                        "recommended_bundle": {
                            "bundle_id": "temporal-only",
                            "target_types": ["temporal"],
                            "target_names": ["time_decay"],
                        },
                    },
                    "guidance": {
                        "status": "tune_temporal_decay",
                        "priority": "medium",
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "top_reason": "time_decay",
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/health")

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            payload["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(payload["recommended_bundle_verify_command"], "python tools/evaluate_avm.py")
        self.assertEqual(
            payload["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            payload["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(payload["recommended_bundle_follow_up_command"], "python tools/evaluate_avm.py")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "verify")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )

    def test_analysis_health_alias_normalizes_malformed_calibration_target_lists(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": {
                        "target_type": "temporal",
                        "name": "time_decay",
                        "suggested_next_value": 0.72,
                    },
                    "global_risk_targets": {},
                    "risk_factor_targets": "bad-shape",
                    "strategy_targets": None,
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "recommended_bundle": {
                            "bundle_id": "temporal-only",
                            "target_types": ["temporal"],
                            "target_names": ["time_decay"],
                        },
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(
            payload["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            payload["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )

    def test_analysis_status_alias_uses_gate_embedded_calibration_targets_when_file_is_missing(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "evaluation": {
                        "coordinate_strategy_watchlist": ["district_centroid"],
                        "top_coordinate_strategy_group": "district_centroid",
                        "calibration_targets": {
                            "config_patch": {"weighting": {"time_decay": 0.72}},
                            "temporal_targets": [
                                {
                                    "target_type": "temporal",
                                    "name": "time_decay",
                                    "suggested_next_value": 0.72,
                                }
                            ],
                            "global_risk_targets": [],
                            "risk_factor_targets": [],
                            "strategy_targets": [],
                            "top_calibration_target": {
                                "target_type": "temporal",
                                "name": "time_decay",
                            },
                            "top_calibration_target_hint": {
                                "status": "tune_temporal_decay",
                                "target_type": "temporal",
                                "target_name": "time_decay",
                                "playbook_id": "tune-temporal-decay",
                                "recommended_bundle": {
                                    "bundle_id": "temporal-only",
                                    "target_types": ["temporal"],
                                    "target_names": ["time_decay"],
                                },
                            },
                            "guidance": {
                                "status": "tune_temporal_decay",
                                "priority": "medium",
                                "recommended_actions": ["adjust_weighting_time_decay"],
                                "top_reason": "time_decay",
                            },
                        },
                    }
                },
                f,
                ensure_ascii=False,
            )

        status, payload = self._get_json("/api/analysis/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "tune_temporal_decay")
        self.assertEqual(payload["calibration_target_counts"]["temporal"], 1)
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(payload["recommended_bundle_risk_level"], "low")
        self.assertEqual(payload["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )

    def test_analysis_status_alias_merges_partial_embedded_calibration_targets_with_file_context(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {"is_occupied": 0.8},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 0.99,
                        "risk_factor_overrides": {"is_occupied": 0.5},
                    },
                    "temporal_targets": [
                        {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 0.99,
                        }
                    ],
                    "risk_factor_targets": [
                        {
                            "target_type": "risk_flag",
                            "name": "is_occupied",
                            "suggested_next_factor": 0.5,
                        }
                    ],
                    "strategy_targets": [],
                    "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                    "top_calibration_target_hint": {
                        "status": "tune_risk_factors",
                        "playbook_id": "split-bundle-or-single-target-first",
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk-risk-flag",
                            "target_types": ["temporal", "global_risk", "risk_flag"],
                            "target_names": ["time_decay", "risk_discount_factor", "is_occupied"],
                        },
                        "suggested_bundle_commands": [
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied",
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write",
                            "python tools/evaluate_avm.py",
                            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
                        ],
                    },
                    "guidance": {
                        "status": "tune_risk_factors",
                        "priority": "high",
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "top_reason": "multi_flag_bundle",
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "evaluation": {
                        "calibration_targets": {
                            "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                        }
                    }
                },
                f,
                ensure_ascii=False,
            )

        status, payload = self._get_json("/api/analysis/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "tune_risk_factors")
        self.assertEqual(payload["recommended_bundle_risk_level"], "high")
        self.assertEqual(payload["recommended_bundle_next_action"], "split_bundle_or_single_target_first")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["preview"],
        )

    def test_analysis_status_alias_stops_high_risk_bundle_chain_at_preview(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {"is_occupied": 0.8},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 0.99,
                        }
                    ],
                    "risk_factor_targets": [
                        {
                            "target_type": "risk_flag",
                            "name": "is_occupied",
                            "suggested_next_factor": 0.5,
                        }
                    ],
                    "strategy_targets": [],
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 0.99,
                        "risk_factor_overrides": {"is_occupied": 0.5},
                    },
                    "top_calibration_target": {
                        "target_type": "risk_flag",
                        "name": "is_occupied",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_risk_factors",
                        "target_type": "risk_flag",
                        "target_name": "is_occupied",
                        "playbook_id": "split-bundle-or-single-target-first",
                        "runbook_refs": ["tools/apply_avm_calibration_patch.py"],
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "suggested_commands": ["python tools/apply_avm_calibration_patch.py --target-type risk_flag --target-name is_occupied"],
                        "suggested_bundle_commands": [
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied",
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write",
                            "python tools/evaluate_avm.py",
                            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
                        ],
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk-risk-flag",
                            "target_types": ["temporal", "global_risk", "risk_flag"],
                            "target_names": ["time_decay", "risk_discount_factor", "is_occupied"],
                        },
                    },
                    "guidance": {
                        "status": "tune_risk_factors",
                        "priority": "high",
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "top_reason": "multi_flag_bundle",
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["recommended_bundle_risk_level"], "high")
        self.assertIn("high_risk_bundle", payload["recommended_bundle_next_action_reasons"])
        self.assertEqual(payload["recommended_bundle_next_action"], "split_bundle_or_single_target_first")
        self.assertEqual(
            payload["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied",
        )
        self.assertEqual(payload["recommended_bundle_next_action_command_kind"], "preview")
        self.assertEqual(payload["recommended_bundle_follow_up_command"], "")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(len(payload["recommended_bundle_command_chain"]), 1)
        preview_step = payload["recommended_bundle_command_chain"][0]
        self.assertEqual(preview_step["kind"], "preview")
        self.assertEqual(preview_step["step_ready_follow_up_command"], "")
        self.assertEqual(preview_step["step_ready_follow_up_expected_signal"], "")
        self.assertEqual(preview_step["step_ready_follow_up_success_criterion"], "")
        self.assertEqual(preview_step["step_ready_terminal_outcome"], "ready_for_write_decision")
        self.assertEqual(preview_step["step_ready_stage_span"], "preview_then_split")
        self.assertEqual(preview_step["step_ready_badge"], "now-preview-then-split")
        self.assertEqual(preview_step["step_ready_group_id"], "preview-and-split")
        self.assertEqual(preview_step["step_ready_display_order"], 0)

    def test_analysis_status_alias_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [],
                    "risk_factor_targets": [],
                    "strategy_targets": [],
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                    },
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "runbook_refs": ["tools/evaluate_avm.py"],
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "suggested_commands": ["python tools/evaluate_avm.py"],
                        "recommended_bundle": {
                            "bundle_id": "temporal-only",
                            "target_types": ["temporal"],
                            "target_names": ["time_decay"],
                        },
                    },
                    "guidance": {
                        "status": "tune_temporal_decay",
                        "priority": "medium",
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "top_reason": "time_decay",
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/status")

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            payload["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(payload["recommended_bundle_verify_command"], "python tools/evaluate_avm.py")
        self.assertEqual(
            payload["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            payload["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(payload["recommended_bundle_follow_up_command"], "python tools/evaluate_avm.py")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "verify")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )

    def test_analysis_status_alias_normalizes_malformed_calibration_target_lists(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": {
                        "target_type": "temporal",
                        "name": "time_decay",
                        "suggested_next_value": 0.72,
                    },
                    "global_risk_targets": {},
                    "risk_factor_targets": "bad-shape",
                    "strategy_targets": None,
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "recommended_bundle": {
                            "bundle_id": "temporal-only",
                            "target_types": ["temporal"],
                            "target_names": ["time_decay"],
                        },
                    },
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(
            payload["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            payload["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )

    def test_analysis_health_alias_tolerates_non_object_calibration_targets_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_analysis_status_alias_tolerates_non_object_calibration_targets_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_analysis_health_alias_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_analysis_status_alias_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_analysis_health_alias_tolerates_invalid_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": [],
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_analysis_health_alias_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            f.write("{")
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_analysis_status_alias_tolerates_invalid_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": [],
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_analysis_status_alias_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            f.write("{")
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump({"evaluation": {}}, f, ensure_ascii=False)

        status, payload = self._get_json("/api/analysis/status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_collection_template_endpoint(self):
        status, payload = self._get_json("/api/avm/collection_template")
        self.assertEqual(status, 200)
        self.assertEqual(payload["version"], "avm_collection_contract_v1_frozen")
        self.assertTrue(payload["frozen_contract"])
        self.assertIn("groups", payload)
        self.assertIn("collector_priorities", payload)
        self.assertIn("final_template", payload)
        self.assertIn("source", payload["consumer_payload_shape"])
        self.assertIn("archive", payload["consumer_payload_shape"])
        self.assertIn("subject", payload["consumer_payload_shape"])
        self.assertIn("auction", payload["consumer_payload_shape"])
        self.assertIn("legal_context", payload["consumer_payload_shape"])
        self.assertIn("bidder_count", payload["consumer_payload_shape"]["subject"])
        self.assertIn("source", payload["final_template"])
        self.assertIn("source_platform", payload["final_template"]["source"])
        self.assertIn("archive", payload["final_template"])
        self.assertIn("ownership_share_ratio", payload["final_template"]["property"])
        self.assertIn("legal_context", payload["final_template"])
        group_ids = {group["id"] for group in payload["groups"]}
        self.assertIn("auction_core", group_ids)
        self.assertIn("raw_archive", group_ids)
        self.assertIn("legal_context", group_ids)
        self.assertIn("location_spatial", group_ids)

    def test_collection_template_endpoint_returns_json_error_on_failure(self):
        with mock.patch("src.avm.collection_template.get_collection_template", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/collection_template")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_COLLECTION_TEMPLATE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_build_sniff_stub_preserves_address_and_bid_semantics(self):
        stub = server_module.build_sniff_stub(
            {
                "id": "stub-1",
                "title": "测试标题",
                "url": "https://x/stub-1",
                "location": "上海市浦东新区测试路99号",
                "city": "上海市",
                "district": "浦东新区",
                "auction_date": "2026-04-01 10:00:00",
                "currentPrice": "100万",
                "initialPrice": "80万",
                "applyCount": 3,
                "bidCount": 7,
                "bidderCount": 2,
                "deposit": "5万",
                "latitude": 31.2,
                "longitude": 121.5,
                "coordinate_source": "list",
                "auction_round": 2,
                "housing_type": "住宅",
            }
        )

        self.assertEqual(stub["title"], "测试标题")
        self.assertEqual(stub["source_title"], "测试标题")
        self.assertEqual(stub["地点"], "上海市浦东新区测试路99号")
        self.assertEqual(stub["完整地址"], "上海市浦东新区测试路99号")
        self.assertEqual(stub["bid_count"], 7)
        self.assertEqual(stub["出价次数"], 7)
        self.assertEqual(stub["bidder_count"], 2)
        self.assertEqual(stub["出价人数"], 2)
        self.assertEqual(stub["deposit"], 50000.0)
        self.assertEqual(stub["保证金"], 50000.0)
        self.assertEqual(stub["coordinate_source"], "list")
        self.assertEqual(stub["source"]["source_title"], "测试标题")
        self.assertEqual(stub["auction"]["bid_count"], 7)
        self.assertEqual(stub["auction"]["bidder_count"], 2)
        self.assertEqual(stub["auction"]["deposit"], 50000.0)
        self.assertEqual(stub["location"]["full_address"], "上海市浦东新区测试路99号")
        self.assertEqual(stub["location"]["coordinate_source"], "list")

    def test_predict_endpoint(self):
        status, payload = self._get_json("/api/avm/predict?id=3001")
        self.assertEqual(status, 200)
        self.assertEqual(payload["item_id"], "3001")
        self.assertIsNotNone(payload["predicted_price"])
        self.assertIn("risk_validation", payload)
        self.assertIn("valuation_mode", payload["trace"])
        self.assertIn("subject_coordinate_strategy", payload["trace"])

    def test_predict_missing_id_returns_json_error(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/predict")

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_ID")

    def test_predict_not_found_returns_json_error(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/predict?id=999999")

        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_NOT_FOUND")
        self.assertEqual(body["error"]["details"]["id"], "999999")

    def test_predict_failure_returns_json_error(self):
        with mock.patch.object(server_module.AVM_SERVICE, "predict_by_item_id", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/predict?id=3001")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_PREDICT_FAILED")
        self.assertEqual(body["error"]["details"]["id"], "3001")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_predict_alias_endpoint(self):
        status, payload = self._get_json("/api/analysis/predict?id=3001")
        self.assertEqual(status, 200)
        self.assertEqual(payload["item_id"], "3001")
        self.assertIsNotNone(payload["predicted_price"])
        self.assertIn("risk_validation", payload)
        self.assertIn("valuation_mode", payload["trace"])
        self.assertIn("subject_coordinate_strategy", payload["trace"])

    def test_analysis_predict_alias_missing_id_returns_json_error(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/predict")

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_ID")

    def test_analysis_predict_alias_not_found_returns_json_error(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/predict?id=999999")

        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_NOT_FOUND")
        self.assertEqual(body["error"]["details"]["id"], "999999")

    def test_analysis_predict_alias_failure_returns_json_error(self):
        with mock.patch.object(server_module.AVM_SERVICE, "predict_by_item_id", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/predict?id=3001")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_PREDICT_FAILED")
        self.assertEqual(body["error"]["details"]["id"], "3001")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_evaluate_endpoint(self):
        payload = {
            "request_id": "req-test-1",
            "subject": {
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试小区",
                "area_sqm": 100,
                "housing_type": "住宅",
            },
            "auction": {
                "starting_price": 850000,
                "auction_date": "2026-04-01",
            },
            "risk_flags": {
                "is_occupied": True,
            },
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/evaluate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(resp.status, 200)
        self.assertEqual(body["request_id"], "req-test-1")
        self.assertEqual(body["model_version"], "avm_multidim_v1")
        self.assertIsNotNone(body["valuation"]["estimated_fair_price"])
        self.assertIn("risk_validation", body)
        self.assertIn("valuation_mode", body["trace"])
        self.assertIn("risk_adjustments", body)
        self.assertIn("manual_review", body)
        self.assertIn(body["trace"]["strategy"], {"spatial", "community_fallback"})

    def test_evaluate_missing_subject_returns_json_error(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/evaluate",
            data=json.dumps({"request_id": "bad"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_SUBJECT")

    def test_evaluate_missing_area_returns_json_error(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/evaluate",
            data=json.dumps({"request_id": "bad", "subject": {"city": "上海市"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MISSING_AREA")

    def test_evaluate_invalid_json_returns_json_error(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/evaluate",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_evaluate_rejects_non_object_json_body(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/evaluate",
            data=json.dumps([]).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_REQUEST_BODY")
        self.assertEqual(body["error"]["details"]["expected_type"], "object")
        self.assertEqual(body["error"]["details"]["received_type"], "list")

    def test_evaluate_failure_returns_json_error(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/evaluate",
            data=json.dumps({"request_id": "req-test-1", "subject": {"area_sqm": 100}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module.AVM_SERVICE, "evaluate_request", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_EVALUATE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_evaluate_alias_endpoint(self):
        payload = {
            "request_id": "req-test-1",
            "subject": {
                "city": "上海市",
                "district": "浦东新区",
                "community_name": "测试小区",
                "area_sqm": 100,
                "housing_type": "住宅",
            },
            "auction": {
                "starting_price": 850000,
                "auction_date": "2026-04-01",
            },
            "risk_flags": {
                "is_occupied": True,
            },
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/evaluate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(resp.status, 200)
        self.assertEqual(body["request_id"], "req-test-1")
        self.assertEqual(body["model_version"], "avm_multidim_v1")
        self.assertIsNotNone(body["valuation"]["estimated_fair_price"])
        self.assertIn("risk_validation", body)
        self.assertIn("valuation_mode", body["trace"])
        self.assertIn("risk_adjustments", body)
        self.assertIn("manual_review", body)
        self.assertIn(body["trace"]["strategy"], {"spatial", "community_fallback"})

    def test_analysis_evaluate_alias_missing_subject_returns_json_error(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/evaluate",
            data=json.dumps({"request_id": "bad"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_SUBJECT")

    def test_analysis_evaluate_alias_missing_area_returns_json_error(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/evaluate",
            data=json.dumps({"request_id": "bad", "subject": {"city": "上海市"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MISSING_AREA")

    def test_analysis_evaluate_alias_invalid_json_returns_json_error(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/evaluate",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_analysis_evaluate_alias_rejects_non_object_json_body(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/evaluate",
            data=json.dumps([]).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_REQUEST_BODY")
        self.assertEqual(body["error"]["details"]["expected_type"], "object")
        self.assertEqual(body["error"]["details"]["received_type"], "list")

    def test_analysis_evaluate_alias_failure_returns_json_error(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/evaluate",
            data=json.dumps({"request_id": "req-test-1", "subject": {"area_sqm": 100}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module.AVM_SERVICE, "evaluate_request", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_EVALUATE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_run_endpoint_passes_sync_config_to_pipeline_manager(self):
        expected_result = {"status": "completed", "source": "http"}
        with mock.patch.object(server_module.AVM_PIPELINE, "run", return_value=expected_result) as mocked_run:
            status, payload = self._post_json(
                "/api/avm/run",
                {
                    "mode": "sync",
                    "data_dir": self.data_dir,
                    "alerts_threshold": 0.05,
                    "alerts_limit": 12,
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload, expected_result)
        mocked_run.assert_called_once()
        _, kwargs = mocked_run.call_args
        self.assertFalse(kwargs["async_mode"])
        self.assertEqual(kwargs["config"].data_dir, self.data_dir)
        self.assertEqual(kwargs["config"].alerts_threshold, 0.05)
        self.assertEqual(kwargs["config"].alerts_limit, 12)

    def test_run_endpoint_defaults_to_async_when_body_is_empty(self):
        expected_result = {"status": "started", "source": "http-main"}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/run",
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module.AVM_PIPELINE, "run", return_value=expected_result) as mocked_run:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(resp.status, 200)
        self.assertEqual(body, expected_result)
        mocked_run.assert_called_once()
        _, kwargs = mocked_run.call_args
        self.assertTrue(kwargs["async_mode"])
        self.assertEqual(kwargs["config"].data_dir, server_module.DATA_DIR)
        self.assertEqual(kwargs["config"].alerts_threshold, 0.15)
        self.assertEqual(kwargs["config"].alerts_limit, 500)

    def test_run_endpoint_rejects_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/run",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_run_endpoint_rejects_non_object_json_body(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/run",
            data=json.dumps([]).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_REQUEST_BODY")
        self.assertEqual(body["error"]["details"]["expected_type"], "object")
        self.assertEqual(body["error"]["details"]["received_type"], "list")

    def test_run_endpoint_rejects_invalid_pipeline_config_values(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/run",
            data=json.dumps({"alerts_threshold": "bad"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_PIPELINE_CONFIG")
        self.assertIn("alerts_threshold", body["error"]["details"]["invalid_fields"])

    def test_analysis_pipeline_run_alias_passes_sync_config_to_pipeline_manager(self):
        expected_result = {"status": "completed", "source": "http-alias-sync"}
        with mock.patch.object(server_module.AVM_PIPELINE, "run", return_value=expected_result) as mocked_run:
            status, payload = self._post_json(
                "/api/analysis/pipeline/run",
                {
                    "mode": "sync",
                    "data_dir": self.data_dir,
                    "alerts_threshold": 0.05,
                    "alerts_limit": 12,
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload, expected_result)
        mocked_run.assert_called_once()
        _, kwargs = mocked_run.call_args
        self.assertFalse(kwargs["async_mode"])
        self.assertEqual(kwargs["config"].data_dir, self.data_dir)
        self.assertEqual(kwargs["config"].alerts_threshold, 0.05)
        self.assertEqual(kwargs["config"].alerts_limit, 12)

    def test_analysis_pipeline_run_alias_defaults_to_async_when_body_is_empty(self):
        expected_result = {"status": "started", "source": "http-alias"}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/pipeline/run",
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module.AVM_PIPELINE, "run", return_value=expected_result) as mocked_run:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(resp.status, 200)
        self.assertEqual(body, expected_result)
        mocked_run.assert_called_once()
        _, kwargs = mocked_run.call_args
        self.assertTrue(kwargs["async_mode"])
        self.assertEqual(kwargs["config"].data_dir, server_module.DATA_DIR)
        self.assertEqual(kwargs["config"].alerts_threshold, 0.15)
        self.assertEqual(kwargs["config"].alerts_limit, 500)

    def test_analysis_pipeline_run_alias_rejects_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/pipeline/run",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_analysis_pipeline_run_alias_rejects_non_object_json_body(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/pipeline/run",
            data=json.dumps([]).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_REQUEST_BODY")
        self.assertEqual(body["error"]["details"]["expected_type"], "object")
        self.assertEqual(body["error"]["details"]["received_type"], "list")

    def test_analysis_pipeline_run_alias_rejects_invalid_pipeline_config_values(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/pipeline/run",
            data=json.dumps({"alerts_limit": "bad"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_PIPELINE_CONFIG")
        self.assertIn("alerts_limit", body["error"]["details"]["invalid_fields"])

    def test_run_endpoint_returns_json_error_on_pipeline_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/run",
            data=json.dumps({"mode": "sync"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module.AVM_PIPELINE, "run", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_PIPELINE_RUN_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_pipeline_run_alias_returns_json_error_on_pipeline_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/pipeline/run",
            data=json.dumps({"mode": "sync"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module.AVM_PIPELINE, "run", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_PIPELINE_RUN_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_drift_status_endpoint(self):
        status, payload = self._get_json("/api/avm/drift_status?window_days=30")
        self.assertEqual(status, 200)
        self.assertEqual(payload["window_days"], 30)
        self.assertIn("feature_metrics", payload)
        self.assertIn("alerts", payload)

    def test_drift_status_endpoint_defaults_invalid_numeric_query_params(self):
        mocked_output = {"window_days": 30, "feature_metrics": [], "alerts": []}
        with mock.patch("tools.check_feature_drift.generate_drift_report", return_value=mocked_output) as mocked_report:
            status, payload = self._get_json("/api/avm/drift_status?window_days=bad")

        self.assertEqual(status, 200)
        self.assertEqual(payload["window_days"], 30)
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs["window_days"], 30)

    def test_drift_status_endpoint_clamps_negative_numeric_query_params(self):
        mocked_output = {"window_days": 30, "feature_metrics": [], "alerts": []}
        with mock.patch("tools.check_feature_drift.generate_drift_report", return_value=mocked_output) as mocked_report:
            status, payload = self._get_json("/api/avm/drift_status?window_days=-1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["window_days"], 30)
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs["window_days"], 30)

    def test_drift_status_endpoint_returns_json_error_on_failure(self):
        with mock.patch("tools.check_feature_drift.generate_drift_report", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/drift_status?window_days=30")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DRIFT_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_drift_status_alias_endpoint(self):
        status, payload = self._get_json("/api/analysis/drift_status?window_days=30")
        self.assertEqual(status, 200)
        self.assertEqual(payload["window_days"], 30)
        self.assertIn("feature_metrics", payload)
        self.assertIn("alerts", payload)

    def test_analysis_drift_status_alias_defaults_invalid_numeric_query_params(self):
        mocked_output = {"window_days": 30, "feature_metrics": [], "alerts": []}
        with mock.patch("tools.check_feature_drift.generate_drift_report", return_value=mocked_output) as mocked_report:
            status, payload = self._get_json("/api/analysis/drift_status?window_days=bad")

        self.assertEqual(status, 200)
        self.assertEqual(payload["window_days"], 30)
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs["window_days"], 30)

    def test_analysis_drift_status_alias_clamps_negative_numeric_query_params(self):
        mocked_output = {"window_days": 30, "feature_metrics": [], "alerts": []}
        with mock.patch("tools.check_feature_drift.generate_drift_report", return_value=mocked_output) as mocked_report:
            status, payload = self._get_json("/api/analysis/drift_status?window_days=-1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["window_days"], 30)
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs["window_days"], 30)

    def test_analysis_drift_status_alias_returns_json_error_on_failure(self):
        with mock.patch("tools.check_feature_drift.generate_drift_report", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/drift_status?window_days=30")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DRIFT_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_pipeline_status_endpoint(self):
        expected_state = {
            "running": False,
            "started_at": None,
            "finished_at": None,
            "last_error": None,
            "last_result": {"status": "completed"},
            "config": {"data_dir": self.data_dir},
            "merge_check": {"is_fully_merged": True},
        }
        with mock.patch.object(server_module.AVM_PIPELINE, "status", return_value=expected_state) as mocked_status:
            status, payload = self._get_json("/api/avm/pipeline_status")

        self.assertEqual(status, 200)
        self.assertEqual(payload, expected_state)
        mocked_status.assert_called_once()

    def test_pipeline_status_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module.AVM_PIPELINE, "status", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/pipeline_status")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_PIPELINE_STATUS_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_merge_check_endpoint(self):
        expected_merge = {
            "expected_subtasks": [
                "build_canonical_dataset",
                "build_avm_features",
                "generate_avm_alerts",
                "evaluate_avm",
                "suggest_calibration_targets",
                "generate_release_gate_report",
            ],
            "observed_subtasks": [
                "build_canonical_dataset",
                "build_avm_features",
                "generate_avm_alerts",
                "evaluate_avm",
                "suggest_calibration_targets",
                "generate_release_gate_report",
            ],
            "missing_subtasks": [],
            "unexpected_subtasks": [],
            "is_fully_merged": True,
        }
        with mock.patch.object(server_module.AVM_PIPELINE, "verify_merge_completeness", return_value=expected_merge) as mocked_merge:
            status, payload = self._get_json("/api/avm/merge_check")

        self.assertEqual(status, 200)
        self.assertEqual(payload, expected_merge)
        mocked_merge.assert_called_once()

    def test_merge_check_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module.AVM_PIPELINE, "verify_merge_completeness", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/merge_check")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MERGE_CHECK_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_get_item_legacy_endpoint_prefers_repository_item(self):
        fake_repo = mock.Mock()
        fake_repo.enabled = True
        fake_repo.get_flat_item.return_value = {"id": "db-1", "url": "https://x/db-1"}
        with mock.patch.object(server_module, "DB_REPOSITORY", fake_repo):
            status, payload = self._get_json("/api/get_item?id=db-1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["id"], "db-1")
        self.assertEqual(payload["url"], "https://x/db-1")
        fake_repo.get_flat_item.assert_called_once_with("db-1")

    def test_get_item_legacy_endpoint_returns_empty_object_when_id_missing(self):
        status, payload = self._get_json("/api/get_item")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {})

    def test_get_item_legacy_endpoint_returns_empty_object_when_item_not_found(self):
        fake_repo = mock.Mock()
        fake_repo.enabled = True
        fake_repo.get_flat_item.return_value = None
        with mock.patch.object(server_module, "DB_REPOSITORY", fake_repo):
            status, payload = self._get_json("/api/get_item?id=missing")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {})
        fake_repo.get_flat_item.assert_called_once_with("missing")

    def test_get_or_create_sniff_task_legacy_endpoint(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {"task": {"url": "https://x/task"}, "message": "ok"}
        with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
            status, payload = self._get_json("/api/get_or_create_sniff_task?session_id=s-1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["url"], "https://x/task")
        fake_service.next_task.assert_called_once_with("s-1", paused=False)

    def test_get_or_create_sniff_task_legacy_endpoint_returns_empty_task_payload_when_no_task_available(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {"task": None, "message": "所有嗅探任务已完成"}
        with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
            status, payload = self._get_json("/api/get_or_create_sniff_task?session_id=s-1")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"task": None, "message": "所有嗅探任务已完成"})
        fake_service.next_task.assert_called_once_with("s-1", paused=False)

    def test_get_or_create_sniff_task_legacy_endpoint_passes_paused_state(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {"task": {}, "message": "ok"}
        original_paused = server_module.PAUSED
        server_module.PAUSED = True
        try:
            with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
                status, payload = self._get_json("/api/get_or_create_sniff_task?session_id=s-1")
        finally:
            server_module.PAUSED = original_paused

        self.assertEqual(status, 200)
        self.assertEqual(payload["message"], "ok")
        fake_service.next_task.assert_called_once_with("s-1", paused=True)

    def test_get_or_create_sniff_task_legacy_endpoint_treats_force_unlock_flag_as_paused(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {"task": {}, "message": "ok"}
        original_paused = server_module.PAUSED
        original_data_dir = server_module.DATA_DIR
        server_module.PAUSED = False
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, "force_unlock.flag")
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write("manual verification required")
        try:
            with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
                status, payload = self._get_json("/api/get_or_create_sniff_task?session_id=s-1")
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.PAUSED = original_paused

        self.assertEqual(status, 200)
        self.assertEqual(payload["message"], "ok")
        fake_service.next_task.assert_called_once_with("s-1", paused=True)

    def test_get_or_create_sniff_task_legacy_endpoint_returns_json_error_on_failure(self):
        fake_service = mock.Mock()
        fake_service.next_task.side_effect = RuntimeError("boom")
        with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/get_or_create_sniff_task?session_id=s-1")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_SEED_NEXT_TASK_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_get_tasks_legacy_endpoint(self):
        with mock.patch.object(server_module, "_prefer_db_task_reads", return_value=True), mock.patch.object(
            server_module, "_detail_collection_service"
        ) as mocked_factory:
            fake_service = mock.Mock()
            fake_service.batch_tasks.return_value = {
                "tasks": [{"id": "x-1", "url": "https://x/detail-1"}],
                "total": 10,
                "done": 5,
                "pending": 5,
            }
            mocked_factory.return_value = fake_service
            status, payload = self._get_json("/api/get_tasks")

        self.assertEqual(status, 200)
        self.assertEqual(payload["tasks"][0]["id"], "x-1")
        self.assertEqual(payload["total"], 10)
        fake_service.batch_tasks.assert_called_once()

    def test_get_tasks_legacy_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_prefer_db_task_reads", return_value=True), mock.patch.object(
            server_module, "_detail_collection_service"
        ) as mocked_factory:
            fake_service = mock.Mock()
            fake_service.batch_tasks.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/get_tasks")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_BATCH_TASKS_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_get_next_task_legacy_endpoint(self):
        with mock.patch.object(server_module, "_prefer_db_task_reads", return_value=True), mock.patch.object(
            server_module, "_detail_collection_service"
        ) as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_visit_task.return_value = {"task_type": "visit", "id": "x-1", "url": "https://x/detail-1"}
            mocked_factory.return_value = fake_service
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/get_next_task",
                data=b"",
                method="POST",
            )
            with urllib.request.urlopen(request) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["task_type"], "visit")
        self.assertEqual(payload["id"], "x-1")
        fake_service.next_visit_task.assert_called_once()

    def test_get_next_task_legacy_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_visit_task.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/get_next_task",
                data=b"",
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_NEXT_VISIT_TASK_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_get_next_task_legacy_endpoint_returns_none_task_when_no_task_available(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_visit_task.return_value = {"task_type": "none"}
            mocked_factory.return_value = fake_service
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/get_next_task",
                data=b"",
                method="POST",
            )
            with urllib.request.urlopen(request) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"task_type": "none"})
        fake_service.next_visit_task.assert_called_once()

    def test_start_all_subtasks_endpoint_runs_async_defaults(self):
        expected_result = {"status": "started", "source": "start-all"}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/start_all_subtasks",
            data=b"",
            method="POST",
        )
        with mock.patch.object(server_module.AVM_PIPELINE, "run", return_value=expected_result) as mocked_run:
            with urllib.request.urlopen(req) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                status = resp.status

        self.assertEqual(status, 200)
        self.assertEqual(payload, expected_result)
        mocked_run.assert_called_once()
        _, kwargs = mocked_run.call_args
        self.assertTrue(kwargs["async_mode"])
        self.assertEqual(kwargs["config"].data_dir, server_module.DATA_DIR)
        self.assertEqual(kwargs["config"].alerts_threshold, 0.15)
        self.assertEqual(kwargs["config"].alerts_limit, 500)

    def test_start_all_subtasks_endpoint_returns_json_error_on_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/start_all_subtasks",
            data=b"",
            method="POST",
        )
        with mock.patch.object(server_module.AVM_PIPELINE, "run", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_START_ALL_SUBTASKS_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_run_all_subtasks_sync_endpoint_runs_sync_defaults(self):
        expected_result = {"status": "completed", "source": "sync-all"}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/run_all_subtasks_sync",
            data=b"",
            method="POST",
        )
        with mock.patch.object(server_module.AVM_PIPELINE, "run", return_value=expected_result) as mocked_run:
            with urllib.request.urlopen(req) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                status = resp.status

        self.assertEqual(status, 200)
        self.assertEqual(payload, expected_result)
        mocked_run.assert_called_once()
        _, kwargs = mocked_run.call_args
        self.assertFalse(kwargs["async_mode"])
        self.assertEqual(kwargs["config"].data_dir, server_module.DATA_DIR)
        self.assertEqual(kwargs["config"].alerts_threshold, 0.15)
        self.assertEqual(kwargs["config"].alerts_limit, 500)

    def test_run_all_subtasks_sync_endpoint_returns_json_error_on_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/run_all_subtasks_sync",
            data=b"",
            method="POST",
        )
        with mock.patch.object(server_module.AVM_PIPELINE, "run", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_RUN_ALL_SUBTASKS_SYNC_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_release_gate_endpoint(self):
        status, payload = self._get_json("/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")
        self.assertEqual(status, 200)
        self.assertIn("completeness", payload)
        self.assertIn("evaluation", payload)
        self.assertIn("api_smoke", payload)
        self.assertTrue(payload["api_smoke"].get("skipped"))

    def test_release_gate_endpoint_defaults_invalid_numeric_query_params(self):
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }
        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload) as mocked_report, \
             mock.patch.object(server_module, "_avm_operator_eval_summary", return_value={}):
            status, payload = self._get_json("/api/avm/release_gate?window_days=bad&min_sample_size=bad&smoke_sample_size=bad")

        self.assertEqual(status, 200)
        self.assertTrue(payload["api_smoke"].get("skipped"))
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs["window_days"], 7)
        self.assertEqual(mocked_report.call_args.kwargs["min_sample_size"], 1000)
        self.assertEqual(mocked_report.call_args.kwargs["smoke_sample_size"], 0)

    def test_release_gate_endpoint_clamps_negative_numeric_query_params(self):
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }
        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload) as mocked_report, \
             mock.patch.object(server_module, "_avm_operator_eval_summary", return_value={}):
            status, payload = self._get_json("/api/avm/release_gate?window_days=-1&min_sample_size=-1&smoke_sample_size=-1")

        self.assertEqual(status, 200)
        self.assertTrue(payload["api_smoke"].get("skipped"))
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs["window_days"], 7)
        self.assertEqual(mocked_report.call_args.kwargs["min_sample_size"], 1000)
        self.assertEqual(mocked_report.call_args.kwargs["smoke_sample_size"], 0)

    def test_release_gate_endpoint_returns_json_error_on_report_generation_failure(self):
        with mock.patch("tools.avm_release_gate.generate_release_gate_report", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_RELEASE_GATE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_release_gate_endpoint_returns_json_error_on_operator_summary_failure(self):
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }
        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload), \
             mock.patch.object(server_module, "_avm_operator_eval_summary", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_RELEASE_GATE_SUMMARY_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_release_gate_endpoint_returns_json_error_on_report_generation_failure(self):
        with mock.patch("tools.avm_release_gate.generate_release_gate_report", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_RELEASE_GATE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_release_gate_endpoint_defaults_invalid_numeric_query_params(self):
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }
        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload) as mocked_report, \
             mock.patch.object(server_module, "_avm_operator_eval_summary", return_value={}):
            status, payload = self._get_json("/api/analysis/release_gate?window_days=bad&min_sample_size=bad&smoke_sample_size=bad")

        self.assertEqual(status, 200)
        self.assertTrue(payload["api_smoke"].get("skipped"))
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs["window_days"], 7)
        self.assertEqual(mocked_report.call_args.kwargs["min_sample_size"], 1000)
        self.assertEqual(mocked_report.call_args.kwargs["smoke_sample_size"], 0)

    def test_analysis_release_gate_endpoint_clamps_negative_numeric_query_params(self):
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }
        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload) as mocked_report, \
             mock.patch.object(server_module, "_avm_operator_eval_summary", return_value={}):
            status, payload = self._get_json("/api/analysis/release_gate?window_days=-1&min_sample_size=-1&smoke_sample_size=-1")

        self.assertEqual(status, 200)
        self.assertTrue(payload["api_smoke"].get("skipped"))
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs["window_days"], 7)
        self.assertEqual(mocked_report.call_args.kwargs["min_sample_size"], 1000)
        self.assertEqual(mocked_report.call_args.kwargs["smoke_sample_size"], 0)

    def test_release_gate_endpoint_surfaces_calibration_operator_summary(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        gate_payload = {
            "pass": False,
            "evaluation": {
                "pass": False,
                "coordinate_strategy_watchlist": ["district_centroid"],
                "top_coordinate_strategy_group": "district_centroid",
                "calibration_targets": {
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 1.05,
                    },
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 1.05,
                        }
                    ],
                    "risk_factor_targets": [],
                    "strategy_targets": [],
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk",
                            "target_types": ["global_risk", "temporal"],
                            "target_names": None,
                        },
                    },
                    "guidance": {
                        "status": "fix_coordinate_quality",
                        "priority": "high",
                        "recommended_actions": ["review_coordinate_strategy_cohorts"],
                        "top_reason": "district_centroid",
                    },
                },
            },
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(gate_payload, f, ensure_ascii=False)

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "fix_coordinate_quality")
        self.assertEqual(payload["calibration_target_counts"]["temporal"], 1)
        self.assertEqual(payload["calibration_target_counts"]["global_risk"], 1)
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(payload["top_calibration_target_hint"]["playbook_id"], "tune-temporal-decay")
        self.assertEqual(payload["recommended_bundle_risk_level"], "medium")
        self.assertEqual(payload["recommended_bundle_next_action"], "preview_only_first")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["preview", "write", "verify", "gate"],
        )

    def test_release_gate_endpoint_prefers_generated_report_over_stale_gate_file_for_operator_summary(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        stale_gate_payload = {
            "pass": False,
            "evaluation": {
                "pass": False,
                "coordinate_strategy_watchlist": [],
            },
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }
        fresh_gate_payload = {
            "pass": False,
            "evaluation": {
                "pass": False,
                "coordinate_strategy_watchlist": ["district_centroid"],
                "top_coordinate_strategy_group": "district_centroid",
                "calibration_targets": {
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 1.05,
                    },
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 1.05,
                        }
                    ],
                    "risk_factor_targets": [],
                    "strategy_targets": [],
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk",
                            "target_types": ["global_risk", "temporal"],
                            "target_names": None,
                        },
                    },
                    "guidance": {
                        "status": "fix_coordinate_quality",
                        "priority": "high",
                        "recommended_actions": ["review_coordinate_strategy_cohorts"],
                        "top_reason": "district_centroid",
                    },
                },
            },
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(stale_gate_payload, f, ensure_ascii=False)

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=fresh_gate_payload):
            status, payload = self._get_json("/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "fix_coordinate_quality")
        self.assertEqual(payload["calibration_target_counts"]["temporal"], 1)
        self.assertEqual(payload["calibration_target_counts"]["global_risk"], 1)
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(payload["top_calibration_target_hint"]["playbook_id"], "tune-temporal-decay")
        self.assertEqual(payload["recommended_bundle_risk_level"], "medium")
        self.assertEqual(payload["recommended_bundle_next_action"], "preview_only_first")

    def test_release_gate_endpoint_uses_embedded_calibration_targets_when_file_is_missing(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        gate_payload = {
            "pass": False,
            "evaluation": {
                "pass": False,
                "coordinate_strategy_watchlist": ["district_centroid"],
                "top_coordinate_strategy_group": "district_centroid",
                "calibration_targets": {
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                    },
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [],
                    "risk_factor_targets": [],
                    "strategy_targets": [],
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "recommended_bundle": {
                            "bundle_id": "temporal-only",
                            "target_types": ["temporal"],
                            "target_names": ["time_decay"],
                        },
                    },
                    "guidance": {
                        "status": "tune_temporal_decay",
                        "priority": "medium",
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "top_reason": "time_decay",
                    },
                },
            },
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "tune_temporal_decay")
        self.assertEqual(payload["calibration_target_counts"]["temporal"], 1)
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(payload["recommended_bundle_risk_level"], "low")
        self.assertEqual(payload["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )

    def test_release_gate_endpoint_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [],
                    "risk_factor_targets": [],
                    "strategy_targets": [],
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                    },
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "runbook_refs": ["tools/evaluate_avm.py"],
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "suggested_commands": ["python tools/evaluate_avm.py"],
                        "recommended_bundle": {
                            "bundle_id": "temporal-only",
                            "target_types": ["temporal"],
                            "target_names": ["time_decay"],
                        },
                    },
                    "guidance": {
                        "status": "tune_temporal_decay",
                        "priority": "medium",
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "top_reason": "time_decay",
                    },
                },
                f,
                ensure_ascii=False,
            )
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False, "coordinate_strategy_watchlist": []},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(
            payload["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            payload["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(payload["recommended_bundle_verify_command"], "python tools/evaluate_avm.py")
        self.assertEqual(
            payload["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            payload["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(payload["recommended_bundle_follow_up_command"], "python tools/evaluate_avm.py")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "verify")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )

    def test_release_gate_endpoint_normalizes_malformed_calibration_target_lists(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": {
                        "target_type": "temporal",
                        "name": "time_decay",
                        "suggested_next_value": 0.72,
                    },
                    "global_risk_targets": {},
                    "risk_factor_targets": "bad-shape",
                    "strategy_targets": None,
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "recommended_bundle": {
                            "bundle_id": "temporal-only",
                            "target_types": ["temporal"],
                            "target_names": ["time_decay"],
                        },
                    },
                },
                f,
                ensure_ascii=False,
            )
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False, "coordinate_strategy_watchlist": []},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(
            payload["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            payload["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )

    def test_release_gate_endpoint_merges_partial_embedded_calibration_targets_with_file_context(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {"is_occupied": 0.8},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 0.99,
                        "risk_factor_overrides": {"is_occupied": 0.5},
                    },
                    "temporal_targets": [
                        {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 0.99,
                        }
                    ],
                    "risk_factor_targets": [
                        {
                            "target_type": "risk_flag",
                            "name": "is_occupied",
                            "suggested_next_factor": 0.5,
                        }
                    ],
                    "strategy_targets": [],
                    "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                    "top_calibration_target_hint": {
                        "status": "tune_risk_factors",
                        "playbook_id": "split-bundle-or-single-target-first",
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk-risk-flag",
                            "target_types": ["temporal", "global_risk", "risk_flag"],
                            "target_names": ["time_decay", "risk_discount_factor", "is_occupied"],
                        },
                        "suggested_bundle_commands": [
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied",
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write",
                            "python tools/evaluate_avm.py",
                            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
                        ],
                    },
                    "guidance": {
                        "status": "tune_risk_factors",
                        "priority": "high",
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "top_reason": "multi_flag_bundle",
                    },
                },
                f,
                ensure_ascii=False,
            )
        gate_payload = {
            "pass": False,
            "evaluation": {
                "pass": False,
                "coordinate_strategy_watchlist": [],
                "calibration_targets": {
                    "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                },
            },
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["recommended_bundle_risk_level"], "high")
        self.assertEqual(payload["recommended_bundle_next_action"], "split_bundle_or_single_target_first")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["preview"],
        )

    def test_release_gate_endpoint_tolerates_non_object_calibration_targets_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False, "coordinate_strategy_watchlist": []},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_release_gate_endpoint_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False, "coordinate_strategy_watchlist": []},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_release_gate_endpoint_tolerates_invalid_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": -1,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False, "coordinate_strategy_watchlist": []},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_release_gate_endpoint_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            f.write("{")
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False, "coordinate_strategy_watchlist": []},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_analysis_release_gate_endpoint_preserves_analysis_readiness_and_flattens_calibration_summary(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        gate_payload = {
            "pass": False,
            "evaluation": {
                "pass": False,
                "coordinate_strategy_watchlist": ["district_centroid"],
                "top_coordinate_strategy_group": "district_centroid",
                "calibration_targets": {
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 1.05,
                    },
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 1.05,
                        }
                    ],
                    "risk_factor_targets": [],
                    "strategy_targets": [],
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk",
                            "target_types": ["global_risk", "temporal"],
                            "target_names": None,
                        },
                    },
                    "guidance": {
                        "status": "fix_coordinate_quality",
                        "priority": "high",
                        "recommended_actions": ["review_coordinate_strategy_cohorts"],
                        "top_reason": "district_centroid",
                    },
                },
            },
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
            "analysis_readiness": {
                "recommended_actions": ["operator_review"],
                "manual_review_receipt_summary": {"receipt_count": 1},
                "manual_review_receipt_jobs_summary": {"queued_count": 0},
                "manual_review_receipt_operations_summary": {"operation_count": 2},
                "manual_review_control_plane_storage": {"state_source": "repository"},
                "manual_review_control_plane_backup": {"backup_state": "in_sync"},
                "manual_review_control_plane_backup_repairs_summary": {"repair_count": 0},
                "operator_overview": {"handoff_lifecycle_state": "stable"},
            },
        }
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(gate_payload, f, ensure_ascii=False)

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["analysis_readiness"]["manual_review_receipt_summary"]["receipt_count"], 1)
        self.assertEqual(payload["analysis_readiness"]["operator_overview"]["handoff_lifecycle_state"], "stable")
        self.assertEqual(payload["calibration_guidance"]["status"], "fix_coordinate_quality")
        self.assertEqual(payload["calibration_target_counts"]["temporal"], 1)
        self.assertEqual(payload["calibration_target_counts"]["global_risk"], 1)
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(payload["top_calibration_target_hint"]["playbook_id"], "tune-temporal-decay")
        self.assertEqual(payload["recommended_bundle_risk_level"], "medium")
        self.assertEqual(payload["recommended_bundle_next_action"], "preview_only_first")

    def test_analysis_release_gate_endpoint_prefers_generated_report_over_stale_gate_file_for_operator_summary(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        stale_gate_payload = {
            "pass": False,
            "evaluation": {
                "pass": False,
                "coordinate_strategy_watchlist": [],
            },
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
            "analysis_readiness": {
                "manual_review_receipt_summary": {"receipt_count": 0},
                "operator_overview": {"handoff_lifecycle_state": "stale"},
            },
        }
        fresh_gate_payload = {
            "pass": False,
            "evaluation": {
                "pass": False,
                "coordinate_strategy_watchlist": ["district_centroid"],
                "top_coordinate_strategy_group": "district_centroid",
                "calibration_targets": {
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 1.05,
                    },
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 1.05,
                        }
                    ],
                    "risk_factor_targets": [],
                    "strategy_targets": [],
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk",
                            "target_types": ["global_risk", "temporal"],
                            "target_names": None,
                        },
                    },
                    "guidance": {
                        "status": "fix_coordinate_quality",
                        "priority": "high",
                        "recommended_actions": ["review_coordinate_strategy_cohorts"],
                        "top_reason": "district_centroid",
                    },
                },
            },
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
            "analysis_readiness": {
                "manual_review_receipt_summary": {"receipt_count": 1},
                "operator_overview": {"handoff_lifecycle_state": "fresh"},
            },
        }
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(stale_gate_payload, f, ensure_ascii=False)

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=fresh_gate_payload):
            status, payload = self._get_json("/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["analysis_readiness"]["manual_review_receipt_summary"]["receipt_count"], 1)
        self.assertEqual(payload["analysis_readiness"]["operator_overview"]["handoff_lifecycle_state"], "fresh")
        self.assertEqual(payload["calibration_guidance"]["status"], "fix_coordinate_quality")
        self.assertEqual(payload["calibration_target_counts"]["temporal"], 1)
        self.assertEqual(payload["calibration_target_counts"]["global_risk"], 1)
        self.assertEqual(payload["recommended_bundle_risk_level"], "medium")
        self.assertEqual(payload["recommended_bundle_next_action"], "preview_only_first")

    def test_analysis_release_gate_endpoint_uses_embedded_calibration_targets_when_file_is_missing(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        gate_payload = {
            "pass": False,
            "evaluation": {
                "pass": False,
                "coordinate_strategy_watchlist": ["district_centroid"],
                "top_coordinate_strategy_group": "district_centroid",
                "calibration_targets": {
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                    },
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [],
                    "risk_factor_targets": [],
                    "strategy_targets": [],
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "recommended_bundle": {
                            "bundle_id": "temporal-only",
                            "target_types": ["temporal"],
                            "target_names": ["time_decay"],
                        },
                    },
                    "guidance": {
                        "status": "tune_temporal_decay",
                        "priority": "medium",
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "top_reason": "time_decay",
                    },
                },
            },
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
            "analysis_readiness": {
                "manual_review_receipt_summary": {"receipt_count": 1},
                "operator_overview": {"handoff_lifecycle_state": "fresh"},
            },
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["analysis_readiness"]["manual_review_receipt_summary"]["receipt_count"], 1)
        self.assertEqual(payload["calibration_guidance"]["status"], "tune_temporal_decay")
        self.assertEqual(payload["calibration_target_counts"]["temporal"], 1)
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(payload["recommended_bundle_risk_level"], "low")
        self.assertEqual(payload["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )

    def test_analysis_release_gate_endpoint_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72,
                        }
                    ],
                    "global_risk_targets": [],
                    "risk_factor_targets": [],
                    "strategy_targets": [],
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                    },
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "runbook_refs": ["tools/evaluate_avm.py"],
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "suggested_commands": ["python tools/evaluate_avm.py"],
                        "recommended_bundle": {
                            "bundle_id": "temporal-only",
                            "target_types": ["temporal"],
                            "target_names": ["time_decay"],
                        },
                    },
                    "guidance": {
                        "status": "tune_temporal_decay",
                        "priority": "medium",
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "top_reason": "time_decay",
                    },
                },
                f,
                ensure_ascii=False,
            )
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False, "coordinate_strategy_watchlist": []},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
            "analysis_readiness": {
                "manual_review_receipt_summary": {"receipt_count": 1},
                "operator_overview": {"handoff_lifecycle_state": "fresh"},
            },
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["analysis_readiness"]["manual_review_receipt_summary"]["receipt_count"], 1)
        self.assertEqual(
            payload["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            payload["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(payload["recommended_bundle_verify_command"], "python tools/evaluate_avm.py")
        self.assertEqual(
            payload["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "safe_to_write_then_verify")
        self.assertEqual(
            payload["recommended_bundle_next_action_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )
        self.assertEqual(payload["recommended_bundle_follow_up_command"], "python tools/evaluate_avm.py")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "verify")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["write", "verify", "gate"],
        )

    def test_analysis_release_gate_endpoint_normalizes_malformed_calibration_target_lists(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "temporal_targets": {
                        "target_type": "temporal",
                        "name": "time_decay",
                        "suggested_next_value": 0.72,
                    },
                    "global_risk_targets": {},
                    "risk_factor_targets": "bad-shape",
                    "strategy_targets": None,
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "recommended_bundle": {
                            "bundle_id": "temporal-only",
                            "target_types": ["temporal"],
                            "target_names": ["time_decay"],
                        },
                    },
                },
                f,
                ensure_ascii=False,
            )
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False, "coordinate_strategy_watchlist": []},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
            "analysis_readiness": {
                "manual_review_receipt_summary": {"receipt_count": 1},
                "operator_overview": {"handoff_lifecycle_state": "fresh"},
            },
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["analysis_readiness"]["manual_review_receipt_summary"]["receipt_count"], 1)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(
            payload["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay",
        )
        self.assertEqual(
            payload["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write",
        )

    def test_analysis_release_gate_endpoint_merges_partial_embedded_calibration_targets_with_file_context(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {"is_occupied": 0.8},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 0.99,
                        "risk_factor_overrides": {"is_occupied": 0.5},
                    },
                    "temporal_targets": [
                        {"target_type": "temporal", "name": "time_decay", "suggested_next_value": 0.72}
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 0.99,
                        }
                    ],
                    "risk_factor_targets": [
                        {
                            "target_type": "risk_flag",
                            "name": "is_occupied",
                            "suggested_next_factor": 0.5,
                        }
                    ],
                    "strategy_targets": [],
                    "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                    "top_calibration_target_hint": {
                        "status": "tune_risk_factors",
                        "playbook_id": "split-bundle-or-single-target-first",
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk-risk-flag",
                            "target_types": ["temporal", "global_risk", "risk_flag"],
                            "target_names": ["time_decay", "risk_discount_factor", "is_occupied"],
                        },
                        "suggested_bundle_commands": [
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied",
                            "python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write",
                            "python tools/evaluate_avm.py",
                            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
                        ],
                    },
                    "guidance": {
                        "status": "tune_risk_factors",
                        "priority": "high",
                        "recommended_actions": ["split_bundle_or_single_target_first"],
                        "top_reason": "multi_flag_bundle",
                    },
                },
                f,
                ensure_ascii=False,
            )
        gate_payload = {
            "pass": False,
            "evaluation": {
                "pass": False,
                "coordinate_strategy_watchlist": [],
                "calibration_targets": {
                    "top_calibration_target": {"target_type": "risk_flag", "name": "is_occupied"},
                },
            },
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
            "analysis_readiness": {
                "manual_review_receipt_summary": {"receipt_count": 1},
                "operator_overview": {"handoff_lifecycle_state": "fresh"},
            },
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["analysis_readiness"]["manual_review_receipt_summary"]["receipt_count"], 1)
        self.assertEqual(payload["recommended_bundle_risk_level"], "high")
        self.assertEqual(payload["recommended_bundle_next_action"], "split_bundle_or_single_target_first")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "none")
        self.assertEqual(
            [item["kind"] for item in payload["recommended_bundle_command_chain"]],
            ["preview"],
        )

    def test_analysis_release_gate_endpoint_tolerates_non_object_calibration_targets_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False, "coordinate_strategy_watchlist": []},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
            "analysis_readiness": {
                "manual_review_receipt_summary": {"receipt_count": 1},
                "operator_overview": {"handoff_lifecycle_state": "fresh"},
            },
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["analysis_readiness"]["manual_review_receipt_summary"]["receipt_count"], 1)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_analysis_release_gate_endpoint_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False)
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False, "coordinate_strategy_watchlist": []},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
            "analysis_readiness": {
                "manual_review_receipt_summary": {"receipt_count": 1},
                "operator_overview": {"handoff_lifecycle_state": "fresh"},
            },
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["analysis_readiness"]["manual_review_receipt_summary"]["receipt_count"], 1)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_analysis_release_gate_endpoint_tolerates_invalid_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "radius_km": 3.0,
                    "weighting": [],
                    "risk_discount_factor": 0.9,
                    "alert_threshold": 0.25,
                    "risk_factor_overrides": {},
                },
                f,
                ensure_ascii=False,
            )
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False, "coordinate_strategy_watchlist": []},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
            "analysis_readiness": {
                "manual_review_receipt_summary": {"receipt_count": 1},
                "operator_overview": {"handoff_lifecycle_state": "fresh"},
            },
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["analysis_readiness"]["manual_review_receipt_summary"]["receipt_count"], 1)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_analysis_release_gate_endpoint_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "config.json"), "w", encoding="utf-8") as f:
            f.write("{")
        gate_payload = {
            "pass": False,
            "evaluation": {"pass": False, "coordinate_strategy_watchlist": []},
            "completeness": {"pass": True},
            "drift": {"pass": True},
            "api_smoke": {"skipped": True},
            "analysis_readiness": {
                "manual_review_receipt_summary": {"receipt_count": 1},
                "operator_overview": {"handoff_lifecycle_state": "fresh"},
            },
        }

        with mock.patch("tools.avm_release_gate.generate_release_gate_report", return_value=gate_payload):
            status, payload = self._get_json("/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0")

        self.assertEqual(status, 200)
        self.assertEqual(payload["analysis_readiness"]["manual_review_receipt_summary"]["receipt_count"], 1)
        self.assertEqual(payload["calibration_guidance"]["status"], "unavailable")
        self.assertEqual(
            payload["calibration_target_counts"],
            {
                "global_risk": 0,
                "risk_factor": 0,
                "temporal": 0,
                "strategy": 0,
            },
        )
        self.assertEqual(payload["recommended_bundle_next_action"], "no_action_required")

    def test_health_endpoint_surfaces_risk_validation_summary(self):
        status, payload = self._get_json("/api/avm/health")
        self.assertEqual(status, 200)
        self.assertIn("risk_validation_counts", payload)
        self.assertIn("risk_feature_completeness_avg", payload)
        self.assertIn("active_weighting", payload)
        self.assertIn("active_risk_discount_factor", payload)
        self.assertIn("active_risk_factor_override_count", payload)
        self.assertIn("active_risk_factor_overrides", payload)
        self.assertIn("coordinate_strategy_counts", payload)
        self.assertIn("calibration_guidance", payload)
        self.assertIn("calibration_target_counts", payload)
        self.assertIn("top_calibration_target", payload)
        self.assertIn("top_calibration_target_hint", payload)
        self.assertIn("calibration_patch_preview", payload)
        self.assertIn("top_calibration_patch_preview", payload)
        self.assertIn("recommended_bundle_patch_preview", payload)
        self.assertIn("recommended_bundle_risk_level", payload)
        self.assertIn("recommended_bundle_risk_reasons", payload)
        self.assertIn("recommended_bundle_next_action", payload)
        self.assertIn("recommended_bundle_next_action_reasons", payload)
        self.assertIn("recommended_bundle_next_action_command", payload)
        self.assertIn("recommended_bundle_next_action_command_kind", payload)
        self.assertIn("recommended_bundle_follow_up_command", payload)
        self.assertIn("recommended_bundle_follow_up_command_kind", payload)
        self.assertIn("recommended_bundle_command_chain", payload)
        self.assertIn("coordinate_strategy_watchlist", payload)

    def test_health_endpoint_surfaces_calibration_guidance_and_coordinate_watchlist(self):
        avm_dir = os.path.join(self.data_dir, "avm")
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, "calibration_targets.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "risk_factor_targets": [
                        {
                            "target_type": "risk_flag",
                            "name": "is_occupied",
                            "suggested_next_factor": 0.5
                        }
                    ],
                    "global_risk_targets": [
                        {
                            "target_type": "global_risk",
                            "name": "risk_discount_factor",
                            "suggested_next_value": 1.05
                        }
                    ],
                    "temporal_targets": [
                        {
                            "target_type": "temporal",
                            "name": "time_decay",
                            "suggested_next_value": 0.72
                        }
                    ],
                    "strategy_targets": [],
                    "config_patch": {
                        "weighting": {"time_decay": 0.72},
                        "risk_discount_factor": 1.05,
                        "risk_factor_overrides": {"is_occupied": 0.5}
                    },
                    "top_calibration_target": {
                        "target_type": "temporal",
                        "name": "time_decay",
                    },
                    "top_calibration_target_hint": {
                        "status": "tune_temporal_decay",
                        "target_type": "temporal",
                        "target_name": "time_decay",
                        "playbook_id": "tune-temporal-decay",
                        "runbook_refs": ["tools/evaluate_avm.py"],
                        "recommended_actions": ["adjust_weighting_time_decay"],
                        "suggested_commands": ["python tools/evaluate_avm.py"],
                        "suggested_bundle_commands": [
                            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal"
                        ],
                        "recommended_bundle": {
                            "bundle_id": "temporal-global-risk",
                            "target_types": ["global_risk", "temporal"],
                            "target_names": None
                        },
                    },
                    "guidance": {
                        "status": "fix_coordinate_quality",
                        "priority": "high",
                        "recommended_actions": ["review_coordinate_strategy_cohorts"],
                        "top_reason": "district_centroid",
                    }
                },
                f,
                ensure_ascii=False,
            )
        with open(os.path.join(avm_dir, "release_gate.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "evaluation": {
                        "top_coordinate_strategy_group": "district_centroid",
                        "coordinate_strategy_watchlist": ["district_centroid"],
                    }
                },
                f,
                ensure_ascii=False,
            )

        status, payload = self._get_json("/api/avm/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["calibration_guidance"]["status"], "fix_coordinate_quality")
        self.assertEqual(payload["top_calibration_target"]["name"], "time_decay")
        self.assertEqual(payload["top_calibration_target_hint"]["target_name"], "time_decay")
        self.assertEqual(payload["top_calibration_target_hint"]["playbook_id"], "tune-temporal-decay")
        self.assertIn("tools/evaluate_avm.py", payload["top_calibration_target_hint"]["runbook_refs"])
        self.assertIn("python tools/evaluate_avm.py", payload["top_calibration_target_hint"]["suggested_commands"])
        self.assertIn("python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal", payload["top_calibration_target_hint"]["suggested_bundle_commands"])
        self.assertTrue(payload["calibration_patch_preview"]["patch_ready"])
        self.assertIn("weighting.time_decay", payload["calibration_patch_preview"]["changed_keys"])
        self.assertIn("risk_discount_factor", payload["calibration_patch_preview"]["changed_keys"])
        self.assertEqual(payload["calibration_patch_preview"]["changed_paths"]["weighting.time_decay"]["before"], 0.85)
        self.assertEqual(payload["calibration_patch_preview"]["changed_paths"]["weighting.time_decay"]["after"], 0.72)
        self.assertEqual(payload["calibration_patch_preview"]["rollback_patch"]["weighting"]["time_decay"], 0.85)
        self.assertEqual(payload["calibration_target_counts"]["temporal"], 1)
        self.assertEqual(payload["calibration_target_counts"]["global_risk"], 1)
        self.assertEqual(payload["top_calibration_patch_preview"]["applied_filter"], {"target_type": "temporal", "target_name": "time_decay"})
        self.assertEqual(payload["top_calibration_patch_preview"]["changed_keys"], ["weighting.time_decay"])
        self.assertEqual(payload["top_calibration_patch_preview"]["matched_targets"], [{"target_type": "temporal", "target_name": "time_decay"}])
        self.assertEqual(
            payload["recommended_bundle_preview_command"],
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal",
        )
        self.assertEqual(
            payload["recommended_bundle_write_command"],
            "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write",
        )
        self.assertEqual(payload["recommended_bundle_verify_command"], "python tools/evaluate_avm.py")
        self.assertEqual(
            payload["recommended_bundle_gate_command"],
            "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        )
        self.assertEqual(payload["recommended_bundle_patch_preview"]["bundle_id"], "temporal-global-risk")
        self.assertEqual(payload["recommended_bundle_patch_preview"]["applied_filter"], {"target_types": ["global_risk", "temporal"], "target_names": None})
        self.assertEqual(payload["recommended_bundle_patch_preview"]["changed_keys"], ["risk_discount_factor", "weighting.time_decay"])
        self.assertEqual(payload["recommended_bundle_risk_level"], "medium")
        self.assertIn("multiple_changed_keys", payload["recommended_bundle_risk_reasons"])
        self.assertEqual(payload["recommended_bundle_next_action"], "preview_only_first")
        self.assertIn("medium_risk_bundle", payload["recommended_bundle_next_action_reasons"])
        self.assertEqual(payload["recommended_bundle_next_action_command"], "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal")
        self.assertEqual(payload["recommended_bundle_next_action_command_kind"], "preview")
        self.assertEqual(payload["recommended_bundle_follow_up_command"], "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write")
        self.assertEqual(payload["recommended_bundle_follow_up_command_kind"], "write")
        command_chain = payload["recommended_bundle_command_chain"]
        self.assertEqual(
            [item["kind"] for item in command_chain],
            ["preview", "write", "verify", "gate"],
        )
        preview_step, write_step, verify_step, gate_step = command_chain
        self.assertEqual(
            preview_step["step_ready_action_command"],
            payload["recommended_bundle_preview_command"],
        )
        self.assertEqual(
            preview_step["step_ready_follow_up_command"],
            payload["recommended_bundle_write_command"],
        )
        self.assertEqual(preview_step["step_ready_stage_span"], "write_then_evaluate")
        self.assertEqual(preview_step["artifact_state_reason"], "config_not_written_yet")
        self.assertEqual(
            write_step["step_ready_action_command"],
            payload["recommended_bundle_write_command"],
        )
        self.assertEqual(
            write_step["step_ready_follow_up_command"],
            payload["recommended_bundle_verify_command"],
        )
        self.assertEqual(write_step["step_ready_stage_span"], "write_then_evaluate")
        self.assertEqual(
            verify_step["step_ready_action_command"],
            payload["recommended_bundle_verify_command"],
        )
        self.assertEqual(
            verify_step["step_ready_follow_up_command"],
            payload["recommended_bundle_gate_command"],
        )
        self.assertEqual(verify_step["step_ready_stage_span"], "evaluate_then_gate")
        self.assertEqual(verify_step["artifact_state_reason"], "eval_not_rerun_yet")
        self.assertEqual(
            gate_step["step_ready_action_command"],
            payload["recommended_bundle_gate_command"],
        )
        self.assertEqual(gate_step["step_ready_stage_span"], "gate_only")
        self.assertEqual(gate_step["artifact_state_reason"], "pre_bundle_gate_report")
        self.assertEqual(payload["coordinate_strategy_watchlist"], ["district_centroid"])
        self.assertEqual(payload["top_coordinate_strategy_group"], "district_centroid")

    def test_recent_gap_audit_endpoint(self):
        status, payload = self._get_json("/api/avm/recent_gap_audit?window_days=7&sample_limit=5")
        self.assertEqual(status, 200)
        self.assertIn("record_count", payload)
        self.assertIn("missing_field_counts", payload)
        self.assertIn("samples", payload)

    def test_recent_gap_audit_endpoint_defaults_invalid_numeric_query_params(self):
        mocked_output = {"record_count": 0, "missing_field_counts": {}, "samples": []}
        with mock.patch("tools.audit_recent_avm_gaps.build_recent_gap_audit", return_value=mocked_output) as mocked_audit:
            status, payload = self._get_json("/api/avm/recent_gap_audit?window_days=bad&sample_limit=bad")

        self.assertEqual(status, 200)
        self.assertEqual(payload["record_count"], 0)
        mocked_audit.assert_called_once()
        self.assertEqual(mocked_audit.call_args.kwargs["window_days"], 7)
        self.assertEqual(mocked_audit.call_args.kwargs["sample_limit"], 20)

    def test_recent_gap_audit_endpoint_clamps_negative_numeric_query_params(self):
        mocked_output = {"record_count": 0, "missing_field_counts": {}, "samples": []}
        with mock.patch("tools.audit_recent_avm_gaps.build_recent_gap_audit", return_value=mocked_output) as mocked_audit:
            status, payload = self._get_json("/api/avm/recent_gap_audit?window_days=-1&sample_limit=-1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["record_count"], 0)
        mocked_audit.assert_called_once()
        self.assertEqual(mocked_audit.call_args.kwargs["window_days"], 7)
        self.assertEqual(mocked_audit.call_args.kwargs["sample_limit"], 20)

    def test_recent_gap_audit_endpoint_returns_json_error_on_failure(self):
        with mock.patch("tools.audit_recent_avm_gaps.build_recent_gap_audit", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/recent_gap_audit?window_days=7&sample_limit=5")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_RECENT_GAP_AUDIT_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_recent_detail_replay_endpoint(self):
        archive_dir = os.path.join(self.data_dir, "archive", "2026")
        os.makedirs(archive_dir, exist_ok=True)
        recent_file = os.path.join(archive_dir, "2026-03-05.json")
        with open(recent_file, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "id": 9101,
                        "交易时间": "2026-03-05 10:00:00",
                        "成交价格": "100万",
                        "起拍价格": "80万",
                        "建筑面积": "100㎡",
                        "detail_captured": True,
                        "原始网站": "https://sf-item.taobao.com/sf_item/9101.htm",
                    }
                ],
                f,
                ensure_ascii=False,
            )
        status, payload = self._get_json("/api/avm/recent_detail_replay?window_days=7&limit=10&dry_run=false")
        self.assertEqual(status, 200)
        self.assertEqual(payload["prepared_count"], 1)
        with open(recent_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved[0]["url"], "https://sf-item.taobao.com/sf_item/9101.htm")
        self.assertFalse(saved[0]["is_processed"])

    def test_recent_detail_replay_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/recent_detail_replay?window_days=7&limit=10&dry_run=true")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_RECENT_DETAIL_REPLAY_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_recent_detail_replay_get_endpoint_defaults_invalid_numeric_query_params(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {
                "window_days": 7,
                "limit": 100,
                "dry_run": True,
                "prepared_count": 0,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/avm/recent_detail_replay?window_days=bad&limit=bad&dry_run=maybe")

        self.assertEqual(status, 200)
        self.assertEqual(payload["window_days"], 7)
        self.assertEqual(payload["limit"], 100)
        fake_service.prepare_replay.assert_called_once_with(window_days=7, limit=100, dry_run=True)

    def test_recent_detail_replay_get_endpoint_clamps_negative_query_params(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {
                "window_days": 7,
                "limit": 0,
                "dry_run": True,
                "prepared_count": 0,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/avm/recent_detail_replay?window_days=-1&limit=-1&dry_run=maybe")

        self.assertEqual(status, 200)
        self.assertEqual(payload["window_days"], 7)
        self.assertEqual(payload["limit"], 0)
        fake_service.prepare_replay.assert_called_once_with(window_days=7, limit=0, dry_run=True)

    def test_collection_detail_prepare_replay_get_alias_endpoint(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {
                "window_days": 7,
                "limit": 10,
                "dry_run": True,
                "prepared_count": 1,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/collection/details/prepare_replay?window_days=7&limit=10&dry_run=true")

        self.assertEqual(status, 200)
        self.assertEqual(payload["prepared_count"], 1)
        fake_service.prepare_replay.assert_called_once_with(window_days=7, limit=10, dry_run=True)

    def test_collection_detail_prepare_replay_get_alias_defaults_invalid_numeric_query_params(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {
                "window_days": 7,
                "limit": 100,
                "dry_run": True,
                "prepared_count": 0,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/collection/details/prepare_replay?window_days=bad&limit=bad&dry_run=maybe")

        self.assertEqual(status, 200)
        self.assertEqual(payload["window_days"], 7)
        self.assertEqual(payload["limit"], 100)
        fake_service.prepare_replay.assert_called_once_with(window_days=7, limit=100, dry_run=True)

    def test_collection_detail_prepare_replay_get_alias_clamps_negative_query_params(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {
                "window_days": 7,
                "limit": 0,
                "dry_run": True,
                "prepared_count": 0,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/collection/details/prepare_replay?window_days=-1&limit=-1&dry_run=maybe")

        self.assertEqual(status, 200)
        self.assertEqual(payload["window_days"], 7)
        self.assertEqual(payload["limit"], 0)
        fake_service.prepare_replay.assert_called_once_with(window_days=7, limit=0, dry_run=True)

    def test_collection_detail_prepare_replay_get_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/collection/details/prepare_replay?window_days=7&limit=10&dry_run=true")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_RECENT_DETAIL_REPLAY_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_archive_detail_replay_get_endpoint(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {
                "window_days": 30,
                "limit": 11,
                "dry_run": True,
                "prepared_count": 2,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/avm/archive_detail_replay?window_days=30&limit=11&dry_run=true")

        self.assertEqual(status, 200)
        self.assertEqual(payload["prepared_count"], 2)
        fake_service.prepare_replay.assert_called_once_with(window_days=30, limit=11, dry_run=True)

    def test_archive_detail_replay_get_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/archive_detail_replay?window_days=30&limit=11&dry_run=true")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_ARCHIVE_DETAIL_REPLAY_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_archive_detail_replay_get_endpoint_defaults_invalid_numeric_query_params(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {
                "window_days": 30,
                "limit": 500,
                "dry_run": True,
                "prepared_count": 0,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/avm/archive_detail_replay?window_days=bad&limit=bad&dry_run=maybe")

        self.assertEqual(status, 200)
        self.assertEqual(payload["window_days"], 30)
        self.assertEqual(payload["limit"], 500)
        fake_service.prepare_replay.assert_called_once_with(window_days=30, limit=500, dry_run=True)

    def test_archive_detail_replay_get_endpoint_clamps_negative_query_params(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {
                "window_days": 30,
                "limit": 0,
                "dry_run": True,
                "prepared_count": 0,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/avm/archive_detail_replay?window_days=-1&limit=-1&dry_run=maybe")

        self.assertEqual(status, 200)
        self.assertEqual(payload["window_days"], 30)
        self.assertEqual(payload["limit"], 0)
        fake_service.prepare_replay.assert_called_once_with(window_days=30, limit=0, dry_run=True)

    def test_archive_detail_replay_post_endpoint(self):
        archive_dir = os.path.join(self.data_dir, "archive", "2026")
        os.makedirs(archive_dir, exist_ok=True)
        recent_file = os.path.join(archive_dir, "2026-03-05.json")
        with open(recent_file, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "id": 9301,
                        "交易时间": "2026-03-05 10:00:00",
                        "成交价格": "100万",
                        "起拍价格": "80万",
                        "建筑面积": "100㎡",
                        "是否成交": True,
                    }
                ],
                f,
                ensure_ascii=False,
            )
        status, payload = self._post_json(
            "/api/avm/archive_detail_replay",
            {
                "window_days": 30,
                "limit": 10,
                "dry_run": False,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["prepared_count"], 1)

    def test_recent_enrich_maintenance_endpoint(self):
        archive_dir = os.path.join(self.data_dir, "archive", "2026")
        os.makedirs(archive_dir, exist_ok=True)
        detail_dir = os.path.join(self.data_dir, "html_archive", "2026", "2026-03-05")
        os.makedirs(detail_dir, exist_ok=True)
        detail_path = os.path.join(detail_dir, "item-9001.html")
        with open(detail_path, "w", encoding="utf-8") as f:
            f.write("<html><script>var center=[121.5001,31.2002];</script></html>")
        recent_file = os.path.join(archive_dir, "2026-03-05.json")
        with open(recent_file, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "id": 9001,
                        "交易时间": "2026-03-05 10:00:00",
                        "成交价格": "100万",
                        "起拍价格": "80万",
                        "建筑面积": "100㎡",
                        "城市": "上海市",
                        "区": "浦东新区",
                        "detail_captured": True,
                        "detail_archive_path": "html_archive/2026/2026-03-05/item-9001.html",
                    }
                ],
                f,
                ensure_ascii=False,
            )

        status, payload = self._post_json(
            "/api/avm/recent_enrich_maintenance",
            {
                "window_days": 7,
                "archive_limit": 20,
                "sample_limit": 5,
                "dry_run": False,
                "extract_risk": False,
            },
        )
        self.assertEqual(status, 200)
        self.assertIn("before", payload)
        self.assertIn("after", payload)
        self.assertEqual(payload["archived_detail_backfill"]["updated_records"], 1)
        with open(recent_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved[0]["latitude"], 31.2002)
        self.assertEqual(saved[0]["longitude"], 121.5001)

    def test_recent_enrich_maintenance_can_prepare_replay(self):
        archive_dir = os.path.join(self.data_dir, "archive", "2026")
        os.makedirs(archive_dir, exist_ok=True)
        recent_file = os.path.join(archive_dir, "2026-03-05.json")
        with open(recent_file, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "id": 9201,
                        "交易时间": "2026-03-05 10:00:00",
                        "成交价格": "100万",
                        "起拍价格": "80万",
                        "建筑面积": "100㎡",
                        "detail_captured": True,
                        "原始网站": "https://sf-item.taobao.com/sf_item/9201.htm",
                    }
                ],
                f,
                ensure_ascii=False,
            )

        status, payload = self._post_json(
            "/api/avm/recent_enrich_maintenance",
            {
                "window_days": 7,
                "archive_limit": 10,
                "sample_limit": 5,
                "replay_limit": 10,
                "dry_run": False,
                "extract_risk": False,
                "prepare_replay": True,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["detail_replay_preparation"]["prepared_count"], 1)

    def test_collection_detail_maintenance_alias_endpoint(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.run_maintenance.return_value = {
                "before": {"detail_missing": 2},
                "after": {"detail_missing": 1},
                "archived_detail_backfill": {"updated_records": 1},
            }
            mocked_factory.return_value = fake_service

            status, payload = self._post_json(
                "/api/collection/details/maintenance",
                {
                    "window_days": 7,
                    "archive_limit": 20,
                    "sample_limit": 5,
                    "dry_run": True,
                    "extract_risk": False,
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["archived_detail_backfill"]["updated_records"], 1)
        fake_service.run_maintenance.assert_called_once()

    def test_recent_enrich_maintenance_endpoint_rejects_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/recent_enrich_maintenance",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_collection_detail_maintenance_alias_rejects_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/collection/details/maintenance",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_collection_detail_maintenance_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.run_maintenance.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/collection/details/maintenance",
                data=json.dumps({"window_days": 7, "dry_run": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_RECENT_ENRICH_MAINTENANCE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_fetch_missing_detail_archives_endpoint(self):
        with mock.patch("tools.fetch_missing_detail_archives.fetch_missing_detail_archives") as mocked_fetch:
            mocked_fetch.return_value = {
                "limit": 1,
                "timeout": 9,
                "dry_run": True,
                "candidate_count": 2,
                "fetched_count": 1,
                "failed_count": 0,
                "blocked_count": 1,
                "touched_files": 0,
                "samples": [{"item_id": "x-1"}],
            }
            status, payload = self._post_json(
                "/api/avm/fetch_missing_detail_archives",
                {"limit": 1, "timeout": 9, "dry_run": True},
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["candidate_count"], 2)
        self.assertEqual(payload["fetched_count"], 1)
        self.assertEqual(payload["blocked_count"], 1)

    def test_fetch_missing_detail_archives_endpoint_rejects_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/fetch_missing_detail_archives",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_fetch_missing_detail_archives_get_endpoint(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.return_value = {
                "limit": 2,
                "timeout": 11,
                "dry_run": True,
                "candidate_count": 3,
                "fetched_count": 1,
                "failed_count": 1,
                "blocked_count": 1,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/avm/fetch_missing_detail_archives?limit=2&timeout=11&dry_run=true&extract_risk=false")

        self.assertEqual(status, 200)
        self.assertEqual(payload["candidate_count"], 3)
        self.assertEqual(payload["fetched_count"], 1)
        self.assertEqual(payload["blocked_count"], 1)
        fake_service.fetch_missing_archives.assert_called_once_with(limit=2, timeout=11, extract_risk=False, dry_run=True)

    def test_fetch_missing_detail_archives_get_endpoint_defaults_invalid_numeric_query_params(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.return_value = {
                "limit": 20,
                "timeout": 15,
                "dry_run": True,
                "candidate_count": 0,
                "fetched_count": 0,
                "failed_count": 0,
                "blocked_count": 0,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/avm/fetch_missing_detail_archives?limit=bad&timeout=bad&dry_run=maybe&extract_risk=maybe")

        self.assertEqual(status, 200)
        self.assertEqual(payload["limit"], 20)
        self.assertEqual(payload["timeout"], 15)
        fake_service.fetch_missing_archives.assert_called_once_with(limit=20, timeout=15, extract_risk=True, dry_run=True)

    def test_fetch_missing_detail_archives_get_endpoint_clamps_negative_query_params(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.return_value = {
                "limit": 0,
                "timeout": 15,
                "dry_run": True,
                "candidate_count": 0,
                "fetched_count": 0,
                "failed_count": 0,
                "blocked_count": 0,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/avm/fetch_missing_detail_archives?limit=-1&timeout=-1&dry_run=maybe&extract_risk=maybe")

        self.assertEqual(status, 200)
        self.assertEqual(payload["limit"], 0)
        self.assertEqual(payload["timeout"], 15)
        fake_service.fetch_missing_archives.assert_called_once_with(limit=0, timeout=15, extract_risk=True, dry_run=True)

    def test_fetch_missing_detail_archives_get_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/fetch_missing_detail_archives?limit=2&timeout=11&dry_run=true&extract_risk=false")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_detail_fetch_missing_alias_rejects_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/collection/details/fetch_missing",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_collection_detail_fetch_missing_get_alias_endpoint(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.return_value = {
                "limit": 1,
                "timeout": 9,
                "dry_run": True,
                "candidate_count": 2,
                "fetched_count": 1,
                "failed_count": 0,
                "blocked_count": 1,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/collection/details/fetch_missing?limit=1&timeout=9&dry_run=true&extract_risk=false")

        self.assertEqual(status, 200)
        self.assertEqual(payload["candidate_count"], 2)
        self.assertEqual(payload["fetched_count"], 1)
        self.assertEqual(payload["blocked_count"], 1)
        fake_service.fetch_missing_archives.assert_called_once_with(limit=1, timeout=9, extract_risk=False, dry_run=True)

    def test_collection_detail_fetch_missing_get_alias_defaults_invalid_numeric_query_params(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.return_value = {
                "limit": 20,
                "timeout": 15,
                "dry_run": True,
                "candidate_count": 0,
                "fetched_count": 0,
                "failed_count": 0,
                "blocked_count": 0,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/collection/details/fetch_missing?limit=bad&timeout=bad&dry_run=maybe&extract_risk=maybe")

        self.assertEqual(status, 200)
        self.assertEqual(payload["limit"], 20)
        self.assertEqual(payload["timeout"], 15)
        fake_service.fetch_missing_archives.assert_called_once_with(limit=20, timeout=15, extract_risk=True, dry_run=True)

    def test_collection_detail_fetch_missing_get_alias_clamps_negative_query_params(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.return_value = {
                "limit": 0,
                "timeout": 15,
                "dry_run": True,
                "candidate_count": 0,
                "fetched_count": 0,
                "failed_count": 0,
                "blocked_count": 0,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._get_json("/api/collection/details/fetch_missing?limit=-1&timeout=-1&dry_run=maybe&extract_risk=maybe")

        self.assertEqual(status, 200)
        self.assertEqual(payload["limit"], 0)
        self.assertEqual(payload["timeout"], 15)
        fake_service.fetch_missing_archives.assert_called_once_with(limit=0, timeout=15, extract_risk=True, dry_run=True)

    def test_collection_detail_fetch_missing_get_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/collection/details/fetch_missing?limit=1&timeout=9&dry_run=true&extract_risk=false")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_detail_fetch_missing_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.fetch_missing_archives.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/collection/details/fetch_missing",
                data=json.dumps({"limit": 1, "timeout": 9, "dry_run": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_seed_next_task_endpoint(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {"task": {"url": "https://x/task"}, "message": "ok"}
        with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
            status, payload = self._get_json("/api/collection/seeds/next_task?session_id=s-1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["url"], "https://x/task")
        fake_service.next_task.assert_called_once()

    def test_collection_seed_next_task_alias_returns_empty_task_payload_when_no_task_available(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {"task": None, "message": "所有嗅探任务已完成"}
        with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
            status, payload = self._get_json("/api/collection/seeds/next_task?session_id=s-1")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"task": None, "message": "所有嗅探任务已完成"})
        fake_service.next_task.assert_called_once_with("s-1", paused=False)

    def test_collection_seed_next_task_alias_passes_paused_state(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {"task": {}, "message": "ok"}
        original_paused = server_module.PAUSED
        server_module.PAUSED = True
        try:
            with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
                status, payload = self._get_json("/api/collection/seeds/next_task?session_id=s-1")
        finally:
            server_module.PAUSED = original_paused

        self.assertEqual(status, 200)
        self.assertEqual(payload["message"], "ok")
        fake_service.next_task.assert_called_once_with("s-1", paused=True)

    def test_collection_seed_next_task_alias_treats_force_unlock_flag_as_paused(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {"task": {}, "message": "ok"}
        original_paused = server_module.PAUSED
        original_data_dir = server_module.DATA_DIR
        server_module.PAUSED = False
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, "force_unlock.flag")
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write("manual verification required")
        try:
            with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
                status, payload = self._get_json("/api/collection/seeds/next_task?session_id=s-1")
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.PAUSED = original_paused

        self.assertEqual(status, 200)
        self.assertEqual(payload["message"], "ok")
        fake_service.next_task.assert_called_once_with("s-1", paused=True)

    def test_collection_seed_next_task_alias_returns_json_error_on_failure(self):
        fake_service = mock.Mock()
        fake_service.next_task.side_effect = RuntimeError("boom")
        with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/collection/seeds/next_task?session_id=s-1")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_SEED_NEXT_TASK_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_seed_report_progress_alias_endpoint(self):
        fake_service = mock.Mock()
        fake_service.report_progress.return_value = {"status": "ok", "updated": True}
        with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
            status, payload = self._post_json(
                "/api/collection/seeds/report_progress",
                {
                    "url": "https://x/list",
                    "page": 2,
                    "has_next": True,
                    "total_pages": 5,
                    "zero_bid_detected": False,
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        fake_service.report_progress.assert_called_once()

    def test_collection_seed_report_progress_alias_requires_url(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/collection/seeds/report_progress",
            data=json.dumps({"page": 2, "has_next": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_SEED_PROGRESS_MISSING_URL")

    def test_collection_seed_report_progress_alias_returns_500_on_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/collection/seeds/report_progress",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_collection_seed_report_progress_alias_returns_json_error_on_failure(self):
        fake_service = mock.Mock()
        fake_service.report_progress.side_effect = RuntimeError("boom")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/collection/seeds/report_progress",
            data=json.dumps({"url": "https://x/list"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_SEED_PROGRESS_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_seed_report_progress_legacy_endpoint(self):
        fake_service = mock.Mock()
        fake_service.report_progress.return_value = {"status": "ok", "updated": True}
        with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
            status, payload = self._post_json(
                "/api/report_sniff_status",
                {
                    "url": "https://x/list",
                    "page": 2,
                    "has_next": True,
                    "total_pages": 5,
                    "zero_bid_detected": False,
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        fake_service.report_progress.assert_called_once()

    def test_report_sniff_status_legacy_endpoint_requires_url(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/report_sniff_status",
            data=json.dumps({"page": 2, "has_next": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_SEED_PROGRESS_MISSING_URL")

    def test_report_sniff_status_legacy_endpoint_returns_500_on_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/report_sniff_status",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_report_sniff_status_legacy_endpoint_returns_json_error_on_failure(self):
        fake_service = mock.Mock()
        fake_service.report_progress.side_effect = RuntimeError("boom")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/report_sniff_status",
            data=json.dumps({"url": "https://x/list"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module, "_seed_collection_service", return_value=fake_service):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_SEED_PROGRESS_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_seed_batch_endpoint(self):
        with mock.patch.object(server_module, "handle_seed_batch_submission", return_value={"status": "ok", "new": 2}) as mocked_save:
            status, payload = self._post_json(
                "/api/collection/seeds/batch",
                {"items": [{"id": "1"}], "source_page_url": "https://sf.taobao.com/list/x?page=1"},
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["new"], 2)
        mocked_save.assert_called_once()

    def test_collection_seed_batch_alias_returns_500_on_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/collection/seeds/batch",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_collection_seed_batch_legacy_endpoint(self):
        with mock.patch.object(server_module, "handle_seed_batch_submission", return_value={"status": "ok", "new": 2}) as mocked_save:
            status, payload = self._post_json(
                "/api/save",
                {"items": [{"id": "1"}], "source_page_url": "https://sf.taobao.com/list/x?page=1"},
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["new"], 2)
        mocked_save.assert_called_once()

    def test_save_legacy_endpoint_returns_500_on_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/save",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_collection_seed_batch_alias_returns_json_error_on_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/collection/seeds/batch",
            data=json.dumps({"items": [{"id": "1"}]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module, "handle_seed_batch_submission", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_SEED_BATCH_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_save_legacy_endpoint_returns_json_error_on_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/save",
            data=json.dumps({"items": [{"id": "1"}]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module, "handle_seed_batch_submission", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_SEED_BATCH_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_manual_review_receipts_crud_endpoint(self):
        status, payload = self._get_json("/api/avm/manual_review_receipts")
        self.assertEqual(status, 200)
        self.assertEqual(payload["receipt_count"], 0)
        self.assertEqual(payload["manual_review_control_plane_storage"]["state_source"], "json_fallback")
        self.assertEqual(payload["manual_review_control_plane_backup"]["backup_state"], "runtime_json")

        status, backend_status = self._get_json("/api/avm/manual_review_control_plane_status")
        self.assertEqual(status, 200)
        self.assertEqual(backend_status["manual_review_control_plane_storage"]["state_source"], "json_fallback")
        self.assertEqual(backend_status["manual_review_control_plane_backup"]["backup_state"], "runtime_json")
        self.assertEqual(backend_status["manual_review_control_plane_backup_repairs_summary"]["repair_count"], 0)
        self.assertEqual(backend_status["manual_review_control_plane_integrity"]["integrity_status"], "healthy_json_runtime")
        self.assertFalse(backend_status["manual_review_control_plane_integrity"]["attention_required"])
        self.assertEqual(backend_status["manual_review_control_plane_stability"]["stability_status"], "stable_json_runtime")
        self.assertFalse(backend_status["manual_review_control_plane_stability"]["attention_required"])
        self.assertEqual(backend_status["manual_review_control_plane_guidance"]["guidance_status"], "no_action_required")
        self.assertFalse(backend_status["manual_review_control_plane_guidance"]["requires_operator_action"])
        self.assertIn("manual_review_receipt_jobs_summary", backend_status)
        self.assertIn("manual_review_receipt_operations_summary", backend_status)

        status, repairs_payload = self._get_json("/api/avm/manual_review_control_plane_backup_repairs")
        self.assertEqual(status, 200)
        self.assertEqual(repairs_payload["repair_count"], 0)
        self.assertEqual(repairs_payload["repairs"], [])
        self.assertEqual(repairs_payload["manual_review_control_plane_backup_repairs_summary"]["repair_count"], 0)

        status, integrity_history = self._get_json("/api/avm/manual_review_control_plane_integrity_history")
        self.assertEqual(status, 200)
        self.assertEqual(integrity_history["transition_count"], 1)
        self.assertEqual(integrity_history["history"][0]["integrity_status"], "healthy_json_runtime")
        self.assertEqual(integrity_history["manual_review_control_plane_integrity_history_summary"]["last_integrity_status"], "healthy_json_runtime")

        with mock.patch.object(server_module, "run_recent_enrich_maintenance", return_value={"generated_at": "x", "manual_review_reentry_application_summary": {"reentry_applied": False}}) as mocked_maintenance:
            status, payload = self._post_json(
                "/api/avm/manual_review_receipts",
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "async",
                },
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload["operation"], "created")
        self.assertEqual(payload["execution_mode"], "async")
        self.assertTrue(payload["maintenance_triggered"])
        self.assertEqual(payload["maintenance_job_status"], "queued")
        self.assertIn("maintenance_job_id", payload)
        self.assertEqual(payload["manual_review_control_plane_storage"]["state_source"], "json_fallback")
        self.assertEqual(payload["manual_review_control_plane_backup"]["backup_state"], "runtime_json")
        job_payload = self._wait_for_job(payload["maintenance_job_id"])
        self.assertEqual(job_payload["job"]["status"], "completed")
        mocked_maintenance.assert_called_once()

        status, payload = self._get_json("/api/avm/manual_review_receipts")
        self.assertEqual(status, 200)
        self.assertEqual(payload["receipt_count"], 1)
        self.assertEqual(payload["receipts"][0]["action"], "manual_location_review")

        status, payload = self._delete_json(
            "/api/avm/manual_review_receipts",
            {"action": "manual_location_review", "ready_signal": "location_artifacts_complete"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["deleted"])
        self.assertEqual(payload["receipt_count"], 0)

    def test_manual_review_receipts_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "list_manual_review_receipts", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/manual_review_receipts")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPTS_READ_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_manual_review_receipts_crud_alias_endpoint(self):
        status, payload = self._get_json("/api/analysis/manual_review_receipts")
        self.assertEqual(status, 200)
        self.assertEqual(payload["receipt_count"], 0)
        self.assertEqual(payload["manual_review_control_plane_storage"]["state_source"], "json_fallback")
        self.assertEqual(payload["manual_review_control_plane_backup"]["backup_state"], "runtime_json")

        status, backend_status = self._get_json("/api/analysis/manual_review_control_plane_status")
        self.assertEqual(status, 200)
        self.assertEqual(backend_status["manual_review_control_plane_storage"]["state_source"], "json_fallback")
        self.assertEqual(backend_status["manual_review_control_plane_backup"]["backup_state"], "runtime_json")
        self.assertEqual(backend_status["manual_review_control_plane_backup_repairs_summary"]["repair_count"], 0)
        self.assertEqual(backend_status["manual_review_control_plane_integrity"]["integrity_status"], "healthy_json_runtime")
        self.assertFalse(backend_status["manual_review_control_plane_integrity"]["attention_required"])
        self.assertEqual(backend_status["manual_review_control_plane_stability"]["stability_status"], "stable_json_runtime")
        self.assertFalse(backend_status["manual_review_control_plane_stability"]["attention_required"])
        self.assertEqual(backend_status["manual_review_control_plane_guidance"]["guidance_status"], "no_action_required")
        self.assertFalse(backend_status["manual_review_control_plane_guidance"]["requires_operator_action"])
        self.assertIn("manual_review_receipt_jobs_summary", backend_status)
        self.assertIn("manual_review_receipt_operations_summary", backend_status)

        status, repairs_payload = self._get_json("/api/analysis/manual_review_control_plane_backup_repairs")
        self.assertEqual(status, 200)
        self.assertEqual(repairs_payload["repair_count"], 0)
        self.assertEqual(repairs_payload["repairs"], [])
        self.assertEqual(repairs_payload["manual_review_control_plane_backup_repairs_summary"]["repair_count"], 0)

        status, integrity_history = self._get_json("/api/analysis/manual_review_control_plane_integrity_history")
        self.assertEqual(status, 200)
        self.assertEqual(integrity_history["transition_count"], 1)
        self.assertEqual(integrity_history["history"][0]["integrity_status"], "healthy_json_runtime")
        self.assertEqual(integrity_history["manual_review_control_plane_integrity_history_summary"]["last_integrity_status"], "healthy_json_runtime")

        with mock.patch.object(server_module, "run_recent_enrich_maintenance", return_value={"generated_at": "x", "manual_review_reentry_application_summary": {"reentry_applied": False}}) as mocked_maintenance:
            status, payload = self._post_json(
                "/api/analysis/manual_review_receipts",
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "async",
                },
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload["operation"], "created")
        self.assertEqual(payload["execution_mode"], "async")
        self.assertTrue(payload["maintenance_triggered"])
        self.assertEqual(payload["maintenance_job_status"], "queued")
        self.assertIn("maintenance_job_id", payload)
        self.assertEqual(payload["manual_review_control_plane_storage"]["state_source"], "json_fallback")
        self.assertEqual(payload["manual_review_control_plane_backup"]["backup_state"], "runtime_json")
        job_payload = self._wait_for_job(payload["maintenance_job_id"])
        self.assertEqual(job_payload["job"]["status"], "completed")
        mocked_maintenance.assert_called_once()

        status, payload = self._get_json("/api/analysis/manual_review_receipts")
        self.assertEqual(status, 200)
        self.assertEqual(payload["receipt_count"], 1)
        self.assertEqual(payload["receipts"][0]["action"], "manual_location_review")

        status, payload = self._delete_json(
            "/api/analysis/manual_review_receipts",
            {"action": "manual_location_review", "ready_signal": "location_artifacts_complete"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["deleted"])
        self.assertEqual(payload["receipt_count"], 0)

    def test_analysis_manual_review_receipts_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "list_manual_review_receipts", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPTS_READ_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_manual_review_control_plane_status_records_integrity_once_per_request(self):
        original = server_module.record_manual_review_control_plane_integrity
        calls = []

        def _spy(data_root, integrity):
            calls.append(dict(integrity))
            return original(data_root, integrity)

        with mock.patch.object(server_module, "record_manual_review_control_plane_integrity", side_effect=_spy):
            status, payload = self._get_json("/api/avm/manual_review_control_plane_status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["manual_review_control_plane_integrity"]["integrity_status"], "healthy_json_runtime")
        self.assertEqual(len(calls), 1)

    def test_manual_review_control_plane_status_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_manual_review_receipt_context", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/manual_review_control_plane_status")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_CONTROL_PLANE_STATUS_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_manual_review_control_plane_backup_repairs_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "load_manual_review_control_plane_backup_repairs", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/manual_review_control_plane_backup_repairs")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIRS_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_manual_review_control_plane_backup_repairs_endpoints_default_invalid_limit_query_params(self):
        mocked_repairs = [
            {"repair_status": "scheduled"},
            {"repair_status": "completed"},
        ]
        with mock.patch.object(server_module, "load_manual_review_control_plane_backup_repairs", return_value=mocked_repairs):
            for path in (
                "/api/avm/manual_review_control_plane_backup_repairs?limit=bad",
                "/api/analysis/manual_review_control_plane_backup_repairs?limit=bad",
            ):
                with self.subTest(path=path):
                    status, payload = self._get_json(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload["repair_count"], 2)
                    self.assertEqual(payload["applied_filters"]["limit"], 50)

    def test_manual_review_control_plane_backup_repairs_endpoints_clamp_negative_limit(self):
        mocked_repairs = [
            {"repair_status": "scheduled"},
            {"repair_status": "completed"},
        ]
        with mock.patch.object(server_module, "load_manual_review_control_plane_backup_repairs", return_value=mocked_repairs):
            for path in (
                "/api/avm/manual_review_control_plane_backup_repairs?limit=-1",
                "/api/analysis/manual_review_control_plane_backup_repairs?limit=-1",
            ):
                with self.subTest(path=path):
                    status, payload = self._get_json(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload["repair_count"], 0)
                    self.assertEqual(payload["repairs"], [])
                    self.assertEqual(payload["applied_filters"]["limit"], 0)

    def test_manual_review_control_plane_integrity_history_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "load_manual_review_control_plane_integrity_history", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/manual_review_control_plane_integrity_history")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_manual_review_control_plane_integrity_history_endpoints_default_invalid_limit_query_params(self):
        mocked_history = [
            {"integrity_status": "healthy_json_runtime"},
            {"integrity_status": "backup_repair_scheduled"},
        ]
        with mock.patch.object(server_module, "load_manual_review_control_plane_integrity_history", return_value=mocked_history):
            for path in (
                "/api/avm/manual_review_control_plane_integrity_history?limit=bad",
                "/api/analysis/manual_review_control_plane_integrity_history?limit=bad",
            ):
                with self.subTest(path=path):
                    status, payload = self._get_json(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload["transition_count"], 2)
                    self.assertEqual(payload["applied_filters"]["limit"], 50)

    def test_manual_review_control_plane_integrity_history_endpoints_clamp_negative_limit(self):
        mocked_history = [
            {"integrity_status": "healthy_json_runtime"},
            {"integrity_status": "backup_repair_scheduled"},
        ]
        with mock.patch.object(server_module, "load_manual_review_control_plane_integrity_history", return_value=mocked_history):
            for path in (
                "/api/avm/manual_review_control_plane_integrity_history?limit=-1",
                "/api/analysis/manual_review_control_plane_integrity_history?limit=-1",
            ):
                with self.subTest(path=path):
                    status, payload = self._get_json(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload["transition_count"], 0)
                    self.assertEqual(payload["history"], [])
                    self.assertEqual(payload["applied_filters"]["limit"], 0)

    def test_analysis_manual_review_control_plane_status_records_integrity_once_per_request(self):
        original = server_module.record_manual_review_control_plane_integrity
        calls = []

        def _spy(data_root, integrity):
            calls.append(dict(integrity))
            return original(data_root, integrity)

        with mock.patch.object(server_module, "record_manual_review_control_plane_integrity", side_effect=_spy):
            status, payload = self._get_json("/api/analysis/manual_review_control_plane_status")

        self.assertEqual(status, 200)
        self.assertEqual(payload["manual_review_control_plane_integrity"]["integrity_status"], "healthy_json_runtime")
        self.assertEqual(len(calls), 1)

    def test_analysis_manual_review_control_plane_status_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_manual_review_receipt_context", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/manual_review_control_plane_status")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_CONTROL_PLANE_STATUS_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_manual_review_control_plane_backup_repairs_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "load_manual_review_control_plane_backup_repairs", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/manual_review_control_plane_backup_repairs")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIRS_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_manual_review_control_plane_integrity_history_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "load_manual_review_control_plane_integrity_history", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/manual_review_control_plane_integrity_history")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_manual_review_receipts_sync_mode_can_trigger_maintenance(self):
        fake_report = {
            "generated_at": "x",
            "manual_review_reentry_application_summary": {"reentry_applied": False},
            "operator_overview": {"handoff_lifecycle_state": "receipt_ready_for_reentry"},
        }
        with mock.patch.object(server_module, "run_recent_enrich_maintenance", return_value=fake_report) as mocked_maintenance:
            status, payload = self._post_json(
                "/api/avm/manual_review_receipts",
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "sync",
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["execution_mode"], "sync")
        self.assertTrue(payload["maintenance_triggered"])
        self.assertEqual(payload["maintenance_report"]["generated_at"], "x")
        mocked_maintenance.assert_called_once()

    def test_manual_review_receipts_sync_mode_returns_json_error_on_maintenance_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "sync",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module, "run_recent_enrich_maintenance", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_MAINTENANCE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_manual_review_receipts_sync_mode_can_trigger_maintenance(self):
        fake_report = {
            "generated_at": "x",
            "manual_review_reentry_application_summary": {"reentry_applied": False},
            "operator_overview": {"handoff_lifecycle_state": "receipt_ready_for_reentry"},
        }
        with mock.patch.object(server_module, "run_recent_enrich_maintenance", return_value=fake_report) as mocked_maintenance:
            status, payload = self._post_json(
                "/api/analysis/manual_review_receipts",
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "sync",
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["execution_mode"], "sync")
        self.assertTrue(payload["maintenance_triggered"])
        self.assertEqual(payload["maintenance_report"]["generated_at"], "x")
        mocked_maintenance.assert_called_once()

    def test_analysis_manual_review_receipts_sync_mode_returns_json_error_on_maintenance_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "sync",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module, "run_recent_enrich_maintenance", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_MAINTENANCE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_manual_review_receipt_jobs_endpoint_lists_async_jobs(self):
        with mock.patch.object(server_module, "run_recent_enrich_maintenance", return_value={"generated_at": "x"}) as mocked_maintenance:
            status, payload = self._post_json(
                "/api/avm/manual_review_receipts",
                {
                    "action": "manual_status_review",
                    "ready_signal": "status_reconciled",
                    "status": "ready_for_reentry",
                    "payload": {"status_notes": "ok"},
                    "mode": "async",
                },
            )

        self.assertEqual(status, 200)
        job_id = payload["maintenance_job_id"]
        completed = self._wait_for_job(job_id)
        self.assertEqual(completed["job"]["status"], "completed")
        status, jobs_payload = self._get_json("/api/avm/manual_review_receipt_jobs")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(jobs_payload["job_count"], 1)
        self.assertTrue(any(job["job_id"] == job_id for job in jobs_payload["jobs"]))
        mocked_maintenance.assert_called_once()

    def test_manual_review_receipt_jobs_endpoint_returns_null_job_for_unknown_job_id(self):
        fake_manager = mock.Mock()
        fake_manager.snapshot.return_value = {"jobs": [], "running_job_id": None}
        fake_manager.get_job.return_value = None
        with mock.patch.object(server_module, "_get_manual_review_maintenance_manager", return_value=fake_manager):
            status, payload = self._get_json("/api/avm/manual_review_receipt_jobs?job_id=missing-job")

        self.assertEqual(status, 200)
        self.assertEqual(payload["job_count"], 0)
        self.assertIsNone(payload["job"])
        self.assertEqual(payload["queued_jobs"], [])
        fake_manager.get_job.assert_called_once_with("missing-job")

    def test_manual_review_receipt_jobs_endpoint_returns_json_error_on_failure(self):
        fake_manager = mock.Mock()
        fake_manager.snapshot.side_effect = RuntimeError("boom")
        with mock.patch.object(server_module, "_get_manual_review_maintenance_manager", return_value=fake_manager):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/manual_review_receipt_jobs")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_JOBS_READ_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_manual_review_receipt_jobs_alias_endpoint_lists_async_jobs(self):
        with mock.patch.object(server_module, "run_recent_enrich_maintenance", return_value={"generated_at": "x"}) as mocked_maintenance:
            status, payload = self._post_json(
                "/api/analysis/manual_review_receipts",
                {
                    "action": "manual_status_review",
                    "ready_signal": "status_reconciled",
                    "status": "ready_for_reentry",
                    "payload": {"status_notes": "ok"},
                    "mode": "async",
                },
            )

        self.assertEqual(status, 200)
        job_id = payload["maintenance_job_id"]
        completed = self._wait_for_job(job_id)
        self.assertEqual(completed["job"]["status"], "completed")
        status, jobs_payload = self._get_json("/api/analysis/manual_review_receipt_jobs")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(jobs_payload["job_count"], 1)
        self.assertTrue(any(job["job_id"] == job_id for job in jobs_payload["jobs"]))
        mocked_maintenance.assert_called_once()

    def test_analysis_manual_review_receipt_jobs_alias_returns_null_job_for_unknown_job_id(self):
        fake_manager = mock.Mock()
        fake_manager.snapshot.return_value = {"jobs": [], "running_job_id": None}
        fake_manager.get_job.return_value = None
        with mock.patch.object(server_module, "_get_manual_review_maintenance_manager", return_value=fake_manager):
            status, payload = self._get_json("/api/analysis/manual_review_receipt_jobs?job_id=missing-job")

        self.assertEqual(status, 200)
        self.assertEqual(payload["job_count"], 0)
        self.assertIsNone(payload["job"])
        self.assertEqual(payload["queued_jobs"], [])
        fake_manager.get_job.assert_called_once_with("missing-job")

    def test_analysis_manual_review_receipt_jobs_alias_returns_json_error_on_failure(self):
        fake_manager = mock.Mock()
        fake_manager.snapshot.side_effect = RuntimeError("boom")
        with mock.patch.object(server_module, "_get_manual_review_maintenance_manager", return_value=fake_manager):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/manual_review_receipt_jobs")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_JOBS_READ_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_manual_review_receipt_operations_endpoint_lists_and_filters_history(self):
        with mock.patch.object(server_module, "run_recent_enrich_maintenance", return_value={"generated_at": "x"}):
            status, created = self._post_json(
                "/api/avm/manual_review_receipts",
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "async",
                },
            )
            self.assertEqual(status, 200)
            self._wait_for_job(created["maintenance_job_id"])

            status, updated = self._post_json(
                "/api/avm/manual_review_receipts",
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "B"},
                    "mode": "sync",
                },
            )
            self.assertEqual(status, 200)

            status, deleted = self._delete_json(
                "/api/avm/manual_review_receipts",
                {"action": "manual_location_review", "ready_signal": "location_artifacts_complete"},
            )
            self.assertEqual(status, 200)

        status, payload = self._get_json("/api/avm/manual_review_receipt_operations")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(payload["operation_count"], 3)
        self.assertEqual(payload["operations"][0]["operation"], "deleted")
        self.assertEqual(payload["operations"][1]["operation"], "updated")
        self.assertEqual(payload["operations"][2]["operation"], "created")
        self.assertEqual(payload["manual_review_control_plane_storage"]["state_source"], "json_fallback")
        self.assertEqual(payload["manual_review_control_plane_backup"]["backup_state"], "runtime_json")

        status, filtered = self._get_json(
            "/api/avm/manual_review_receipt_operations?action=manual_location_review&ready_signal=location_artifacts_complete&limit=2"
        )
        self.assertEqual(status, 200)
        self.assertEqual(filtered["operation_count"], 2)
        self.assertEqual(filtered["operations"][0]["ready_signal"], "location_artifacts_complete")

    def test_manual_review_receipt_operations_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "load_manual_review_receipt_operations", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/avm/manual_review_receipt_operations")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_OPERATIONS_READ_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_manual_review_receipt_operations_endpoints_default_invalid_limit_query_params(self):
        mocked_operations = [
            {"operation": "created", "ready_signal": "location_artifacts_complete"},
            {"operation": "updated", "ready_signal": "location_artifacts_complete"},
        ]
        with mock.patch.object(server_module, "load_manual_review_receipt_operations", return_value=mocked_operations), \
             mock.patch.object(server_module, "filter_manual_review_receipt_operations", return_value=mocked_operations) as mocked_filter:
            for path in (
                "/api/avm/manual_review_receipt_operations?limit=bad",
                "/api/analysis/manual_review_receipt_operations?limit=bad",
            ):
                with self.subTest(path=path):
                    status, payload = self._get_json(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload["operation_count"], 2)
                    self.assertEqual(payload["applied_filters"]["limit"], 50)

        self.assertEqual(mocked_filter.call_args_list[0].kwargs["limit"], 50)
        self.assertEqual(mocked_filter.call_args_list[1].kwargs["limit"], 50)

    def test_manual_review_receipt_operations_endpoints_clamp_negative_limit(self):
        mocked_operations = [
            {"operation": "created", "ready_signal": "location_artifacts_complete"},
            {"operation": "updated", "ready_signal": "location_artifacts_complete"},
        ]
        with mock.patch.object(server_module, "load_manual_review_receipt_operations", return_value=mocked_operations), \
             mock.patch.object(
                 server_module,
                 "filter_manual_review_receipt_operations",
                 side_effect=lambda operations, **kwargs: [] if kwargs.get("limit") == 0 else mocked_operations,
             ) as mocked_filter:
            for path in (
                "/api/avm/manual_review_receipt_operations?limit=-1",
                "/api/analysis/manual_review_receipt_operations?limit=-1",
            ):
                with self.subTest(path=path):
                    status, payload = self._get_json(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload["operation_count"], 0)
                    self.assertEqual(payload["operations"], [])
                    self.assertEqual(payload["applied_filters"]["limit"], 0)

        self.assertEqual(mocked_filter.call_args_list[0].kwargs["limit"], 0)
        self.assertEqual(mocked_filter.call_args_list[1].kwargs["limit"], 0)

    def test_analysis_manual_review_receipt_operations_alias_endpoint_lists_and_filters_history(self):
        with mock.patch.object(server_module, "run_recent_enrich_maintenance", return_value={"generated_at": "x"}):
            status, created = self._post_json(
                "/api/analysis/manual_review_receipts",
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "async",
                },
            )
            self.assertEqual(status, 200)
            self._wait_for_job(created["maintenance_job_id"])

            status, updated = self._post_json(
                "/api/analysis/manual_review_receipts",
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "B"},
                    "mode": "sync",
                },
            )
            self.assertEqual(status, 200)

            status, deleted = self._delete_json(
                "/api/analysis/manual_review_receipts",
                {"action": "manual_location_review", "ready_signal": "location_artifacts_complete"},
            )
            self.assertEqual(status, 200)

        status, payload = self._get_json("/api/analysis/manual_review_receipt_operations")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(payload["operation_count"], 3)
        self.assertEqual(payload["operations"][0]["operation"], "deleted")
        self.assertEqual(payload["operations"][1]["operation"], "updated")
        self.assertEqual(payload["operations"][2]["operation"], "created")
        self.assertEqual(payload["manual_review_control_plane_storage"]["state_source"], "json_fallback")
        self.assertEqual(payload["manual_review_control_plane_backup"]["backup_state"], "runtime_json")

        status, filtered = self._get_json(
            "/api/analysis/manual_review_receipt_operations?action=manual_location_review&ready_signal=location_artifacts_complete&limit=2"
        )
        self.assertEqual(status, 200)
        self.assertEqual(filtered["operation_count"], 2)
        self.assertEqual(filtered["operations"][0]["ready_signal"], "location_artifacts_complete")

    def test_analysis_manual_review_receipt_operations_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "load_manual_review_receipt_operations", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/analysis/manual_review_receipt_operations")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_OPERATIONS_READ_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_manual_review_receipts_reject_missing_action(self):
        for path in ("/api/avm/manual_review_receipts", "/api/analysis/manual_review_receipts"):
            with self.subTest(path=path):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    data=json.dumps(
                        {
                            "ready_signal": "location_artifacts_complete",
                            "status": "ready_for_reentry",
                            "payload": {"full_address": "A"},
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)

                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(body["error"]["code"], "AVM_INVALID_RECEIPT_ACTION")

    def test_manual_review_receipts_reject_missing_ready_signal(self):
        for path in ("/api/avm/manual_review_receipts", "/api/analysis/manual_review_receipts"):
            with self.subTest(path=path):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    data=json.dumps(
                        {
                            "action": "manual_location_review",
                            "status": "ready_for_reentry",
                            "payload": {"full_address": "A"},
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)

                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(body["error"]["code"], "AVM_INVALID_RECEIPT_SIGNAL")

    def test_manual_review_receipts_reject_missing_status(self):
        for path in ("/api/avm/manual_review_receipts", "/api/analysis/manual_review_receipts"):
            with self.subTest(path=path):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    data=json.dumps(
                        {
                            "action": "manual_location_review",
                            "ready_signal": "location_artifacts_complete",
                            "payload": {"full_address": "A"},
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)

                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(body["error"]["code"], "AVM_INVALID_RECEIPT_STATUS")

    def test_manual_review_receipts_reject_invalid_payload_shape(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": "not-an-object",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_RECEIPT_PAYLOAD")

    def test_analysis_manual_review_receipts_reject_invalid_payload_shape(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": "not-an-object",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_RECEIPT_PAYLOAD")

    def test_manual_review_receipts_reject_invalid_mode(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "later",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_RECEIPT_MODE")

    def test_manual_review_receipts_endpoint_returns_json_error_on_upsert_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "sync",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module, "upsert_manual_review_receipt", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_UPSERT_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_manual_review_receipts_endpoint_returns_json_error_on_async_enqueue_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "async",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        fake_manager = mock.Mock()
        fake_manager.enqueue.side_effect = RuntimeError("boom")
        with mock.patch.object(server_module, "_get_manual_review_maintenance_manager", return_value=fake_manager):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_ENQUEUE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_manual_review_receipts_sync_mode_returns_json_error_on_finalize_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "sync",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module, "run_recent_enrich_maintenance", return_value={"generated_at": "x"}), \
             mock.patch.object(server_module, "append_manual_review_receipt_operation", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_SYNC_FINALIZE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_manual_review_receipts_reject_invalid_mode(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "later",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_RECEIPT_MODE")

    def test_analysis_manual_review_receipts_endpoint_returns_json_error_on_upsert_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "sync",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module, "upsert_manual_review_receipt", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_UPSERT_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_manual_review_receipts_endpoint_returns_json_error_on_async_enqueue_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "async",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        fake_manager = mock.Mock()
        fake_manager.enqueue.side_effect = RuntimeError("boom")
        with mock.patch.object(server_module, "_get_manual_review_maintenance_manager", return_value=fake_manager):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_ENQUEUE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_manual_review_receipts_sync_mode_returns_json_error_on_finalize_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "sync",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module, "run_recent_enrich_maintenance", return_value={"generated_at": "x"}), \
             mock.patch.object(server_module, "append_manual_review_receipt_operation", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_SYNC_FINALIZE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_manual_review_receipts_delete_rejects_missing_action(self):
        for path in ("/api/avm/manual_review_receipts", "/api/analysis/manual_review_receipts"):
            with self.subTest(path=path):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    data=json.dumps({"ready_signal": "location_artifacts_complete"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="DELETE",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)

                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(body["error"]["code"], "AVM_INVALID_RECEIPT_ACTION")

    def test_manual_review_receipts_delete_rejects_missing_ready_signal(self):
        for path in ("/api/avm/manual_review_receipts", "/api/analysis/manual_review_receipts"):
            with self.subTest(path=path):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    data=json.dumps({"action": "manual_location_review"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="DELETE",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)

                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(body["error"]["code"], "AVM_INVALID_RECEIPT_SIGNAL")

    def test_manual_review_receipts_require_control_plane_token_when_configured(self):
        with mock.patch.dict(os.environ, {"FAPAI_CONTROL_PLANE_TOKEN": "secret"}), mock.patch.object(server_module, "run_recent_enrich_maintenance", return_value={"generated_at": "x"}):
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/avm/manual_review_receipts",
                data=json.dumps(
                    {
                        "action": "manual_location_review",
                        "ready_signal": "location_artifacts_complete",
                        "status": "ready_for_reentry",
                        "payload": {"full_address": "A"},
                        "mode": "async",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 403)
            body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertEqual(body["error"]["code"], "AVM_CONTROL_PLANE_FORBIDDEN")

            status, payload = self._post_json(
                "/api/avm/manual_review_receipts",
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "async",
                },
                headers={"X-FAPAI-Control-Token": "secret"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "ok")

            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/avm/manual_review_receipts",
                data=json.dumps(
                    {
                        "action": "manual_location_review",
                        "ready_signal": "location_artifacts_complete",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="DELETE",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 403)
            body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertEqual(body["error"]["code"], "AVM_CONTROL_PLANE_FORBIDDEN")

    def test_manual_review_receipts_delete_returns_json_error_on_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="DELETE",
        )
        with mock.patch.object(server_module, "delete_manual_review_receipt", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_DELETE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_analysis_manual_review_receipts_require_control_plane_token_when_configured(self):
        with mock.patch.dict(os.environ, {"FAPAI_CONTROL_PLANE_TOKEN": "secret"}), mock.patch.object(server_module, "run_recent_enrich_maintenance", return_value={"generated_at": "x"}):
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts",
                data=json.dumps(
                    {
                        "action": "manual_location_review",
                        "ready_signal": "location_artifacts_complete",
                        "status": "ready_for_reentry",
                        "payload": {"full_address": "A"},
                        "mode": "async",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 403)
            body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertEqual(body["error"]["code"], "AVM_CONTROL_PLANE_FORBIDDEN")

            status, payload = self._post_json(
                "/api/analysis/manual_review_receipts",
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                    "mode": "async",
                },
                headers={"X-FAPAI-Control-Token": "secret"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "ok")

            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts",
                data=json.dumps(
                    {
                        "action": "manual_location_review",
                        "ready_signal": "location_artifacts_complete",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="DELETE",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 403)
            body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertEqual(body["error"]["code"], "AVM_CONTROL_PLANE_FORBIDDEN")

    def test_analysis_manual_review_receipts_delete_returns_json_error_on_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts",
            data=json.dumps(
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="DELETE",
        )
        with mock.patch.object(server_module, "delete_manual_review_receipt", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_MANUAL_REVIEW_RECEIPT_DELETE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_detail_fetch_endpoint(self):
        fake_service = mock.Mock()
        fake_service.fetch_missing_archives.return_value = {
            "candidate_count": 2,
            "fetched_count": 1,
            "failed_count": 0,
            "blocked_count": 1,
            "dry_run": True,
        }
        with mock.patch.object(server_module, "_detail_collection_service", return_value=fake_service):
            status, payload = self._post_json(
                "/api/collection/details/fetch_missing",
                {"limit": 1, "timeout": 9, "dry_run": True, "extract_risk": False},
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["candidate_count"], 2)
        self.assertEqual(payload["blocked_count"], 1)
        fake_service.fetch_missing_archives.assert_called_once()

    def test_collection_detail_next_task_alias_endpoint(self):
        with mock.patch.object(server_module, "_prefer_db_task_reads", return_value=True), mock.patch.object(
            server_module, "_detail_collection_service"
        ) as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_task.return_value = {"url": "https://x/detail-task"}
            mocked_factory.return_value = fake_service
            status, payload = self._get_json("/api/collection/details/next_task")

        self.assertEqual(status, 200)
        self.assertEqual(payload["url"], "https://x/detail-task")
        fake_service.next_task.assert_called_once()

    def test_collection_detail_next_task_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_prefer_db_task_reads", return_value=True), mock.patch.object(
            server_module, "_detail_collection_service"
        ) as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_task.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/collection/details/next_task")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_NEXT_TASK_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_detail_next_task_alias_returns_empty_object_when_no_task_available(self):
        with mock.patch.object(server_module, "_prefer_db_task_reads", return_value=True), mock.patch.object(
            server_module, "_detail_collection_service"
        ) as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_task.return_value = None
            mocked_factory.return_value = fake_service
            status, payload = self._get_json("/api/collection/details/next_task")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {})
        fake_service.next_task.assert_called_once()

    def test_collection_detail_next_task_legacy_endpoint(self):
        with mock.patch.object(server_module, "_prefer_db_task_reads", return_value=True), mock.patch.object(
            server_module, "_detail_collection_service"
        ) as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_task.return_value = {"url": "https://x/detail-task"}
            mocked_factory.return_value = fake_service
            status, payload = self._get_json("/api/next_task")

        self.assertEqual(status, 200)
        self.assertEqual(payload["url"], "https://x/detail-task")
        fake_service.next_task.assert_called_once()

    def test_collection_detail_next_task_legacy_endpoint_returns_empty_object_when_no_task_available(self):
        with mock.patch.object(server_module, "_prefer_db_task_reads", return_value=True), mock.patch.object(
            server_module, "_detail_collection_service"
        ) as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_task.return_value = None
            mocked_factory.return_value = fake_service
            status, payload = self._get_json("/api/next_task")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {})
        fake_service.next_task.assert_called_once()

    def test_collection_detail_tasks_alias_endpoint(self):
        with mock.patch.object(server_module, "_prefer_db_task_reads", return_value=True), mock.patch.object(
            server_module, "_detail_collection_service"
        ) as mocked_factory:
            fake_service = mock.Mock()
            fake_service.batch_tasks.return_value = {
                "tasks": [{"id": "x-1", "url": "https://x/detail-1"}],
                "total": 10,
                "done": 5,
                "pending": 5,
            }
            mocked_factory.return_value = fake_service
            status, payload = self._get_json("/api/collection/details/tasks")

        self.assertEqual(status, 200)
        self.assertEqual(payload["tasks"][0]["id"], "x-1")
        self.assertEqual(payload["total"], 10)
        fake_service.batch_tasks.assert_called_once()

    def test_collection_detail_tasks_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_prefer_db_task_reads", return_value=True), mock.patch.object(
            server_module, "_detail_collection_service"
        ) as mocked_factory:
            fake_service = mock.Mock()
            fake_service.batch_tasks.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/collection/details/tasks")

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_BATCH_TASKS_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_detail_tasks_alias_returns_empty_tasks_when_paused(self):
        original_paused = server_module.PAUSED
        server_module.PAUSED = True
        try:
            status, payload = self._get_json("/api/collection/details/tasks")
        finally:
            server_module.PAUSED = original_paused

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"tasks": []})

    def test_collection_detail_tasks_alias_returns_empty_tasks_when_force_unlock_flag_exists(self):
        original_paused = server_module.PAUSED
        original_data_dir = server_module.DATA_DIR
        server_module.PAUSED = False
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, "force_unlock.flag")
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write("manual verification required")
        try:
            status, payload = self._get_json("/api/collection/details/tasks")
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.PAUSED = original_paused

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"tasks": []})

    def test_get_tasks_legacy_endpoint_returns_empty_tasks_when_paused(self):
        original_paused = server_module.PAUSED
        server_module.PAUSED = True
        try:
            status, payload = self._get_json("/api/get_tasks")
        finally:
            server_module.PAUSED = original_paused

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"tasks": []})

    def test_get_tasks_legacy_endpoint_returns_empty_tasks_when_force_unlock_flag_exists(self):
        original_paused = server_module.PAUSED
        original_data_dir = server_module.DATA_DIR
        server_module.PAUSED = False
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, "force_unlock.flag")
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write("manual verification required")
        try:
            status, payload = self._get_json("/api/get_tasks")
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.PAUSED = original_paused

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"tasks": []})

    def test_collection_detail_update_and_area_aliases(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {"status": "ok"}
            mocked_factory.return_value = fake_service

            status, payload = self._post_json("/api/collection/details/update_item", {"id": "3001", "status": "done"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "updated")

            status, payload = self._post_json("/api/collection/details/area_result", {"id": "3001", "建筑面积": 88.8})
            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "ok")

            status, payload = self._post_json("/api/collection/details/approve_area", {"id": "3001", "建筑面积": 88.8})
            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "ok")

        self.assertEqual(fake_service.apply_working_item_patch.call_count, 3)

    def test_collection_detail_update_item_alias_returns_id_not_found_for_missing_item(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {"status": "id_not_found"}
            mocked_factory.return_value = fake_service

            status, payload = self._post_json("/api/collection/details/update_item", {"id": "missing", "status": "done"})

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "id_not_found")
        fake_service.apply_working_item_patch.assert_called_once()

    def test_collection_detail_area_result_alias_returns_404_for_missing_item(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {"status": "id_not_found"}
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/collection/details/area_result",
                data=json.dumps({"id": "missing", "建筑面积": 88.8}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_ITEM_NOT_FOUND")

    def test_collection_detail_approve_area_alias_returns_404_for_missing_item(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {"status": "id_not_found"}
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/collection/details/approve_area",
                data=json.dumps({"id": "missing", "建筑面积": 88.8}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_ITEM_NOT_FOUND")

    def test_collection_detail_update_and_area_legacy_routes(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {"status": "ok"}
            mocked_factory.return_value = fake_service

            status, payload = self._post_json("/api/update_item", {"id": "3001", "status": "done"})
            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "updated")

            status, payload = self._post_json("/api/area_result", {"id": "3001", "建筑面积": 88.8})
            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "ok")

            status, payload = self._post_json("/api/approve_area", {"id": "3001", "建筑面积": 88.8})
            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "ok")

        self.assertEqual(fake_service.apply_working_item_patch.call_count, 3)

    def test_update_item_legacy_endpoint_returns_id_not_found_for_missing_item(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {"status": "id_not_found"}
            mocked_factory.return_value = fake_service

            status, payload = self._post_json("/api/update_item", {"id": "missing", "status": "done"})

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "id_not_found")
        fake_service.apply_working_item_patch.assert_called_once()

    def test_collection_detail_update_item_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/collection/details/update_item",
                data=json.dumps({"id": "3001", "status": "done"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_UPDATE_ITEM_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_update_item_legacy_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/update_item",
                data=json.dumps({"id": "3001", "status": "done"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_UPDATE_ITEM_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_area_result_legacy_endpoint_returns_404_for_missing_item(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {"status": "id_not_found"}
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/area_result",
                data=json.dumps({"id": "missing", "建筑面积": 88.8}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_ITEM_NOT_FOUND")

    def test_approve_area_legacy_endpoint_returns_404_for_missing_item(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {"status": "id_not_found"}
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/approve_area",
                data=json.dumps({"id": "missing", "建筑面积": 88.8}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_ITEM_NOT_FOUND")

    def test_collection_detail_area_result_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/collection/details/area_result",
                data=json.dumps({"id": "3001", "建筑面积": 88.8}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_AREA_RESULT_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_area_result_legacy_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/area_result",
                data=json.dumps({"id": "3001", "建筑面积": 88.8}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_AREA_RESULT_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_detail_approve_area_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/collection/details/approve_area",
                data=json.dumps({"id": "3001", "建筑面积": 88.8}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_APPROVE_AREA_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_approve_area_legacy_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/approve_area",
                data=json.dumps({"id": "3001", "建筑面积": 88.8}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_APPROVE_AREA_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_detail_infer_location_alias(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.infer_location.return_value = {"所属小区": "测试小区", "城市": "上海市"}
            mocked_factory.return_value = fake_service

            status, payload = self._post_json(
                "/api/collection/details/infer_location",
                {"id": "3001", "address": "上海市浦东新区测试路99号", "title": "测试标题"},
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["所属小区"], "测试小区")
        fake_service.infer_location.assert_called_once()

    def test_collection_detail_infer_location_alias_returns_500_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.infer_location.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/collection/details/infer_location",
                data=json.dumps({"id": "3001", "address": "x", "title": "y"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_INFER_LOCATION_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_infer_location_legacy_endpoint_returns_500_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.infer_location.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/infer_location",
                data=json.dumps({"id": "3001", "address": "x", "title": "y"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_INFER_LOCATION_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_detail_infer_location_legacy_endpoint(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.infer_location.return_value = {"所属小区": "测试小区", "城市": "上海市"}
            mocked_factory.return_value = fake_service

            status, payload = self._post_json(
                "/api/infer_location",
                {"id": "3001", "address": "上海市浦东新区测试路99号", "title": "测试标题"},
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["所属小区"], "测试小区")
        fake_service.infer_location.assert_called_once()

    def test_collection_detail_prepare_replay_alias_endpoint(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {
                "window_days": 30,
                "limit": 10,
                "dry_run": True,
                "prepared_count": 1,
            }
            mocked_factory.return_value = fake_service

            status, payload = self._post_json(
                "/api/collection/details/prepare_replay",
                {
                    "window_days": 30,
                    "limit": 10,
                    "dry_run": True,
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["prepared_count"], 1)
        fake_service.prepare_replay.assert_called_once()

    def test_archive_detail_replay_endpoint_rejects_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/archive_detail_replay",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_collection_detail_prepare_replay_alias_rejects_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/collection/details/prepare_replay",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_collection_detail_prepare_replay_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/collection/details/prepare_replay",
                data=json.dumps({"window_days": 30, "limit": 10, "dry_run": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_ARCHIVE_DETAIL_REPLAY_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_detail_html_alias(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.submit_html.return_value = {"status": "queued"}
            mocked_factory.return_value = fake_service

            status, payload = self._post_json(
                "/api/collection/details/html",
                {"id": "3001", "html": "<html></html>", "status": "done"},
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "queued")
        fake_service.submit_html.assert_called_once()

    def test_collection_detail_html_alias_returns_500_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.submit_html.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/collection/details/html",
                data=json.dumps({"id": "3001", "html": "<html></html>", "status": "done"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_ANALYZE_HTML_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_detail_html_legacy_endpoint(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.submit_html.return_value = {"status": "queued"}
            mocked_factory.return_value = fake_service

            status, payload = self._post_json(
                "/api/analyze_html",
                {"id": "3001", "html": "<html></html>", "status": "done"},
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "queued")
        fake_service.submit_html.assert_called_once()

    def test_analyze_html_legacy_endpoint_returns_500_on_failure(self):
        with mock.patch.object(server_module, "_detail_collection_service") as mocked_factory:
            fake_service = mock.Mock()
            fake_service.submit_html.side_effect = RuntimeError("boom")
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/analyze_html",
                data=json.dumps({"id": "3001", "html": "<html></html>", "status": "done"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_DETAIL_ANALYZE_HTML_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_resume_endpoint_clears_pause_and_force_unlock_flag(self):
        original_paused = server_module.PAUSED
        original_data_dir = server_module.DATA_DIR
        original_running = server_module.SOLVER_RUNNING
        original_start_time = server_module.SOLVER_START_TIME
        server_module.PAUSED = True
        server_module.DATA_DIR = self.data_dir
        server_module.SOLVER_RUNNING = True
        server_module.SOLVER_START_TIME = time.time() - 300
        flag_path = os.path.join(self.data_dir, "force_unlock.flag")
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write("1")

        try:
            status, payload = self._get_json("/api/resume")
        finally:
            observed_running = server_module.SOLVER_RUNNING
            server_module.DATA_DIR = original_data_dir
            server_module.PAUSED = original_paused
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "resumed")
        self.assertFalse(os.path.exists(flag_path))
        self.assertFalse(observed_running)

    def test_save_locations_endpoint_deduplicates_by_code(self):
        original_data_dir = server_module.DATA_DIR
        server_module.DATA_DIR = self.data_dir
        try:
            status, payload = self._post_json(
                "/api/save_locations",
                {
                    "locations": [
                        {"code": "310115", "name": "浦东新区"},
                        {"code": "310115", "name": "浦东新区"},
                        {"code": "310104", "name": "徐汇区"},
                    ]
                },
            )
        finally:
            server_module.DATA_DIR = original_data_dir

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["count"], 3)

        with open(os.path.join(self.data_dir, "collected_locations.json"), "r", encoding="utf-8") as f:
            persisted = json.load(f)
        self.assertEqual(len(persisted), 2)
        self.assertEqual({item["code"] for item in persisted}, {"310115", "310104"})

    def test_save_locations_endpoint_returns_500_on_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/save_locations",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_save_locations_endpoint_returns_json_error_on_failure(self):
        original_data_dir = server_module.DATA_DIR
        server_module.DATA_DIR = self.data_dir
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/save_locations",
            data=json.dumps({"locations": [{"code": "1", "name": "A"}]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with mock.patch.object(server_module, "open", side_effect=RuntimeError("boom"), create=True):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
        finally:
            server_module.DATA_DIR = original_data_dir

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_SAVE_LOCATIONS_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_report_captcha_endpoint_queues_solver(self):
        with mock.patch.object(server_module.executor, "submit") as mocked_submit:
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/report_captcha",
                data=b"",
                method="POST",
            )
            with urllib.request.urlopen(request) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "solving")
        mocked_submit.assert_called_once()
        submitted_callable = mocked_submit.call_args.args[0]
        self.assertEqual(getattr(submitted_callable, "__name__", ""), "run_solver")
        self.assertEqual(mocked_submit.call_args.args[1], {})

    def test_report_captcha_endpoint_deduplicates_solver_while_first_submission_is_pending(self):
        original_paused = server_module.PAUSED
        original_pause_reason = server_module.COLLECTION_PAUSE_REASON
        original_running = server_module.SOLVER_RUNNING
        original_start_time = server_module.SOLVER_START_TIME
        original_last_status = server_module.SOLVER_LAST_STATUS
        original_last_failure = server_module.SOLVER_LAST_FAILURE_REASON
        original_last_request = dict(server_module.SOLVER_LAST_REQUEST)
        original_data_dir = server_module.DATA_DIR
        original_pending_token = getattr(server_module, "SOLVER_PENDING_TOKEN", None)
        try:
            server_module.PAUSED = False
            server_module.COLLECTION_PAUSE_REASON = None
            server_module.SOLVER_RUNNING = False
            server_module.SOLVER_START_TIME = 0
            server_module.SOLVER_LAST_STATUS = "idle"
            server_module.SOLVER_LAST_FAILURE_REASON = None
            server_module.SOLVER_LAST_REQUEST = {}
            server_module.DATA_DIR = self.data_dir
            if hasattr(server_module, "SOLVER_PENDING_TOKEN"):
                server_module.SOLVER_PENDING_TOKEN = None

            with mock.patch.object(server_module.executor, "submit") as mocked_submit:
                first_status, first_body = self._post_json("/api/report_captcha", {})
                second_status, second_body = self._post_json("/api/report_captcha", {})
        finally:
            if hasattr(server_module, "SOLVER_PENDING_TOKEN"):
                server_module.SOLVER_PENDING_TOKEN = original_pending_token
            server_module.DATA_DIR = original_data_dir
            server_module.SOLVER_LAST_REQUEST = original_last_request
            server_module.SOLVER_LAST_FAILURE_REASON = original_last_failure
            server_module.SOLVER_LAST_STATUS = original_last_status
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running
            server_module.COLLECTION_PAUSE_REASON = original_pause_reason
            server_module.PAUSED = original_paused

        self.assertEqual(first_status, 200)
        self.assertEqual(first_body["status"], "solving")
        self.assertEqual(second_status, 200)
        self.assertEqual(second_body["status"], "already_running")
        mocked_submit.assert_called_once()

    def test_report_captcha_endpoint_does_not_requeue_while_solver_is_running(self):
        original_running = server_module.SOLVER_RUNNING
        original_start_time = server_module.SOLVER_START_TIME
        try:
            server_module.SOLVER_RUNNING = True
            server_module.SOLVER_START_TIME = time.time() - 7
            with mock.patch.object(server_module.executor, "submit") as mocked_submit:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/api/report_captcha",
                    data=b"",
                    method="POST",
                )
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))

        finally:
            server_module.SOLVER_RUNNING = original_running
            server_module.SOLVER_START_TIME = original_start_time

        self.assertEqual(body["status"], "already_running")
        self.assertEqual(body["elapsed_seconds"], 7)
        mocked_submit.assert_not_called()

    def test_report_captcha_endpoint_refreshes_last_request_while_solver_is_running(self):
        original_running = server_module.SOLVER_RUNNING
        original_start_time = server_module.SOLVER_START_TIME
        original_last_request = dict(server_module.SOLVER_LAST_REQUEST)
        body = None
        mocked_submit = None
        try:
            server_module.SOLVER_RUNNING = True
            server_module.SOLVER_START_TIME = time.time() - 7
            server_module.SOLVER_LAST_REQUEST = {
                "cdp_endpoint": "http://192.168.15.104:9224",
                "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
                "node_id": "pc2",
            }
            with mock.patch.object(server_module.executor, "submit") as mocked_submit:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/api/report_captcha",
                    data=json.dumps(
                        {
                            "cdp_endpoint": "http://192.168.15.20:9224",
                            "node_id": "pc2",
                            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&__captcha_solver_bg=1",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))

            self.assertEqual(body["status"], "already_running")
            mocked_submit.assert_not_called()
            self.assertEqual(
                server_module.SOLVER_LAST_REQUEST,
                {
                    "cdp_endpoint": "http://192.168.15.20:9224",
                    "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&__captcha_solver_bg=1",
                    "node_id": "pc2",
                },
            )
        finally:
            server_module.SOLVER_LAST_REQUEST = original_last_request
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running

    def test_report_captcha_endpoint_does_not_start_parallel_solver_after_timeout(self):
        original_paused = server_module.PAUSED
        original_pause_reason = server_module.COLLECTION_PAUSE_REASON
        original_running = server_module.SOLVER_RUNNING
        original_start_time = server_module.SOLVER_START_TIME
        original_last_status = server_module.SOLVER_LAST_STATUS
        original_last_failure = server_module.SOLVER_LAST_FAILURE_REASON
        original_data_dir = server_module.DATA_DIR
        try:
            server_module.PAUSED = False
            server_module.COLLECTION_PAUSE_REASON = None
            server_module.SOLVER_RUNNING = True
            server_module.SOLVER_START_TIME = time.time() - 180
            server_module.SOLVER_LAST_STATUS = "running"
            server_module.SOLVER_LAST_FAILURE_REASON = None
            server_module.DATA_DIR = self.data_dir
            with mock.patch.object(server_module.executor, "submit") as mocked_submit:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/api/report_captcha",
                    data=b"",
                    method="POST",
                )
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.SOLVER_LAST_FAILURE_REASON = original_last_failure
            server_module.SOLVER_LAST_STATUS = original_last_status
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running
            server_module.COLLECTION_PAUSE_REASON = original_pause_reason
            server_module.PAUSED = original_paused

        self.assertEqual(body["status"], "manual_required")
        self.assertEqual(body["elapsed_seconds"], 180)
        self.assertTrue(body["captcha_solver"]["manual_required"])
        self.assertTrue(body["captcha_solver"]["force_unlock_flag_exists"])
        self.assertTrue(os.path.exists(os.path.join(self.data_dir, "force_unlock.flag")))
        mocked_submit.assert_not_called()

    def test_report_captcha_endpoint_respects_configured_solver_runtime(self):
        original_paused = server_module.PAUSED
        original_pause_reason = server_module.COLLECTION_PAUSE_REASON
        original_running = server_module.SOLVER_RUNNING
        original_start_time = server_module.SOLVER_START_TIME
        original_last_status = server_module.SOLVER_LAST_STATUS
        original_last_failure = server_module.SOLVER_LAST_FAILURE_REASON
        original_data_dir = server_module.DATA_DIR
        body = None
        try:
            server_module.PAUSED = False
            server_module.COLLECTION_PAUSE_REASON = None
            server_module.SOLVER_RUNNING = True
            server_module.SOLVER_START_TIME = time.time() - 180
            server_module.SOLVER_LAST_STATUS = "running"
            server_module.SOLVER_LAST_FAILURE_REASON = None
            server_module.DATA_DIR = self.data_dir
            with mock.patch.dict(os.environ, {"FAPAI_SOLVER_MAX_RUNTIME_SECONDS": "240"}):
                with mock.patch.object(server_module.executor, "submit") as mocked_submit:
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{self.port}/api/report_captcha",
                        data=b"",
                        method="POST",
                    )
                    with urllib.request.urlopen(request) as resp:
                        self.assertEqual(resp.status, 200)
                        body = json.loads(resp.read().decode("utf-8"))
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.SOLVER_LAST_FAILURE_REASON = original_last_failure
            server_module.SOLVER_LAST_STATUS = original_last_status
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running
            server_module.COLLECTION_PAUSE_REASON = original_pause_reason
            server_module.PAUSED = original_paused

        self.assertEqual(body["status"], "already_running")
        self.assertEqual(body["elapsed_seconds"], 180)
        mocked_submit.assert_not_called()

    def test_report_captcha_endpoint_does_not_requeue_while_manual_verification_is_required(self):
        original_paused = server_module.PAUSED
        original_running = server_module.SOLVER_RUNNING
        original_start_time = server_module.SOLVER_START_TIME
        original_data_dir = server_module.DATA_DIR
        server_module.PAUSED = True
        server_module.SOLVER_RUNNING = True
        server_module.SOLVER_START_TIME = time.time() - 1800
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, "force_unlock.flag")
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write("manual verification required")
        try:
            with mock.patch.object(server_module.executor, "submit") as mocked_submit:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/api/report_captcha",
                    data=b"",
                    method="POST",
                )
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running
            server_module.PAUSED = original_paused

        self.assertEqual(body["status"], "manual_required")
        self.assertTrue(body["captcha_solver"]["manual_required"])
        self.assertTrue(body["captcha_solver"]["force_unlock_flag_exists"])
        mocked_submit.assert_not_called()

    def test_report_captcha_endpoint_refreshes_last_request_while_manual_verification_is_required(self):
        original_paused = server_module.PAUSED
        original_running = server_module.SOLVER_RUNNING
        original_start_time = server_module.SOLVER_START_TIME
        original_last_request = dict(server_module.SOLVER_LAST_REQUEST)
        original_data_dir = server_module.DATA_DIR
        body = None
        mocked_submit = None
        server_module.PAUSED = True
        server_module.SOLVER_RUNNING = True
        server_module.SOLVER_START_TIME = time.time() - 1800
        server_module.SOLVER_LAST_REQUEST = {
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
            "node_id": "pc2",
        }
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, "force_unlock.flag")
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write("manual verification required")
        try:
            with mock.patch.object(server_module.executor, "submit") as mocked_submit:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/api/report_captcha",
                    data=json.dumps(
                        {
                            "cdp_endpoint": "http://192.168.15.20:9224",
                            "node_id": "pc2",
                            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&__captcha_solver_bg=1",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))

            self.assertEqual(body["status"], "manual_required")
            mocked_submit.assert_not_called()
            self.assertEqual(
                server_module.SOLVER_LAST_REQUEST,
                {
                    "cdp_endpoint": "http://192.168.15.20:9224",
                    "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&__captcha_solver_bg=1",
                    "node_id": "pc2",
                },
            )
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.SOLVER_LAST_REQUEST = original_last_request
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running
            server_module.PAUSED = original_paused

    def test_report_captcha_endpoint_force_retry_clears_manual_state_without_queueing_parallel_solver(self):
        original_paused = server_module.PAUSED
        original_pause_reason = server_module.COLLECTION_PAUSE_REASON
        original_running = server_module.SOLVER_RUNNING
        original_start_time = server_module.SOLVER_START_TIME
        original_last_status = server_module.SOLVER_LAST_STATUS
        original_last_failure = server_module.SOLVER_LAST_FAILURE_REASON
        original_resume_epoch = server_module.SOLVER_MANUAL_RESUME_EPOCH
        original_data_dir = server_module.DATA_DIR
        server_module.PAUSED = True
        server_module.COLLECTION_PAUSE_REASON = "manual_required"
        server_module.SOLVER_RUNNING = True
        server_module.SOLVER_START_TIME = time.time() - 1800
        server_module.SOLVER_LAST_STATUS = "manual_required"
        server_module.SOLVER_LAST_FAILURE_REASON = "manual_required"
        server_module.SOLVER_MANUAL_RESUME_EPOCH = 0
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, "force_unlock.flag")
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write("manual verification required")
        try:
            with mock.patch.object(server_module.executor, "submit") as mocked_submit:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/api/report_captcha",
                    data=json.dumps(
                        {
                            "target_url": "https://contest.local/challenge?__captcha_solver_bg=1",
                            "force_retry": True,
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))
                observed_paused = server_module.PAUSED
                observed_running = server_module.SOLVER_RUNNING
                observed_last_status = server_module.SOLVER_LAST_STATUS
                observed_last_failure = server_module.SOLVER_LAST_FAILURE_REASON
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.SOLVER_MANUAL_RESUME_EPOCH = original_resume_epoch
            server_module.SOLVER_LAST_FAILURE_REASON = original_last_failure
            server_module.SOLVER_LAST_STATUS = original_last_status
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running
            server_module.COLLECTION_PAUSE_REASON = original_pause_reason
            server_module.PAUSED = original_paused

        self.assertEqual(body["status"], "resuming")
        mocked_submit.assert_not_called()
        self.assertFalse(os.path.exists(flag_path))
        self.assertFalse(observed_paused)
        self.assertTrue(observed_running)
        self.assertEqual(observed_last_status, "resumed")
        self.assertIsNone(observed_last_failure)

    def test_report_captcha_endpoint_force_retry_queues_solver_when_manual_state_exists_but_solver_is_not_running(self):
        original_paused = server_module.PAUSED
        original_pause_reason = server_module.COLLECTION_PAUSE_REASON
        original_running = server_module.SOLVER_RUNNING
        original_start_time = server_module.SOLVER_START_TIME
        original_last_status = server_module.SOLVER_LAST_STATUS
        original_last_failure = server_module.SOLVER_LAST_FAILURE_REASON
        original_resume_epoch = server_module.SOLVER_MANUAL_RESUME_EPOCH
        original_data_dir = server_module.DATA_DIR
        server_module.PAUSED = True
        server_module.COLLECTION_PAUSE_REASON = "manual_required"
        server_module.SOLVER_RUNNING = False
        server_module.SOLVER_START_TIME = 0
        server_module.SOLVER_LAST_STATUS = "manual_required"
        server_module.SOLVER_LAST_FAILURE_REASON = "manual_required"
        server_module.SOLVER_MANUAL_RESUME_EPOCH = 0
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, "force_unlock.flag")
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write("manual verification required")
        try:
            with mock.patch.object(server_module.executor, "submit") as mocked_submit:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/api/report_captcha",
                    data=json.dumps(
                        {
                            "target_url": "https://contest.local/challenge?__captcha_solver_bg=1",
                            "force_retry": True,
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))
                observed_paused = server_module.PAUSED
                observed_running = server_module.SOLVER_RUNNING
                observed_last_status = server_module.SOLVER_LAST_STATUS
                observed_last_failure = server_module.SOLVER_LAST_FAILURE_REASON
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.SOLVER_MANUAL_RESUME_EPOCH = original_resume_epoch
            server_module.SOLVER_LAST_FAILURE_REASON = original_last_failure
            server_module.SOLVER_LAST_STATUS = original_last_status
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running
            server_module.COLLECTION_PAUSE_REASON = original_pause_reason
            server_module.PAUSED = original_paused

        self.assertEqual(body["status"], "solving")
        mocked_submit.assert_called_once()
        self.assertEqual(
            mocked_submit.call_args.args[1],
            {"target_url": "https://contest.local/challenge?__captcha_solver_bg=1"},
        )
        self.assertFalse(os.path.exists(flag_path))
        self.assertFalse(observed_paused)
        self.assertFalse(observed_running)
        self.assertEqual(observed_last_status, "resumed")
        self.assertIsNone(observed_last_failure)

    def test_report_captcha_endpoint_passes_cdp_endpoint_and_target_url_to_solver(self):
        with mock.patch.object(server_module.executor, "submit") as mocked_submit:
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/report_captcha",
                data=json.dumps(
                    {
                        "cdp_endpoint": "http://192.168.65.254:9223",
                        "url": "https://contest.local/challenge?__captcha_solver_bg=1",
                        "timestamp": 123,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "solving")
        mocked_submit.assert_called_once()
        submitted_callable = mocked_submit.call_args.args[0]
        self.assertEqual(getattr(submitted_callable, "__name__", ""), "run_solver")
        self.assertEqual(
            mocked_submit.call_args.args[1],
            {
                "cdp_endpoint": "http://192.168.65.254:9223",
                "target_url": "https://contest.local/challenge?__captcha_solver_bg=1",
            },
        )

    def test_report_captcha_endpoint_preserves_detail_challenge_when_seed_stage_still_has_work(self):
        with (
            mock.patch.dict(
                os.environ,
                {
                    "FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS": "https://sf.taobao.com/list/50025969__2.htm",
                    "FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED": "1",
                },
                clear=False,
            ),
            mock.patch.object(
                server_module,
                "_collection_api_lightweight_status_payload",
                return_value={
                    "seed_scan_job_pending": 10,
                    "seed_scan_job_in_progress": 1,
                    "seed_scan_progress_pending": 20,
                    "seed_scan_progress_in_progress": 0,
                },
            ),
            mock.patch.object(server_module, "_solver_force_unlock_flag_exists", return_value=False),
            mock.patch.object(server_module, "PAUSED", False),
            mock.patch.object(server_module, "SOLVER_LAST_STATUS", None),
            mock.patch.object(server_module, "SOLVER_MANUAL_ONLY", False),
            mock.patch.object(server_module, "SOLVER_LAST_REQUEST", {}),
            mock.patch.object(server_module, "SOLVER_CHALLENGE_ID", None),
            mock.patch.object(server_module.executor, "submit") as mocked_submit,
        ):
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/report_captcha",
                data=json.dumps(
                    {
                        "cdp_endpoint": "http://192.168.65.254:9223",
                        "node_id": "pc2",
                        "target_url": "https://sf-item.taobao.com/sf_item/817695886927.htm?track_id=test&__captcha_solver_bg=1",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "solving")
        self.assertEqual(
            mocked_submit.call_args.args[1],
            {
                "cdp_endpoint": "http://192.168.65.254:9223",
                "node_id": "pc2",
                "target_url": "https://sf-item.taobao.com/sf_item/817695886927.htm?track_id=test&__captcha_solver_bg=1",
            },
        )

    def test_report_captcha_endpoint_rewrites_loopback_cdp_endpoint_for_container_runtime(self):
        original_endpoint = os.environ.get("FAPAI_CDP_ENDPOINT")
        try:
            os.environ["FAPAI_CDP_ENDPOINT"] = "http://192.168.65.254:9223"
            with mock.patch.object(server_module.executor, "submit") as mocked_submit:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/api/report_captcha",
                    data=json.dumps(
                        {
                            "cdp_endpoint": "http://127.0.0.1:9223",
                            "url": "https://contest.local/challenge?__captcha_solver_bg=1",
                            "timestamp": 456,
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request) as resp:
                    status = resp.status
                    payload = json.loads(resp.read().decode("utf-8"))

            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "solving")
            self.assertEqual(
                mocked_submit.call_args.args[1],
                {
                    "cdp_endpoint": "http://192.168.65.254:9223",
                    "target_url": "https://contest.local/challenge?__captcha_solver_bg=1",
                },
            )
        finally:
            if original_endpoint is None:
                os.environ.pop("FAPAI_CDP_ENDPOINT", None)
            else:
                os.environ["FAPAI_CDP_ENDPOINT"] = original_endpoint

    def test_report_captcha_endpoint_returns_json_error_on_queue_failure(self):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/report_captcha",
            data=b"",
            method="POST",
        )
        with mock.patch.object(server_module.executor, "submit", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_CAPTCHA_SOLVER_QUEUE_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_solver_instance_prefers_fapai_cdp_endpoint_for_live_runtime(self):
        original_endpoint = os.environ.get("FAPAI_CDP_ENDPOINT")
        original_solver = server_module.solver
        try:
            os.environ["FAPAI_CDP_ENDPOINT"] = "http://192.168.65.254:9223"
            server_module.solver = server_module.CaptchaSolver(port=9222)
            self.assertEqual(server_module.solver.port, 9223)
            self.assertEqual(server_module.solver.cdp_endpoint, "http://192.168.65.254:9223")
        finally:
            server_module.solver = original_solver
            if original_endpoint is None:
                os.environ.pop("FAPAI_CDP_ENDPOINT", None)
            else:
                os.environ["FAPAI_CDP_ENDPOINT"] = original_endpoint

    def test_build_solver_for_request_uses_request_specific_target_and_cdp_endpoint(self):
        request_solver = server_module._build_solver_for_request(
            {
                "cdp_endpoint": "http://192.168.65.254:9223",
                "target_url": "https://contest.local/challenge?__captcha_solver_bg=1",
            }
        )

        self.assertEqual(request_solver.cdp_endpoint, "http://192.168.65.254:9223")
        self.assertEqual(request_solver.port, 9223)
        self.assertEqual(request_solver.target_url, "https://contest.local/challenge?__captcha_solver_bg=1")

    def test_log_endpoint_records_client_error_message(self):
        with mock.patch.object(server_module, "print") as mocked_print:
            status, payload = self._post_json("/api/log", {"msg": "frontend exploded", "isError": True})

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        mocked_print.assert_called_once_with("[Client Error] frontend exploded")

    def test_log_endpoint_rejects_invalid_json(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/log",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_upload_endpoint_saves_binary_file(self):
        original_data_dir = server_module.DATA_DIR
        server_module.DATA_DIR = self.data_dir
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/upload?id=3001&name=test%20image.jpg",
                data=b"fake-image-bytes",
                method="POST",
            )
            with urllib.request.urlopen(request) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode("utf-8"))
        finally:
            server_module.DATA_DIR = original_data_dir

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "saved")
        saved_path = os.path.join(self.data_dir, "downloads", "3001", "test image.jpg")
        with open(saved_path, "rb") as f:
            self.assertEqual(f.read(), b"fake-image-bytes")

    def test_upload_endpoint_requires_id_and_name(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/upload?id=3001",
            data=b"fake-image-bytes",
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_UPLOAD_REQUEST")

    def test_upload_endpoint_returns_json_error_on_failure(self):
        original_data_dir = server_module.DATA_DIR
        server_module.DATA_DIR = self.data_dir
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/upload?id=3001&name=test%20image.jpg",
            data=b"fake-image-bytes",
            method="POST",
        )
        try:
            with mock.patch.object(server_module, "open", side_effect=RuntimeError("boom"), create=True):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
        finally:
            server_module.DATA_DIR = original_data_dir

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_UPLOAD_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_screen_endpoint_summary(self):
        status, payload = self._post_json(
            "/api/avm/screen",
            {
                "margin_threshold": 0.01,
                "items": [
                    {"id": "3001"},
                    {"id": "3002"},
                ],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 2)
        self.assertIn("summary", payload)
        self.assertIn("strategy_counts", payload["summary"])
        self.assertIn("coordinate_strategy_counts", payload["summary"])
        self.assertIn("confidence_bucket_counts", payload["summary"])
        self.assertIn("manual_review_count", payload["summary"])
        self.assertIn("blocked_reason_counts", payload["summary"])
        self.assertIn("risk_validation", payload["results"][0])
        self.assertIn("manual_review_recommended", payload["results"][0])
        self.assertIn("manual_review_reasons", payload["results"][0])
        self.assertIn("alert_blockers", payload["results"][0])

    def test_screen_endpoint_does_not_alert_when_manual_review_or_risk_validation_blocks(self):
        mocked_prediction = {
            "predicted_price": 1_500_000.0,
            "predicted_unit_price": 15_000.0,
            "confidence": 0.42,
            "comparable_count": 2,
            "strategy": "community_fallback",
            "trace": {
                "valuation_mode": "current_market",
                "subject_coordinate_strategy": "observed",
            },
            "top_factors": [],
            "manual_review_recommended": True,
            "manual_review_reasons": ["risk_feature_incomplete"],
            "risk_validation": {
                "ok": False,
                "missing_required_count": 5,
                "invalid_field_count": 0,
                "feature_completeness": 0.7,
                "missing_required_fields": ["build_year"],
                "invalid_fields": [],
            },
        }

        with mock.patch.object(server_module.AVM_SERVICE, "predict_by_item_data", return_value=mocked_prediction):
            status, payload = self._post_json(
                "/api/avm/screen",
                {
                    "margin_threshold": 0.01,
                    "items": [{"id": "3001"}],
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["alerts_written"], 0)
        self.assertEqual(payload["summary"]["alert_candidate_count"], 0)
        self.assertEqual(payload["summary"]["manual_review_blocked_count"], 1)
        self.assertEqual(payload["summary"]["risk_validation_blocked_count"], 1)
        self.assertEqual(payload["summary"]["blocked_reason_counts"]["manual_review_required"], 1)
        self.assertEqual(payload["summary"]["blocked_reason_counts"]["risk_validation_incomplete"], 1)
        self.assertFalse(payload["results"][0]["meets_alert_threshold"])
        self.assertFalse(payload["results"][0]["risk_validation"]["ok"])
        self.assertTrue(payload["results"][0]["manual_review_recommended"])
        self.assertIn("risk_feature_incomplete", payload["results"][0]["manual_review_reasons"])
        self.assertIn("manual_review_required", payload["results"][0]["alert_blockers"])
        self.assertIn("risk_validation_incomplete", payload["results"][0]["alert_blockers"])

    def test_screen_endpoint_uses_configured_alert_threshold_when_payload_omits_one(self):
        mocked_prediction = {
            "predicted_price": 1_000_000.0,
            "predicted_unit_price": 10_000.0,
            "confidence": 0.8,
            "comparable_count": 3,
            "strategy": "spatial",
            "trace": {
                "valuation_mode": "current_market",
                "subject_coordinate_strategy": "observed",
            },
            "top_factors": [],
            "manual_review_recommended": False,
            "manual_review_reasons": [],
            "risk_validation": {
                "ok": True,
                "missing_required_count": 0,
                "invalid_field_count": 0,
                "feature_completeness": 1.0,
                "missing_required_fields": [],
                "invalid_fields": [],
            },
        }

        with mock.patch.object(server_module.AVM_CONFIG_MANAGER, "get_config", return_value={"alert_threshold": 0.2}):
            with mock.patch.object(server_module.AVM_SERVICE, "predict_by_item_data", return_value=mocked_prediction):
                status, payload = self._post_json(
                    "/api/avm/screen",
                    {
                        "items": [{"id": "3001", "starting_price": 820000}],
                    },
                )

        self.assertEqual(status, 200)
        self.assertEqual(payload["alerts_written"], 0)
        self.assertIn("margin_below_threshold", payload["results"][0]["alert_blockers"])

    def test_screen_endpoint_allows_zero_alert_threshold_from_config(self):
        mocked_prediction = {
            "predicted_price": 1_000_000.0,
            "predicted_unit_price": 10_000.0,
            "confidence": 0.8,
            "comparable_count": 3,
            "strategy": "spatial",
            "trace": {
                "valuation_mode": "current_market",
                "subject_coordinate_strategy": "observed",
            },
            "top_factors": [],
            "manual_review_recommended": False,
            "manual_review_reasons": [],
            "risk_validation": {
                "ok": True,
                "missing_required_count": 0,
                "invalid_field_count": 0,
                "feature_completeness": 1.0,
                "missing_required_fields": [],
                "invalid_fields": [],
            },
        }

        with mock.patch.object(server_module.AVM_CONFIG_MANAGER, "get_config", return_value={"alert_threshold": 0.0}):
            with mock.patch.object(server_module.AVM_SERVICE, "predict_by_item_data", return_value=mocked_prediction):
                status, payload = self._post_json(
                    "/api/avm/screen",
                    {
                        "items": [{"id": "3002", "starting_price": 920000}],
                    },
                )

        self.assertEqual(status, 200)
        self.assertEqual(payload["margin_threshold"], 0.0)
        self.assertEqual(payload["alerts_written"], 1)
        self.assertTrue(payload["results"][0]["meets_alert_threshold"])

    def test_screen_endpoint_rejects_invalid_json_body(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/screen",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_screen_endpoint_rejects_non_object_json_body(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/screen",
            data=json.dumps([]).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_REQUEST_BODY")
        self.assertEqual(body["error"]["details"]["expected_type"], "object")
        self.assertEqual(body["error"]["details"]["received_type"], "list")

    def test_screen_endpoint_rejects_non_list_items(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/screen",
            data=json.dumps({"items": {"id": "3001"}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_INVALID_SCREEN_ITEMS")

    def test_screen_endpoint_returns_json_error_on_failure(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/avm/screen",
            data=json.dumps({"items": [{"id": "3001"}]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with mock.patch.object(server_module, "write_avm_alerts", side_effect=RuntimeError("boom")):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)

        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["error"]["code"], "AVM_SCREEN_FAILED")
        self.assertEqual(body["error"]["details"]["error"], "boom")

    def test_collection_observer_get_error_routes_return_structured_codes(self):
        with mock.patch.object(server_module, "_collection_observer_overview_payload", side_effect=RuntimeError("boom")):
            self._assert_http_error_code("/api/collection/overview", 500, "COLLECTION_OBSERVER_OVERVIEW_FAILED")
        with mock.patch.object(server_module, "_collection_observer_items_payload", side_effect=RuntimeError("boom")):
            self._assert_http_error_code("/api/collection/items", 500, "COLLECTION_OBSERVER_ITEMS_FAILED")
        with mock.patch.object(server_module, "_collection_observer_regions_payload", side_effect=RuntimeError("boom")):
            self._assert_http_error_code("/api/collection/regions", 500, "COLLECTION_OBSERVER_REGIONS_FAILED")
        with mock.patch.object(server_module, "_collection_observer_item_payload", side_effect=RuntimeError("boom")):
            self._assert_http_error_code(
                "/api/collection/items/1001",
                500,
                "COLLECTION_OBSERVER_ITEM_FAILED",
            )
        self._assert_http_error_code("/collection/assets/missing.js", 404, "COLLECTION_STATIC_ASSET_NOT_FOUND")

    def test_collection_observer_post_error_routes_return_structured_codes(self):
        with mock.patch.object(
            server_module,
            "_collection_observer_reset_region_links_payload",
            side_effect=RuntimeError("boom"),
        ):
            self._assert_http_error_code(
                "/api/collection/region/reset_links",
                500,
                "COLLECTION_OBSERVER_REGION_RESET_FAILED",
                method="POST",
                payload={},
            )
        with mock.patch.object(server_module, "_collection_observer_reset_region_links_payload", return_value={"ok": False}):
            self._assert_http_error_code(
                "/api/collection/region/reset_links",
                400,
                "COLLECTION_OBSERVER_REGION_RESET_REJECTED",
                method="POST",
                payload={},
            )

        with mock.patch.object(
            server_module,
            "_collection_observer_reanalysis_payload",
            side_effect=RuntimeError("boom"),
        ):
            self._assert_http_error_code(
                "/api/collection/item/reanalyze",
                500,
                "COLLECTION_OBSERVER_REANALYZE_FAILED",
                method="POST",
                payload={},
            )
        with mock.patch.object(server_module, "_collection_observer_reanalysis_payload", return_value={"ok": False}):
            self._assert_http_error_code(
                "/api/collection/item/reanalyze",
                400,
                "COLLECTION_OBSERVER_REANALYZE_REJECTED",
                method="POST",
                payload={},
            )

        with mock.patch.object(
            server_module,
            "_collection_observer_manual_update_payload",
            side_effect=RuntimeError("boom"),
        ):
            self._assert_http_error_code(
                "/api/collection/item/manual_update",
                500,
                "COLLECTION_OBSERVER_MANUAL_UPDATE_FAILED",
                method="POST",
                payload={},
            )
        with mock.patch.object(server_module, "_collection_observer_manual_update_payload", return_value={"ok": False}):
            self._assert_http_error_code(
                "/api/collection/item/manual_update",
                400,
                "COLLECTION_OBSERVER_MANUAL_UPDATE_REJECTED",
                method="POST",
                payload={},
            )

        with mock.patch.object(
            server_module,
            "_collection_observer_runtime_control_payload",
            side_effect=RuntimeError("boom"),
        ):
            self._assert_http_error_code(
                "/api/collection/control/pause",
                500,
                "COLLECTION_OBSERVER_RUNTIME_CONTROL_FAILED",
                method="POST",
            )
        with mock.patch.object(server_module, "_collection_observer_runtime_control_payload", return_value={"ok": False}):
            self._assert_http_error_code(
                "/api/collection/control/resume",
                400,
                "COLLECTION_OBSERVER_RUNTIME_CONTROL_REJECTED",
                method="POST",
            )

        with mock.patch.object(
            server_module,
            "_collection_observer_auth_complete_payload",
            side_effect=RuntimeError("boom"),
        ):
            self._assert_http_error_code(
                "/api/collection/auth/complete",
                500,
                "COLLECTION_OBSERVER_AUTH_COMPLETE_FAILED",
                method="POST",
                payload={},
            )
        with mock.patch.object(server_module, "_collection_observer_auth_complete_payload", return_value={"ok": False}):
            self._assert_http_error_code(
                "/api/collection/auth/complete",
                400,
                "COLLECTION_OBSERVER_AUTH_COMPLETE_REJECTED",
                method="POST",
                payload={},
            )

        with mock.patch.object(
            server_module,
            "_collection_observer_resume_after_cooldown_payload",
            side_effect=RuntimeError("boom"),
        ):
            self._assert_http_error_code(
                "/api/collection/auth/resume_after_cooldown",
                500,
                "COLLECTION_OBSERVER_AUTH_RESUME_FAILED",
                method="POST",
                payload={},
            )
        with mock.patch.object(
            server_module,
            "_collection_observer_resume_after_cooldown_payload",
            return_value={"ok": False},
        ):
            self._assert_http_error_code(
                "/api/collection/auth/resume_after_cooldown",
                400,
                "COLLECTION_OBSERVER_AUTH_RESUME_REJECTED",
                method="POST",
                payload={},
            )

    def test_report_captcha_force_retry_failure_returns_structured_error(self):
        with (
            mock.patch.object(
                server_module,
                "_captcha_solver_runtime_status",
                return_value={"manual_required": True, "running": False},
            ),
            mock.patch.object(server_module, "_clear_solver_manual_required_pause", return_value="boom"),
        ):
            self._assert_http_error_code(
                "/api/report_captcha",
                500,
                "AVM_CAPTCHA_SOLVER_FORCE_RETRY_FAILED",
                method="POST",
                payload={"force_retry": True, "target_url": "https://contest.local/challenge"},
            )

    def test_seed_progress_routes_reject_non_object_json_body(self):
        for path in ("/api/report_sniff_status", "/api/collection/seeds/report_progress"):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_recent_enrich_maintenance_routes_reject_non_object_json_body(self):
        for path in ("/api/avm/recent_enrich_maintenance", "/api/collection/details/maintenance"):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_fetch_missing_detail_archive_routes_reject_non_object_json_body(self):
        for path in ("/api/avm/fetch_missing_detail_archives", "/api/collection/details/fetch_missing"):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_archive_detail_replay_routes_reject_non_object_json_body(self):
        for path in ("/api/avm/archive_detail_replay", "/api/collection/details/prepare_replay"):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_save_locations_endpoint_rejects_non_object_json_body(self):
        self._assert_non_object_json_body_rejected("/api/save_locations")

    def test_seed_batch_routes_reject_non_object_json_body(self):
        for path in ("/api/save", "/api/collection/seeds/batch"):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_log_endpoint_rejects_non_object_json_body(self):
        self._assert_non_object_json_body_rejected("/api/log")

    def test_update_item_routes_reject_non_object_json_body(self):
        for path in ("/api/update_item", "/api/collection/details/update_item"):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_area_result_routes_reject_non_object_json_body(self):
        for path in ("/api/area_result", "/api/collection/details/area_result"):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_infer_location_routes_reject_non_object_json_body(self):
        for path in ("/api/infer_location", "/api/collection/details/infer_location"):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_approve_area_routes_reject_non_object_json_body(self):
        for path in ("/api/approve_area", "/api/collection/details/approve_area"):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_analyze_html_routes_reject_non_object_json_body(self):
        for path in ("/api/analyze_html", "/api/collection/details/html"):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_manual_review_receipts_routes_reject_non_object_json_body(self):
        for path in ("/api/avm/manual_review_receipts", "/api/analysis/manual_review_receipts"):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_manual_review_receipts_delete_routes_reject_non_object_json_body(self):
        for path in ("/api/avm/manual_review_receipts", "/api/analysis/manual_review_receipts"):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path, method="DELETE")

    def test_manual_review_receipts_routes_reject_invalid_json(self):
        for path in ("/api/avm/manual_review_receipts", "/api/analysis/manual_review_receipts"):
            with self.subTest(path=path):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    data=b"{",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)

                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_manual_review_receipts_delete_routes_reject_invalid_json(self):
        for path in ("/api/avm/manual_review_receipts", "/api/analysis/manual_review_receipts"):
            with self.subTest(path=path):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    data=b"{",
                    headers={"Content-Type": "application/json"},
                    method="DELETE",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)

                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_object_json_routes_reject_invalid_json_in_live_sweep(self):
        for path, method in self._object_json_route_methods():
            with self.subTest(path=path, method=method):
                self._assert_invalid_json_body_rejected(path, method=method)

    def test_object_json_routes_reject_non_object_json_in_live_sweep(self):
        for path, method in self._object_json_route_methods():
            with self.subTest(path=path, method=method):
                self._assert_non_object_json_body_rejected(path, method=method)

    def test_update_item_routes_reject_invalid_json(self):
        for path in ("/api/update_item", "/api/collection/details/update_item"):
            with self.subTest(path=path):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    data=b"{",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)

                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_area_result_routes_reject_invalid_json(self):
        for path in ("/api/area_result", "/api/collection/details/area_result"):
            with self.subTest(path=path):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    data=b"{",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)

                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_infer_location_routes_reject_invalid_json(self):
        for path in ("/api/infer_location", "/api/collection/details/infer_location"):
            with self.subTest(path=path):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    data=b"{",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)

                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_approve_area_routes_reject_invalid_json(self):
        for path in ("/api/approve_area", "/api/collection/details/approve_area"):
            with self.subTest(path=path):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    data=b"{",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)

                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")

    def test_analyze_html_routes_reject_invalid_json(self):
        for path in ("/api/analyze_html", "/api/collection/details/html"):
            with self.subTest(path=path):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    data=b"{",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)

                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertEqual(body["error"]["code"], "AVM_INVALID_JSON")


if __name__ == "__main__":
    unittest.main()
