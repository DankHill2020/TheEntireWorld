"""Generated pipeline.
Goal: Create a Maya to Blender to Unreal validation pipeline: in Maya build a simple rigged animated proxy and export FBX to C:/tmp/tc_chain_maya.fbx, in Blender import it, clean mesh names, apply transforms, add material and collision proxy, export FBX to C:/tmp/tc_chain_blender.fbx, then in Unreal import it into /Game/AIStudio/Validation/Chain, save assets, and report registry readback.

Flow edges control execution order only.
Data edges bind return/output values into downstream function arguments.
"""

import importlib
import json
import time
import traceback

def _tc_bridge_payload(response):
    ok, payload = response if isinstance(response, tuple) and len(response) == 2 else (True, response)
    if not ok:
        raise RuntimeError(str(payload))
    if isinstance(payload, dict):
        if payload.get('ok') is False:
            detail = '\n'.join(str(value) for value in (payload.get('error'), payload.get('traceback'), payload.get('python_stderr')) if value) or str(payload)
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

def maya_blender_unreal_validation(step5_selection=None, step6_skeleton_path=None, step7_destination_path=None):
    global _TC_PIPELINE_LAST_TRACE
    results = {}
    outputs = {}
    trace = []
    _TC_PIPELINE_LAST_TRACE = trace
    flow_links = [{'from': 'step1.flow', 'to': 'step2.flow'}, {'from': 'step2.flow', 'to': 'step3.flow'}, {'from': 'step3.flow', 'to': 'step4.flow'}, {'from': 'step4.flow', 'to': 'step5.flow'}, {'from': 'step5.flow', 'to': 'step6.flow'}, {'from': 'step6.flow', 'to': 'step7.flow'}]

    # Step 1: stage_01_maya_pipeline_create_rigged_proxy (function)
    print('[Pipeline 1/7] START MAYA: stage_01_maya_pipeline_create_rigged_proxy')
    try:
        _step1_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'name_prefix': 'AIStudio_Proxy', 'start_frame': 1, 'end_frame': 24, 'travel_distance': 100.0}
        step1_result = execute_pipeline_operation(
            'maya', 'pipeline.create_rigged_proxy', 'maya_tools.Rigging.validation_proxy.create_rigged_proxy', _operation_params
        )
        step1_outputs = {}
        step1_outputs['maya_scene'] = step1_result.get('maya_scene', None)
        if step1_outputs['maya_scene'] is None:
            raise RuntimeError('DCC stage did not return required output: maya_scene')
        step1_outputs['mesh'] = step1_result.get('mesh', None)
        if step1_outputs['mesh'] is None:
            raise RuntimeError('DCC stage did not return required output: mesh')
        step1_outputs['root_joint'] = step1_result.get('root_joint', None)
        if step1_outputs['root_joint'] is None:
            raise RuntimeError('DCC stage did not return required output: root_joint')
        step1_outputs['joints'] = step1_result.get('joints', None)
        if step1_outputs['joints'] is None:
            raise RuntimeError('DCC stage did not return required output: joints')
        step1_outputs['frame_range'] = step1_result.get('frame_range', None)
        if step1_outputs['frame_range'] is None:
            raise RuntimeError('DCC stage did not return required output: frame_range')
        step1_outputs['selection'] = step1_result.get('selection', None)
        if step1_outputs['selection'] is None:
            raise RuntimeError('DCC stage did not return required output: selection')
        outputs['step1'] = step1_outputs
        results['step1'] = step1_result
        print(f'[Pipeline 1/7] COMPLETE MAYA: stage_01_maya_pipeline_create_rigged_proxy ({(time.perf_counter() - _step1_started) * 1000.0:.1f} ms)')
        trace.append({'step': 1, 'name': 'stage_01_maya_pipeline_create_rigged_proxy', 'host': 'maya', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': step1_result.get('rollback') if isinstance(step1_result, dict) else None, 'outputs': step1_outputs, 'result': step1_result})
    except Exception as e:
        print(f'[Pipeline 1/7] FAILED MAYA: stage_01_maya_pipeline_create_rigged_proxy - {e}')
        trace.append({'step': 1, 'name': 'stage_01_maya_pipeline_create_rigged_proxy', 'host': 'maya', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 1 failed: {e}')
        traceback.print_exc()
        raise

    # Step 2: stage_02_maya_animation_export (function)
    print('[Pipeline 2/7] START MAYA: stage_02_maya_animation_export')
    try:
        _step2_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'start_frame': 1, 'end_frame': 120, 'selected_only': True, 'export_path': 'C:/tmp/tc_chain_maya.fbx'}
        step2_result = execute_pipeline_operation(
            'maya', 'animation.export', 'maya_tools.Animation.anim_export.anim_export.export_anim', _operation_params
        )
        step2_outputs = {}
        step2_outputs['fbx_path'] = step2_result.get('fbx_path', _operation_params.get('export_path'))
        if step2_outputs['fbx_path'] is None:
            raise RuntimeError('DCC stage did not return required output: fbx_path')
        outputs['step2'] = step2_outputs
        results['step2'] = step2_result
        print(f'[Pipeline 2/7] COMPLETE MAYA: stage_02_maya_animation_export ({(time.perf_counter() - _step2_started) * 1000.0:.1f} ms)')
        trace.append({'step': 2, 'name': 'stage_02_maya_animation_export', 'host': 'maya', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': step2_result.get('rollback') if isinstance(step2_result, dict) else None, 'outputs': step2_outputs, 'result': step2_result})
    except Exception as e:
        print(f'[Pipeline 2/7] FAILED MAYA: stage_02_maya_animation_export - {e}')
        trace.append({'step': 2, 'name': 'stage_02_maya_animation_export', 'host': 'maya', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 2 failed: {e}')
        traceback.print_exc()
        raise

    # Step 3: stage_03_blender_io_import_fbx (function)
    print('[Pipeline 3/7] START BLENDER: stage_03_blender_io_import_fbx')
    try:
        _step3_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'use_image_search': True, 'filepath': outputs['step2']['fbx_path']}
        step3_result = execute_pipeline_operation(
            'blender', 'io.import_fbx', 'blender_tools.io.import_fbx', _operation_params
        )
        step3_outputs = {}
        step3_outputs['blender_scene'] = step3_result.get('blender_scene', None)
        if step3_outputs['blender_scene'] is None:
            raise RuntimeError('DCC stage did not return required output: blender_scene')
        step3_outputs['meshes'] = step3_result.get('meshes', None)
        if step3_outputs['meshes'] is None:
            raise RuntimeError('DCC stage did not return required output: meshes')
        step3_outputs['armatures'] = step3_result.get('armatures', None)
        if step3_outputs['armatures'] is None:
            raise RuntimeError('DCC stage did not return required output: armatures')
        step3_outputs['animations'] = step3_result.get('animations', None)
        if step3_outputs['animations'] is None:
            raise RuntimeError('DCC stage did not return required output: animations')
        outputs['step3'] = step3_outputs
        results['step3'] = step3_result
        print(f'[Pipeline 3/7] COMPLETE BLENDER: stage_03_blender_io_import_fbx ({(time.perf_counter() - _step3_started) * 1000.0:.1f} ms)')
        trace.append({'step': 3, 'name': 'stage_03_blender_io_import_fbx', 'host': 'blender', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step3_started) * 1000.0, 3), 'rollback': step3_result.get('rollback') if isinstance(step3_result, dict) else None, 'outputs': step3_outputs, 'result': step3_result})
    except Exception as e:
        print(f'[Pipeline 3/7] FAILED BLENDER: stage_03_blender_io_import_fbx - {e}')
        trace.append({'step': 3, 'name': 'stage_03_blender_io_import_fbx', 'host': 'blender', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step3_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 3 failed: {e}')
        traceback.print_exc()
        raise

    # Step 4: stage_04_blender_pipeline_process_meshes_for_transfer (function)
    print('[Pipeline 4/7] START BLENDER: stage_04_blender_pipeline_process_meshes_for_transfer')
    try:
        _step4_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'objects': [], 'clean_names': True, 'apply_transforms': True, 'lod_count': 0, 'ensure_material_slots': True, 'create_collision': True}
        step4_result = execute_pipeline_operation(
            'blender', 'pipeline.process_meshes_for_transfer', 'blender_tools.pipeline_transfer.process_meshes_for_transfer', _operation_params
        )
        step4_outputs = {}
        step4_outputs['blender_scene'] = step4_result.get('blender_scene', None)
        if step4_outputs['blender_scene'] is None:
            raise RuntimeError('DCC stage did not return required output: blender_scene')
        step4_outputs['meshes'] = step4_result.get('meshes', None)
        if step4_outputs['meshes'] is None:
            raise RuntimeError('DCC stage did not return required output: meshes')
        step4_outputs['materials'] = step4_result.get('materials', None)
        if step4_outputs['materials'] is None:
            raise RuntimeError('DCC stage did not return required output: materials')
        step4_outputs['collision'] = step4_result.get('collision', None)
        if step4_outputs['collision'] is None:
            raise RuntimeError('DCC stage did not return required output: collision')
        step4_outputs['lods'] = step4_result.get('lods', None)
        if step4_outputs['lods'] is None:
            raise RuntimeError('DCC stage did not return required output: lods')
        outputs['step4'] = step4_outputs
        results['step4'] = step4_result
        print(f'[Pipeline 4/7] COMPLETE BLENDER: stage_04_blender_pipeline_process_meshes_for_transfer ({(time.perf_counter() - _step4_started) * 1000.0:.1f} ms)')
        trace.append({'step': 4, 'name': 'stage_04_blender_pipeline_process_meshes_for_transfer', 'host': 'blender', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step4_started) * 1000.0, 3), 'rollback': step4_result.get('rollback') if isinstance(step4_result, dict) else None, 'outputs': step4_outputs, 'result': step4_result})
    except Exception as e:
        print(f'[Pipeline 4/7] FAILED BLENDER: stage_04_blender_pipeline_process_meshes_for_transfer - {e}')
        trace.append({'step': 4, 'name': 'stage_04_blender_pipeline_process_meshes_for_transfer', 'host': 'blender', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step4_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 4 failed: {e}')
        traceback.print_exc()
        raise

    # Step 5: stage_05_blender_blender_export_fbx (function)
    print('[Pipeline 5/7] START BLENDER: stage_05_blender_blender_export_fbx')
    try:
        _step5_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'selection': step5_selection, 'settings': {'axis_forward': '-Y', 'axis_up': 'Z', 'apply_unit_scale': True, 'bake_animation': True}, 'output_path': 'C:/tmp/tc_chain_blender.fbx'}
        step5_result = execute_pipeline_operation(
            'blender', 'blender.export_fbx', 'ai_studio.blender.generated.blender_export_fbx', _operation_params
        )
        step5_outputs = {}
        step5_outputs['fbx_path'] = step5_result.get('fbx_path', _operation_params.get('output_path'))
        if step5_outputs['fbx_path'] is None:
            raise RuntimeError('DCC stage did not return required output: fbx_path')
        outputs['step5'] = step5_outputs
        results['step5'] = step5_result
        print(f'[Pipeline 5/7] COMPLETE BLENDER: stage_05_blender_blender_export_fbx ({(time.perf_counter() - _step5_started) * 1000.0:.1f} ms)')
        trace.append({'step': 5, 'name': 'stage_05_blender_blender_export_fbx', 'host': 'blender', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step5_started) * 1000.0, 3), 'rollback': step5_result.get('rollback') if isinstance(step5_result, dict) else None, 'outputs': step5_outputs, 'result': step5_result})
    except Exception as e:
        print(f'[Pipeline 5/7] FAILED BLENDER: stage_05_blender_blender_export_fbx - {e}')
        trace.append({'step': 5, 'name': 'stage_05_blender_blender_export_fbx', 'host': 'blender', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step5_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 5 failed: {e}')
        traceback.print_exc()
        raise

    # Step 6: stage_06_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified (function)
    print('[Pipeline 6/7] START UNREAL: stage_06_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified')
    try:
        _step6_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'destination_path': '/Game/AIStudio/Validation/Chain', 'subject': 'skeletal_mesh', 'skeleton_path': step6_skeleton_path, 'replace_existing': False, 'save': True, 'source_file': outputs['step5']['fbx_path']}
        step6_result = execute_pipeline_operation(
            'unreal', 'unreal_tools.asset_transfer_adapter.import_fbx_verified', 'unreal_tools.asset_transfer_adapter.import_fbx_verified', _operation_params
        )
        step6_outputs = {}
        step6_outputs['asset_path'] = step6_result.get('asset_path', None)
        if step6_outputs['asset_path'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_path')
        step6_outputs['imported_paths'] = step6_result.get('imported_paths', None)
        if step6_outputs['imported_paths'] is None:
            raise RuntimeError('DCC stage did not return required output: imported_paths')
        step6_outputs['asset_count'] = step6_result.get('asset_count', None)
        if step6_outputs['asset_count'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_count')
        outputs['step6'] = step6_outputs
        results['step6'] = step6_result
        print(f'[Pipeline 6/7] COMPLETE UNREAL: stage_06_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified ({(time.perf_counter() - _step6_started) * 1000.0:.1f} ms)')
        trace.append({'step': 6, 'name': 'stage_06_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step6_started) * 1000.0, 3), 'rollback': step6_result.get('rollback') if isinstance(step6_result, dict) else None, 'outputs': step6_outputs, 'result': step6_result})
    except Exception as e:
        print(f'[Pipeline 6/7] FAILED UNREAL: stage_06_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified - {e}')
        trace.append({'step': 6, 'name': 'stage_06_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step6_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 6 failed: {e}')
        traceback.print_exc()
        raise

    # Step 7: stage_07_unreal_unreal_tools_asset_transfer_adapter_registry_readback (function)
    print('[Pipeline 7/7] START UNREAL: stage_07_unreal_unreal_tools_asset_transfer_adapter_registry_readback')
    try:
        _step7_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'imported_paths': outputs['step6']['imported_paths'], 'destination_path': step7_destination_path}
        step7_result = execute_pipeline_operation(
            'unreal', 'unreal_tools.asset_transfer_adapter.registry_readback', 'unreal_tools.asset_transfer_adapter.registry_readback', _operation_params
        )
        step7_outputs = {}
        step7_outputs['assets'] = step7_result.get('assets', None)
        if step7_outputs['assets'] is None:
            raise RuntimeError('DCC stage did not return required output: assets')
        step7_outputs['asset_count'] = step7_result.get('asset_count', None)
        if step7_outputs['asset_count'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_count')
        outputs['step7'] = step7_outputs
        results['step7'] = step7_result
        print(f'[Pipeline 7/7] COMPLETE UNREAL: stage_07_unreal_unreal_tools_asset_transfer_adapter_registry_readback ({(time.perf_counter() - _step7_started) * 1000.0:.1f} ms)')
        trace.append({'step': 7, 'name': 'stage_07_unreal_unreal_tools_asset_transfer_adapter_registry_readback', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step7_started) * 1000.0, 3), 'rollback': step7_result.get('rollback') if isinstance(step7_result, dict) else None, 'outputs': step7_outputs, 'result': step7_result})
    except Exception as e:
        print(f'[Pipeline 7/7] FAILED UNREAL: stage_07_unreal_unreal_tools_asset_transfer_adapter_registry_readback - {e}')
        trace.append({'step': 7, 'name': 'stage_07_unreal_unreal_tools_asset_transfer_adapter_registry_readback', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step7_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 7 failed: {e}')
        traceback.print_exc()
        raise

    print('[Pipeline] COMPLETE: 7 stage(s) succeeded')
    return results.get('step7')
