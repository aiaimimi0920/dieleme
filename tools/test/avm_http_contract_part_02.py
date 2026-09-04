from __future__ import annotations

from tools.test.avm_http_contract_context import *  # noqa: F401,F403


class AVMHttpContractPart02:
    def test_analysis_health_alias_surfaces_calibration_guidance_and_coordinate_watchlist(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'risk_factor_targets': [{'target_type': 'risk_flag', 'name': 'is_occupied', 'suggested_next_factor': 0.5}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 1.05}], 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'strategy_targets': [], 'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 1.05, 'risk_factor_overrides': {'is_occupied': 0.5}}, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'runbook_refs': ['tools/evaluate_avm.py'], 'recommended_actions': ['adjust_weighting_time_decay'], 'suggested_commands': ['python tools/evaluate_avm.py'], 'suggested_bundle_commands': ['python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal'], 'recommended_bundle': {'bundle_id': 'temporal-global-risk', 'target_types': ['global_risk', 'temporal'], 'target_names': None}}, 'guidance': {'status': 'fix_coordinate_quality', 'priority': 'high', 'recommended_actions': ['review_coordinate_strategy_cohorts'], 'top_reason': 'district_centroid'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {'top_coordinate_strategy_group': 'district_centroid', 'coordinate_strategy_watchlist': ['district_centroid']}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'fix_coordinate_quality')
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['top_calibration_target_hint']['target_name'], 'time_decay')
        self.assertEqual(payload['top_calibration_target_hint']['playbook_id'], 'tune-temporal-decay')
        self.assertIn('tools/evaluate_avm.py', payload['top_calibration_target_hint']['runbook_refs'])
        self.assertIn('python tools/evaluate_avm.py', payload['top_calibration_target_hint']['suggested_commands'])
        self.assertIn('python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal', payload['top_calibration_target_hint']['suggested_bundle_commands'])
        self.assertTrue(payload['calibration_patch_preview']['patch_ready'])
        self.assertEqual(payload['calibration_patch_preview']['changed_paths']['weighting.time_decay']['after'], 0.72)
        self.assertEqual(payload['calibration_patch_preview']['rollback_patch']['weighting']['time_decay'], 0.85)
        self.assertEqual(payload['calibration_target_counts']['global_risk'], 1)
        self.assertEqual(payload['top_calibration_patch_preview']['applied_filter'], {'target_type': 'temporal', 'target_name': 'time_decay'})
        self.assertEqual(payload['top_calibration_patch_preview']['changed_keys'], ['weighting.time_decay'])
        self.assertEqual(payload['recommended_bundle_patch_preview']['bundle_id'], 'temporal-global-risk')
        self.assertEqual(payload['recommended_bundle_patch_preview']['applied_filter'], {'target_types': ['global_risk', 'temporal'], 'target_names': None})
        self.assertEqual(payload['recommended_bundle_patch_preview']['changed_keys'], ['risk_discount_factor', 'weighting.time_decay'])
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write')
        self.assertEqual(payload['recommended_bundle_verify_command'], 'python tools/evaluate_avm.py')
        self.assertEqual(payload['recommended_bundle_gate_command'], 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report')
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
        self.assertEqual(payload['coordinate_strategy_watchlist'], ['district_centroid'])
        self.assertEqual(payload['top_coordinate_strategy_group'], 'district_centroid')

    def test_analysis_status_alias_endpoint(self):
        (status, payload) = self._get_json('/api/analysis/status')
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'ok')
        self.assertIn('collection_stage', payload)
        self.assertIn('operator_action_summary', payload['collection_stage'])
        self.assertIn('scheduler_feedback_summary', payload['collection_stage'])
        self.assertIn('operator_overview', payload['collection_stage'])
        self.assertIn('manual_review_backlog_summary', payload['collection_stage'])
        self.assertIn('calibration_guidance', payload)
        self.assertIn('calibration_target_counts', payload)
        self.assertIn('top_calibration_target', payload)
        self.assertIn('coordinate_strategy_watchlist', payload)

    def test_analysis_status_alias_returns_json_error_on_health_snapshot_failure(self):
        with mock.patch.object(server_module.AVM_SERVICE, 'health_snapshot', side_effect=RuntimeError('boom')):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/analysis/status')
        self.assertEqual(ctx.exception.code, 500)
        body = json.loads(ctx.exception.read().decode('utf-8'))
        self.assertEqual(body['error']['code'], 'AVM_HEALTH_FAILED')
        self.assertEqual(body['error']['details']['error'], 'boom')

    def test_analysis_status_alias_surfaces_risk_validation_summary(self):
        (status, payload) = self._get_json('/api/analysis/status')
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

    def test_analysis_status_alias_surfaces_calibration_guidance_and_coordinate_watchlist(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'risk_factor_targets': [{'target_type': 'risk_flag', 'name': 'is_occupied', 'suggested_next_factor': 0.5}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 1.05}], 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'strategy_targets': [], 'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 1.05, 'risk_factor_overrides': {'is_occupied': 0.5}}, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'runbook_refs': ['tools/evaluate_avm.py'], 'recommended_actions': ['adjust_weighting_time_decay'], 'suggested_commands': ['python tools/evaluate_avm.py'], 'suggested_bundle_commands': ['python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal'], 'recommended_bundle': {'bundle_id': 'temporal-global-risk', 'target_types': ['global_risk', 'temporal'], 'target_names': None}}, 'guidance': {'status': 'fix_coordinate_quality', 'priority': 'high', 'recommended_actions': ['review_coordinate_strategy_cohorts'], 'top_reason': 'district_centroid'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {'top_coordinate_strategy_group': 'district_centroid', 'coordinate_strategy_watchlist': ['district_centroid']}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/status')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'fix_coordinate_quality')
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['top_calibration_target_hint']['target_name'], 'time_decay')
        self.assertEqual(payload['top_calibration_target_hint']['playbook_id'], 'tune-temporal-decay')
        self.assertIn('tools/evaluate_avm.py', payload['top_calibration_target_hint']['runbook_refs'])
        self.assertIn('python tools/evaluate_avm.py', payload['top_calibration_target_hint']['suggested_commands'])
        self.assertIn('python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal', payload['top_calibration_target_hint']['suggested_bundle_commands'])
        self.assertTrue(payload['calibration_patch_preview']['patch_ready'])
        self.assertEqual(payload['calibration_patch_preview']['changed_paths']['weighting.time_decay']['after'], 0.72)
        self.assertEqual(payload['calibration_patch_preview']['rollback_patch']['weighting']['time_decay'], 0.85)
        self.assertEqual(payload['calibration_target_counts']['global_risk'], 1)
        self.assertEqual(payload['top_calibration_patch_preview']['applied_filter'], {'target_type': 'temporal', 'target_name': 'time_decay'})
        self.assertEqual(payload['top_calibration_patch_preview']['changed_keys'], ['weighting.time_decay'])
        self.assertEqual(payload['recommended_bundle_patch_preview']['bundle_id'], 'temporal-global-risk')
        self.assertEqual(payload['recommended_bundle_patch_preview']['applied_filter'], {'target_types': ['global_risk', 'temporal'], 'target_names': None})
        self.assertEqual(payload['recommended_bundle_patch_preview']['changed_keys'], ['risk_discount_factor', 'weighting.time_decay'])
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write')
        self.assertEqual(payload['recommended_bundle_verify_command'], 'python tools/evaluate_avm.py')
        self.assertEqual(payload['recommended_bundle_gate_command'], 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report')
        self.assertEqual(payload['recommended_bundle_risk_level'], 'medium')
        self.assertIn('multiple_changed_keys', payload['recommended_bundle_risk_reasons'])
        self.assertEqual(payload['recommended_bundle_next_action'], 'preview_only_first')
        self.assertIn('medium_risk_bundle', payload['recommended_bundle_next_action_reasons'])
        self.assertEqual(payload['recommended_bundle_next_action_command_kind'], 'preview')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'write')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['preview', 'write', 'verify', 'gate'])
        self.assertEqual(payload['coordinate_strategy_watchlist'], ['district_centroid'])
        self.assertEqual(payload['top_coordinate_strategy_group'], 'district_centroid')

    def test_analysis_health_alias_uses_gate_embedded_calibration_targets_when_file_is_missing(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {'coordinate_strategy_watchlist': ['district_centroid'], 'top_coordinate_strategy_group': 'district_centroid', 'calibration_targets': {'config_patch': {'weighting': {'time_decay': 0.72}}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [], 'risk_factor_targets': [], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}, 'guidance': {'status': 'tune_temporal_decay', 'priority': 'medium', 'recommended_actions': ['adjust_weighting_time_decay'], 'top_reason': 'time_decay'}}}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'tune_temporal_decay')
        self.assertEqual(payload['calibration_target_counts']['temporal'], 1)
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['recommended_bundle_risk_level'], 'low')
        self.assertEqual(payload['recommended_bundle_next_action'], 'safe_to_write_then_verify')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['write', 'verify', 'gate'])

    def test_analysis_health_alias_merges_partial_embedded_calibration_targets_with_file_context(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {'is_occupied': 0.8}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 0.99, 'risk_factor_overrides': {'is_occupied': 0.5}}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 0.99}], 'risk_factor_targets': [{'target_type': 'risk_flag', 'name': 'is_occupied', 'suggested_next_factor': 0.5}], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}, 'top_calibration_target_hint': {'status': 'tune_risk_factors', 'playbook_id': 'split-bundle-or-single-target-first', 'recommended_bundle': {'bundle_id': 'temporal-global-risk-risk-flag', 'target_types': ['temporal', 'global_risk', 'risk_flag'], 'target_names': ['time_decay', 'risk_discount_factor', 'is_occupied']}, 'suggested_bundle_commands': ['python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied', 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write', 'python tools/evaluate_avm.py', 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report']}, 'guidance': {'status': 'tune_risk_factors', 'priority': 'high', 'recommended_actions': ['split_bundle_or_single_target_first'], 'top_reason': 'multi_flag_bundle'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {'calibration_targets': {'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}}}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'tune_risk_factors')
        self.assertEqual(payload['recommended_bundle_risk_level'], 'high')
        self.assertEqual(payload['recommended_bundle_next_action'], 'split_bundle_or_single_target_first')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'none')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['preview'])

    def test_analysis_health_alias_stops_high_risk_bundle_chain_at_preview(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {'is_occupied': 0.8}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 0.99}], 'risk_factor_targets': [{'target_type': 'risk_flag', 'name': 'is_occupied', 'suggested_next_factor': 0.5}], 'strategy_targets': [], 'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 0.99, 'risk_factor_overrides': {'is_occupied': 0.5}}, 'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}, 'top_calibration_target_hint': {'status': 'tune_risk_factors', 'target_type': 'risk_flag', 'target_name': 'is_occupied', 'playbook_id': 'split-bundle-or-single-target-first', 'runbook_refs': ['tools/apply_avm_calibration_patch.py'], 'recommended_actions': ['split_bundle_or_single_target_first'], 'suggested_commands': ['python tools/apply_avm_calibration_patch.py --target-type risk_flag --target-name is_occupied'], 'suggested_bundle_commands': ['python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied', 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write', 'python tools/evaluate_avm.py', 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report'], 'recommended_bundle': {'bundle_id': 'temporal-global-risk-risk-flag', 'target_types': ['temporal', 'global_risk', 'risk_flag'], 'target_names': ['time_decay', 'risk_discount_factor', 'is_occupied']}}, 'guidance': {'status': 'tune_risk_factors', 'priority': 'high', 'recommended_actions': ['split_bundle_or_single_target_first'], 'top_reason': 'multi_flag_bundle'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['recommended_bundle_risk_level'], 'high')
        self.assertIn('high_risk_bundle', payload['recommended_bundle_next_action_reasons'])
        self.assertEqual(payload['recommended_bundle_next_action'], 'split_bundle_or_single_target_first')
        self.assertEqual(payload['recommended_bundle_next_action_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied')
        self.assertEqual(payload['recommended_bundle_next_action_command_kind'], 'preview')
        self.assertEqual(payload['recommended_bundle_follow_up_command'], '')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'none')
        self.assertEqual(len(payload['recommended_bundle_command_chain']), 1)
        preview_step = payload['recommended_bundle_command_chain'][0]
        self.assertEqual(preview_step['kind'], 'preview')
        self.assertEqual(preview_step['step_ready_follow_up_command'], '')
        self.assertEqual(preview_step['step_ready_follow_up_expected_signal'], '')
        self.assertEqual(preview_step['step_ready_follow_up_success_criterion'], '')
        self.assertEqual(preview_step['step_ready_terminal_outcome'], 'ready_for_write_decision')
        self.assertEqual(preview_step['step_ready_stage_span'], 'preview_then_split')
        self.assertEqual(preview_step['step_ready_badge'], 'now-preview-then-split')
        self.assertEqual(preview_step['step_ready_group_id'], 'preview-and-split')
        self.assertEqual(preview_step['step_ready_display_order'], 0)

    def test_analysis_health_alias_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [], 'risk_factor_targets': [], 'strategy_targets': [], 'config_patch': {'weighting': {'time_decay': 0.72}}, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'runbook_refs': ['tools/evaluate_avm.py'], 'recommended_actions': ['adjust_weighting_time_decay'], 'suggested_commands': ['python tools/evaluate_avm.py'], 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}, 'guidance': {'status': 'tune_temporal_decay', 'priority': 'medium', 'recommended_actions': ['adjust_weighting_time_decay'], 'top_reason': 'time_decay'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/health')
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

    def test_analysis_health_alias_normalizes_malformed_calibration_target_lists(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': {'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}, 'global_risk_targets': {}, 'risk_factor_targets': 'bad-shape', 'strategy_targets': None, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')

    def test_analysis_status_alias_uses_gate_embedded_calibration_targets_when_file_is_missing(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {'coordinate_strategy_watchlist': ['district_centroid'], 'top_coordinate_strategy_group': 'district_centroid', 'calibration_targets': {'config_patch': {'weighting': {'time_decay': 0.72}}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [], 'risk_factor_targets': [], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}, 'guidance': {'status': 'tune_temporal_decay', 'priority': 'medium', 'recommended_actions': ['adjust_weighting_time_decay'], 'top_reason': 'time_decay'}}}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/status')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'tune_temporal_decay')
        self.assertEqual(payload['calibration_target_counts']['temporal'], 1)
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['recommended_bundle_risk_level'], 'low')
        self.assertEqual(payload['recommended_bundle_next_action'], 'safe_to_write_then_verify')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['write', 'verify', 'gate'])

    def test_analysis_status_alias_merges_partial_embedded_calibration_targets_with_file_context(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {'is_occupied': 0.8}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 0.99, 'risk_factor_overrides': {'is_occupied': 0.5}}, 'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 0.99}], 'risk_factor_targets': [{'target_type': 'risk_flag', 'name': 'is_occupied', 'suggested_next_factor': 0.5}], 'strategy_targets': [], 'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}, 'top_calibration_target_hint': {'status': 'tune_risk_factors', 'playbook_id': 'split-bundle-or-single-target-first', 'recommended_bundle': {'bundle_id': 'temporal-global-risk-risk-flag', 'target_types': ['temporal', 'global_risk', 'risk_flag'], 'target_names': ['time_decay', 'risk_discount_factor', 'is_occupied']}, 'suggested_bundle_commands': ['python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied', 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write', 'python tools/evaluate_avm.py', 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report']}, 'guidance': {'status': 'tune_risk_factors', 'priority': 'high', 'recommended_actions': ['split_bundle_or_single_target_first'], 'top_reason': 'multi_flag_bundle'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {'calibration_targets': {'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}}}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/status')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'tune_risk_factors')
        self.assertEqual(payload['recommended_bundle_risk_level'], 'high')
        self.assertEqual(payload['recommended_bundle_next_action'], 'split_bundle_or_single_target_first')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'none')
        self.assertEqual([item['kind'] for item in payload['recommended_bundle_command_chain']], ['preview'])

    def test_analysis_status_alias_stops_high_risk_bundle_chain_at_preview(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {'is_occupied': 0.8}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [{'target_type': 'global_risk', 'name': 'risk_discount_factor', 'suggested_next_value': 0.99}], 'risk_factor_targets': [{'target_type': 'risk_flag', 'name': 'is_occupied', 'suggested_next_factor': 0.5}], 'strategy_targets': [], 'config_patch': {'weighting': {'time_decay': 0.72}, 'risk_discount_factor': 0.99, 'risk_factor_overrides': {'is_occupied': 0.5}}, 'top_calibration_target': {'target_type': 'risk_flag', 'name': 'is_occupied'}, 'top_calibration_target_hint': {'status': 'tune_risk_factors', 'target_type': 'risk_flag', 'target_name': 'is_occupied', 'playbook_id': 'split-bundle-or-single-target-first', 'runbook_refs': ['tools/apply_avm_calibration_patch.py'], 'recommended_actions': ['split_bundle_or_single_target_first'], 'suggested_commands': ['python tools/apply_avm_calibration_patch.py --target-type risk_flag --target-name is_occupied'], 'suggested_bundle_commands': ['python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied', 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied --write', 'python tools/evaluate_avm.py', 'python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report'], 'recommended_bundle': {'bundle_id': 'temporal-global-risk-risk-flag', 'target_types': ['temporal', 'global_risk', 'risk_flag'], 'target_names': ['time_decay', 'risk_discount_factor', 'is_occupied']}}, 'guidance': {'status': 'tune_risk_factors', 'priority': 'high', 'recommended_actions': ['split_bundle_or_single_target_first'], 'top_reason': 'multi_flag_bundle'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/status')
        self.assertEqual(status, 200)
        self.assertEqual(payload['recommended_bundle_risk_level'], 'high')
        self.assertIn('high_risk_bundle', payload['recommended_bundle_next_action_reasons'])
        self.assertEqual(payload['recommended_bundle_next_action'], 'split_bundle_or_single_target_first')
        self.assertEqual(payload['recommended_bundle_next_action_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-type global_risk --target-type risk_flag --target-name time_decay --target-name risk_discount_factor --target-name is_occupied')
        self.assertEqual(payload['recommended_bundle_next_action_command_kind'], 'preview')
        self.assertEqual(payload['recommended_bundle_follow_up_command'], '')
        self.assertEqual(payload['recommended_bundle_follow_up_command_kind'], 'none')
        self.assertEqual(len(payload['recommended_bundle_command_chain']), 1)
        preview_step = payload['recommended_bundle_command_chain'][0]
        self.assertEqual(preview_step['kind'], 'preview')
        self.assertEqual(preview_step['step_ready_follow_up_command'], '')
        self.assertEqual(preview_step['step_ready_follow_up_expected_signal'], '')
        self.assertEqual(preview_step['step_ready_follow_up_success_criterion'], '')
        self.assertEqual(preview_step['step_ready_terminal_outcome'], 'ready_for_write_decision')
        self.assertEqual(preview_step['step_ready_stage_span'], 'preview_then_split')
        self.assertEqual(preview_step['step_ready_badge'], 'now-preview-then-split')
        self.assertEqual(preview_step['step_ready_group_id'], 'preview-and-split')
        self.assertEqual(preview_step['step_ready_display_order'], 0)

    def test_analysis_status_alias_backfills_bundle_commands_from_recommended_bundle_when_suggestions_missing(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': {'distance_power': 2.0, 'time_decay': 0.85, 'community_boost': 1.3}, 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': [{'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}], 'global_risk_targets': [], 'risk_factor_targets': [], 'strategy_targets': [], 'config_patch': {'weighting': {'time_decay': 0.72}}, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'runbook_refs': ['tools/evaluate_avm.py'], 'recommended_actions': ['adjust_weighting_time_decay'], 'suggested_commands': ['python tools/evaluate_avm.py'], 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}, 'guidance': {'status': 'tune_temporal_decay', 'priority': 'medium', 'recommended_actions': ['adjust_weighting_time_decay'], 'top_reason': 'time_decay'}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/status')
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

    def test_analysis_status_alias_normalizes_malformed_calibration_target_lists(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump({'temporal_targets': {'target_type': 'temporal', 'name': 'time_decay', 'suggested_next_value': 0.72}, 'global_risk_targets': {}, 'risk_factor_targets': 'bad-shape', 'strategy_targets': None, 'top_calibration_target': {'target_type': 'temporal', 'name': 'time_decay'}, 'top_calibration_target_hint': {'status': 'tune_temporal_decay', 'target_type': 'temporal', 'target_name': 'time_decay', 'playbook_id': 'tune-temporal-decay', 'recommended_bundle': {'bundle_id': 'temporal-only', 'target_types': ['temporal'], 'target_names': ['time_decay']}}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/status')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['top_calibration_target']['name'], 'time_decay')
        self.assertEqual(payload['recommended_bundle_preview_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay')
        self.assertEqual(payload['recommended_bundle_write_command'], 'python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write')

    def test_analysis_health_alias_tolerates_non_object_calibration_targets_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_analysis_status_alias_tolerates_non_object_calibration_targets_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'calibration_targets.json'), 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/status')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_analysis_health_alias_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_analysis_status_alias_tolerates_non_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/status')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_analysis_health_alias_tolerates_invalid_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': [], 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_analysis_health_alias_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            f.write('{')
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_analysis_status_alias_tolerates_invalid_object_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            json.dump({'radius_km': 3.0, 'weighting': [], 'risk_discount_factor': 0.9, 'alert_threshold': 0.25, 'risk_factor_overrides': {}}, f, ensure_ascii=False)
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/status')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

    def test_analysis_status_alias_tolerates_malformed_config_file(self):
        avm_dir = os.path.join(self.data_dir, 'avm')
        os.makedirs(avm_dir, exist_ok=True)
        with open(os.path.join(avm_dir, 'config.json'), 'w', encoding='utf-8') as f:
            f.write('{')
        with open(os.path.join(avm_dir, 'release_gate.json'), 'w', encoding='utf-8') as f:
            json.dump({'evaluation': {}}, f, ensure_ascii=False)
        (status, payload) = self._get_json('/api/analysis/status')
        self.assertEqual(status, 200)
        self.assertEqual(payload['calibration_guidance']['status'], 'unavailable')
        self.assertEqual(payload['calibration_target_counts'], {'global_risk': 0, 'risk_factor': 0, 'temporal': 0, 'strategy': 0})
        self.assertEqual(payload['recommended_bundle_next_action'], 'no_action_required')

__all__ = ["AVMHttpContractPart02"]
