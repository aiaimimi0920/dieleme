from __future__ import annotations

from tools.test.avm_http_contract_context import *  # noqa: F401,F403
from tools.test.collection_job_checks import wait_for_job


class AVMHttpContractBase(unittest.TestCase):
    def setUp(self):
        import os

        control_environment = mock.patch.dict(os.environ, {'FAPAI_CONTROL_PLANE_TOKEN': 'test-operator'})
        control_environment.start()
        self.addCleanup(control_environment.stop)
        token_file = mock.patch.object(server_module._engine_tokens, 'token', return_value='')
        token_file.start()
        self.addCleanup(token_file.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name + '\\datas'
        os.makedirs(self.data_dir, exist_ok=True)
        state_environment = mock.patch.dict(os.environ, {'FAPAI_SOLVER_STATE_DIR': self.data_dir})
        state_environment.start()
        self.addCleanup(state_environment.stop)
        with open(self.data_dir + '\\2026-01-01.json', 'w', encoding='utf-8') as f:
            json.dump([{'id': '3001', 'url': 'https://x/3001', '成交价格': '100万', '起拍价格': '80万', '建筑面积': '100㎡', '交易时间': '2026-01-01 10:00:00', '城市': '上海市', '区': '浦东新区', '所属小区': '测试小区', '纬度': 31.2, '经度': 121.5}, {'id': '3002', 'url': 'https://x/3002', '成交价格': '110万', '起拍价格': '90万', '建筑面积': '100㎡', '交易时间': '2026-02-01 10:00:00', '城市': '上海市', '区': '浦东新区', '所属小区': '测试小区', '纬度': 31.2001, '经度': 121.5001}], f, ensure_ascii=False)
        self.original_service = server_module.AVM_SERVICE
        self.original_start_time = server_module.RUNTIME.started_at
        self.original_solver_pending_token = server_module.RUNTIME.solver.pending_token
        server_module.RUNTIME.solver.pending_token = None
        server_module.AVM_SERVICE = AVMService(data_dir=self.data_dir)
        server_module.RUNTIME.started_at = time.time() - 5
        self.httpd = server_module.ReusableTCPServer(('127.0.0.1', 0), server_module.DataHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.collection_jobs(Path(self.data_dir)).close(timeout=5)
        self.httpd.server_close()
        server_module.AVM_SERVICE = self.original_service
        server_module.RUNTIME.started_at = self.original_start_time
        server_module.RUNTIME.solver.pending_token = self.original_solver_pending_token
        self.tmp.cleanup()

    def _get_json(self, path, headers=None):
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', headers=headers or {})
        with urllib.request.urlopen(request) as resp:
            return (resp.status, json.loads(resp.read().decode('utf-8')))

    def _post_json(self, path, payload, headers=None):
        with self._open_post(path, payload, headers) as resp:
            return (resp.status, json.loads(resp.read().decode('utf-8')))

    def _wait_for_collection_job(self, status, accepted, headers=None):
        self.assertEqual(status, 202)
        self.assertEqual(accepted['status'], 'accepted')
        self.assertRegex(accepted['job_id'], r'^[a-f0-9]{32}$')
        self.assertEqual(accepted['status_url'], f"/api/collection/jobs?id={accepted['job_id']}")
        request_headers = {'X-FAPAI-Control-Token': 'test-operator'}
        request_headers.update(headers or {})

        def fetch(path):
            response_status, job = self._get_json(path, headers=request_headers)
            self.assertEqual(response_status, 200)
            self.assertEqual(job['job_id'], accepted['job_id'])
            return job

        return wait_for_job(fetch, accepted['status_url'])

    def _complete_collection_job(self, status, accepted, headers=None):
        job = self._wait_for_collection_job(status, accepted, headers)
        self.assertEqual(job['status'], 'completed', job)
        return job['result']

    def _post_collection_job(self, path, payload, headers=None):
        status, accepted = self._post_json(path, payload, headers)
        return status, self._complete_collection_job(status, accepted, headers)

    def _assert_collection_job_failed(self, status, accepted, expected_code, headers=None):
        job = self._wait_for_collection_job(status, accepted, headers)
        self.assertEqual(job['status'], 'failed', job)
        self.assertEqual(job['error']['code'], expected_code)
        self.assertEqual(job['error']['message'], 'Collection operation failed')
        self.assertEqual(job['error']['error_id'], accepted['job_id'])
        self.assertIsNone(job['result'])
        return job

    def _open_post(self, path, payload, headers=None):
        request_headers = {'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}
        if headers:
            request_headers.update(headers)
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=json.dumps(payload).encode('utf-8'), headers=request_headers, method='POST')
        return urllib.request.urlopen(req)

    def _delete_json(self, path, payload, headers=None):
        request_headers = {'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}
        if headers:
            request_headers.update(headers)
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=json.dumps(payload).encode('utf-8'), headers=request_headers, method='DELETE')
        with urllib.request.urlopen(req) as resp:
            return (resp.status, json.loads(resp.read().decode('utf-8')))

    def _assert_non_object_json_body_rejected(self, path, payload=None, method='POST'):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=json.dumps([] if payload is None else payload).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method=method)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_REQUEST_BODY')
        self.assertEqual(body['error']['details']['expected_type'], 'object')
        self.assertEqual(body['error']['details']['received_type'], 'list')

    def _assert_invalid_json_body_rejected(self, path, method='POST'):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=b'{', headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method=method)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def _assert_http_error_code(self, path, expected_status, expected_code, *, method='GET', payload=None):
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=None if payload is None else json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json', 'X-FAPAI-Control-Token': 'test-operator'}, method=method)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request)
        self.assertEqual(ctx.exception.code, expected_status)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], expected_code)
        return body

    def _object_json_route_methods(self):
        return [
            ('/api/get_or_create_sniff_task', 'POST'),
            ('/api/collection/seeds/next_task', 'POST'),
            ('/api/get_tasks', 'POST'),
            ('/api/collection/details/tasks', 'POST'),
            ('/api/next_task', 'POST'),
            ('/api/collection/details/next_task', 'POST'),
            ('/api/get_next_task', 'POST'),
            ('/api/avm/recent_detail_replay', 'POST'),
            ('/api/avm/drift_status', 'POST'),
            ('/api/analysis/drift_status', 'POST'),
            ('/api/avm/release_gate', 'POST'),
            ('/api/analysis/release_gate', 'POST'),
            ('/api/avm/recent_gap_audit', 'POST'),
            ('/api/report_sniff_status', 'POST'),
            ('/api/collection/seeds/report_progress', 'POST'),
            ('/api/avm/manual_review_receipts', 'POST'),
            ('/api/analysis/manual_review_receipts', 'POST'),
            ('/api/avm/manual_review_receipts', 'DELETE'),
            ('/api/analysis/manual_review_receipts', 'DELETE'),
            ('/api/avm/run', 'POST'),
            ('/api/analysis/pipeline/run', 'POST'),
            ('/api/avm/start_all_subtasks', 'POST'),
            ('/api/avm/run_all_subtasks_sync', 'POST'),
            ('/api/avm/evaluate', 'POST'),
            ('/api/analysis/evaluate', 'POST'),
            ('/api/avm/recent_enrich_maintenance', 'POST'),
            ('/api/collection/details/maintenance', 'POST'),
            ('/api/avm/fetch_missing_detail_archives', 'POST'),
            ('/api/collection/details/fetch_missing', 'POST'),
            ('/api/avm/archive_detail_replay', 'POST'),
            ('/api/collection/details/prepare_replay', 'POST'),
            ('/api/collection/region/reset_links', 'POST'),
            ('/api/collection/item/reanalyze', 'POST'),
            ('/api/collection/item/manual_update', 'POST'),
            ('/api/collection/auth/force_reset', 'POST'),
            ('/api/collection/auth/complete', 'POST'),
            ('/api/collection/auth/resume_after_cooldown', 'POST'),
            ('/api/save_locations', 'POST'),
            ('/api/area_result', 'POST'),
            ('/api/collection/details/area_result', 'POST'),
            ('/api/infer_location', 'POST'),
            ('/api/collection/details/infer_location', 'POST'),
            ('/api/approve_area', 'POST'),
            ('/api/collection/details/approve_area', 'POST'),
            ('/api/save', 'POST'),
            ('/api/collection/seeds/batch', 'POST'),
            ('/api/avm/screen', 'POST'),
            ('/api/report_captcha', 'POST'),
            ('/api/report_manual_captcha', 'POST'),
            ('/api/log', 'POST'),
            ('/api/update_item', 'POST'),
            ('/api/collection/details/update_item', 'POST'),
            ('/api/analyze_html', 'POST'),
            ('/api/collection/details/html', 'POST'),
        ]

    def _repo_owned_python_files(self):
        files = []
        repo_root = Path(__file__).resolve().parents[2]
        for root in (repo_root / 'src', repo_root / 'tools', repo_root / 'tests'):
            if not root.exists():
                continue
            files.extend(sorted(root.rglob('*.py')))
        return files

    def _repo_owned_python_test_files(self):
        import subprocess

        # Archived release snapshots and runtime data are not repository tests.
        output = subprocess.run(
            ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '--', '**/test_*.py', 'test_*.py'],
            check=True, capture_output=True, text=True, encoding='utf-8',
            cwd=Path(__file__).resolve().parents[2],
        ).stdout
        repo_root = Path(__file__).resolve().parents[2]
        return sorted({repo_root / value for value in output.splitlines() if value})

    def _primary_repo_test_files(self):
        files = []
        repo_root = Path(__file__).resolve().parents[2]
        for root in (repo_root / 'tests', repo_root / 'tools/test'):
            if not root.exists():
                continue
            files.extend(sorted(root.rglob('test_*.py')))
        return sorted(files)

    def _wait_for_job(self, job_id, timeout=3.0):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            (status, payload) = self._get_json(f'/api/avm/manual_review_receipt_jobs?job_id={urllib.parse.quote(job_id)}')
            self.assertEqual(status, 200)
            last = payload
            if payload['job']['status'] in {'completed', 'failed'}:
                return payload
            time.sleep(0.05)
        self.fail(f'job {job_id} did not finish in time; last payload={last}')

__all__ = ["AVMHttpContractBase"]
