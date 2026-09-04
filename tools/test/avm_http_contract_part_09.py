from __future__ import annotations

from tools.test.avm_http_contract_context import *  # noqa: F401,F403


class AVMHttpContractPart09:
    def test_collection_detail_infer_location_alias_returns_500_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.infer_location.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/details/infer_location', data=json.dumps({'id': '3001', 'address': 'x', 'title': 'y'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_INFER_LOCATION_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_infer_location_legacy_endpoint_returns_500_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.infer_location.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/infer_location', data=json.dumps({'id': '3001', 'address': 'x', 'title': 'y'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_INFER_LOCATION_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_collection_detail_infer_location_legacy_endpoint(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.infer_location.return_value = {'所属小区': '测试小区', '城市': '上海市'}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_json('/api/infer_location', {'id': '3001', 'address': '上海市浦东新区测试路99号', 'title': '测试标题'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['所属小区'], '测试小区')
        fake_service.infer_location.assert_called_once()

    def test_collection_detail_prepare_replay_alias_endpoint(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {'window_days': 30, 'limit': 10, 'dry_run': True, 'prepared_count': 1}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_json('/api/collection/details/prepare_replay', {'window_days': 30, 'limit': 10, 'dry_run': True})
        self.assertEqual(status, 200)
        self.assertEqual(payload['prepared_count'], 1)
        fake_service.prepare_replay.assert_called_once()

    def test_archive_detail_replay_endpoint_rejects_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/archive_detail_replay', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_collection_detail_prepare_replay_alias_rejects_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/details/prepare_replay', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_collection_detail_prepare_replay_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/details/prepare_replay', data=json.dumps({'window_days': 30, 'limit': 10, 'dry_run': True}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_ARCHIVE_DETAIL_REPLAY_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_collection_detail_html_alias(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.submit_html.return_value = {'status': 'queued'}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_json('/api/collection/details/html', {'id': '3001', 'html': '<html></html>', 'status': 'done'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'queued')
        fake_service.submit_html.assert_called_once()

    def test_collection_detail_html_alias_returns_500_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.submit_html.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/details/html', data=json.dumps({'id': '3001', 'html': '<html></html>', 'status': 'done'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_ANALYZE_HTML_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_collection_detail_html_legacy_endpoint(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.submit_html.return_value = {'status': 'queued'}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_json('/api/analyze_html', {'id': '3001', 'html': '<html></html>', 'status': 'done'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'queued')
        fake_service.submit_html.assert_called_once()

    def test_analyze_html_legacy_endpoint_returns_500_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.submit_html.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analyze_html', data=json.dumps({'id': '3001', 'html': '<html></html>', 'status': 'done'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_ANALYZE_HTML_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_resume_endpoint_clears_pause_and_force_unlock_flag(self):
        original_paused = server_module.PAUSED
        original_data_dir = server_module.DATA_DIR
        original_running = server_module.SOLVER_RUNNING
        original_start_time = server_module.SOLVER_START_TIME
        server_module.PAUSED = True
        server_module.DATA_DIR = self.data_dir
        server_module.SOLVER_RUNNING = True
        server_module.SOLVER_START_TIME = time.time() - 300
        flag_path = os.path.join(self.data_dir, 'force_unlock.flag')
        with open(flag_path, 'w', encoding='utf-8') as f:
            f.write('1')
        try:
            (status, payload) = self._get_json('/api/resume')
        finally:
            observed_running = server_module.SOLVER_RUNNING
            server_module.DATA_DIR = original_data_dir
            server_module.PAUSED = original_paused
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'resumed')
        self.assertFalse(os.path.exists(flag_path))
        self.assertFalse(observed_running)

    def test_save_locations_endpoint_deduplicates_by_code(self):
        original_data_dir = server_module.DATA_DIR
        server_module.DATA_DIR = self.data_dir
        try:
            (status, payload) = self._post_json('/api/save_locations', {'locations': [{'code': '310115', 'name': '浦东新区'}, {'code': '310115', 'name': '浦东新区'}, {'code': '310104', 'name': '徐汇区'}]})
        finally:
            server_module.DATA_DIR = original_data_dir
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['count'], 3)
        with open(os.path.join(self.data_dir, 'collected_locations.json'), 'r', encoding='utf-8') as f:
            persisted = json.load(f)
        self.assertEqual(len(persisted), 2)
        self.assertEqual({item['code'] for item in persisted}, {'310115', '310104'})

    def test_save_locations_endpoint_returns_500_on_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/save_locations', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_save_locations_endpoint_returns_json_error_on_failure(self):
        original_data_dir = server_module.DATA_DIR
        server_module.DATA_DIR = self.data_dir
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/save_locations', data=json.dumps({'locations': [{'code': '1', 'name': 'A'}]}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with mock.patch.object(server_module, 'open', side_effect=RuntimeError('boom'), create=True):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
        finally:
            server_module.DATA_DIR = original_data_dir
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_SAVE_LOCATIONS_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_report_captcha_endpoint_queues_solver(self):
        with mock.patch.object(server_module.executor, 'submit') as mocked_submit:
            request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_captcha', data=b'', method='POST')
            with urllib.request.urlopen(request) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'solving')
        mocked_submit.assert_called_once()
        submitted_callable = mocked_submit.call_args.args[0]
        self.assertEqual(getattr(submitted_callable, '__name__', ''), 'run_solver')
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
        original_pending_token = getattr(server_module, 'SOLVER_PENDING_TOKEN', None)
        try:
            server_module.PAUSED = False
            server_module.COLLECTION_PAUSE_REASON = None
            server_module.SOLVER_RUNNING = False
            server_module.SOLVER_START_TIME = 0
            server_module.SOLVER_LAST_STATUS = 'idle'
            server_module.SOLVER_LAST_FAILURE_REASON = None
            server_module.SOLVER_LAST_REQUEST = {}
            server_module.DATA_DIR = self.data_dir
            if hasattr(server_module, 'SOLVER_PENDING_TOKEN'):
                server_module.SOLVER_PENDING_TOKEN = None
            with mock.patch.object(server_module.executor, 'submit') as mocked_submit:
                (first_status, first_body) = self._post_json('/api/report_captcha', {})
                (second_status, second_body) = self._post_json('/api/report_captcha', {})
        finally:
            if hasattr(server_module, 'SOLVER_PENDING_TOKEN'):
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
        self.assertEqual(first_body['status'], 'solving')
        self.assertEqual(second_status, 200)
        self.assertEqual(second_body['status'], 'already_running')
        mocked_submit.assert_called_once()

    def test_report_captcha_endpoint_does_not_requeue_while_solver_is_running(self):
        original_running = server_module.SOLVER_RUNNING
        original_start_time = server_module.SOLVER_START_TIME
        try:
            server_module.SOLVER_RUNNING = True
            server_module.SOLVER_START_TIME = time.time() - 7
            with mock.patch.object(server_module.executor, 'submit') as mocked_submit:
                request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_captcha', data=b'', method='POST')
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode('utf-8'))
        finally:
            server_module.SOLVER_RUNNING = original_running
            server_module.SOLVER_START_TIME = original_start_time
        self.assertEqual(body['status'], 'already_running')
        self.assertEqual(body['elapsed_seconds'], 7)
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
            server_module.SOLVER_LAST_REQUEST = {'cdp_endpoint': 'http://192.168.15.104:9224', 'target_url': 'https://contest.local/challenge?__captcha_solver_bg=1', 'node_id': 'pc2'}
            with mock.patch.object(server_module.executor, 'submit') as mocked_submit:
                request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_captcha', data=json.dumps({'cdp_endpoint': 'http://192.168.15.20:9224', 'node_id': 'pc2', 'target_url': 'https://contest.local/challenge?__captcha_solver_bg=1'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode('utf-8'))
            self.assertEqual(body['status'], 'already_running')
            mocked_submit.assert_not_called()
            self.assertEqual(server_module.SOLVER_LAST_REQUEST, {'cdp_endpoint': 'http://192.168.15.20:9224', 'target_url': 'https://contest.local/challenge?__captcha_solver_bg=1', 'node_id': 'pc2'})
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
            server_module.SOLVER_LAST_STATUS = 'running'
            server_module.SOLVER_LAST_FAILURE_REASON = None
            server_module.DATA_DIR = self.data_dir
            with mock.patch.object(server_module.executor, 'submit') as mocked_submit:
                request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_captcha', data=b'', method='POST')
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode('utf-8'))
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.SOLVER_LAST_FAILURE_REASON = original_last_failure
            server_module.SOLVER_LAST_STATUS = original_last_status
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running
            server_module.COLLECTION_PAUSE_REASON = original_pause_reason
            server_module.PAUSED = original_paused
        self.assertEqual(body['status'], 'manual_required')
        self.assertEqual(body['elapsed_seconds'], 180)
        self.assertTrue(body['captcha_solver']['manual_required'])
        self.assertTrue(body['captcha_solver']['force_unlock_flag_exists'])
        self.assertTrue(os.path.exists(os.path.join(self.data_dir, 'force_unlock.flag')))
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
            server_module.SOLVER_LAST_STATUS = 'running'
            server_module.SOLVER_LAST_FAILURE_REASON = None
            server_module.DATA_DIR = self.data_dir
            with mock.patch.dict(os.environ, {'FAPAI_SOLVER_MAX_RUNTIME_SECONDS': '240'}):
                with mock.patch.object(server_module.executor, 'submit') as mocked_submit:
                    request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_captcha', data=b'', method='POST')
                    with urllib.request.urlopen(request) as resp:
                        self.assertEqual(resp.status, 200)
                        body = json.loads(resp.read().decode('utf-8'))
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.SOLVER_LAST_FAILURE_REASON = original_last_failure
            server_module.SOLVER_LAST_STATUS = original_last_status
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running
            server_module.COLLECTION_PAUSE_REASON = original_pause_reason
            server_module.PAUSED = original_paused
        self.assertEqual(body['status'], 'already_running')
        self.assertEqual(body['elapsed_seconds'], 180)
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
        flag_path = os.path.join(self.data_dir, 'force_unlock.flag')
        with open(flag_path, 'w', encoding='utf-8') as f:
            f.write('manual verification required')
        try:
            with mock.patch.object(server_module.executor, 'submit') as mocked_submit:
                request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_captcha', data=b'', method='POST')
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode('utf-8'))
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running
            server_module.PAUSED = original_paused
        self.assertEqual(body['status'], 'manual_required')
        self.assertTrue(body['captcha_solver']['manual_required'])
        self.assertTrue(body['captcha_solver']['force_unlock_flag_exists'])
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
        server_module.SOLVER_LAST_REQUEST = {'cdp_endpoint': 'http://192.168.15.104:9224', 'target_url': 'https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1', 'node_id': 'pc2'}
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, 'force_unlock.flag')
        with open(flag_path, 'w', encoding='utf-8') as f:
            f.write('manual verification required')
        try:
            with mock.patch.object(server_module.executor, 'submit') as mocked_submit:
                request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_captcha', data=json.dumps({'cdp_endpoint': 'http://192.168.15.20:9224', 'node_id': 'pc2', 'target_url': 'https://sf.taobao.com/list/50025969__2.htm?location_code=440115&__captcha_solver_bg=1'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode('utf-8'))
            self.assertEqual(body['status'], 'manual_required')
            mocked_submit.assert_not_called()
            self.assertEqual(server_module.SOLVER_LAST_REQUEST, {'cdp_endpoint': 'http://192.168.15.20:9224', 'target_url': 'https://sf.taobao.com/list/50025969__2.htm?location_code=440115&__captcha_solver_bg=1', 'node_id': 'pc2'})
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.SOLVER_LAST_REQUEST = original_last_request
            server_module.SOLVER_START_TIME = original_start_time
            server_module.SOLVER_RUNNING = original_running
            server_module.PAUSED = original_paused

__all__ = ["AVMHttpContractPart09"]
