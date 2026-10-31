"""Generated pipeline.
Goal: Export Maya animation to MotionBuilder for cleanup, export FBX to C:/temp/tc_review_roundtrip.fbx, then import into Unreal /Game/TechConnector/Review/Roundtrip using skeleton /Game/Characters/Mannequins/Meshes/SK_Mannequin, inspect skeleton and root-motion compatibility, retarget if needed, save assets, report final animation paths, and validate registry readback.

Flow edges control execution order only.
Data edges bind return/output values into downstream function arguments.
"""
import importlib
import json
import time
import traceback

def review_maya_motionbuilder_unreal_roundtrip(response):
    (ok, payload) = response if isinstance(response, tuple) and len(response) == 2 else (True, response)
    if not ok:
        raise RuntimeError(str(payload))
    if isinstance(payload, dict):
        if payload.get('ok') is False:
            detail = '\n'.join((str(value) for value in (payload.get('error'), payload.get('traceback'), payload.get('python_stderr')) if value)) or str(payload)
            raise RuntimeError(str(detail))
        for key in ('python_result', 'result', 'data'):
            nested = payload.get(key)
            if isinstance(nested, dict):
                return nested
        text = payload.get('python_stdout') or payload.get('stdout') or payload.get('raw')
        if text:
            payload = text
        else:
            return payload
    if isinstance(payload, str):
        for line in reversed([line.strip() for line in payload.splitlines() if line.strip()]):
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    return parsed
            except (TypeError, ValueError):
                continue
    return {'result': payload}

def review_maya_motionbuilder_unreal_roundtrip(session_ports=None, require_live_preflight=True, operation_timeout_seconds=120.0, step5_target_skeletal_mesh_path=None, step6_source_skeletal_mesh_path=None, step6_target_skeletal_mesh_path=None, step6_retargeter_path=None, step7_target_anim_blueprint_path=None):
    global _TC_PIPELINE_LAST_TRACE
    results = {}
    outputs = {}
    trace = []
    _TC_PIPELINE_LAST_TRACE = trace
    _tc_pipeline_hosts = ['maya', 'motionbuilder', 'unreal']
    _tc_pipeline_callables = {'maya': ['maya_tools.Animation.anim_export.bridge_export.export_fbx'], 'motionbuilder': ['motionbuilder_tools.io.import_fbx', 'motionbuilder_tools.io.export_fbx'], 'unreal': ['unreal_tools.asset_transfer_adapter.import_fbx_verified', 'unreal_tools.animation.inspect_imported_animation_pipeline', 'unreal_tools.animation.retarget_imported_animations_if_needed', 'unreal_tools.animation.report_animation_pipeline_assets', 'unreal_tools.asset_transfer_adapter.registry_readback']}
    _tc_session_ports = dict(session_ports or {})
    if require_live_preflight and _tc_pipeline_hosts:
        from tech_connector.game_engine.integration.pipeline_execution_preflight_service import resolve_pipeline_session_ports
        _tc_session_ports = resolve_pipeline_session_ports(_tc_pipeline_hosts, session_ports=_tc_session_ports, callables_by_host=_tc_pipeline_callables, timeout_seconds=operation_timeout_seconds)
    flow_links = [{'from': 'step1', 'to': 'step2'}, {'from': 'step2', 'to': 'step3'}, {'from': 'step3', 'to': 'step4'}, {'from': 'step4', 'to': 'step5'}, {'from': 'step5', 'to': 'step6'}, {'from': 'step6', 'to': 'step7'}, {'from': 'step7', 'to': 'step8'}]
    print('[Pipeline 1/8] START MAYA: stage_01_maya_animation_export')
    try:
        _step1_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'export_path': 'C:/temp/tc_review_roundtrip.fbx', 'start_frame': 1, 'end_frame': 120, 'selected_only': True, 'nodes': {'$pipeline_context': 'dcc_export_scope_v1', 'host': 'maya', 'scope': 'rig_contents', 'subject': 'animation', 'label': 'Rig, skinned meshes, and export children'}}
        step1_result = execute_pipeline_operation('maya', 'animation.export', 'maya_tools.Animation.anim_export.bridge_export.export_fbx', _operation_params, session_port=_tc_session_ports.get('maya'), timeout_seconds=operation_timeout_seconds)
        step1_outputs = {}
        step1_outputs['fbx_path'] = step1_result.get('fbx_path', _operation_params.get('export_path'))
        if step1_outputs['fbx_path'] is None:
            raise RuntimeError('DCC stage did not return required output: fbx_path')
        outputs['step1'] = step1_outputs
        results['step1'] = step1_result
        print(f'[Pipeline 1/8] COMPLETE MAYA: stage_01_maya_animation_export ({(time.perf_counter() - _step1_started) * 1000.0:.1f} ms)')
        trace.append({'step': 1, 'name': 'stage_01_maya_animation_export', 'host': 'maya', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': step1_result.get('rollback') if isinstance(step1_result, dict) else None, 'outputs': step1_outputs, 'result': step1_result})
    except Exception as e:
        print(f'[Pipeline 1/8] FAILED MAYA: stage_01_maya_animation_export - {e}')
        trace.append({'step': 1, 'name': 'stage_01_maya_animation_export', 'host': 'maya', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 1 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 2/8] START MOTIONBUILDER: stage_02_motionbuilder_io_import_fbx')
    try:
        _step2_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'filepath': outputs['step1']['fbx_path'], 'merge': True}
        step2_result = execute_pipeline_operation('motionbuilder', 'io.import_fbx', 'motionbuilder_tools.io.import_fbx', _operation_params, session_port=_tc_session_ports.get('motionbuilder'), timeout_seconds=operation_timeout_seconds)
        step2_outputs = {}
        step2_outputs['motionbuilder_scene'] = step2_result.get('motionbuilder_scene', None)
        if step2_outputs['motionbuilder_scene'] is None:
            raise RuntimeError('DCC stage did not return required output: motionbuilder_scene')
        step2_outputs['animations'] = step2_result.get('animations', None)
        if step2_outputs['animations'] is None:
            raise RuntimeError('DCC stage did not return required output: animations')
        step2_outputs['skeleton'] = step2_result.get('skeleton', None)
        if step2_outputs['skeleton'] is None:
            raise RuntimeError('DCC stage did not return required output: skeleton')
        outputs['step2'] = step2_outputs
        results['step2'] = step2_result
        print(f'[Pipeline 2/8] COMPLETE MOTIONBUILDER: stage_02_motionbuilder_io_import_fbx ({(time.perf_counter() - _step2_started) * 1000.0:.1f} ms)')
        trace.append({'step': 2, 'name': 'stage_02_motionbuilder_io_import_fbx', 'host': 'motionbuilder', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': step2_result.get('rollback') if isinstance(step2_result, dict) else None, 'outputs': step2_outputs, 'result': step2_result})
    except Exception as e:
        print(f'[Pipeline 2/8] FAILED MOTIONBUILDER: stage_02_motionbuilder_io_import_fbx - {e}')
        trace.append({'step': 2, 'name': 'stage_02_motionbuilder_io_import_fbx', 'host': 'motionbuilder', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 2 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 3/8] START MOTIONBUILDER: stage_03_motionbuilder_io_export_fbx')
    try:
        _step3_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'filepath': '${pipeline_workspace}/stage_03_motionbuilder_io_export_fbx.fbx', 'selected_only': False}
        step3_result = execute_pipeline_operation('motionbuilder', 'io.export_fbx', 'motionbuilder_tools.io.export_fbx', _operation_params, session_port=_tc_session_ports.get('motionbuilder'), timeout_seconds=operation_timeout_seconds)
        step3_outputs = {}
        step3_outputs['fbx_path'] = step3_result.get('fbx_path', _operation_params.get('filepath'))
        if step3_outputs['fbx_path'] is None:
            raise RuntimeError('DCC stage did not return required output: fbx_path')
        outputs['step3'] = step3_outputs
        results['step3'] = step3_result
        print(f'[Pipeline 3/8] COMPLETE MOTIONBUILDER: stage_03_motionbuilder_io_export_fbx ({(time.perf_counter() - _step3_started) * 1000.0:.1f} ms)')
        trace.append({'step': 3, 'name': 'stage_03_motionbuilder_io_export_fbx', 'host': 'motionbuilder', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step3_started) * 1000.0, 3), 'rollback': step3_result.get('rollback') if isinstance(step3_result, dict) else None, 'outputs': step3_outputs, 'result': step3_result})
    except Exception as e:
        print(f'[Pipeline 3/8] FAILED MOTIONBUILDER: stage_03_motionbuilder_io_export_fbx - {e}')
        trace.append({'step': 3, 'name': 'stage_03_motionbuilder_io_export_fbx', 'host': 'motionbuilder', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step3_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 3 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 4/8] START UNREAL: stage_04_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified')
    try:
        _step4_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'source_file': outputs['step3']['fbx_path'], 'destination_path': '/Game/TechConnector/Review/Roundtrip', 'subject': 'animation', 'skeleton_path': '/Game/Characters/Mannequins/Meshes/SK_Mannequin', 'replace_existing': False, 'save': True}
        step4_result = execute_pipeline_operation('unreal', 'unreal_tools.asset_transfer_adapter.import_fbx_verified', 'unreal_tools.asset_transfer_adapter.import_fbx_verified', _operation_params, session_port=_tc_session_ports.get('unreal'), timeout_seconds=operation_timeout_seconds)
        step4_outputs = {}
        step4_outputs['asset_path'] = step4_result.get('asset_path', None)
        if step4_outputs['asset_path'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_path')
        step4_outputs['imported_paths'] = step4_result.get('imported_paths', None)
        if step4_outputs['imported_paths'] is None:
            raise RuntimeError('DCC stage did not return required output: imported_paths')
        step4_outputs['asset_count'] = step4_result.get('asset_count', None)
        if step4_outputs['asset_count'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_count')
        outputs['step4'] = step4_outputs
        results['step4'] = step4_result
        print(f'[Pipeline 4/8] COMPLETE UNREAL: stage_04_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified ({(time.perf_counter() - _step4_started) * 1000.0:.1f} ms)')
        trace.append({'step': 4, 'name': 'stage_04_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step4_started) * 1000.0, 3), 'rollback': step4_result.get('rollback') if isinstance(step4_result, dict) else None, 'outputs': step4_outputs, 'result': step4_result})
    except Exception as e:
        print(f'[Pipeline 4/8] FAILED UNREAL: stage_04_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified - {e}')
        trace.append({'step': 4, 'name': 'stage_04_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step4_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 4 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 5/8] START UNREAL: stage_05_unreal_animation_inspect_imported_pipeline')
    try:
        _step5_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'imported_paths': outputs['step4']['imported_paths'], 'target_skeleton_path': '/Game/Characters/Mannequins/Meshes/SK_Mannequin', 'target_skeletal_mesh_path': step5_target_skeletal_mesh_path}
        step5_result = execute_pipeline_operation('unreal', 'animation.inspect_imported_pipeline', 'unreal_tools.animation.inspect_imported_animation_pipeline', _operation_params, session_port=_tc_session_ports.get('unreal'), timeout_seconds=operation_timeout_seconds)
        step5_outputs = {}
        step5_outputs['compatibility_report'] = step5_result.get('compatibility_report', None)
        if step5_outputs['compatibility_report'] is None:
            raise RuntimeError('DCC stage did not return required output: compatibility_report')
        step5_outputs['animation_paths'] = step5_result.get('animation_paths', None)
        if step5_outputs['animation_paths'] is None:
            raise RuntimeError('DCC stage did not return required output: animation_paths')
        outputs['step5'] = step5_outputs
        results['step5'] = step5_result
        print(f'[Pipeline 5/8] COMPLETE UNREAL: stage_05_unreal_animation_inspect_imported_pipeline ({(time.perf_counter() - _step5_started) * 1000.0:.1f} ms)')
        trace.append({'step': 5, 'name': 'stage_05_unreal_animation_inspect_imported_pipeline', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step5_started) * 1000.0, 3), 'rollback': step5_result.get('rollback') if isinstance(step5_result, dict) else None, 'outputs': step5_outputs, 'result': step5_result})
    except Exception as e:
        print(f'[Pipeline 5/8] FAILED UNREAL: stage_05_unreal_animation_inspect_imported_pipeline - {e}')
        trace.append({'step': 5, 'name': 'stage_05_unreal_animation_inspect_imported_pipeline', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step5_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 5 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 6/8] START UNREAL: stage_06_unreal_animation_retarget_imported_if_needed')
    try:
        _step6_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'compatibility_report': outputs['step5']['compatibility_report'], 'source_skeletal_mesh_path': step6_source_skeletal_mesh_path, 'target_skeletal_mesh_path': step6_target_skeletal_mesh_path, 'output_path': '/Game/Animations/Retargeted', 'retargeter_path': step6_retargeter_path}
        step6_result = execute_pipeline_operation('unreal', 'animation.retarget_imported_if_needed', 'unreal_tools.animation.retarget_imported_animations_if_needed', _operation_params, session_port=_tc_session_ports.get('unreal'), timeout_seconds=operation_timeout_seconds)
        step6_outputs = {}
        step6_outputs['animation_paths'] = step6_result.get('animation_paths', None)
        if step6_outputs['animation_paths'] is None:
            raise RuntimeError('DCC stage did not return required output: animation_paths')
        step6_outputs['retarget_report'] = step6_result.get('retarget_report', None)
        if step6_outputs['retarget_report'] is None:
            raise RuntimeError('DCC stage did not return required output: retarget_report')
        outputs['step6'] = step6_outputs
        results['step6'] = step6_result
        print(f'[Pipeline 6/8] COMPLETE UNREAL: stage_06_unreal_animation_retarget_imported_if_needed ({(time.perf_counter() - _step6_started) * 1000.0:.1f} ms)')
        trace.append({'step': 6, 'name': 'stage_06_unreal_animation_retarget_imported_if_needed', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step6_started) * 1000.0, 3), 'rollback': step6_result.get('rollback') if isinstance(step6_result, dict) else None, 'outputs': step6_outputs, 'result': step6_result})
    except Exception as e:
        print(f'[Pipeline 6/8] FAILED UNREAL: stage_06_unreal_animation_retarget_imported_if_needed - {e}')
        trace.append({'step': 6, 'name': 'stage_06_unreal_animation_retarget_imported_if_needed', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step6_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 6 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 7/8] START UNREAL: stage_07_unreal_animation_report_pipeline_assets')
    try:
        _step7_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'imported_paths': outputs['step4']['imported_paths'], 'animation_paths': outputs['step6']['animation_paths'], 'target_skeleton_path': '/Game/Characters/Mannequins/Meshes/SK_Mannequin', 'target_anim_blueprint_path': step7_target_anim_blueprint_path}
        step7_result = execute_pipeline_operation('unreal', 'animation.report_pipeline_assets', 'unreal_tools.animation.report_animation_pipeline_assets', _operation_params, session_port=_tc_session_ports.get('unreal'), timeout_seconds=operation_timeout_seconds)
        step7_outputs = {}
        step7_outputs['pipeline_report'] = step7_result.get('pipeline_report', None)
        if step7_outputs['pipeline_report'] is None:
            raise RuntimeError('DCC stage did not return required output: pipeline_report')
        outputs['step7'] = step7_outputs
        results['step7'] = step7_result
        print(f'[Pipeline 7/8] COMPLETE UNREAL: stage_07_unreal_animation_report_pipeline_assets ({(time.perf_counter() - _step7_started) * 1000.0:.1f} ms)')
        trace.append({'step': 7, 'name': 'stage_07_unreal_animation_report_pipeline_assets', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step7_started) * 1000.0, 3), 'rollback': step7_result.get('rollback') if isinstance(step7_result, dict) else None, 'outputs': step7_outputs, 'result': step7_result})
    except Exception as e:
        print(f'[Pipeline 7/8] FAILED UNREAL: stage_07_unreal_animation_report_pipeline_assets - {e}')
        trace.append({'step': 7, 'name': 'stage_07_unreal_animation_report_pipeline_assets', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step7_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 7 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 8/8] START UNREAL: stage_08_unreal_unreal_tools_asset_transfer_adapter_registry_readback')
    try:
        _step8_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'imported_paths': outputs['step4']['imported_paths'], 'destination_path': '/Game/TechConnector/Review/Roundtrip'}
        step8_result = execute_pipeline_operation('unreal', 'unreal_tools.asset_transfer_adapter.registry_readback', 'unreal_tools.asset_transfer_adapter.registry_readback', _operation_params, session_port=_tc_session_ports.get('unreal'), timeout_seconds=operation_timeout_seconds)
        step8_outputs = {}
        step8_outputs['assets'] = step8_result.get('assets', None)
        if step8_outputs['assets'] is None:
            raise RuntimeError('DCC stage did not return required output: assets')
        step8_outputs['asset_count'] = step8_result.get('asset_count', None)
        if step8_outputs['asset_count'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_count')
        outputs['step8'] = step8_outputs
        results['step8'] = step8_result
        print(f'[Pipeline 8/8] COMPLETE UNREAL: stage_08_unreal_unreal_tools_asset_transfer_adapter_registry_readback ({(time.perf_counter() - _step8_started) * 1000.0:.1f} ms)')
        trace.append({'step': 8, 'name': 'stage_08_unreal_unreal_tools_asset_transfer_adapter_registry_readback', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step8_started) * 1000.0, 3), 'rollback': step8_result.get('rollback') if isinstance(step8_result, dict) else None, 'outputs': step8_outputs, 'result': step8_result})
    except Exception as e:
        print(f'[Pipeline 8/8] FAILED UNREAL: stage_08_unreal_unreal_tools_asset_transfer_adapter_registry_readback - {e}')
        trace.append({'step': 8, 'name': 'stage_08_unreal_unreal_tools_asset_transfer_adapter_registry_readback', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step8_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 8 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline] COMPLETE: 8 stage(s) succeeded')
    return results.get('step8')
