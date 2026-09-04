from __future__ import annotations

from tools.test.avm_http_contract_context import *  # noqa: F401,F403


class AVMHttpContractPart10:
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
        server_module.COLLECTION_PAUSE_REASON = 'manual_required'
        server_module.SOLVER_RUNNING = True
        server_module.SOLVER_START_TIME = time.time() - 1800
        server_module.SOLVER_LAST_STATUS = 'manual_required'
        server_module.SOLVER_LAST_FAILURE_REASON = 'manual_required'
        server_module.SOLVER_MANUAL_RESUME_EPOCH = 0
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, 'force_unlock.flag')
        with open(flag_path, 'w', encoding='utf-8') as f:
            f.write('manual verification required')
        try:
            with mock.patch.object(server_module.executor, 'submit') as mocked_submit:
                request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_captcha', data=json.dumps({'target_url': 'https://contest.local/challenge?__captcha_solver_bg=1', 'force_retry': True}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode('utf-8'))
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
        self.assertEqual(body['status'], 'resuming')
        mocked_submit.assert_not_called()
        self.assertFalse(os.path.exists(flag_path))
        self.assertFalse(observed_paused)
        self.assertTrue(observed_running)
        self.assertEqual(observed_last_status, 'resumed')
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
        server_module.COLLECTION_PAUSE_REASON = 'manual_required'
        server_module.SOLVER_RUNNING = False
        server_module.SOLVER_START_TIME = 0
        server_module.SOLVER_LAST_STATUS = 'manual_required'
        server_module.SOLVER_LAST_FAILURE_REASON = 'manual_required'
        server_module.SOLVER_MANUAL_RESUME_EPOCH = 0
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, 'force_unlock.flag')
        with open(flag_path, 'w', encoding='utf-8') as f:
            f.write('manual verification required')
        try:
            with mock.patch.object(server_module.executor, 'submit') as mocked_submit:
                request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_captcha', data=json.dumps({'target_url': 'https://contest.local/challenge?__captcha_solver_bg=1', 'force_retry': True}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(request) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode('utf-8'))
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
        self.assertEqual(body['status'], 'solving')
        mocked_submit.assert_called_once()
        self.assertEqual(mocked_submit.call_args.args[1], {'target_url': 'https://contest.local/challenge?__captcha_solver_bg=1'})
        self.assertFalse(os.path.exists(flag_path))
        self.assertFalse(observed_paused)
        self.assertFalse(observed_running)
        self.assertEqual(observed_last_status, 'resumed')
        self.assertIsNone(observed_last_failure)

    def test_report_captcha_endpoint_passes_cdp_endpoint_and_target_url_to_solver(self):
        with mock.patch.object(server_module.executor, 'submit') as mocked_submit:
            request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_captcha', data=json.dumps({'cdp_endpoint': 'http://192.168.65.254:9223', 'url': 'https://contest.local/challenge?__captcha_solver_bg=1', 'timestamp': 123}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'solving')
        mocked_submit.assert_called_once()
        submitted_callable = mocked_submit.call_args.args[0]
        self.assertEqual(getattr(submitted_callable, '__name__', ''), 'run_solver')
        self.assertEqual(mocked_submit.call_args.args[1], {'cdp_endpoint': 'http://192.168.65.254:9223', 'target_url': 'https://contest.local/challenge?__captcha_solver_bg=1'})

    def test_report_captcha_endpoint_preserves_detail_challenge_when_seed_stage_still_has_work(self):
        with mock.patch.dict(os.environ, {'FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS': 'https://sf.taobao.com/list/50025969__2.htm', 'FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED': '1'}, clear=False), mock.patch.object(server_module, '_collection_api_lightweight_status_payload', return_value={'seed_scan_job_pending': 10, 'seed_scan_job_in_progress': 1, 'seed_scan_progress_pending': 20, 'seed_scan_progress_in_progress': 0}), mock.patch.object(server_module, '_solver_force_unlock_flag_exists', return_value=False), mock.patch.object(server_module, 'PAUSED', False), mock.patch.object(server_module, 'SOLVER_LAST_STATUS', None), mock.patch.object(server_module, 'SOLVER_MANUAL_ONLY', False), mock.patch.object(server_module, 'SOLVER_LAST_REQUEST', {}), mock.patch.object(server_module, 'SOLVER_CHALLENGE_ID', None), mock.patch.object(server_module.executor, 'submit') as mocked_submit:
            request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_captcha', data=json.dumps({'cdp_endpoint': 'http://192.168.65.254:9223', 'node_id': 'pc2', 'target_url': 'https://sf-item.taobao.com/sf_item/817695886927.htm?track_id=test&__captcha_solver_bg=1'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'solving')
        self.assertEqual(mocked_submit.call_args.args[1], {'cdp_endpoint': 'http://192.168.65.254:9223', 'node_id': 'pc2', 'target_url': 'https://sf-item.taobao.com/sf_item/817695886927.htm?track_id=test&__captcha_solver_bg=1'})

    def test_report_captcha_endpoint_rewrites_loopback_cdp_endpoint_for_container_runtime(self):
        original_endpoint = os.environ.get('FAPAI_CDP_ENDPOINT')
        try:
            os.environ['FAPAI_CDP_ENDPOINT'] = 'http://192.168.65.254:9223'
            with mock.patch.object(server_module.executor, 'submit') as mocked_submit:
                request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_captcha', data=json.dumps({'cdp_endpoint': 'http://127.0.0.1:9223', 'url': 'https://contest.local/challenge?__captcha_solver_bg=1', 'timestamp': 456}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(request) as resp:
                    status = resp.status
                    payload = json.loads(resp.read().decode('utf-8'))
            self.assertEqual(status, 200)
            self.assertEqual(payload['status'], 'solving')
            self.assertEqual(mocked_submit.call_args.args[1], {'cdp_endpoint': 'http://192.168.65.254:9223', 'target_url': 'https://contest.local/challenge?__captcha_solver_bg=1'})
        finally:
            if original_endpoint is None:
                os.environ.pop('FAPAI_CDP_ENDPOINT', None)
            else:
                os.environ['FAPAI_CDP_ENDPOINT'] = original_endpoint

    def test_report_captcha_endpoint_returns_json_error_on_queue_failure(self):
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/report_captcha', data=b'', method='POST')
        with mock.patch.object(server_module.executor, 'submit', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_CAPTCHA_SOLVER_QUEUE_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_solver_instance_prefers_fapai_cdp_endpoint_for_live_runtime(self):
        original_endpoint = os.environ.get('FAPAI_CDP_ENDPOINT')
        original_solver = server_module.solver
        try:
            os.environ['FAPAI_CDP_ENDPOINT'] = 'http://192.168.65.254:9223'
            server_module.solver = server_module.CaptchaSolver(port=9222)
            self.assertEqual(server_module.solver.port, 9223)
            self.assertEqual(server_module.solver.cdp_endpoint, 'http://192.168.65.254:9223')
        finally:
            server_module.solver = original_solver
            if original_endpoint is None:
                os.environ.pop('FAPAI_CDP_ENDPOINT', None)
            else:
                os.environ['FAPAI_CDP_ENDPOINT'] = original_endpoint

    def test_build_solver_for_request_uses_request_specific_target_and_cdp_endpoint(self):
        request_solver = server_module._build_solver_for_request({'cdp_endpoint': 'http://192.168.65.254:9223', 'target_url': 'https://contest.local/challenge?__captcha_solver_bg=1'})
        self.assertEqual(request_solver.cdp_endpoint, 'http://192.168.65.254:9223')
        self.assertEqual(request_solver.port, 9223)
        self.assertEqual(request_solver.target_url, 'https://contest.local/challenge?__captcha_solver_bg=1')

    def test_log_endpoint_records_client_error_message(self):
        with mock.patch.object(server_module, 'print') as mocked_print:
            (status, payload) = self._post_json('/api/log', {'msg': 'frontend exploded', 'isError': True})
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'ok')
        mocked_print.assert_called_once_with('[Client Error] frontend exploded')

    def test_log_endpoint_rejects_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/log', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_upload_endpoint_saves_binary_file(self):
        original_data_dir = server_module.DATA_DIR
        server_module.DATA_DIR = self.data_dir
        try:
            request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/upload?id=3001&name=test%20image.jpg', data=b'fake-image-bytes', method='POST')
            with urllib.request.urlopen(request) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode('utf-8'))
        finally:
            server_module.DATA_DIR = original_data_dir
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'saved')
        saved_path = os.path.join(self.data_dir, 'downloads', '3001', 'test image.jpg')
        with open(saved_path, 'rb') as f:
            self.assertEqual(f.read(), b'fake-image-bytes')

    def test_upload_endpoint_requires_id_and_name(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/upload?id=3001', data=b'fake-image-bytes', method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_UPLOAD_REQUEST')

    def test_upload_endpoint_returns_json_error_on_failure(self):
        original_data_dir = server_module.DATA_DIR
        server_module.DATA_DIR = self.data_dir
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/upload?id=3001&name=test%20image.jpg', data=b'fake-image-bytes', method='POST')
        try:
            with mock.patch.object(server_module, 'open', side_effect=RuntimeError('boom'), create=True):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
        finally:
            server_module.DATA_DIR = original_data_dir
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_UPLOAD_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_screen_endpoint_summary(self):
        (status, payload) = self._post_json('/api/avm/screen', {'margin_threshold': 0.01, 'items': [{'id': '3001'}, {'id': '3002'}]})
        self.assertEqual(status, 200)
        self.assertEqual(payload['total'], 2)
        self.assertIn('summary', payload)
        self.assertIn('strategy_counts', payload['summary'])
        self.assertIn('coordinate_strategy_counts', payload['summary'])
        self.assertIn('confidence_bucket_counts', payload['summary'])
        self.assertIn('manual_review_count', payload['summary'])
        self.assertIn('blocked_reason_counts', payload['summary'])
        self.assertIn('risk_validation', payload['results'][0])
        self.assertIn('manual_review_recommended', payload['results'][0])
        self.assertIn('manual_review_reasons', payload['results'][0])
        self.assertIn('alert_blockers', payload['results'][0])

    def test_screen_endpoint_does_not_alert_when_manual_review_or_risk_validation_blocks(self):
        mocked_prediction = {'predicted_price': 1500000.0, 'predicted_unit_price': 15000.0, 'confidence': 0.42, 'comparable_count': 2, 'strategy': 'community_fallback', 'trace': {'valuation_mode': 'current_market', 'subject_coordinate_strategy': 'observed'}, 'top_factors': [], 'manual_review_recommended': True, 'manual_review_reasons': ['risk_feature_incomplete'], 'risk_validation': {'ok': False, 'missing_required_count': 5, 'invalid_field_count': 0, 'feature_completeness': 0.7, 'missing_required_fields': ['build_year'], 'invalid_fields': []}}
        with mock.patch.object(server_module.AVM_SERVICE, 'predict_by_item_data', return_value=mocked_prediction):
            (status, payload) = self._post_json('/api/avm/screen', {'margin_threshold': 0.01, 'items': [{'id': '3001'}]})
        self.assertEqual(status, 200)
        self.assertEqual(payload['alerts_written'], 0)
        self.assertEqual(payload['summary']['alert_candidate_count'], 0)
        self.assertEqual(payload['summary']['manual_review_blocked_count'], 1)
        self.assertEqual(payload['summary']['risk_validation_blocked_count'], 1)
        self.assertEqual(payload['summary']['blocked_reason_counts']['manual_review_required'], 1)
        self.assertEqual(payload['summary']['blocked_reason_counts']['risk_validation_incomplete'], 1)
        self.assertFalse(payload['results'][0]['meets_alert_threshold'])
        self.assertFalse(payload['results'][0]['risk_validation']['ok'])
        self.assertTrue(payload['results'][0]['manual_review_recommended'])
        self.assertIn('risk_feature_incomplete', payload['results'][0]['manual_review_reasons'])
        self.assertIn('manual_review_required', payload['results'][0]['alert_blockers'])
        self.assertIn('risk_validation_incomplete', payload['results'][0]['alert_blockers'])

    def test_screen_endpoint_uses_configured_alert_threshold_when_payload_omits_one(self):
        mocked_prediction = {'predicted_price': 1000000.0, 'predicted_unit_price': 10000.0, 'confidence': 0.8, 'comparable_count': 3, 'strategy': 'spatial', 'trace': {'valuation_mode': 'current_market', 'subject_coordinate_strategy': 'observed'}, 'top_factors': [], 'manual_review_recommended': False, 'manual_review_reasons': [], 'risk_validation': {'ok': True, 'missing_required_count': 0, 'invalid_field_count': 0, 'feature_completeness': 1.0, 'missing_required_fields': [], 'invalid_fields': []}}
        with mock.patch.object(server_module.AVM_CONFIG_MANAGER, 'get_config', return_value={'alert_threshold': 0.2}):
            with mock.patch.object(server_module.AVM_SERVICE, 'predict_by_item_data', return_value=mocked_prediction):
                (status, payload) = self._post_json('/api/avm/screen', {'items': [{'id': '3001', 'starting_price': 820000}]})
        self.assertEqual(status, 200)
        self.assertEqual(payload['alerts_written'], 0)
        self.assertIn('margin_below_threshold', payload['results'][0]['alert_blockers'])

    def test_screen_endpoint_allows_zero_alert_threshold_from_config(self):
        mocked_prediction = {'predicted_price': 1000000.0, 'predicted_unit_price': 10000.0, 'confidence': 0.8, 'comparable_count': 3, 'strategy': 'spatial', 'trace': {'valuation_mode': 'current_market', 'subject_coordinate_strategy': 'observed'}, 'top_factors': [], 'manual_review_recommended': False, 'manual_review_reasons': [], 'risk_validation': {'ok': True, 'missing_required_count': 0, 'invalid_field_count': 0, 'feature_completeness': 1.0, 'missing_required_fields': [], 'invalid_fields': []}}
        with mock.patch.object(server_module.AVM_CONFIG_MANAGER, 'get_config', return_value={'alert_threshold': 0.0}):
            with mock.patch.object(server_module.AVM_SERVICE, 'predict_by_item_data', return_value=mocked_prediction):
                (status, payload) = self._post_json('/api/avm/screen', {'items': [{'id': '3002', 'starting_price': 920000}]})
        self.assertEqual(status, 200)
        self.assertEqual(payload['margin_threshold'], 0.0)
        self.assertEqual(payload['alerts_written'], 1)
        self.assertTrue(payload['results'][0]['meets_alert_threshold'])

    def test_screen_endpoint_rejects_invalid_json_body(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/screen', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_screen_endpoint_rejects_non_object_json_body(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/screen', data=json.dumps([]).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_REQUEST_BODY')
        self.assertEqual(body['error']['details']['expected_type'], 'object')
        self.assertEqual(body['error']['details']['received_type'], 'list')

    def test_screen_endpoint_rejects_non_list_items(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/screen', data=json.dumps({'items': {'id': '3001'}}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_SCREEN_ITEMS')

    def test_screen_endpoint_returns_json_error_on_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/screen', data=json.dumps({'items': [{'id': '3001'}]}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with mock.patch.object(server_module, 'write_avm_alerts', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_SCREEN_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_collection_observer_get_error_routes_return_structured_codes(self):
        with mock.patch.object(server_module, '_collection_observer_overview_payload', side_effect=RuntimeError('boom')):
            self._assert_http_error_code('/api/collection/overview', 500, 'COLLECTION_OBSERVER_OVERVIEW_FAILED')
        with mock.patch.object(server_module, '_collection_observer_items_payload', side_effect=RuntimeError('boom')):
            self._assert_http_error_code('/api/collection/items', 500, 'COLLECTION_OBSERVER_ITEMS_FAILED')
        with mock.patch.object(server_module, '_collection_observer_regions_payload', side_effect=RuntimeError('boom')):
            self._assert_http_error_code('/api/collection/regions', 500, 'COLLECTION_OBSERVER_REGIONS_FAILED')
        with mock.patch.object(server_module, '_collection_observer_item_payload', side_effect=RuntimeError('boom')):
            self._assert_http_error_code('/api/collection/items/1001', 500, 'COLLECTION_OBSERVER_ITEM_FAILED')
        self._assert_http_error_code('/collection/assets/missing.js', 404, 'COLLECTION_STATIC_ASSET_NOT_FOUND')

    def test_collection_observer_post_error_routes_return_structured_codes(self):
        with mock.patch.object(server_module, '_collection_observer_reset_region_links_payload', side_effect=RuntimeError('boom')):
            self._assert_http_error_code('/api/collection/region/reset_links', 500, 'COLLECTION_OBSERVER_REGION_RESET_FAILED', method='POST', payload={})
        with mock.patch.object(server_module, '_collection_observer_reset_region_links_payload', return_value={'ok': False}):
            self._assert_http_error_code('/api/collection/region/reset_links', 400, 'COLLECTION_OBSERVER_REGION_RESET_REJECTED', method='POST', payload={})
        with mock.patch.object(server_module, '_collection_observer_reanalysis_payload', side_effect=RuntimeError('boom')):
            self._assert_http_error_code('/api/collection/item/reanalyze', 500, 'COLLECTION_OBSERVER_REANALYZE_FAILED', method='POST', payload={})
        with mock.patch.object(server_module, '_collection_observer_reanalysis_payload', return_value={'ok': False}):
            self._assert_http_error_code('/api/collection/item/reanalyze', 400, 'COLLECTION_OBSERVER_REANALYZE_REJECTED', method='POST', payload={})
        with mock.patch.object(server_module, '_collection_observer_manual_update_payload', side_effect=RuntimeError('boom')):
            self._assert_http_error_code('/api/collection/item/manual_update', 500, 'COLLECTION_OBSERVER_MANUAL_UPDATE_FAILED', method='POST', payload={})
        with mock.patch.object(server_module, '_collection_observer_manual_update_payload', return_value={'ok': False}):
            self._assert_http_error_code('/api/collection/item/manual_update', 400, 'COLLECTION_OBSERVER_MANUAL_UPDATE_REJECTED', method='POST', payload={})
        with mock.patch.object(server_module, '_collection_observer_runtime_control_payload', side_effect=RuntimeError('boom')):
            self._assert_http_error_code('/api/collection/control/pause', 500, 'COLLECTION_OBSERVER_RUNTIME_CONTROL_FAILED', method='POST')
        with mock.patch.object(server_module, '_collection_observer_runtime_control_payload', return_value={'ok': False}):
            self._assert_http_error_code('/api/collection/control/resume', 400, 'COLLECTION_OBSERVER_RUNTIME_CONTROL_REJECTED', method='POST')
        with mock.patch.object(server_module, '_collection_observer_auth_complete_payload', side_effect=RuntimeError('boom')):
            self._assert_http_error_code('/api/collection/auth/complete', 500, 'COLLECTION_OBSERVER_AUTH_COMPLETE_FAILED', method='POST', payload={})
        with mock.patch.object(server_module, '_collection_observer_auth_complete_payload', return_value={'ok': False}):
            self._assert_http_error_code('/api/collection/auth/complete', 400, 'COLLECTION_OBSERVER_AUTH_COMPLETE_REJECTED', method='POST', payload={})
        with mock.patch.object(server_module, '_collection_observer_resume_after_cooldown_payload', side_effect=RuntimeError('boom')):
            self._assert_http_error_code('/api/collection/auth/resume_after_cooldown', 500, 'COLLECTION_OBSERVER_AUTH_RESUME_FAILED', method='POST', payload={})
        with mock.patch.object(server_module, '_collection_observer_resume_after_cooldown_payload', return_value={'ok': False}):
            self._assert_http_error_code('/api/collection/auth/resume_after_cooldown', 400, 'COLLECTION_OBSERVER_AUTH_RESUME_REJECTED', method='POST', payload={})

    def test_report_captcha_force_retry_failure_returns_structured_error(self):
        with mock.patch.object(server_module, '_captcha_solver_runtime_status', return_value={'manual_required': True, 'running': False}), mock.patch.object(server_module, '_clear_solver_manual_required_pause', return_value='boom'):
            self._assert_http_error_code('/api/report_captcha', 500, 'AVM_CAPTCHA_SOLVER_FORCE_RETRY_FAILED', method='POST', payload={'force_retry': True, 'target_url': 'https://contest.local/challenge'})

    def test_seed_progress_routes_reject_non_object_json_body(self):
        for path in ('/api/report_sniff_status', '/api/collection/seeds/report_progress'):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_recent_enrich_maintenance_routes_reject_non_object_json_body(self):
        for path in ('/api/avm/recent_enrich_maintenance', '/api/collection/details/maintenance'):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_fetch_missing_detail_archive_routes_reject_non_object_json_body(self):
        for path in ('/api/avm/fetch_missing_detail_archives', '/api/collection/details/fetch_missing'):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_archive_detail_replay_routes_reject_non_object_json_body(self):
        for path in ('/api/avm/archive_detail_replay', '/api/collection/details/prepare_replay'):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_save_locations_endpoint_rejects_non_object_json_body(self):
        self._assert_non_object_json_body_rejected('/api/save_locations')

    def test_seed_batch_routes_reject_non_object_json_body(self):
        for path in ('/api/save', '/api/collection/seeds/batch'):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_log_endpoint_rejects_non_object_json_body(self):
        self._assert_non_object_json_body_rejected('/api/log')

    def test_update_item_routes_reject_non_object_json_body(self):
        for path in ('/api/update_item', '/api/collection/details/update_item'):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_area_result_routes_reject_non_object_json_body(self):
        for path in ('/api/area_result', '/api/collection/details/area_result'):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_infer_location_routes_reject_non_object_json_body(self):
        for path in ('/api/infer_location', '/api/collection/details/infer_location'):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_approve_area_routes_reject_non_object_json_body(self):
        for path in ('/api/approve_area', '/api/collection/details/approve_area'):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_analyze_html_routes_reject_non_object_json_body(self):
        for path in ('/api/analyze_html', '/api/collection/details/html'):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_manual_review_receipts_routes_reject_non_object_json_body(self):
        for path in ('/api/avm/manual_review_receipts', '/api/analysis/manual_review_receipts'):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path)

    def test_manual_review_receipts_delete_routes_reject_non_object_json_body(self):
        for path in ('/api/avm/manual_review_receipts', '/api/analysis/manual_review_receipts'):
            with self.subTest(path=path):
                self._assert_non_object_json_body_rejected(path, method='DELETE')

    def test_manual_review_receipts_routes_reject_invalid_json(self):
        for path in ('/api/avm/manual_review_receipts', '/api/analysis/manual_review_receipts'):
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode('utf-8'))
                self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_manual_review_receipts_delete_routes_reject_invalid_json(self):
        for path in ('/api/avm/manual_review_receipts', '/api/analysis/manual_review_receipts'):
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=b'{', headers={'Content-Type': 'application/json'}, method='DELETE')
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode('utf-8'))
                self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_object_json_routes_reject_invalid_json_in_live_sweep(self):
        for (path, method) in self._object_json_route_methods():
            with self.subTest(path=path, method=method):
                self._assert_invalid_json_body_rejected(path, method=method)

    def test_object_json_routes_reject_non_object_json_in_live_sweep(self):
        for (path, method) in self._object_json_route_methods():
            with self.subTest(path=path, method=method):
                self._assert_non_object_json_body_rejected(path, method=method)

    def test_update_item_routes_reject_invalid_json(self):
        for path in ('/api/update_item', '/api/collection/details/update_item'):
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode('utf-8'))
                self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

__all__ = ["AVMHttpContractPart10"]
