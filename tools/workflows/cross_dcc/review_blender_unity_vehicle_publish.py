"""Generated pipeline.
Goal: Process the selected Blender vehicle meshes, generate LOD0 and LOD1, add collision, export FBX to C:/temp/tc_review_vehicle.fbx, import into Unity Assets/TechConnector/Vehicles.

Flow edges control execution order only.
Data edges bind return/output values into downstream function arguments.
"""
import importlib
import json
import time
import traceback

def review_blender_unity_vehicle_publish(response):
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

def review_blender_unity_vehicle_publish(session_ports=None, require_live_preflight=True, operation_timeout_seconds=120.0):
    global _TC_PIPELINE_LAST_TRACE
    results = {}
    outputs = {}
    trace = []
    _TC_PIPELINE_LAST_TRACE = trace
    _tc_pipeline_hosts = ['blender', 'unity']
    _tc_pipeline_callables = {'blender': ['blender_tools.pipeline_transfer.process_meshes_for_transfer', 'blender_tools.io.export_fbx'], 'unity': ['unity.command.assets.import_fbx']}
    _tc_session_ports = dict(session_ports or {})
    if require_live_preflight and _tc_pipeline_hosts:
        from tech_connector.game_engine.integration.pipeline_execution_preflight_service import resolve_pipeline_session_ports
        _tc_session_ports = resolve_pipeline_session_ports(_tc_pipeline_hosts, session_ports=_tc_session_ports, callables_by_host=_tc_pipeline_callables, timeout_seconds=operation_timeout_seconds)
    flow_links = [{'from': 'step1', 'to': 'step2'}, {'from': 'step2', 'to': 'step3'}]
    print('[Pipeline 1/3] START BLENDER: stage_01_blender_pipeline_process_meshes_for_transfer')
    try:
        _step1_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'objects': {'$pipeline_context': 'dcc_export_scope_v1', 'host': 'blender', 'scope': 'selected_or_scene_meshes', 'subject': 'static_mesh', 'label': 'Selected meshes, or scene meshes when nothing is selected'}, 'clean_names': False, 'apply_transforms': False, 'lod_count': 2, 'ensure_material_slots': False, 'create_collision': True}
        step1_result = execute_pipeline_operation('blender', 'pipeline.process_meshes_for_transfer', 'blender_tools.pipeline_transfer.process_meshes_for_transfer', _operation_params, session_port=_tc_session_ports.get('blender'), timeout_seconds=operation_timeout_seconds)
        step1_outputs = {}
        step1_outputs['blender_scene'] = step1_result.get('blender_scene', None)
        if step1_outputs['blender_scene'] is None:
            raise RuntimeError('DCC stage did not return required output: blender_scene')
        step1_outputs['export_objects'] = step1_result.get('export_objects', None)
        if step1_outputs['export_objects'] is None:
            raise RuntimeError('DCC stage did not return required output: export_objects')
        step1_outputs['meshes'] = step1_result.get('meshes', None)
        if step1_outputs['meshes'] is None:
            raise RuntimeError('DCC stage did not return required output: meshes')
        step1_outputs['materials'] = step1_result.get('materials', None)
        if step1_outputs['materials'] is None:
            raise RuntimeError('DCC stage did not return required output: materials')
        step1_outputs['collision'] = step1_result.get('collision', None)
        if step1_outputs['collision'] is None:
            raise RuntimeError('DCC stage did not return required output: collision')
        step1_outputs['lods'] = step1_result.get('lods', None)
        if step1_outputs['lods'] is None:
            raise RuntimeError('DCC stage did not return required output: lods')
        outputs['step1'] = step1_outputs
        results['step1'] = step1_result
        print(f'[Pipeline 1/3] COMPLETE BLENDER: stage_01_blender_pipeline_process_meshes_for_transfer ({(time.perf_counter() - _step1_started) * 1000.0:.1f} ms)')
        trace.append({'step': 1, 'name': 'stage_01_blender_pipeline_process_meshes_for_transfer', 'host': 'blender', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': step1_result.get('rollback') if isinstance(step1_result, dict) else None, 'outputs': step1_outputs, 'result': step1_result})
    except Exception as e:
        print(f'[Pipeline 1/3] FAILED BLENDER: stage_01_blender_pipeline_process_meshes_for_transfer - {e}')
        trace.append({'step': 1, 'name': 'stage_01_blender_pipeline_process_meshes_for_transfer', 'host': 'blender', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 1 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 2/3] START BLENDER: stage_02_blender_io_export_fbx')
    try:
        _step2_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'filepath': 'C:/temp/tc_review_vehicle.fbx', 'selected_only': True, 'apply_unit_scale': True, 'axis_forward': '-Z', 'axis_up': 'Y', 'object_names': outputs['step1']['export_objects']}
        step2_result = execute_pipeline_operation('blender', 'io.export_fbx', 'blender_tools.io.export_fbx', _operation_params, session_port=_tc_session_ports.get('blender'), timeout_seconds=operation_timeout_seconds)
        step2_outputs = {}
        step2_outputs['fbx_path'] = step2_result.get('fbx_path', _operation_params.get('filepath'))
        if step2_outputs['fbx_path'] is None:
            raise RuntimeError('DCC stage did not return required output: fbx_path')
        outputs['step2'] = step2_outputs
        results['step2'] = step2_result
        print(f'[Pipeline 2/3] COMPLETE BLENDER: stage_02_blender_io_export_fbx ({(time.perf_counter() - _step2_started) * 1000.0:.1f} ms)')
        trace.append({'step': 2, 'name': 'stage_02_blender_io_export_fbx', 'host': 'blender', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': step2_result.get('rollback') if isinstance(step2_result, dict) else None, 'outputs': step2_outputs, 'result': step2_result})
    except Exception as e:
        print(f'[Pipeline 2/3] FAILED BLENDER: stage_02_blender_io_export_fbx - {e}')
        trace.append({'step': 2, 'name': 'stage_02_blender_io_export_fbx', 'host': 'blender', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 2 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 3/3] START UNITY: stage_03_unity_assets_import_fbx')
    try:
        _step3_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'filepath': outputs['step2']['fbx_path'], 'destination_path': 'Assets/TechConnector/Vehicles/tc_review_vehicle.fbx', 'instantiate': True, 'gameobject_name': 'TC_WorkflowAsset'}
        step3_result = execute_pipeline_operation('unity', 'assets.import_fbx', 'unity.command.assets.import_fbx', _operation_params, session_port=_tc_session_ports.get('unity'), timeout_seconds=operation_timeout_seconds)
        step3_outputs = {}
        step3_outputs['unity_asset_path'] = step3_result.get('unity_asset_path', None)
        if step3_outputs['unity_asset_path'] is None:
            raise RuntimeError('DCC stage did not return required output: unity_asset_path')
        outputs['step3'] = step3_outputs
        results['step3'] = step3_result
        print(f'[Pipeline 3/3] COMPLETE UNITY: stage_03_unity_assets_import_fbx ({(time.perf_counter() - _step3_started) * 1000.0:.1f} ms)')
        trace.append({'step': 3, 'name': 'stage_03_unity_assets_import_fbx', 'host': 'unity', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step3_started) * 1000.0, 3), 'rollback': step3_result.get('rollback') if isinstance(step3_result, dict) else None, 'outputs': step3_outputs, 'result': step3_result})
    except Exception as e:
        print(f'[Pipeline 3/3] FAILED UNITY: stage_03_unity_assets_import_fbx - {e}')
        trace.append({'step': 3, 'name': 'stage_03_unity_assets_import_fbx', 'host': 'unity', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step3_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 3 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline] COMPLETE: 3 stage(s) succeeded')
    return results.get('step3')
