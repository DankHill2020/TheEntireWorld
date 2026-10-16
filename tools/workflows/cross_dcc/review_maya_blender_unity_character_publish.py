"""Generated pipeline.
Goal: Export a Maya rigged character FBX to C:/temp/tc_review_character.fbx, import it into Blender, clean mesh names, apply transforms, add a material slot and collision proxy, then export FBX to C:/temp/tc_review_character_clean.fbx and import into Unity Assets/TechConnector/Characters.

Flow edges control execution order only.
Data edges bind return/output values into downstream function arguments.
"""
import importlib
import json
import time
import traceback

def review_maya_blender_unity_character_publish(response):
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

def review_maya_blender_unity_character_publish(session_ports=None, require_live_preflight=True, operation_timeout_seconds=120.0):
    global _TC_PIPELINE_LAST_TRACE
    results = {}
    outputs = {}
    trace = []
    _TC_PIPELINE_LAST_TRACE = trace
    _tc_pipeline_hosts = ['maya', 'blender', 'unity']
    _tc_pipeline_callables = {'maya': ['maya_tools.Animation.anim_export.bridge_export.export_fbx'], 'blender': ['blender_tools.io.import_fbx', 'blender_tools.pipeline_transfer.process_meshes_for_transfer', 'blender_tools.io.export_fbx'], 'unity': ['unity.command.assets.import_fbx']}
    _tc_session_ports = dict(session_ports or {})
    if require_live_preflight and _tc_pipeline_hosts:
        from tech_connector.game_engine.integration.pipeline_execution_preflight_service import resolve_pipeline_session_ports
        _tc_session_ports = resolve_pipeline_session_ports(_tc_pipeline_hosts, session_ports=_tc_session_ports, callables_by_host=_tc_pipeline_callables, timeout_seconds=operation_timeout_seconds)
    flow_links = [{'from': 'step1', 'to': 'step2'}, {'from': 'step2', 'to': 'step3'}, {'from': 'step3', 'to': 'step4'}, {'from': 'step4', 'to': 'step5'}]
    print('[Pipeline 1/5] START MAYA: stage_01_maya_animation_export')
    try:
        _step1_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'export_path': 'C:/temp/tc_review_character.fbx', 'start_frame': 1, 'end_frame': 120, 'selected_only': True, 'nodes': {'$pipeline_context': 'dcc_export_scope_v1', 'host': 'maya', 'scope': 'rig_contents', 'subject': 'skeletal_mesh', 'label': 'Rig, skinned meshes, and export children'}}
        step1_result = execute_pipeline_operation('maya', 'animation.export', 'maya_tools.Animation.anim_export.bridge_export.export_fbx', _operation_params, session_port=_tc_session_ports.get('maya'), timeout_seconds=operation_timeout_seconds)
        step1_outputs = {}
        step1_outputs['fbx_path'] = step1_result.get('fbx_path', _operation_params.get('export_path'))
        if step1_outputs['fbx_path'] is None:
            raise RuntimeError('DCC stage did not return required output: fbx_path')
        outputs['step1'] = step1_outputs
        results['step1'] = step1_result
        print(f'[Pipeline 1/5] COMPLETE MAYA: stage_01_maya_animation_export ({(time.perf_counter() - _step1_started) * 1000.0:.1f} ms)')
        trace.append({'step': 1, 'name': 'stage_01_maya_animation_export', 'host': 'maya', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': step1_result.get('rollback') if isinstance(step1_result, dict) else None, 'outputs': step1_outputs, 'result': step1_result})
    except Exception as e:
        print(f'[Pipeline 1/5] FAILED MAYA: stage_01_maya_animation_export - {e}')
        trace.append({'step': 1, 'name': 'stage_01_maya_animation_export', 'host': 'maya', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 1 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 2/5] START BLENDER: stage_02_blender_io_import_fbx')
    try:
        _step2_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'filepath': outputs['step1']['fbx_path'], 'use_image_search': True}
        step2_result = execute_pipeline_operation('blender', 'io.import_fbx', 'blender_tools.io.import_fbx', _operation_params, session_port=_tc_session_ports.get('blender'), timeout_seconds=operation_timeout_seconds)
        step2_outputs = {}
        step2_outputs['blender_scene'] = step2_result.get('blender_scene', None)
        if step2_outputs['blender_scene'] is None:
            raise RuntimeError('DCC stage did not return required output: blender_scene')
        step2_outputs['objects'] = step2_result.get('objects', None)
        if step2_outputs['objects'] is None:
            raise RuntimeError('DCC stage did not return required output: objects')
        step2_outputs['meshes'] = step2_result.get('meshes', None)
        if step2_outputs['meshes'] is None:
            raise RuntimeError('DCC stage did not return required output: meshes')
        step2_outputs['armatures'] = step2_result.get('armatures', None)
        if step2_outputs['armatures'] is None:
            raise RuntimeError('DCC stage did not return required output: armatures')
        step2_outputs['animations'] = step2_result.get('animations', None)
        if step2_outputs['animations'] is None:
            raise RuntimeError('DCC stage did not return required output: animations')
        outputs['step2'] = step2_outputs
        results['step2'] = step2_result
        print(f'[Pipeline 2/5] COMPLETE BLENDER: stage_02_blender_io_import_fbx ({(time.perf_counter() - _step2_started) * 1000.0:.1f} ms)')
        trace.append({'step': 2, 'name': 'stage_02_blender_io_import_fbx', 'host': 'blender', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': step2_result.get('rollback') if isinstance(step2_result, dict) else None, 'outputs': step2_outputs, 'result': step2_result})
    except Exception as e:
        print(f'[Pipeline 2/5] FAILED BLENDER: stage_02_blender_io_import_fbx - {e}')
        trace.append({'step': 2, 'name': 'stage_02_blender_io_import_fbx', 'host': 'blender', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 2 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 3/5] START BLENDER: stage_03_blender_pipeline_process_meshes_for_transfer')
    try:
        _step3_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'objects': outputs['step2']['objects'], 'clean_names': True, 'apply_transforms': True, 'lod_count': 0, 'ensure_material_slots': True, 'create_collision': True}
        step3_result = execute_pipeline_operation('blender', 'pipeline.process_meshes_for_transfer', 'blender_tools.pipeline_transfer.process_meshes_for_transfer', _operation_params, session_port=_tc_session_ports.get('blender'), timeout_seconds=operation_timeout_seconds)
        step3_outputs = {}
        step3_outputs['blender_scene'] = step3_result.get('blender_scene', None)
        if step3_outputs['blender_scene'] is None:
            raise RuntimeError('DCC stage did not return required output: blender_scene')
        step3_outputs['export_objects'] = step3_result.get('export_objects', None)
        if step3_outputs['export_objects'] is None:
            raise RuntimeError('DCC stage did not return required output: export_objects')
        step3_outputs['meshes'] = step3_result.get('meshes', None)
        if step3_outputs['meshes'] is None:
            raise RuntimeError('DCC stage did not return required output: meshes')
        step3_outputs['materials'] = step3_result.get('materials', None)
        if step3_outputs['materials'] is None:
            raise RuntimeError('DCC stage did not return required output: materials')
        step3_outputs['collision'] = step3_result.get('collision', None)
        if step3_outputs['collision'] is None:
            raise RuntimeError('DCC stage did not return required output: collision')
        step3_outputs['lods'] = step3_result.get('lods', None)
        if step3_outputs['lods'] is None:
            raise RuntimeError('DCC stage did not return required output: lods')
        outputs['step3'] = step3_outputs
        results['step3'] = step3_result
        print(f'[Pipeline 3/5] COMPLETE BLENDER: stage_03_blender_pipeline_process_meshes_for_transfer ({(time.perf_counter() - _step3_started) * 1000.0:.1f} ms)')
        trace.append({'step': 3, 'name': 'stage_03_blender_pipeline_process_meshes_for_transfer', 'host': 'blender', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step3_started) * 1000.0, 3), 'rollback': step3_result.get('rollback') if isinstance(step3_result, dict) else None, 'outputs': step3_outputs, 'result': step3_result})
    except Exception as e:
        print(f'[Pipeline 3/5] FAILED BLENDER: stage_03_blender_pipeline_process_meshes_for_transfer - {e}')
        trace.append({'step': 3, 'name': 'stage_03_blender_pipeline_process_meshes_for_transfer', 'host': 'blender', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step3_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 3 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 4/5] START BLENDER: stage_04_blender_io_export_fbx')
    try:
        _step4_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'filepath': 'C:/temp/tc_review_character_clean.fbx', 'selected_only': True, 'apply_unit_scale': True, 'axis_forward': '-Z', 'axis_up': 'Y', 'object_names': outputs['step3']['export_objects']}
        step4_result = execute_pipeline_operation('blender', 'io.export_fbx', 'blender_tools.io.export_fbx', _operation_params, session_port=_tc_session_ports.get('blender'), timeout_seconds=operation_timeout_seconds)
        step4_outputs = {}
        step4_outputs['fbx_path'] = step4_result.get('fbx_path', _operation_params.get('filepath'))
        if step4_outputs['fbx_path'] is None:
            raise RuntimeError('DCC stage did not return required output: fbx_path')
        outputs['step4'] = step4_outputs
        results['step4'] = step4_result
        print(f'[Pipeline 4/5] COMPLETE BLENDER: stage_04_blender_io_export_fbx ({(time.perf_counter() - _step4_started) * 1000.0:.1f} ms)')
        trace.append({'step': 4, 'name': 'stage_04_blender_io_export_fbx', 'host': 'blender', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step4_started) * 1000.0, 3), 'rollback': step4_result.get('rollback') if isinstance(step4_result, dict) else None, 'outputs': step4_outputs, 'result': step4_result})
    except Exception as e:
        print(f'[Pipeline 4/5] FAILED BLENDER: stage_04_blender_io_export_fbx - {e}')
        trace.append({'step': 4, 'name': 'stage_04_blender_io_export_fbx', 'host': 'blender', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step4_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 4 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 5/5] START UNITY: stage_05_unity_assets_import_fbx')
    try:
        _step5_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'filepath': outputs['step4']['fbx_path'], 'destination_path': 'Assets/TechConnector/Characters/tc_review_character_clean.fbx', 'instantiate': True, 'gameobject_name': 'TC_WorkflowAsset'}
        step5_result = execute_pipeline_operation('unity', 'assets.import_fbx', 'unity.command.assets.import_fbx', _operation_params, session_port=_tc_session_ports.get('unity'), timeout_seconds=operation_timeout_seconds)
        step5_outputs = {}
        step5_outputs['unity_asset_path'] = step5_result.get('unity_asset_path', None)
        if step5_outputs['unity_asset_path'] is None:
            raise RuntimeError('DCC stage did not return required output: unity_asset_path')
        outputs['step5'] = step5_outputs
        results['step5'] = step5_result
        print(f'[Pipeline 5/5] COMPLETE UNITY: stage_05_unity_assets_import_fbx ({(time.perf_counter() - _step5_started) * 1000.0:.1f} ms)')
        trace.append({'step': 5, 'name': 'stage_05_unity_assets_import_fbx', 'host': 'unity', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step5_started) * 1000.0, 3), 'rollback': step5_result.get('rollback') if isinstance(step5_result, dict) else None, 'outputs': step5_outputs, 'result': step5_result})
    except Exception as e:
        print(f'[Pipeline 5/5] FAILED UNITY: stage_05_unity_assets_import_fbx - {e}')
        trace.append({'step': 5, 'name': 'stage_05_unity_assets_import_fbx', 'host': 'unity', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step5_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 5 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline] COMPLETE: 5 stage(s) succeeded')
    return results.get('step5')
