from __future__ import annotations

from tools.test.avm_http_contract_context import *  # noqa: F401,F403


class AVMHttpContractPart05:
    def test_release_gate_endpoint_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            f.write('{')
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/avm/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_analysis_release_gate_endpoint_preserves_analysis_readiness_and_flattens_calibration_summary(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': ['district_centroid'], 'top_coordinate_strategy_group': 'district_centroid', 'calibration_targets': {'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 1.05}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 1.05}], 'risk_factor_targets': [], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-global-risk', 'target_types': ['global_risk', 'temporal'], 'target_names': None}}, 'guidance': {'status': 'fix_coordinate_quality', 'priority': 'high', 'recommended_actions': ['review_coordinate_strategy_cohorts'], 'top_reason': 'district_centroid'}}}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}, 'analysis_readiness': {'recommended_actions': ['operator_review'], 'manual_review_receipt_summary': {'receipt_count': 1}, 'manual_review_receipt_jobs_summary': {'queued_count': 0}, 'manual_review_receipt_operations_summary': {'operation_count': 2}, 'manual_review_control_plane_storage': {'state_source': 'repository'}, 'manual_review_control_plane_backup': {'backup_state': 'in_sync'}, 'manual_review_control_plane_backup_repairs_summary': {'repair_count': 0}, 'operator_overview': {'handoff_lifecycle_state': 'stable'}}}
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump(gate_payload, f, ensure_ascii=False)
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['analysis_readiness']['manual_review_receipt_summary']['receipt_count'], 1)
        self.assertEqual(payload['analysis_readiness']['operator_overview']['handoff_lifecycle_state'], 'stable')
        self.assertEqual(payload['calibration_guidance']['status'], 'fix_coordinate_quality')
        self.assertEqual(payload['calibration_target_counts']['temporal'], 1)
        self.assertEqual(payload['calibration_target_counts']['global_risk'], 1)
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['top_calibration_target_hint']['playbook_id'], 'tune-temporal-decay')
        self.assertEqual(payload['recommended_bundle_risk_level'], 'medium')
        self.assertEqual(payload['recommended_bundle_next_action'], 'preview_only_first')

    def test_analysis_release_gate_endpoint_prefers_generated_report_over_stale_gate_file_for_operator_summary(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        stale_gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}, 'analysis_readiness': {'manual_review_receipt_summary': {'receipt_count': 0}, 'operator_overview': {'handoff_lifecycle_state': 'stale'}}}
        fresh_gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': ['district_centroid'], 'top_coordinate_strategy_group': 'district_centroid', 'calibration_targets': {'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 1.05}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 1.05}], 'risk_factor_targets': [], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-global-risk', 'target_types': ['global_risk', 'temporal'], 'target_names': None}}, 'guidance': {'status': 'fix_coordinate_quality', 'priority': 'high', 'recommended_actions': ['review_coordinate_strategy_cohorts'], 'top_reason': 'district_centroid'}}}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}, 'analysis_readiness': {'manual_review_receipt_summary': {'receipt_count': 1}, 'operator_overview': {'handoff_lifecycle_state': 'fresh'}}}
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump(stale_gate_payload, f, ensure_ascii=False)
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=fresh_gate_payload):
            (status, payload) = self._get_json('/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['analysis_readiness']['manual_review_receipt_summary']['receipt_count'], 1)
        self.assertEqual(payload['analysis_readiness']['operator_overview']['handoff_lifecycle_state'], 'fresh')
        self.assertEqual(payload['calibration_guidance']['status'], 'fix_coordinate_quality')
        self.assertEqual(payload['calibration_target_counts']['temporal'], 1)
        self.assertEqual(payload['calibration_target_counts']['global_risk'], 1)
        self.assertEqual(payload['recommended_bundle_risk_level'], 'medium')
        self.assertEqual(payload['recommended_bundle_next_action'], 'preview_only_first')

    def test_analysis_release_gate_endpoint_uses_embedded_calibration_targets_when_file_is_missing(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': ['district_centroid'], 'top_coordinate_strategy_group': 'district_centroid', 'calibration_targets': {'config_patch': {'weighting': {'time_decay': 0.72}}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [], 'risk_factor_targets': [], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}, 'guidance': {'status': 'tune_temporal_decay', 'priority': 'medium', 'recommended_actions': ['adjust_weighting_time_decay'], 'top_reason': 'time_decay'}}}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}, 'analysis_readiness': {'manual_review_receipt_summary': {'receipt_count': 1}, 'operator_overview': {'handoff_lifecycle_state': 'fresh'}}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['analysis_readiness']['manual_review_receipt_summary']['receipt_count'], 1)
        self.assertEqual(payload['calibration_guidance']['status'], 'tune_temporal_decay')
        self.assertEqual(payload['calibration_target_counts']['temporal'], 1)
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['recommended_bundle_risk_level'], 'low')
        self.assertEqual(payload['recommended_bundle_next_action'], 'safe_to_write_then_verify')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['write', 'verify', 'gate'])

    def test_analysis_release_gate_endpoint_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [], 'risk_factor_targets': [], 'strategy_targets': [], 'config_patch': {'weighting': {'time_decay': 0.72}}, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'runbook_refs': ['tools/evaluate_avm.py'], 'recommended_actions': ['adjust_weighting_time_decay'], 'suggested_commands': ['python tools/evaluate_avm.py'], 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}, 'guidance': {'status': 'tune_temporal_decay', 'priority': 'medium', 'recommended_actions': ['adjust_weighting_time_decay'], 'top_reason': 'time_decay'}}, f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}, 'analysis_readiness': {'manual_review_receipt_summary': {'receipt_count': 1}, 'operator_overview': {'handoff_lifecycle_state': 'fresh'}}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['analysis_readiness']['manual_review_receipt_summary']['receipt_count'], 1)
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')
        self.assertEqual(payload['recommended_bundle_verify_command'], 'python tools/evaluate_avm.py')
        self.assertEqual(payload['recommended_bundle_gate_command'], 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report')
        self.assertEqual(payload['recommended_bundle_next_action'], 'safe_to_write_then_verify')
        self.assertEqual(payload['recommended_bundle_next_action_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')
        self.assertEqual(payload['recommended_bundle_follow_up_command'], 'python tools/evaluate_avm.py')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'verify')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['write', 'verify', 'gate'])

    def test_analysis_release_gate_endpoint_normalizes_malformed_calibration_target_lists(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': {'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}, 'global_risk_targets': {}, 'risk_factor_targets': 'bad-shape', 'strategy_targets': None, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}}, f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}, 'analysis_readiness': {'manual_review_receipt_summary': {'receipt_count': 1}, 'operator_overview': {'handoff_lifecycle_state': 'fresh'}}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['analysis_readiness']['manual_review_receipt_summary']['receipt_count'], 1)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')

    def test_analysis_release_gate_endpoint_merges_partial_embedded_calibration_targets_with_file_context(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {'is_occupied': 0.8}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 0.99, 'risk_factor_overrides': {'is_occupied': 0.5}}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 0.99}], 'risk_factor_targets': [{'target_type': 'risk_flag', 'name': 'is_occupied', 'suggested_next_factor': 0.5}], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}, 'top_calibration_target_hint': {'status': 'tune_risk_factors', 'playbook_id': 'split-bundle-or-single-target-first', 'recommended_bundle': {'bundle_id': 'temporal-global-risk-risk-flag', 'target_types': ['temporal', 'global_risk', 'risk_flag'], 'target_names': ['time_decay', 'risk_discount_factor', 'is_occupied']}, 'suggested_bundle_commands': ['python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied', 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write', 'python tools/evaluate_avm.py', 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report']}, 'guidance': {'status': 'tune_risk_factors', 'priority': 'high', 'recommended_actions': ['split_bundle_or_single_target_first'], 'top_reason': 'multi_flag_bundle'}}, f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': [], 'calibration_targets': {'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}}}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}, 'analysis_readiness': {'manual_review_receipt_summary': {'receipt_count': 1}, 'operator_overview': {'handoff_lifecycle_state': 'fresh'}}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['analysis_readiness']['manual_review_receipt_summary']['receipt_count'], 1)
        self.assertEqual(payload['recommended_bundle_risk_level'], 'high')
        self.assertEqual(payload['recommended_bundle_next_action'], 'split_bundle_or_single_target_first')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'none')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['preview'])

    def test_analysis_release_gate_endpoint_tolerates_non_object_calibration_targets_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}, 'analysis_readiness': {'manual_review_receipt_summary': {'receipt_count': 1}, 'operator_overview': {'handoff_lifecycle_state': 'fresh'}}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['analysis_readiness']['manual_review_receipt_summary']['receipt_count'], 1)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_analysis_release_gate_endpoint_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}, 'analysis_readiness': {'manual_review_receipt_summary': {'receipt_count': 1}, 'operator_overview': {'handoff_lifecycle_state': 'fresh'}}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['analysis_readiness']['manual_review_receipt_summary']['receipt_count'], 1)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_analysis_release_gate_endpoint_tolerates_invalid_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': [], 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}, 'analysis_readiness': {'manual_review_receipt_summary': {'receipt_count': 1}, 'operator_overview': {'handoff_lifecycle_state': 'fresh'}}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['analysis_readiness']['manual_review_receipt_summary']['receipt_count'], 1)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_analysis_release_gate_endpoint_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            f.write('{')
        gate_payload = {'pass': False, 'evaluation': {'pass': False, 'coordinate_strategy_watchlist': []}, 'completeness': {'pass': True}, 'drift': {'pass': True}, 'api_smoke': {'skipped': True}, 'analysis_readiness': {'manual_review_receipt_summary': {'receipt_count': 1}, 'operator_overview': {'handoff_lifecycle_state': 'fresh'}}}
        with mock.patch('tools.avm_release_gate.generate_release_gate_report', return_value=gate_payload):
            (status, payload) = self._get_json('/api/analysis/release_gate?window_days=7&min_sample_size=1&smoke_sample_size=0')
        self.assertEqual(status, 200)
        self.assertEqual(payload['analysis_readiness']['manual_review_receipt_summary']['receipt_count'], 1)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_health_endpoint_surfaces_risk_validation_summary(self):
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertIn('risk_validation_counts', payload)
        self.assertIn('risk_feature_completeness_avg', payload)
        self.assertIn('active_weighting', payload)
        self.assertIn('active_risk_discount_factor', payload)
        self.assertIn('active_risk_factor_override_count', payload)
        self.assertIn('active_risk_factor_overrides', payload)
        self.assertIn('coordinate_strategy_counts', payload)
        self.assertIn('calibration_guidance', payload)
        self.assertIn('calibration_target_counts', payload)
        self.assertIn('top_calibration_target', payload)
        self.assertIn('top_calibration_target_hint', payload)
        self.assertIn('calibration_patch_preview', payload)
        self.assertIn('top_calibration_patch_preview', payload)
        self.assertIn('recommended_bundle_patch_preview', payload)
        self.assertIn('recommended_bundle_risk_level', payload)
        self.assertIn('recommended_bundle_risk_reasons', payload)
        self.assertIn('recommended_bundle_next_action', payload)
        self.assertIn('recommended_bundle_next_action_reasons', payload)
        self.assertIn('recommended_bundle_next_action_command', payload)
        self.assertIn('recommended_bundle_next_action_command_kind', payload)
        self.assertIn('recommended_bundle_follow_up_command', payload)
        self.assertIn('recommended_bundle_follow_up_command_kind', payload)
        self.assertIn('recommended_bundle_command_chain', payload)
        self.assertIn('coordinate_strategy_watchlist', payload)

    def test_health_endpoint_surfaces_calibration_guidance_and_coordinate_watchlist(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'risk_factor_targets': [{'target_type': 'risk_flag', 'name': 'is_occupied', 'suggested_next_factor': 0.5}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 1.05}], 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'strategy_targets': [], 'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 1.05, 'risk_factor_overrides': {'is_occupied': 0.5}}, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'runbook_refs': ['tools/evaluate_avm.py'], 'recommended_actions': ['adjust_weighting_time_decay'], 'suggested_commands': ['python tools/evaluate_avm.py'], 'suggested_bundle_commands': ['python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal'], 'recommended_bundle': {'bundle_id': 'temporal-global-risk', 'target_types': ['global_risk', 'temporal'], 'target_names': None}}, 'guidance': {'status': 'fix_coordinate_quality', 'priority': 'high', 'recommended_actions': ['review_coordinate_strategy_cohorts'], 'top_reason': 'district_centroid'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {'top_coordinate_strategy_group': 'district_centroid', 'coordinate_strategy_watchlist': ['district_centroid']}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'fix_coordinate_quality')
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['top_calibration_target_hint']['target_name'], 'time_decay')
        self.assertEqual(payload['top_calibration_target_hint']['playbook_id'], 'tune-temporal-decay')
        self.assertIn('tools/evaluate_avm.py', payload['top_calibration_target_hint']['runbook_refs'])
        self.assertIn('python tools/evaluate_avm.py', payload['top_calibration_target_hint']['suggested_commands'])
        self.assertIn('python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal', payload['top_calibration_target_hint']['suggested_bundle_commands'])
        self.assertTrue(payload['calibration_patch_preview']['patch_ready'])
        self.assertIn('weighting.time_decay', payload['calibration_patch_preview']['changed_keys'])
        self.assertIn('risk_discount_factor', payload['calibration_patch_preview']['changed_keys'])
        self.assertEqual(payload['calibration_patch_preview']['changed_paths']['weighting.time_decay']['before'], 0.85)
        self.assertEqual(payload['calibration_patch_preview']['changed_paths']['weighting.time_decay']['after'], 0.72)
        self.assertEqual(payload['calibration_patch_preview']['rollback_patch']['weighting']['time_decay'], 0.85)
        self.assertEqual(payload['calibration_target_counts']['temporal'], 1)
        self.assertEqual(payload['calibration_target_counts']['global_risk'], 1)
        self.assertEqual(payload['top_calibration_patch_preview']['applied_filter'], {'target_type': 'temporal', 'target_name': 'time_decay'})
        self.assertEqual(payload['top_calibration_patch_preview']['changed_keys'], ['weighting.time_decay'])
        self.assertEqual(payload['top_calibration_patch_preview']['matched_targets'], [{'target_type': 'temporal', 'target_name': 'time_decay'}])
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write')
        self.assertEqual(payload['recommended_bundle_verify_command'], 'python tools/evaluate_avm.py')
        self.assertEqual(payload['recommended_bundle_gate_command'], 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report')
        self.assertEqual(payload['recommended_bundle_patch_preview']['bundle_id'], 'temporal-global-risk')
        self.assertEqual(payload['recommended_bundle_patch_preview']['applied_filter'], {'target_types': ['global_risk', 'temporal'], 'target_names': None})
        self.assertEqual(payload['recommended_bundle_patch_preview']['changed_keys'], ['risk_discount_factor', 'weighting.time_decay'])
        self.assertEqual(payload['recommended_bundle_risk_level'], 'medium')
        self.assertIn('multiple_changed_keys', payload['recommended_bundle_risk_reasons'])
        self.assertEqual(payload['recommended_bundle_next_action'], 'preview_only_first')
        self.assertIn('medium_risk_bundle', payload['recommended_bundle_next_action_reasons'])
        self.assertEqual(payload['recommended_bundle_next_action_command'], 'python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal')
        self.assertEqual(payload['recommended_bundle_next_action_command_kind'], 'preview')
        self.assertEqual(payload['recommended_bundle_follow_up_command'], 'python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'write')
        command_chain = payload['recommended_bundle_command_chain']
        self.assertEqual([item['kind'] for item in command_chain], ['preview', 'write', 'verify', 'gate'])
        (preview_step, write_step, verify_step, gate_step) = command_chain
        self.assertEqual(preview_step['step_ready_action_command'], payload['recommended_bundle_preview_command'])
        self.assertEqual(preview_step['step_ready_follow_up_command'], payload['recommended_bundle_write_command'])
        self.assertEqual(preview_step['step_ready_stage_span'], 'write_then_evaluate')
        self.assertEqual(preview_step['artifact_state_reason'], 'config_not_written_yet')
        self.assertEqual(write_step['step_ready_action_command'], payload['recommended_bundle_write_command'])
        self.assertEqual(write_step['step_ready_follow_up_command'], payload['recommended_bundle_verify_command'])
        self.assertEqual(write_step['step_ready_stage_span'], 'write_then_evaluate')
        self.assertEqual(verify_step['step_ready_action_command'], payload['recommended_bundle_verify_command'])
        self.assertEqual(verify_step['step_ready_follow_up_command'], payload['recommended_bundle_gate_command'])
        self.assertEqual(verify_step['step_ready_stage_span'], 'evaluate_then_gate')
        self.assertEqual(verify_step['artifact_state_reason'], 'eval_not_rerun_yet')
        self.assertEqual(gate_step['step_ready_action_command'], payload['recommended_bundle_gate_command'])
        self.assertEqual(gate_step['step_ready_stage_span'], 'gate_only')
        self.assertEqual(gate_step['artifact_state_reason'], 'pre_bundle_gate_report')
        self.assertEqual(payload['coordinate_strategy_watchlist'], ['district_centroid'])
        self.assertEqual(payload['top_coordinate_strategy_group'], 'district_centroid')

    def test_recent_gap_audit_endpoint(self):
        (status, payload) = self._get_json('/api/avm/recent_gap_audit?window_days=7&sample_limit=5')
        self.assertEqual(status, 200)
        self.assertIn('record_count', payload)
        self.assertIn('missing_field_counts', payload)
        self.assertIn('samples', payload)

    def test_recent_gap_audit_endpoint_defaults_invalid_numeric_query_params(self):
        mocked_output = {'record_count': 0, 'missing_field_counts': {}, 'samples': []}
        with mock.patch('tools.audit_recent_avm_gaps.build_recent_gap_audit', return_value=mocked_output) as mocked_audit:
            (status, payload) = self._get_json('/api/avm/recent_gap_audit?window_days=bad&sample_limit=bad')
        self.assertEqual(status, 200)
        self.assertEqual(payload['record_count'], 0)
        mocked_audit.assert_called_once()
        self.assertEqual(mocked_audit.call_args.kwargs['window_days'], 7)
        self.assertEqual(mocked_audit.call_args.kwargs['sample_limit'], 20)

    def test_recent_gap_audit_endpoint_clamps_negative_numeric_query_params(self):
        mocked_output = {'record_count': 0, 'missing_field_counts': {}, 'samples': []}
        with mock.patch('tools.audit_recent_avm_gaps.build_recent_gap_audit', return_value=mocked_output) as mocked_audit:
            (status, payload) = self._get_json('/api/avm/recent_gap_audit?window_days=-1&sample_limit=-1')
        self.assertEqual(status, 200)
        self.assertEqual(payload['record_count'], 0)
        mocked_audit.assert_called_once()
        self.assertEqual(mocked_audit.call_args.kwargs['window_days'], 7)
        self.assertEqual(mocked_audit.call_args.kwargs['sample_limit'], 20)

    def test_recent_gap_audit_endpoint_returns_json_error_on_failure(self):
        with mock.patch('tools.audit_recent_avm_gaps.build_recent_gap_audit', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/recent_gap_audit?window_days=7&sample_limit=5')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_RECENT_GAP_AUDIT_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_recent_detail_replay_endpoint(self):
        archive_dir = os.path.join(self.data_dir, 'archive', '2026')
        os.makedirs(archive_dir, exist_ok=True)
        recent_file = os.path.join(archive_dir, '2026-03-05.json')
        with open(recent_file, 'w', encoding='utf-8') as f:
            json.dump([{'id': 9101, '交易时间': '2026-03-05 10:00:00', '成交价格': '100万', '起拍价格': '80万', '建筑面积': '100㎡', 'detail_captured': True, '原始网站': 'https://sf-item.taobao.com/sf_item/9101.htm'}], f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/avm/recent_detail_replay?window_days=7&limit=10&dry_run=false')
        self.assertEqual(status, 200)
        self.assertEqual(payload['prepared_count'], 1)
        with open(recent_file, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        self.assertEqual(saved[0]['url'], 'https://sf-item.taobao.com/sf_item/9101.htm')
        self.assertFalse(saved[0]['is_processed'])

    def test_recent_detail_replay_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/recent_detail_replay?window_days=7&limit=10&dry_run=true')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_RECENT_DETAIL_REPLAY_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_recent_detail_replay_get_endpoint_defaults_invalid_numeric_query_params(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {'window_days': 7, 'limit': 100, 'dry_run': True, 'prepared_count': 0}
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/avm/recent_detail_replay?window_days=bad&limit=bad&dry_run=maybe')
        self.assertEqual(status, 200)
        self.assertEqual(payload['window_days'], 7)
        self.assertEqual(payload['limit'], 100)
        fake_service.prepare_replay.assert_called_once_with(window_days=7, limit=100, dry_run=True)

    def test_recent_detail_replay_get_endpoint_clamps_negative_query_params(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {'window_days': 7, 'limit': 0, 'dry_run': True, 'prepared_count': 0}
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/avm/recent_detail_replay?window_days=-1&limit=-1&dry_run=maybe')
        self.assertEqual(status, 200)
        self.assertEqual(payload['window_days'], 7)
        self.assertEqual(payload['limit'], 0)
        fake_service.prepare_replay.assert_called_once_with(window_days=7, limit=0, dry_run=True)

    def test_collection_detail_prepare_replay_get_alias_endpoint(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {'window_days': 7, 'limit': 10, 'dry_run': True, 'prepared_count': 1}
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/collection/details/prepare_replay?window_days=7&limit=10&dry_run=true')
        self.assertEqual(status, 200)
        self.assertEqual(payload['prepared_count'], 1)
        fake_service.prepare_replay.assert_called_once_with(window_days=7, limit=10, dry_run=True)

    def test_collection_detail_prepare_replay_get_alias_defaults_invalid_numeric_query_params(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {'window_days': 7, 'limit': 100, 'dry_run': True, 'prepared_count': 0}
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/collection/details/prepare_replay?window_days=bad&limit=bad&dry_run=maybe')
        self.assertEqual(status, 200)
        self.assertEqual(payload['window_days'], 7)
        self.assertEqual(payload['limit'], 100)
        fake_service.prepare_replay.assert_called_once_with(window_days=7, limit=100, dry_run=True)

    def test_collection_detail_prepare_replay_get_alias_clamps_negative_query_params(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {'window_days': 7, 'limit': 0, 'dry_run': True, 'prepared_count': 0}
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/collection/details/prepare_replay?window_days=-1&limit=-1&dry_run=maybe')
        self.assertEqual(status, 200)
        self.assertEqual(payload['window_days'], 7)
        self.assertEqual(payload['limit'], 0)
        fake_service.prepare_replay.assert_called_once_with(window_days=7, limit=0, dry_run=True)

    def test_collection_detail_prepare_replay_get_alias_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/collection/details/prepare_replay?window_days=7&limit=10&dry_run=true')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_RECENT_DETAIL_REPLAY_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_archive_detail_replay_get_endpoint(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {'window_days': 30, 'limit': 11, 'dry_run': True, 'prepared_count': 2}
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/avm/archive_detail_replay?window_days=30&limit=11&dry_run=true')
        self.assertEqual(status, 200)
        self.assertEqual(payload['prepared_count'], 2)
        fake_service.prepare_replay.assert_called_once_with(window_days=30, limit=11, dry_run=True)

    def test_archive_detail_replay_get_endpoint_returns_json_error_on_failure(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.side_effect = RuntimeError('boom')
            mocked_factory.return_value = fake_service
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/avm/archive_detail_replay?window_days=30&limit=11&dry_run=true')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_ARCHIVE_DETAIL_REPLAY_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_archive_detail_replay_get_endpoint_defaults_invalid_numeric_query_params(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {'window_days': 30, 'limit': 500, 'dry_run': True, 'prepared_count': 0}
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/avm/archive_detail_replay?window_days=bad&limit=bad&dry_run=maybe')
        self.assertEqual(status, 200)
        self.assertEqual(payload['window_days'], 30)
        self.assertEqual(payload['limit'], 500)
        fake_service.prepare_replay.assert_called_once_with(window_days=30, limit=500, dry_run=True)

    def test_archive_detail_replay_get_endpoint_clamps_negative_query_params(self):
        with mock.patch.object(server_module, '_detail_collection_service') as mocked_factory:
            fake_service = mock.Mock()
            fake_service.prepare_replay.return_value = {'window_days': 30, 'limit': 0, 'dry_run': True, 'prepared_count': 0}
            mocked_factory.return_value = fake_service
            (status, payload) = self._get_json('/api/avm/archive_detail_replay?window_days=-1&limit=-1&dry_run=maybe')
        self.assertEqual(status, 200)
        self.assertEqual(payload['window_days'], 30)
        self.assertEqual(payload['limit'], 0)
        fake_service.prepare_replay.assert_called_once_with(window_days=30, limit=0, dry_run=True)

__all__ = ["AVMHttpContractPart05"]
