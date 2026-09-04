from __future__ import annotations

from tools.test.avm_http_contract_context import *  # noqa: F401,F403


class AVMHttpContractPart03:
    def test_collection_template_endpoint(self):
        (status, payload) = self._get_json('/api/avm/collection_template')
        self.assertEqual(status, 200)
        self.assertEqual(payload['version'], 'avm_collection_contract_v1_frozen')
        self.assertTrue(payload['frozen_contract'])
        self.assertIn('groups', payload)
        self.assertIn('collector_priorities', payload)
        self.assertIn('final_template', payload)
        self.assertIn('source', payload['consumer_payload_shape'])
        self.assertIn('archive', payload['consumer_payload_shape'])
        self.assertIn('subject', payload['consumer_payload_shape'])
        self.assertIn('auction', payload['consumer_payload_shape'])
        self.assertIn('legal_context', payload['consumer_payload_shape'])
        self.assertIn('bidder_count', payload['consumer_payload_shape']['subject'])
        self.assertIn('source', payload['final_template'])
        self.assertIn('source_platform', payload['final_template']['source'])
        self.assertIn('archive', payload['final_template'])
        self.assertIn('ownership_share_ratio', payload['final_template']['property'])
        self.assertIn('legal_context', payload['final_template'])
        group_ids = {group['id'] for group in payload['groups']}
        self.assertIn('auction_core', group_ids)
        self.assertIn('raw_archive', group_ids)
        self.assertIn('legal_context', group_ids)
        self.assertIn('location_spatial', group_ids)

    def test_collection_template_endpoint_returns_json_error_on_failure(self):
        with mock.patch('src.avm.collection_template.get_collection_template', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/collection_template')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_COLLECTION_TEMPLATE_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_build_sniff_stub_preserves_address_and_bid_semantics(self):
        stub = server_module.build_sniff_stub({'id': 'stub-1', 'title': '测试标题', 'url': 'https://x/stub-1', 'location': '上海市浦东新区测试路99号', 'city': '上海市', 'district': '浦东新区', 'auction_date': '2026-04-01 10:00:00', 'currentPrice': '100万', 'initialPrice': '80万', 'applyCount': 3, 'bidCount': 7, 'bidderCount': 2, 'deposit': '5万', 'latitude': 31.2, 'longitude': 121.5, 'coordinate_source': 'list', 'auction_round': 2, 'housing_type': '住宅'})
        self.assertEqual(stub['title'], '测试标题')
        self.assertEqual(stub['source_title'], '测试标题')
        self.assertEqual(stub['地点'], '上海市浦东新区测试路99号')
        self.assertEqual(stub['完整地址'], '上海市浦东新区测试路99号')
        self.assertEqual(stub['bid_count'], 7)
        self.assertEqual(stub['出价次数'], 7)
        self.assertEqual(stub['bidder_count'], 2)
        self.assertEqual(stub['出价人数'], 2)
        self.assertEqual(stub['deposit'], 50000.0)
        self.assertEqual(stub['保证金'], 50000.0)
        self.assertEqual(stub['coordinate_source'], 'list')
        self.assertEqual(stub['source']['source_title'], '测试标题')
        self.assertEqual(stub['auction']['bid_count'], 7)
        self.assertEqual(stub['auction']['bidder_count'], 2)
        self.assertEqual(stub['auction']['deposit'], 50000.0)
        self.assertEqual(stub['location']['full_address'], '上海市浦东新区测试路99号')
        self.assertEqual(stub['location']['coordinate_source'], 'list')

    def test_predict_endpoint(self):
        (status, payload) = self._get_json('/api/avm/predict?id=3001')
        self.assertEqual(status, 200)
        self.assertEqual(payload['item_id'], '3001')
        self.assertIsNotNone(payload['predicted_price'])
        self.assertIn('risk_validation', payload)
        self.assertIn('valuation_mode', payload['trace'])
        self.assertIn('subject_coordinate_strategy', payload['trace'])

    def test_predict_missing_id_returns_json_error(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/predict')
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_ID')

    def test_predict_not_found_returns_json_error(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/predict?id=999999')
        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_NOT_FOUND')
        self.assertEqual(body['error']['details']['id'], '999999')

    def test_predict_failure_returns_json_error(self):
        with mock.patch.object(server_module.AVM_SERVICE, 'predict_by_item_id', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/predict?id=3001')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_PREDICT_FAILED')
        self.assertEqual(body['error']['details']['id'], '3001')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_analysis_predict_alias_endpoint(self):
        (status, payload) = self._get_json('/api/analysis/predict?id=3001')
        self.assertEqual(status, 200)
        self.assertEqual(payload['item_id'], '3001')
        self.assertIsNotNone(payload['predicted_price'])
        self.assertIn('risk_validation', payload)
        self.assertIn('valuation_mode', payload['trace'])
        self.assertIn('subject_coordinate_strategy', payload['trace'])

    def test_analysis_predict_alias_missing_id_returns_json_error(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/analysis/predict')
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_ID')

    def test_analysis_predict_alias_not_found_returns_json_error(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/analysis/predict?id=999999')
        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_NOT_FOUND')
        self.assertEqual(body['error']['details']['id'], '999999')

    def test_analysis_predict_alias_failure_returns_json_error(self):
        with mock.patch.object(server_module.AVM_SERVICE, 'predict_by_item_id', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/analysis/predict?id=3001')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_PREDICT_FAILED')
        self.assertEqual(body['error']['details']['id'], '3001')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_evaluate_endpoint(self):
        payload = {'request_id': 'req-test-1', 'subject': {'city': '上海市', 'district': '浦东新区', 'community_name': '测试小区', 'area_sqm': 100, 'housing_type': '住宅'}, 'auction': {'starting_price': 850000, 'auction_date': '2026-04-01'}, 'risk_flags': {'is_occupied': True}}
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/evaluate', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(resp.status, 200)
        self.assertEqual(body['request_id'], 'req-test-1')
        self.assertEqual(body['model_version'], 'avm_multidim_v1')
        self.assertIsNotNone(body['valuation']['estimated_fair_price'])
        self.assertIn('risk_validation', body)
        self.assertIn('valuation_mode', body['trace'])
        self.assertIn('risk_adjustments', body)
        self.assertIn('manual_review', body)
        self.assertIn(body['trace']['strategy'], {'spatial', 'community_fallback'})

    def test_evaluate_missing_subject_returns_json_error(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/evaluate', data=json.dumps({'request_id': 'bad'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_SUBJECT')

    def test_evaluate_missing_area_returns_json_error(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/evaluate', data=json.dumps({'request_id': 'bad', 'subject': {'city': '上海市'}}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MISSING_AREA')

    def test_evaluate_invalid_json_returns_json_error(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/evaluate', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_evaluate_rejects_non_object_json_body(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/evaluate', data=json.dumps([]).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_REQUEST_BODY')
        self.assertEqual(body['error']['details']['expected_type'], 'object')
        self.assertEqual(body['error']['details']['received_type'], 'list')

    def test_evaluate_failure_returns_json_error(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/evaluate', data=json.dumps({'request_id': 'req-test-1', 'subject': {'area_sqm': 100}}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with mock.patch.object(server_module.AVM_SERVICE, 'evaluate_request', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_EVALUATE_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_analysis_evaluate_alias_endpoint(self):
        payload = {'request_id': 'req-test-1', 'subject': {'city': '上海市', 'district': '浦东新区', 'community_name': '测试小区', 'area_sqm': 100, 'housing_type': '住宅'}, 'auction': {'starting_price': 850000, 'auction_date': '2026-04-01'}, 'risk_flags': {'is_occupied': True}}
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/evaluate', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(resp.status, 200)
        self.assertEqual(body['request_id'], 'req-test-1')
        self.assertEqual(body['model_version'], 'avm_multidim_v1')
        self.assertIsNotNone(body['valuation']['estimated_fair_price'])
        self.assertIn('risk_validation', body)
        self.assertIn('valuation_mode', body['trace'])
        self.assertIn('risk_adjustments', body)
        self.assertIn('manual_review', body)
        self.assertIn(body['trace']['strategy'], {'spatial', 'community_fallback'})

    def test_analysis_evaluate_alias_missing_subject_returns_json_error(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/evaluate', data=json.dumps({'request_id': 'bad'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_SUBJECT')

    def test_analysis_evaluate_alias_missing_area_returns_json_error(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/evaluate', data=json.dumps({'request_id': 'bad', 'subject': {'city': '上海市'}}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MISSING_AREA')

    def test_analysis_evaluate_alias_invalid_json_returns_json_error(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/evaluate', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_analysis_evaluate_alias_rejects_non_object_json_body(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/evaluate', data=json.dumps([]).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_REQUEST_BODY')
        self.assertEqual(body['error']['details']['expected_type'], 'object')
        self.assertEqual(body['error']['details']['received_type'], 'list')

    def test_analysis_evaluate_alias_failure_returns_json_error(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/evaluate', data=json.dumps({'request_id': 'req-test-1', 'subject': {'area_sqm': 100}}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with mock.patch.object(server_module.AVM_SERVICE, 'evaluate_request', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_EVALUATE_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_run_endpoint_passes_sync_config_to_pipeline_manager(self):
        expected_result = {'status': 'completed', 'source': 'http'}
        with mock.patch.object(server_module.AVM_PIPELINE, 'run', return_value=expected_result) as mocked_run:
            (status, payload) = self._post_json('/api/avm/run', {'mode': 'sync', 'data_dir': self.data_dir, 'alerts_threshold': 0.05, 'alerts_limit': 12})
        self.assertEqual(status, 200)
        self.assertEqual(payload, expected_result)
        mocked_run.assert_called_once()
        (_, kwargs) = mocked_run.call_args
        self.assertFalse(kwargs['async_mode'])
        self.assertEqual(kwargs['config'].data_dir, self.data_dir)
        self.assertEqual(kwargs['config'].alerts_threshold, 0.05)
        self.assertEqual(kwargs['config'].alerts_limit, 12)

    def test_run_endpoint_defaults_to_async_when_body_is_empty(self):
        expected_result = {'status': 'started', 'source': 'http-main'}
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/run', data=b'', headers={'Content-Type': 'application/json'}, method='POST')
        with mock.patch.object(server_module.AVM_PIPELINE, 'run', return_value=expected_result) as mocked_run:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(resp.status, 200)
        self.assertEqual(body, expected_result)
        mocked_run.assert_called_once()
        (_, kwargs) = mocked_run.call_args
        self.assertTrue(kwargs['async_mode'])
        self.assertEqual(kwargs['config'].data_dir, server_module.DATA_DIR)
        self.assertEqual(kwargs['config'].alerts_threshold, 0.15)
        self.assertEqual(kwargs['config'].alerts_limit, 500)

    def test_run_endpoint_rejects_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/run', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_run_endpoint_rejects_non_object_json_body(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/run', data=json.dumps([]).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_REQUEST_BODY')
        self.assertEqual(body['error']['details']['expected_type'], 'object')
        self.assertEqual(body['error']['details']['received_type'], 'list')

    def test_run_endpoint_rejects_invalid_pipeline_config_values(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/run', data=json.dumps({'alerts_threshold': 'bad'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_PIPELINE_CONFIG')
        self.assertIn('alerts_threshold', body['error']['details']['invalid_fields'])

    def test_analysis_pipeline_run_alias_passes_sync_config_to_pipeline_manager(self):
        expected_result = {'status': 'completed', 'source': 'http-alias-sync'}
        with mock.patch.object(server_module.AVM_PIPELINE, 'run', return_value=expected_result) as mocked_run:
            (status, payload) = self._post_json('/api/analysis/pipeline/run', {'mode': 'sync', 'data_dir': self.data_dir, 'alerts_threshold': 0.05, 'alerts_limit': 12})
        self.assertEqual(status, 200)
        self.assertEqual(payload, expected_result)
        mocked_run.assert_called_once()
        (_, kwargs) = mocked_run.call_args
        self.assertFalse(kwargs['async_mode'])
        self.assertEqual(kwargs['config'].data_dir, self.data_dir)
        self.assertEqual(kwargs['config'].alerts_threshold, 0.05)
        self.assertEqual(kwargs['config'].alerts_limit, 12)

    def test_analysis_pipeline_run_alias_defaults_to_async_when_body_is_empty(self):
        expected_result = {'status': 'started', 'source': 'http-alias'}
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/pipeline/run', data=b'', headers={'Content-Type': 'application/json'}, method='POST')
        with mock.patch.object(server_module.AVM_PIPELINE, 'run', return_value=expected_result) as mocked_run:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(resp.status, 200)
        self.assertEqual(body, expected_result)
        mocked_run.assert_called_once()
        (_, kwargs) = mocked_run.call_args
        self.assertTrue(kwargs['async_mode'])
        self.assertEqual(kwargs['config'].data_dir, server_module.DATA_DIR)
        self.assertEqual(kwargs['config'].alerts_threshold, 0.15)
        self.assertEqual(kwargs['config'].alerts_limit, 500)

    def test_analysis_pipeline_run_alias_rejects_invalid_json(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/pipeline/run', data=b'{', headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_JSON')

    def test_analysis_pipeline_run_alias_rejects_non_object_json_body(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/pipeline/run', data=json.dumps([]).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_REQUEST_BODY')
        self.assertEqual(body['error']['details']['expected_type'], 'object')
        self.assertEqual(body['error']['details']['received_type'], 'list')

    def test_analysis_pipeline_run_alias_rejects_invalid_pipeline_config_values(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/pipeline/run', data=json.dumps({'alerts_limit': 'bad'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_PIPELINE_CONFIG')
        self.assertIn('alerts_limit', body['error']['details']['invalid_fields'])

    def test_run_endpoint_returns_json_error_on_pipeline_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/run', data=json.dumps({'mode': 'sync'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with mock.patch.object(server_module.AVM_PIPELINE, 'run', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_PIPELINE_RUN_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_analysis_pipeline_run_alias_returns_json_error_on_pipeline_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/pipeline/run', data=json.dumps({'mode': 'sync'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with mock.patch.object(server_module.AVM_PIPELINE, 'run', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_PIPELINE_RUN_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_drift_status_endpoint(self):
        (status, payload) = self._get_json('/api/avm/drift_status?window_days=30')
        self.assertEqual(status, 200)
        self.assertEqual(payload['window_days'], 30)
        self.assertIn('feature_metrics', payload)
        self.assertIn('alerts', payload)

    def test_drift_status_endpoint_defaults_invalid_numeric_query_params(self):
        mocked_output = {'window_days': 30, 'feature_metrics': [], 'alerts': []}
        with mock.patch('tools.check_feature_drift.generate_drift_report', return_value=mocked_output) as mocked_report:
            (status, payload) = self._get_json('/api/avm/drift_status?window_days=bad')
        self.assertEqual(status, 200)
        self.assertEqual(payload['window_days'], 30)
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs['window_days'], 30)

    def test_drift_status_endpoint_clamps_negative_numeric_query_params(self):
        mocked_output = {'window_days': 30, 'feature_metrics': [], 'alerts': []}
        with mock.patch('tools.check_feature_drift.generate_drift_report', return_value=mocked_output) as mocked_report:
            (status, payload) = self._get_json('/api/avm/drift_status?window_days=-1')
        self.assertEqual(status, 200)
        self.assertEqual(payload['window_days'], 30)
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs['window_days'], 30)

    def test_drift_status_endpoint_returns_json_error_on_failure(self):
        with mock.patch('tools.check_feature_drift.generate_drift_report', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/drift_status?window_days=30')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DRIFT_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_analysis_drift_status_alias_endpoint(self):
        (status, payload) = self._get_json('/api/analysis/drift_status?window_days=30')
        self.assertEqual(status, 200)
        self.assertEqual(payload['window_days'], 30)
        self.assertIn('feature_metrics', payload)
        self.assertIn('alerts', payload)

    def test_analysis_drift_status_alias_defaults_invalid_numeric_query_params(self):
        mocked_output = {'window_days': 30, 'feature_metrics': [], 'alerts': []}
        with mock.patch('tools.check_feature_drift.generate_drift_report', return_value=mocked_output) as mocked_report:
            (status, payload) = self._get_json('/api/analysis/drift_status?window_days=bad')
        self.assertEqual(status, 200)
        self.assertEqual(payload['window_days'], 30)
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs['window_days'], 30)

    def test_analysis_drift_status_alias_clamps_negative_numeric_query_params(self):
        mocked_output = {'window_days': 30, 'feature_metrics': [], 'alerts': []}
        with mock.patch('tools.check_feature_drift.generate_drift_report', return_value=mocked_output) as mocked_report:
            (status, payload) = self._get_json('/api/analysis/drift_status?window_days=-1')
        self.assertEqual(status, 200)
        self.assertEqual(payload['window_days'], 30)
        mocked_report.assert_called_once()
        self.assertEqual(mocked_report.call_args.kwargs['window_days'], 30)

    def test_analysis_drift_status_alias_returns_json_error_on_failure(self):
        with mock.patch('tools.check_feature_drift.generate_drift_report', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/analysis/drift_status?window_days=30')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DRIFT_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_pipeline_status_endpoint(self):
        expected_state = {'running': False, 'started_at': None, 'finished_at': None, 'last_error': None, 'last_result': {'status': 'completed'}, 'config': {'data_dir': self.data_dir}, 'merge_check': {'is_fully_merged': True}}
        with mock.patch.object(server_module.AVM_PIPELINE, 'status', return_value=expected_state) as mocked_status:
            (status, payload) = self._get_json('/api/avm/pipeline_status')
        self.assertEqual(status, 200)
        self.assertEqual(payload, expected_state)
        mocked_status.assert_called_once()

    def test_pipeline_status_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module.AVM_PIPELINE, 'status', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/pipeline_status')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_PIPELINE_STATUS_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_merge_check_endpoint(self):
        expected_merge = {'expected_subtasks': ['build_canonical_dataset', 'build_avm_features', 'generate_avm_alerts', 'evaluate_avm', 'suggest_calibration_targets', 'generate_release_gate_report'], 'observed_subtasks': ['build_canonical_dataset', 'build_avm_features', 'generate_avm_alerts', 'evaluate_avm', 'suggest_calibration_targets', 'generate_release_gate_report'], 'missing_subtasks': [], 'unexpected_subtasks': [], 'is_fully_merged': True}
        with mock.patch.object(server_module.AVM_PIPELINE, 'verify_merge_completeness', return_value=expected_merge) as mocked_merge:
            (status, payload) = self._get_json('/api/avm/merge_check')
        self.assertEqual(status, 200)
        self.assertEqual(payload, expected_merge)
        mocked_merge.assert_called_once()

__all__ = ["AVMHttpContractPart03"]
