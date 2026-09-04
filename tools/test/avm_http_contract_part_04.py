from __future__ import annotations

from tools.test.avm_http_contract_context import *  # noqa: F401,F403


class AVMHttpContractPart04:
    def test_merge_check_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module.AVM_PIPELINE, 'verify_merge_completeness', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/merge_check')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MERGE_CHECK_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_get_item_legacy_endpoint_prefers_repository_item(self):
        fake_repo = mock.Mock()
        fake_repo.enabled = True
        fake_repo.get_flat_item.return_value = {'id': 'db-1', 'url': 'https://x/db-1'}
        with mock.patch.object(server_module, 'DB_REPOSITORY', fake_repo):
            (status, payload) = self._get_json('/api/get_item?id=db-1')
        self.assertEqual(status, 200)
        self.assertEqual(payload['id'], 'db-1')
        self.assertEqual(payload['url'], 'https://x/db-1')
        fake_repo.get_flat_item.assert_called_once_with('db-1')

    def test_get_item_legacy_endpoint_returns_empty_object_when_id_missing(self):
        (status, payload) = self._get_json('/api/get_item')
        self.assertEqual(status, 200)
        self.assertEqual(payload, {})

    def test_get_item_legacy_endpoint_returns_empty_object_when_item_not_found(self):
        fake_repo = mock.Mock()
        fake_repo.enabled = True
        fake_repo.get_flat_item.return_value = None
        with mock.patch.object(server_module, 'DB_REPOSITORY', fake_repo):
            (status, payload) = self._get_json('/api/get_item?id=missing')
        self.assertEqual(status, 200)
        self.assertEqual(payload, {})
        fake_repo.get_flat_item.assert_called_once_with('missing')

    def test_get_or_create_sniff_task_legacy_endpoint(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {'task': {'url': 'https://x/task'}, 'message': 'ok'}
        with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
            (status, payload) = self._get_json('/api/get_or_create_sniff_task?session_id=s-1')
        self.assertEqual(status, 200)
        self.assertEqual(payload['task']['url'], 'https://x/task')
        fake_service.next_task.assert_called_once_with('s-1', paused=False)

    def test_get_or_create_sniff_task_legacy_endpoint_returns_empty_task_payload_when_no_task_available(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {'task': None, 'message': '所有嗅探任务已完成'}
        with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
            (status, payload) = self._get_json('/api/get_or_create_sniff_task?session_id=s-1')
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'task': None, 'message': '所有嗅探任务已完成'})
        fake_service.next_task.assert_called_once_with('s-1', paused=False)

    def test_get_or_create_sniff_task_legacy_endpoint_passes_paused_state(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {'task': {}, 'message': 'ok'}
        original_paused = server_module.PAUSED
        server_module.PAUSED = True
        try:
            with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
                (status, payload) = self._get_json('/api/get_or_create_sniff_task?session_id=s-1')
        finally:
            server_module.PAUSED = original_paused
        self.assertEqual(status, 200)
        self.assertEqual(payload['message'], 'ok')
        fake_service.next_task.assert_called_once_with('s-1', paused=True)

    def test_get_or_create_sniff_task_legacy_endpoint_treats_force_unlock_flag_as_paused(self):
        fake_service = mock.Mock()
        fake_service.next_task.return_value = {'task': {}, 'message': 'ok'}
        original_paused = server_module.PAUSED
        original_data_dir = server_module.DATA_DIR
        server_module.PAUSED = False
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, 'force_unlock.flag')
        with open(flag_path, 'w', encoding='utf-8') as f:
            f.write('manual verification required')
        try:
            with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
                (status, payload) = self._get_json('/api/get_or_create_sniff_task?session_id=s-1')
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.PAUSED = original_paused
        self.assertEqual(status, 200)
        self.assertEqual(payload['message'], 'ok')
        fake_service.next_task.assert_called_once_with('s-1', paused=True)

    def test_get_or_create_sniff_task_legacy_endpoint_returns_json_error_on_failure(self):
        fake_service = mock.Mock()
        fake_service.next_task.side_effect = RuntimeError('boom')
        with mock.patch.object(server_module, '_seed_collection_service', return_value=fake_service):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/get_or_create_sniff_task?session_id=s-1')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_SEED_NEXT_TASK_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_get_tasks_legacy_endpoint(self):
        with mock.patch.object(server_module, '_prefer_db_task_reads', return_value=True), mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.batch_tasks.return_value = {'tasks': [{'id': 'x-1', 'url': 'https://x/detail-1'}], 'total': 10, 'done': 5, 'pending': 5}
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/get_tasks')
        self.assertEqual(status, 200)
        self.assertEqual(payload['tasks'][0]['id'], 'x-1')
        self.assertEqual(payload['total'], 10)
        fake_service.batch_tasks.assert_called_once()

    def test_get_tasks_legacy_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_prefer_db_task_reads', return_value=True), mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.batch_tasks.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/get_tasks')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_BATCH_TASKS_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_get_next_task_legacy_endpoint(self):
        with mock.patch.object(server_module, '_prefer_db_task_reads', return_value=True), mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_visit_task.return_value = {'task_type': 'visit', 'id': 'x-1', 'url': 'https://x/detail-1'}
            mocked_factory.return_value = fake_service
            request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/get_next_task', data=b'', method='POST')
            with urllib.request.urlopen(request) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(status, 200)
        self.assertEqual(payload['task_type'], 'visit')
        self.assertEqual(payload['id'], 'x-1')
        fake_service.next_visit_task.assert_called_once()

    def test_get_next_task_legacy_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_visit_task.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/get_next_task', data=b'', method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_NEXT_VISIT_TASK_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_get_next_task_legacy_endpoint_returns_none_task_when_no_task_available(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_visit_task.return_value = {'task_type': 'none'}
            mocked_factory.return_value = fake_service
            request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/get_next_task', data=b'', method='POST')
            with urllib.request.urlopen(request) as resp:
                status = resp.status
                payload = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'task_type': 'none'})
        fake_service.next_visit_task.assert_called_once()

    def test_start_all_subtasks_endpoint_runs_async_defaults(self):
        expected_result = {'status': 'started', 'source': 'start-all'}
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/start_all_subtasks', data=b'', method='POST')
        with mock.patch.object(server_module.AVM_PIPELINE, 'run', return_value=expected_result) as mocked_run:
            with urllib.request.urlopen(req) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
                status = resp.status
        self.assertEqual(status, 200)
        self.assertEqual(payload, expected_result)
        mocked_run.assert_called_once()
        (_, kwargs) = mocked_run.call_args
        self.assertTrue(kwargs['async_mode'])
        self.assertEqual(kwargs['config'].data_dir, server_module.DATA_DIR)
        self.assertEqual(kwargs['config'].alerts_threshold, 0.15)
        self.assertEqual(kwargs['config'].alerts_limit, 500)

    def test_start_all_subtasks_endpoint_returns_json_error_on_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/start_all_subtasks', data=b'', method='POST')
        with mock.patch.object(server_module.AVM_PIPELINE, 'run', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_START_ALL_SUBTASKS_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_run_all_subtasks_sync_endpoint_runs_sync_defaults(self):
        expected_result = {'status': 'completed', 'source': 'sync-all'}
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/run_all_subtasks_sync', data=b'', method='POST')
        with mock.patch.object(server_module.AVM_PIPELINE, 'run', return_value=expected_result) as mocked_run:
            with urllib.request.urlopen(req) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
                status = resp.status
        self.assertEqual(status, 200)
        self.assertEqual(payload, expected_result)
        mocked_run.assert_called_once()
        (_, kwargs) = mocked_run.call_args
        self.assertFalse(kwargs['async_mode'])
        self.assertEqual(kwargs['config'].data_dir, server_module.DATA_DIR)
        self.assertEqual(kwargs['config'].alerts_threshold, 0.15)
        self.assertEqual(kwargs['config'].alerts_limit, 500)

    def test_run_all_subtasks_sync_endpoint_returns_json_error_on_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/run_all_subtasks_sync', data=b'', method='POST')
        with mock.patch.object(server_module.AVM_PIPELINE, 'run', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_RUN_ALL_SUBTASKS_SYNC_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_release_gate_endpoint(self):
        (status, payload) = self._get_json('/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertIn('completeness', payload)
        self.assertIn('evaluation', payload)
        self.assertIn('api_smoke', payload)
        self.assertTrue(payload['api_smoke'].get('skipped'))

    def test_release_gate_endpoint_defaults_invalid_numeric_query_params(self):
        gate_payload = {'pass': False, 'evaluation': {'pass': False}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload) as mocked_report, mock.patch.object(server_module, '_avm_operator_eval_summary', return_value={}):
            (status, payload) = self._get_json('/api/avm/release_gate?window_days=bad&min_sample_size=bad&smoke_sample_size=bad')
        self.assertEqual(status, 200)
        self.assertTrue(payload['api_smoke'].get('skipped'))
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs['window_days'], 7)
        self.assertEqual(mocked_report.call_args.kwargs['min_sample_size'], 1000)
        self.assertEqual(mocked_report.call_args.kwargs['smoke_sample_size'], 0)

    def test_release_gate_endpoint_clamps_negative_numeric_query_params(self):
        gate_payload = {'pass': False, 'evaluation': {'pass': False}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload) as mocked_report, mock.patch.object(server_module, '_avm_operator_eval_summary', return_value={}):
            (status, payload) = self._get_json('/api/avm/release_gate?window_days=-1&min_sample_size=-1&smoke_sample_size=-1')
        self.assertEqual(status, 200)
        self.assertTrue(payload['api_smoke'].get('skipped'))
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs['window_days'], 7)
        self.assertEqual(mocked_report.call_args.kwargs['min_sample_size'], 1000)
        self.assertEqual(mocked_report.call_args.kwargs['smoke_sample_size'], 0)

    def test_release_gate_endpoint_returns_json_error_on_report_generation_failure(self):
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_RELEASE_GATE_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_release_gate_endpoint_returns_json_error_on_operator_summary_failure(self):
        gate_payload = {'pass': False, 'evaluation': {'pass': False}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload), mock.patch.object(server_module, '_avm_operator_eval_summary', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_RELEASE_GATE_SUMMARY_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_analysis_release_gate_endpoint_returns_json_error_on_report_generation_failure(self):
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_RELEASE_GATE_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_analysis_release_gate_endpoint_defaults_invalid_numeric_query_params(self):
        gate_payload = {'pass': False, 'evaluation': {'pass': False}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload) as mocked_report, mock.patch.object(server_module, '_avm_operator_eval_summary', return_value={}):
            (status, payload) = self._get_json('/api/analysis/release_gate?window_days=bad&min_sample_size=bad&smoke_sample_size=bad')
        self.assertEqual(status, 200)
        self.assertTrue(payload['api_smoke'].get('skipped'))
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs['window_days'], 7)
        self.assertEqual(mocked_report.call_args.kwargs['min_sample_size'], 1000)
        self.assertEqual(mocked_report.call_args.kwargs['smoke_sample_size'], 0)

    def test_analysis_release_gate_endpoint_clamps_negative_numeric_query_params(self):
        gate_payload = {'pass': False, 'evaluation': {'pass': False}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload) as mocked_report, mock.patch.object(server_module, '_avm_operator_eval_summary', return_value={}):
            (status, payload) = self._get_json('/api/analysis/release_gate?window_days=-1&min_sample_size=-1&smoke_sample_size=-1')
        self.assertEqual(status, 200)
        self.assertTrue(payload['api_smoke'].get('skipped'))
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs['window_days'], 7)
        self.assertEqual(mocked_report.call_args.kwargs['min_sample_size'], 1000)
        self.assertEqual(mocked_report.call_args.kwargs['smoke_sample_size'], 0)

    def test_release_gate_endpoint_surfaces_calibration_operator_summary(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': ['district_centroid'], 'top_coordinate_strategy_group': 'district_centroid', 'calibration_targets': {'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 1.05}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 1.05}], 'risk_factor_targets': [], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-global-risk', 'target_types': ['global_risk', 'temporal'], 'target_names': None}}, 'guidance': {'status': 'fix_coordinate_quality', 'priority': 'high', 'recommended_actions': ['review_coordinate_strategy_cohorts'], 'top_reason': 'district_centroid'}}}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump(gate_payload, f, ensure_ascii=False)
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'fix_coordinate_quality')
        self.assertEqual(payload['calibration_target_counts']['temporal'], 1)
        self.assertEqual(payload['calibration_target_counts']['global_risk'], 1)
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['top_calibration_target_hint']['playbook_id'], 'tune-temporal-decay')
        self.assertEqual(payload['recommended_bundle_risk_level'], 'medium')
        self.assertEqual(payload['recommended_bundle_next_action'], 'preview_only_first')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['preview', 'write', 'verify', 'gate'])

    def test_release_gate_endpoint_prefers_generated_report_over_stale_gate_file_for_operator_summary(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        stale_gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        fresh_gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': ['district_centroid'], 'top_coordinate_strategy_group': 'district_centroid', 'calibration_targets': {'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 1.05}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 1.05}], 'risk_factor_targets': [], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-global-risk', 'target_types': ['global_risk', 'temporal'], 'target_names': None}}, 'guidance': {'status': 'fix_coordinate_quality', 'priority': 'high', 'recommended_actions': ['review_coordinate_strategy_cohorts'], 'top_reason': 'district_centroid'}}}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump(stale_gate_payload, f, ensure_ascii=False)
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=fresh_gate_payload):
            (status, payload) = self._get_json('/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'fix_coordinate_quality')
        self.assertEqual(payload['calibration_target_counts']['temporal'], 1)
        self.assertEqual(payload['calibration_target_counts']['global_risk'], 1)
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['top_calibration_target_hint']['playbook_id'], 'tune-temporal-decay')
        self.assertEqual(payload['recommended_bundle_risk_level'], 'medium')
        self.assertEqual(payload['recommended_bundle_next_action'], 'preview_only_first')

    def test_release_gate_endpoint_uses_embedded_calibration_targets_when_file_is_missing(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': ['district_centroid'], 'top_coordinate_strategy_group': 'district_centroid', 'calibration_targets': {'config_patch': {'weighting': {'time_decay': 0.72}}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [], 'risk_factor_targets': [], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}, 'guidance': {'status': 'tune_temporal_decay', 'priority': 'medium', 'recommended_actions': ['adjust_weighting_time_decay'], 'top_reason': 'time_decay'}}}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'tune_temporal_decay')
        self.assertEqual(payload['calibration_target_counts']['temporal'], 1)
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['recommended_bundle_risk_level'], 'low')
        self.assertEqual(payload['recommended_bundle_next_action'], 'safe_to_write_then_verify')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['write', 'verify', 'gate'])

    def test_release_gate_endpoint_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [], 'risk_factor_targets': [], 'strategy_targets': [], 'config_patch': {'weighting': {'time_decay': 0.72}}, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'runbook_refs': ['tools/evaluate_avm.py'], 'recommended_actions': ['adjust_weighting_time_decay'], 'suggested_commands': ['python tools/evaluate_avm.py'], 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}, 'guidance': {'status': 'tune_temporal_decay', 'priority': 'medium', 'recommended_actions': ['adjust_weighting_time_decay'], 'top_reason': 'time_decay'}}, f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')
        self.assertEqual(payload['recommended_bundle_verify_command'], 'python tools/evaluate_avm.py')
        self.assertEqual(payload['recommended_bundle_gate_command'], 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report')
        self.assertEqual(payload['recommended_bundle_next_action'], 'safe_to_write_then_verify')
        self.assertEqual(payload['recommended_bundle_next_action_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')
        self.assertEqual(payload['recommended_bundle_follow_up_command'], 'python tools/evaluate_avm.py')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'verify')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['write', 'verify', 'gate'])

    def test_release_gate_endpoint_normalizes_malformed_calibration_target_lists(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': {'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}, 'global_risk_targets': {}, 'risk_factor_targets': 'bad-shape', 'strategy_targets': None, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}}, f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')

    def test_release_gate_endpoint_merges_partial_embedded_calibration_targets_with_file_context(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {'is_occupied': 0.8}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 0.99, 'risk_factor_overrides': {'is_occupied': 0.5}}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 0.99}], 'risk_factor_targets': [{'target_type': 'risk_flag', 'name': 'is_occupied', 'suggested_next_factor': 0.5}], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}, 'top_calibration_target_hint': {'status': 'tune_risk_factors', 'playbook_id': 'split-bundle-or-single-target-first', 'recommended_bundle': {'bundle_id': 'temporal-global-risk-risk-flag', 'target_types': ['temporal', 'global_risk', 'risk_flag'], 'target_names': ['time_decay', 'risk_discount_factor', 'is_occupied']}, 'suggested_bundle_commands': ['python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied', 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write', 'python tools/evaluate_avm.py', 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report']}, 'guidance': {'status': 'tune_risk_factors', 'priority': 'high', 'recommended_actions': ['split_bundle_or_single_target_first'], 'top_reason': 'multi_flag_bundle'}}, f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': [], 'calibration_targets': {'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}}}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['recommended_bundle_risk_level'], 'high')
        self.assertEqual(payload['recommended_bundle_next_action'], 'split_bundle_or_single_target_first')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'none')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['preview'])

    def test_release_gate_endpoint_tolerates_non_object_calibration_targets_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_release_gate_endpoint_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_release_gate_endpoint_tolerates_invalid_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': -1, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

__all__ = ["AVMHttpContractPart04"]
