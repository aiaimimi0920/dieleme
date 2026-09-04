from __future__ import annotations

from tools.test.avm_http_contract_context import *  # noqa: F401,F403


class AVMHttpContractPart08:
    def test_manual_review_receipts_sync_mode_returns_json_error_on_finalize_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'sync'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with mock.patch.object(server_module, 'run_recent_enrich_maintenance', return_value={'generated_at': 'x'}), mock.patch.object(server_module, 'append_manual_review_receipt_operation', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_RECEIPT_SYNC_FINALIZE_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_analysis_manual_review_receipts_reject_invalid_mode(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'later'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_INVALID_RECEIPT_MODE')

    def test_analysis_manual_review_receipts_endpoint_returns_json_error_on_upsert_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'sync'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with mock.patch.object(server_module, 'upsert_manual_review_receipt', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_RECEIPT_UPSERT_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_analysis_manual_review_receipts_endpoint_returns_json_error_on_async_enqueue_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'async'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        fake_manager = mock.Mock()
        fake_manager.enqueue.side_effect = RuntimeError('boom')
        with mock.patch.object(server_module, '_get_manual_review_maintenance_manager', return_value=fake_manager):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_RECEIPT_ENQUEUE_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_analysis_manual_review_receipts_sync_mode_returns_json_error_on_finalize_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'sync'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with mock.patch.object(server_module, 'run_recent_enrich_maintenance', return_value={'generated_at': 'x'}), mock.patch.object(server_module, 'append_manual_review_receipt_operation', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_RECEIPT_SYNC_FINALIZE_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_manual_review_receipts_delete_rejects_missing_action(self):
        for path in ('/api/avm/manual_review_receipts', '/api/analysis/manual_review_receipts'):
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=json.dumps({'ready_signal': 'location_artifacts_complete'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='DELETE')
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode('utf-8'))
                self.assertEqual(body['error']['code'], 'AVM_INVALID_RECEIPT_ACTION')

    def test_manual_review_receipts_delete_rejects_missing_ready_signal(self):
        for path in ('/api/avm/manual_review_receipts', '/api/analysis/manual_review_receipts'):
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=json.dumps({'action': 'manual_location_review'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='DELETE')
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req)
                self.assertEqual(ctx.exception.code, 400)
                body = json.loads(ctx.exception.read().decode('utf-8'))
                self.assertEqual(body['error']['code'], 'AVM_INVALID_RECEIPT_SIGNAL')

    def test_manual_review_receipts_require_control_plane_token_when_configured(self):
        with mock.patch.dict(os.environ, {'FAPAI_CONTROL_PLANE_TOKEN': 'secret'}), mock.patch.object(server_module, 'run_recent_enrich_maintenance', return_value={'generated_at': 'x'}):
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'async'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 403)
            body = json.loads(ctx.exception.read().decode('utf-8'))
            self.assertEqual(body['error']['code'], 'AVM_CONTROL_PLANE_FORBIDDEN')
            (status, payload) = self._post_json('/api/avm/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'async'}, headers={'X-FAPAI-Control-Token': 'secret'})
            self.assertEqual(status, 200)
            self.assertEqual(payload['status'], 'ok')
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='DELETE')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 403)
            body = json.loads(ctx.exception.read().decode('utf-8'))
            self.assertEqual(body['error']['code'], 'AVM_CONTROL_PLANE_FORBIDDEN')

    def test_manual_review_receipts_delete_returns_json_error_on_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/avm/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='DELETE')
        with mock.patch.object(server_module, 'delete_manual_review_receipt', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_RECEIPT_DELETE_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_analysis_manual_review_receipts_require_control_plane_token_when_configured(self):
        with mock.patch.dict(os.environ, {'FAPAI_CONTROL_PLANE_TOKEN': 'secret'}), mock.patch.object(server_module, 'run_recent_enrich_maintenance', return_value={'generated_at': 'x'}):
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'async'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 403)
            body = json.loads(ctx.exception.read().decode('utf-8'))
            self.assertEqual(body['error']['code'], 'AVM_CONTROL_PLANE_FORBIDDEN')
            (status, payload) = self._post_json('/api/analysis/manual_review_receipts', {'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete', 'status': 'ready_for_reentry', 'payload': {'full_address': 'A'}, 'mode': 'async'}, headers={'X-FAPAI-Control-Token': 'secret'})
            self.assertEqual(status, 200)
            self.assertEqual(payload['status'], 'ok')
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='DELETE')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 403)
            body = json.loads(ctx.exception.read().decode('utf-8'))
            self.assertEqual(body['error']['code'], 'AVM_CONTROL_PLANE_FORBIDDEN')

    def test_analysis_manual_review_receipts_delete_returns_json_error_on_failure(self):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/analysis/manual_review_receipts', data=json.dumps({'action': 'manual_location_review', 'ready_signal': 'location_artifacts_complete'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='DELETE')
        with mock.patch.object(server_module, 'delete_manual_review_receipt', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_MANUAL_REVIEW_RECEIPT_DELETE_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_collection_detail_fetch_endpoint(self):
        fake_service = mock.Mock()
        fake_service.fetch_missing_archives.return_value = {'candidate_count': 2, 'fetched_count': 1, 'failed_count': 0, 'blocked_count': 1, 'dry_run': True}
        with mock.patch.object(server_module, '_detail_collection_service', return_value=fake_service):
            (status, payload) = self._post_json('/api/collection/details/fetch_missing', {'limit': 1, 'timeout': 9, 'dry_run': True, 'extract_risk': False})
        self.assertEqual(status, 200)
        self.assertEqual(payload['candidate_count'], 2)
        self.assertEqual(payload['blocked_count'], 1)
        fake_service.fetch_missing_archives.assert_called_once()

    def test_collection_detail_next_task_alias_endpoint(self):
        with mock.patch.object(server_module, '_prefer_db_task_reads', return_value=True), mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_task.return_value = {'url': 'https://x/detail-task'}
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/collection/details/next_task')
        self.assertEqual(status, 200)
        self.assertEqual(payload['url'], 'https://x/detail-task')
        fake_service.next_task.assert_called_once()

    def test_collection_detail_next_task_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_prefer_db_task_reads', return_value=True), mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_task.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/collection/details/next_task')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_NEXT_TASK_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_collection_detail_next_task_alias_returns_empty_object_when_no_task_available(self):
        with mock.patch.object(server_module, '_prefer_db_task_reads', return_value=True), mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_task.return_value = None
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/collection/details/next_task')
        self.assertEqual(status, 200)
        self.assertEqual(payload, {})
        fake_service.next_task.assert_called_once()

    def test_collection_detail_next_task_legacy_endpoint(self):
        with mock.patch.object(server_module, '_prefer_db_task_reads', return_value=True), mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_task.return_value = {'url': 'https://x/detail-task'}
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/next_task')
        self.assertEqual(status, 200)
        self.assertEqual(payload['url'], 'https://x/detail-task')
        fake_service.next_task.assert_called_once()

    def test_collection_detail_next_task_legacy_endpoint_returns_empty_object_when_no_task_available(self):
        with mock.patch.object(server_module, '_prefer_db_task_reads', return_value=True), mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.next_task.return_value = None
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/next_task')
        self.assertEqual(status, 200)
        self.assertEqual(payload, {})
        fake_service.next_task.assert_called_once()

    def test_collection_detail_tasks_alias_endpoint(self):
        with mock.patch.object(server_module, '_prefer_db_task_reads', return_value=True), mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.batch_tasks.return_value = {'tasks': [{'id': 'x-1', 'url': 'https://x/detail-1'}], 'total': 10, 'done': 5, 'pending': 5}
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/collection/details/tasks')
        self.assertEqual(status, 200)
        self.assertEqual(payload['tasks'][0]['id'], 'x-1')
        self.assertEqual(payload['total'], 10)
        fake_service.batch_tasks.assert_called_once()

    def test_collection_detail_tasks_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_prefer_db_task_reads', return_value=True), mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.batch_tasks.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/collection/details/tasks')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_BATCH_TASKS_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_collection_detail_tasks_alias_returns_empty_tasks_when_paused(self):
        original_paused = server_module.PAUSED
        server_module.PAUSED = True
        try:
            (status, payload) = self._get_json('/api/collection/details/tasks')
        finally:
            server_module.PAUSED = original_paused
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'tasks': []})

    def test_collection_detail_tasks_alias_returns_empty_tasks_when_force_unlock_flag_exists(self):
        original_paused = server_module.PAUSED
        original_data_dir = server_module.DATA_DIR
        server_module.PAUSED = False
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, 'force_unlock.flag')
        with open(flag_path, 'w', encoding='utf-8') as f:
            f.write('manual verification required')
        try:
            (status, payload) = self._get_json('/api/collection/details/tasks')
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.PAUSED = original_paused
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'tasks': []})

    def test_get_tasks_legacy_endpoint_returns_empty_tasks_when_paused(self):
        original_paused = server_module.PAUSED
        server_module.PAUSED = True
        try:
            (status, payload) = self._get_json('/api/get_tasks')
        finally:
            server_module.PAUSED = original_paused
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'tasks': []})

    def test_get_tasks_legacy_endpoint_returns_empty_tasks_when_force_unlock_flag_exists(self):
        original_paused = server_module.PAUSED
        original_data_dir = server_module.DATA_DIR
        server_module.PAUSED = False
        server_module.DATA_DIR = self.data_dir
        flag_path = os.path.join(self.data_dir, 'force_unlock.flag')
        with open(flag_path, 'w', encoding='utf-8') as f:
            f.write('manual verification required')
        try:
            (status, payload) = self._get_json('/api/get_tasks')
        finally:
            server_module.DATA_DIR = original_data_dir
            server_module.PAUSED = original_paused
        self.assertEqual(status, 200)
        self.assertEqual(payload, {'tasks': []})

    def test_collection_detail_update_and_area_aliases(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {'status': 'ok'}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_json('/api/collection/details/update_item', {'id': '3001', 'status': 'done'})
            self.assertEqual(status, 200)
            self.assertEqual(payload['status'], 'updated')
            (status, payload) = self._post_json('/api/collection/details/area_result', {'id': '3001', '建筑面积': 88.8})
            self.assertEqual(status, 200)
            self.assertEqual(payload['status'], 'ok')
            (status, payload) = self._post_json('/api/collection/details/approve_area', {'id': '3001', '建筑面积': 88.8})
            self.assertEqual(status, 200)
            self.assertEqual(payload['status'], 'ok')
        self.assertEqual(fake_service.apply_working_item_patch.call_count, 3)

    def test_collection_detail_update_item_alias_returns_id_not_found_for_missing_item(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {'status': 'id_not_found'}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_json('/api/collection/details/update_item', {'id': 'missing', 'status': 'done'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'id_not_found')
        fake_service.apply_working_item_patch.assert_called_once()

    def test_collection_detail_area_result_alias_returns_404_for_missing_item(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {'status': 'id_not_found'}
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/details/area_result', data=json.dumps({'id': 'missing', '建筑面积': 88.8}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_ITEM_NOT_FOUND')

    def test_collection_detail_approve_area_alias_returns_404_for_missing_item(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {'status': 'id_not_found'}
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/details/approve_area', data=json.dumps({'id': 'missing', '建筑面积': 88.8}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_ITEM_NOT_FOUND')

    def test_collection_detail_update_and_area_legacy_routes(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {'status': 'ok'}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_json('/api/update_item', {'id': '3001', 'status': 'done'})
            self.assertEqual(status, 200)
            self.assertEqual(payload['status'], 'updated')
            (status, payload) = self._post_json('/api/area_result', {'id': '3001', '建筑面积': 88.8})
            self.assertEqual(status, 200)
            self.assertEqual(payload['status'], 'ok')
            (status, payload) = self._post_json('/api/approve_area', {'id': '3001', '建筑面积': 88.8})
            self.assertEqual(status, 200)
            self.assertEqual(payload['status'], 'ok')
        self.assertEqual(fake_service.apply_working_item_patch.call_count, 3)

    def test_update_item_legacy_endpoint_returns_id_not_found_for_missing_item(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {'status': 'id_not_found'}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_json('/api/update_item', {'id': 'missing', 'status': 'done'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'id_not_found')
        fake_service.apply_working_item_patch.assert_called_once()

    def test_collection_detail_update_item_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/details/update_item', data=json.dumps({'id': '3001', 'status': 'done'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_UPDATE_ITEM_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_update_item_legacy_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/update_item', data=json.dumps({'id': '3001', 'status': 'done'}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_UPDATE_ITEM_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_area_result_legacy_endpoint_returns_404_for_missing_item(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {'status': 'id_not_found'}
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/area_result', data=json.dumps({'id': 'missing', '建筑面积': 88.8}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_ITEM_NOT_FOUND')

    def test_approve_area_legacy_endpoint_returns_404_for_missing_item(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.return_value = {'status': 'id_not_found'}
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/approve_area', data=json.dumps({'id': 'missing', '建筑面积': 88.8}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 404)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_ITEM_NOT_FOUND')

    def test_collection_detail_area_result_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/details/area_result', data=json.dumps({'id': '3001', '建筑面积': 88.8}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_AREA_RESULT_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_area_result_legacy_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/area_result', data=json.dumps({'id': '3001', '建筑面积': 88.8}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_AREA_RESULT_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_collection_detail_approve_area_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/collection/details/approve_area', data=json.dumps({'id': '3001', '建筑面积': 88.8}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_APPROVE_AREA_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_approve_area_legacy_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.apply_working_item_patch.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/approve_area', data=json.dumps({'id': '3001', '建筑面积': 88.8}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_DETAIL_APPROVE_AREA_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_collection_detail_infer_location_alias(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.infer_location.return_value = {'所属小区': '测试小区', '城市': '上海市'}
            mocked_factory.return_value = fake_service
            (status, payload) = self._post_json('/api/collection/details/infer_location', {'id': '3001', 'address': '上海市浦东新区测试路99号', 'title': '测试标题'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['所属小区'], '测试小区')
        fake_service.infer_location.assert_called_once()

__all__ = ["AVMHttpContractPart08"]
