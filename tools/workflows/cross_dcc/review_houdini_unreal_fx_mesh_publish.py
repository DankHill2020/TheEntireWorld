"""Generated pipeline.
Goal: Export Houdini static mesh FX geometry from /obj/OUT_FX as FBX to C:/temp/tc_review_fx_mesh.fbx, import it into Unreal /Game/TechConnector/Review/FXMeshes, save it and validate registry readback.

Flow edges control execution order only.
Data edges bind return/output values into downstream function arguments.
"""
import importlib
import json
import time
import traceback

def review_houdini_unreal_fx_mesh_publish(response):
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

def review_houdini_unreal_fx_mesh_publish(session_ports=None, require_live_preflight=True, operation_timeout_seconds=120.0, step2_skeleton_path=None):
    global _TC_PIPELINE_LAST_TRACE
    results = {}
    outputs = {}
    trace = []
    _TC_PIPELINE_LAST_TRACE = trace
    _tc_pipeline_hosts = ['houdini', 'unreal']
    _tc_pipeline_callables = {'houdini': ['houdini_tools.geometry.export_file'], 'unreal': ['unreal_tools.asset_transfer_adapter.import_fbx_verified', 'unreal_tools.asset_transfer_adapter.registry_readback']}
    _tc_session_ports = dict(session_ports or {})
    if require_live_preflight and _tc_pipeline_hosts:
        from tech_connector.game_engine.integration.pipeline_execution_preflight_service import resolve_pipeline_session_ports
        _tc_session_ports = resolve_pipeline_session_ports(_tc_pipeline_hosts, session_ports=_tc_session_ports, callables_by_host=_tc_pipeline_callables, timeout_seconds=operation_timeout_seconds)
    flow_links = [{'from': 'step1', 'to': 'step2'}, {'from': 'step2', 'to': 'step3'}]
    print('[Pipeline 1/3] START HOUDINI: stage_01_houdini_geometry_export')
    try:
        _step1_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'node_path': '/obj/OUT_FX', 'filepath': 'C:/temp/tc_review_fx_mesh.fbx', 'frame': 1}
        step1_result = execute_pipeline_operation('houdini', 'geometry.export', 'houdini_tools.geometry.export_file', _operation_params, session_port=_tc_session_ports.get('houdini'), timeout_seconds=operation_timeout_seconds)
        step1_outputs = {}
        step1_outputs['fbx_path'] = step1_result.get('fbx_path', _operation_params.get('filepath'))
        if step1_outputs['fbx_path'] is None:
            raise RuntimeError('DCC stage did not return required output: fbx_path')
        outputs['step1'] = step1_outputs
        results['step1'] = step1_result
        print(f'[Pipeline 1/3] COMPLETE HOUDINI: stage_01_houdini_geometry_export ({(time.perf_counter() - _step1_started) * 1000.0:.1f} ms)')
        trace.append({'step': 1, 'name': 'stage_01_houdini_geometry_export', 'host': 'houdini', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': step1_result.get('rollback') if isinstance(step1_result, dict) else None, 'outputs': step1_outputs, 'result': step1_result})
    except Exception as e:
        print(f'[Pipeline 1/3] FAILED HOUDINI: stage_01_houdini_geometry_export - {e}')
        trace.append({'step': 1, 'name': 'stage_01_houdini_geometry_export', 'host': 'houdini', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 1 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 2/3] START UNREAL: stage_02_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified')
    try:
        _step2_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'source_file': outputs['step1']['fbx_path'], 'destination_path': '/Game/TechConnector/Review/FXMeshes', 'subject': 'static_mesh', 'skeleton_path': step2_skeleton_path, 'replace_existing': False, 'save': True}
        step2_result = execute_pipeline_operation('unreal', 'unreal_tools.asset_transfer_adapter.import_fbx_verified', 'unreal_tools.asset_transfer_adapter.import_fbx_verified', _operation_params, session_port=_tc_session_ports.get('unreal'), timeout_seconds=operation_timeout_seconds)
        step2_outputs = {}
        step2_outputs['asset_path'] = step2_result.get('asset_path', None)
        if step2_outputs['asset_path'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_path')
        step2_outputs['imported_paths'] = step2_result.get('imported_paths', None)
        if step2_outputs['imported_paths'] is None:
            raise RuntimeError('DCC stage did not return required output: imported_paths')
        step2_outputs['asset_count'] = step2_result.get('asset_count', None)
        if step2_outputs['asset_count'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_count')
        outputs['step2'] = step2_outputs
        results['step2'] = step2_result
        print(f'[Pipeline 2/3] COMPLETE UNREAL: stage_02_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified ({(time.perf_counter() - _step2_started) * 1000.0:.1f} ms)')
        trace.append({'step': 2, 'name': 'stage_02_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': step2_result.get('rollback') if isinstance(step2_result, dict) else None, 'outputs': step2_outputs, 'result': step2_result})
    except Exception as e:
        print(f'[Pipeline 2/3] FAILED UNREAL: stage_02_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified - {e}')
        trace.append({'step': 2, 'name': 'stage_02_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 2 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 3/3] START UNREAL: stage_03_unreal_unreal_tools_asset_transfer_adapter_registry_readback')
    try:
        _step3_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'imported_paths': outputs['step2']['imported_paths'], 'destination_path': '/Game/TechConnector/Review/FXMeshes'}
        step3_result = execute_pipeline_operation('unreal', 'unreal_tools.asset_transfer_adapter.registry_readback', 'unreal_tools.asset_transfer_adapter.registry_readback', _operation_params, session_port=_tc_session_ports.get('unreal'), timeout_seconds=operation_timeout_seconds)
        step3_outputs = {}
        step3_outputs['assets'] = step3_result.get('assets', None)
        if step3_outputs['assets'] is None:
            raise RuntimeError('DCC stage did not return required output: assets')
        step3_outputs['asset_count'] = step3_result.get('asset_count', None)
        if step3_outputs['asset_count'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_count')
        outputs['step3'] = step3_outputs
        results['step3'] = step3_result
        print(f'[Pipeline 3/3] COMPLETE UNREAL: stage_03_unreal_unreal_tools_asset_transfer_adapter_registry_readback ({(time.perf_counter() - _step3_started) * 1000.0:.1f} ms)')
        trace.append({'step': 3, 'name': 'stage_03_unreal_unreal_tools_asset_transfer_adapter_registry_readback', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step3_started) * 1000.0, 3), 'rollback': step3_result.get('rollback') if isinstance(step3_result, dict) else None, 'outputs': step3_outputs, 'result': step3_result})
    except Exception as e:
        print(f'[Pipeline 3/3] FAILED UNREAL: stage_03_unreal_unreal_tools_asset_transfer_adapter_registry_readback - {e}')
        trace.append({'step': 3, 'name': 'stage_03_unreal_unreal_tools_asset_transfer_adapter_registry_readback', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step3_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 3 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline] COMPLETE: 3 stage(s) succeeded')
    return results.get('step3')
