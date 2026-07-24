"""Generated pipeline.
Goal: Build a MotionBuilder to Blender to Unreal gameplay animation pipeline: export current take to C:/tmp/mb_sprint.fbx, Blender import, clean curves and bake frames 1-90, export C:/tmp/blender_sprint.fbx, Unreal import /Game/Characters/Animations using skeleton /Game/Characters/Mannequins/Meshes/SK_Mannequin.SK_Mannequin, inspect root motion and skeleton compatibility, retarget only incompatible clips, create BlendSpace /Game/Characters/Animations/BS_Sprint, save everything, report.

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

def mb_blender_unreal_sprint(step3_armature=None, step3_action=None, step4_selection=None, step6_target_skeletal_mesh_path=None, step7_source_skeletal_mesh_path=None, step7_target_skeletal_mesh_path=None, step7_retargeter_path=None, step9_target_anim_blueprint_path=None, step10_destination_path=None):
    global _TC_PIPELINE_LAST_TRACE
    results = {}
    outputs = {}
    trace = []
    _TC_PIPELINE_LAST_TRACE = trace
    flow_links = [{'from': 'step1.flow', 'to': 'step2.flow'}, {'from': 'step2.flow', 'to': 'step3.flow'}, {'from': 'step3.flow', 'to': 'step4.flow'}, {'from': 'step4.flow', 'to': 'step5.flow'}, {'from': 'step5.flow', 'to': 'step6.flow'}, {'from': 'step6.flow', 'to': 'step7.flow'}, {'from': 'step7.flow', 'to': 'step8.flow'}, {'from': 'step8.flow', 'to': 'step9.flow'}, {'from': 'step9.flow', 'to': 'step10.flow'}]

    # Step 1: stage_01_motionbuilder_io_export_fbx (function)
    print('[Pipeline 1/10] START MOTIONBUILDER: stage_01_motionbuilder_io_export_fbx')
    try:
        _step1_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'selected_only': False, 'filepath': 'C:/tmp/mb_sprint.fbx'}
        step1_result = execute_pipeline_operation(
            'motionbuilder', 'io.export_fbx', 'motionbuilder_tools.io.export_fbx', _operation_params
        )
        step1_outputs = {}
        step1_outputs['fbx_path'] = step1_result.get('fbx_path', _operation_params.get('filepath'))
        if step1_outputs['fbx_path'] is None:
            raise RuntimeError('DCC stage did not return required output: fbx_path')
        outputs['step1'] = step1_outputs
        results['step1'] = step1_result
        print(f'[Pipeline 1/10] COMPLETE MOTIONBUILDER: stage_01_motionbuilder_io_export_fbx ({(time.perf_counter() - _step1_started) * 1000.0:.1f} ms)')
        trace.append({'step': 1, 'name': 'stage_01_motionbuilder_io_export_fbx', 'host': 'motionbuilder', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': step1_result.get('rollback') if isinstance(step1_result, dict) else None, 'outputs': step1_outputs, 'result': step1_result})
    except Exception as e:
        print(f'[Pipeline 1/10] FAILED MOTIONBUILDER: stage_01_motionbuilder_io_export_fbx - {e}')
        trace.append({'step': 1, 'name': 'stage_01_motionbuilder_io_export_fbx', 'host': 'motionbuilder', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 1 failed: {e}')
        traceback.print_exc()
        raise

    # Step 2: stage_02_blender_io_import_fbx (function)
    print('[Pipeline 2/10] START BLENDER: stage_02_blender_io_import_fbx')
    try:
        _step2_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'use_image_search': True, 'filepath': outputs['step1']['fbx_path']}
        step2_result = execute_pipeline_operation(
            'blender', 'io.import_fbx', 'blender_tools.io.import_fbx', _operation_params
        )
        step2_outputs = {}
        step2_outputs['blender_scene'] = step2_result.get('blender_scene', None)
        if step2_outputs['blender_scene'] is None:
            raise RuntimeError('DCC stage did not return required output: blender_scene')
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
        print(f'[Pipeline 2/10] COMPLETE BLENDER: stage_02_blender_io_import_fbx ({(time.perf_counter() - _step2_started) * 1000.0:.1f} ms)')
        trace.append({'step': 2, 'name': 'stage_02_blender_io_import_fbx', 'host': 'blender', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': step2_result.get('rollback') if isinstance(step2_result, dict) else None, 'outputs': step2_outputs, 'result': step2_result})
    except Exception as e:
        print(f'[Pipeline 2/10] FAILED BLENDER: stage_02_blender_io_import_fbx - {e}')
        trace.append({'step': 2, 'name': 'stage_02_blender_io_import_fbx', 'host': 'blender', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 2 failed: {e}')
        traceback.print_exc()
        raise

    # Step 3: stage_03_blender_blender_clean_animation (function)
    print('[Pipeline 3/10] START BLENDER: stage_03_blender_blender_clean_animation')
    try:
        _step3_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'armature': step3_armature, 'action': step3_action, 'frame_range': [1, 90], 'cleanup': []}
        step3_result = execute_pipeline_operation(
            'blender', 'blender.clean_animation', 'ai_studio.blender.generated.blender_clean_animation', _operation_params
        )
        step3_outputs = {}
        step3_outputs['animations'] = step3_result.get('animations', None)
        if step3_outputs['animations'] is None:
            raise RuntimeError('DCC stage did not return required output: animations')
        outputs['step3'] = step3_outputs
        results['step3'] = step3_result
        print(f'[Pipeline 3/10] COMPLETE BLENDER: stage_03_blender_blender_clean_animation ({(time.perf_counter() - _step3_started) * 1000.0:.1f} ms)')
        trace.append({'step': 3, 'name': 'stage_03_blender_blender_clean_animation', 'host': 'blender', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step3_started) * 1000.0, 3), 'rollback': step3_result.get('rollback') if isinstance(step3_result, dict) else None, 'outputs': step3_outputs, 'result': step3_result})
    except Exception as e:
        print(f'[Pipeline 3/10] FAILED BLENDER: stage_03_blender_blender_clean_animation - {e}')
        trace.append({'step': 3, 'name': 'stage_03_blender_blender_clean_animation', 'host': 'blender', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step3_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 3 failed: {e}')
        traceback.print_exc()
        raise

    # Step 4: stage_04_blender_blender_export_fbx (function)
    print('[Pipeline 4/10] START BLENDER: stage_04_blender_blender_export_fbx')
    try:
        _step4_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'selection': step4_selection, 'settings': {'axis_forward': '-Y', 'axis_up': 'Z', 'apply_unit_scale': True, 'bake_animation': True}, 'output_path': 'C:/tmp/blender_sprint.fbx'}
        step4_result = execute_pipeline_operation(
            'blender', 'blender.export_fbx', 'ai_studio.blender.generated.blender_export_fbx', _operation_params
        )
        step4_outputs = {}
        step4_outputs['fbx_path'] = step4_result.get('fbx_path', _operation_params.get('output_path'))
        if step4_outputs['fbx_path'] is None:
            raise RuntimeError('DCC stage did not return required output: fbx_path')
        outputs['step4'] = step4_outputs
        results['step4'] = step4_result
        print(f'[Pipeline 4/10] COMPLETE BLENDER: stage_04_blender_blender_export_fbx ({(time.perf_counter() - _step4_started) * 1000.0:.1f} ms)')
        trace.append({'step': 4, 'name': 'stage_04_blender_blender_export_fbx', 'host': 'blender', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step4_started) * 1000.0, 3), 'rollback': step4_result.get('rollback') if isinstance(step4_result, dict) else None, 'outputs': step4_outputs, 'result': step4_result})
    except Exception as e:
        print(f'[Pipeline 4/10] FAILED BLENDER: stage_04_blender_blender_export_fbx - {e}')
        trace.append({'step': 4, 'name': 'stage_04_blender_blender_export_fbx', 'host': 'blender', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step4_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 4 failed: {e}')
        traceback.print_exc()
        raise

    # Step 5: stage_05_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified (function)
    print('[Pipeline 5/10] START UNREAL: stage_05_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified')
    try:
        _step5_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'destination_path': '/Game/Characters/Animations', 'subject': 'animation', 'skeleton_path': '/Game/Characters/Mannequins/Meshes/SK_Mannequin.SK_Mannequin', 'replace_existing': False, 'save': True, 'source_file': outputs['step4']['fbx_path']}
        step5_result = execute_pipeline_operation(
            'unreal', 'unreal_tools.asset_transfer_adapter.import_fbx_verified', 'unreal_tools.asset_transfer_adapter.import_fbx_verified', _operation_params
        )
        step5_outputs = {}
        step5_outputs['asset_path'] = step5_result.get('asset_path', None)
        if step5_outputs['asset_path'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_path')
        step5_outputs['imported_paths'] = step5_result.get('imported_paths', None)
        if step5_outputs['imported_paths'] is None:
            raise RuntimeError('DCC stage did not return required output: imported_paths')
        step5_outputs['asset_count'] = step5_result.get('asset_count', None)
        if step5_outputs['asset_count'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_count')
        outputs['step5'] = step5_outputs
        results['step5'] = step5_result
        print(f'[Pipeline 5/10] COMPLETE UNREAL: stage_05_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified ({(time.perf_counter() - _step5_started) * 1000.0:.1f} ms)')
        trace.append({'step': 5, 'name': 'stage_05_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step5_started) * 1000.0, 3), 'rollback': step5_result.get('rollback') if isinstance(step5_result, dict) else None, 'outputs': step5_outputs, 'result': step5_result})
    except Exception as e:
        print(f'[Pipeline 5/10] FAILED UNREAL: stage_05_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified - {e}')
        trace.append({'step': 5, 'name': 'stage_05_unreal_unreal_tools_asset_transfer_adapter_import_fbx_verified', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step5_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 5 failed: {e}')
        traceback.print_exc()
        raise

    # Step 6: stage_06_unreal_animation_inspect_imported_pipeline (function)
    print('[Pipeline 6/10] START UNREAL: stage_06_unreal_animation_inspect_imported_pipeline')
    try:
        _step6_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'target_skeleton_path': '/Game/Characters/Mannequins/Meshes/SK_Mannequin.SK_Mannequin', 'target_skeletal_mesh_path': step6_target_skeletal_mesh_path, 'imported_paths': outputs['step5']['imported_paths']}
        step6_result = execute_pipeline_operation(
            'unreal', 'animation.inspect_imported_pipeline', 'unreal_tools.animation.inspect_imported_animation_pipeline', _operation_params
        )
        step6_outputs = {}
        step6_outputs['compatibility_report'] = step6_result.get('compatibility_report', None)
        if step6_outputs['compatibility_report'] is None:
            raise RuntimeError('DCC stage did not return required output: compatibility_report')
        step6_outputs['animation_paths'] = step6_result.get('animation_paths', None)
        if step6_outputs['animation_paths'] is None:
            raise RuntimeError('DCC stage did not return required output: animation_paths')
        outputs['step6'] = step6_outputs
        results['step6'] = step6_result
        print(f'[Pipeline 6/10] COMPLETE UNREAL: stage_06_unreal_animation_inspect_imported_pipeline ({(time.perf_counter() - _step6_started) * 1000.0:.1f} ms)')
        trace.append({'step': 6, 'name': 'stage_06_unreal_animation_inspect_imported_pipeline', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step6_started) * 1000.0, 3), 'rollback': step6_result.get('rollback') if isinstance(step6_result, dict) else None, 'outputs': step6_outputs, 'result': step6_result})
    except Exception as e:
        print(f'[Pipeline 6/10] FAILED UNREAL: stage_06_unreal_animation_inspect_imported_pipeline - {e}')
        trace.append({'step': 6, 'name': 'stage_06_unreal_animation_inspect_imported_pipeline', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step6_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 6 failed: {e}')
        traceback.print_exc()
        raise

    # Step 7: stage_07_unreal_animation_retarget_imported_if_needed (function)
    print('[Pipeline 7/10] START UNREAL: stage_07_unreal_animation_retarget_imported_if_needed')
    try:
        _step7_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'source_skeletal_mesh_path': step7_source_skeletal_mesh_path, 'target_skeletal_mesh_path': step7_target_skeletal_mesh_path, 'output_path': '/Game/Animations/Retargeted', 'retargeter_path': step7_retargeter_path, 'compatibility_report': outputs['step6']['compatibility_report']}
        step7_result = execute_pipeline_operation(
            'unreal', 'animation.retarget_imported_if_needed', 'unreal_tools.animation.retarget_imported_animations_if_needed', _operation_params
        )
        step7_outputs = {}
        step7_outputs['animation_paths'] = step7_result.get('animation_paths', None)
        if step7_outputs['animation_paths'] is None:
            raise RuntimeError('DCC stage did not return required output: animation_paths')
        step7_outputs['retarget_report'] = step7_result.get('retarget_report', None)
        if step7_outputs['retarget_report'] is None:
            raise RuntimeError('DCC stage did not return required output: retarget_report')
        outputs['step7'] = step7_outputs
        results['step7'] = step7_result
        print(f'[Pipeline 7/10] COMPLETE UNREAL: stage_07_unreal_animation_retarget_imported_if_needed ({(time.perf_counter() - _step7_started) * 1000.0:.1f} ms)')
        trace.append({'step': 7, 'name': 'stage_07_unreal_animation_retarget_imported_if_needed', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step7_started) * 1000.0, 3), 'rollback': step7_result.get('rollback') if isinstance(step7_result, dict) else None, 'outputs': step7_outputs, 'result': step7_result})
    except Exception as e:
        print(f'[Pipeline 7/10] FAILED UNREAL: stage_07_unreal_animation_retarget_imported_if_needed - {e}')
        trace.append({'step': 7, 'name': 'stage_07_unreal_animation_retarget_imported_if_needed', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step7_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 7 failed: {e}')
        traceback.print_exc()
        raise

    # Step 8: stage_08_unreal_unreal_create_blendspace (function)
    print('[Pipeline 8/10] START UNREAL: stage_08_unreal_unreal_create_blendspace')
    try:
        _step8_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'samples': [], 'animation_paths': outputs['step7']['animation_paths'], 'sample_layout': 'speed_line', 'axis_x': None, 'axis_y': None, 'save': True, 'asset_path': '/Game/Characters/Animations/BS_Sprint', 'skeleton_path': '/Game/Characters/Mannequins/Meshes/SK_Mannequin.SK_Mannequin'}
        step8_result = execute_pipeline_operation(
            'unreal', 'unreal.create_blendspace', 'unreal_tools.animation.create_blendspace', _operation_params
        )
        step8_outputs = {}
        step8_outputs['blendspace_path'] = step8_result.get('blendspace_path', None)
        if step8_outputs['blendspace_path'] is None:
            raise RuntimeError('DCC stage did not return required output: blendspace_path')
        outputs['step8'] = step8_outputs
        results['step8'] = step8_result
        print(f'[Pipeline 8/10] COMPLETE UNREAL: stage_08_unreal_unreal_create_blendspace ({(time.perf_counter() - _step8_started) * 1000.0:.1f} ms)')
        trace.append({'step': 8, 'name': 'stage_08_unreal_unreal_create_blendspace', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step8_started) * 1000.0, 3), 'rollback': step8_result.get('rollback') if isinstance(step8_result, dict) else None, 'outputs': step8_outputs, 'result': step8_result})
    except Exception as e:
        print(f'[Pipeline 8/10] FAILED UNREAL: stage_08_unreal_unreal_create_blendspace - {e}')
        trace.append({'step': 8, 'name': 'stage_08_unreal_unreal_create_blendspace', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step8_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 8 failed: {e}')
        traceback.print_exc()
        raise

    # Step 9: stage_09_unreal_animation_report_pipeline_assets (function)
    print('[Pipeline 9/10] START UNREAL: stage_09_unreal_animation_report_pipeline_assets')
    try:
        _step9_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'target_skeleton_path': '/Game/Characters/Mannequins/Meshes/SK_Mannequin.SK_Mannequin', 'target_anim_blueprint_path': step9_target_anim_blueprint_path, 'imported_paths': outputs['step5']['imported_paths'], 'animation_paths': outputs['step7']['animation_paths']}
        step9_result = execute_pipeline_operation(
            'unreal', 'animation.report_pipeline_assets', 'unreal_tools.animation.report_animation_pipeline_assets', _operation_params
        )
        step9_outputs = {}
        step9_outputs['pipeline_report'] = step9_result.get('pipeline_report', None)
        if step9_outputs['pipeline_report'] is None:
            raise RuntimeError('DCC stage did not return required output: pipeline_report')
        outputs['step9'] = step9_outputs
        results['step9'] = step9_result
        print(f'[Pipeline 9/10] COMPLETE UNREAL: stage_09_unreal_animation_report_pipeline_assets ({(time.perf_counter() - _step9_started) * 1000.0:.1f} ms)')
        trace.append({'step': 9, 'name': 'stage_09_unreal_animation_report_pipeline_assets', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step9_started) * 1000.0, 3), 'rollback': step9_result.get('rollback') if isinstance(step9_result, dict) else None, 'outputs': step9_outputs, 'result': step9_result})
    except Exception as e:
        print(f'[Pipeline 9/10] FAILED UNREAL: stage_09_unreal_animation_report_pipeline_assets - {e}')
        trace.append({'step': 9, 'name': 'stage_09_unreal_animation_report_pipeline_assets', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step9_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 9 failed: {e}')
        traceback.print_exc()
        raise

    # Step 10: stage_10_unreal_unreal_tools_asset_transfer_adapter_registry_readback (function)
    print('[Pipeline 10/10] START UNREAL: stage_10_unreal_unreal_tools_asset_transfer_adapter_registry_readback')
    try:
        _step10_started = time.perf_counter()
        from tech_connector.services.dcc.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'imported_paths': outputs['step5']['imported_paths'], 'destination_path': step10_destination_path}
        step10_result = execute_pipeline_operation(
            'unreal', 'unreal_tools.asset_transfer_adapter.registry_readback', 'unreal_tools.asset_transfer_adapter.registry_readback', _operation_params
        )
        step10_outputs = {}
        step10_outputs['assets'] = step10_result.get('assets', None)
        if step10_outputs['assets'] is None:
            raise RuntimeError('DCC stage did not return required output: assets')
        step10_outputs['asset_count'] = step10_result.get('asset_count', None)
        if step10_outputs['asset_count'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_count')
        outputs['step10'] = step10_outputs
        results['step10'] = step10_result
        print(f'[Pipeline 10/10] COMPLETE UNREAL: stage_10_unreal_unreal_tools_asset_transfer_adapter_registry_readback ({(time.perf_counter() - _step10_started) * 1000.0:.1f} ms)')
        trace.append({'step': 10, 'name': 'stage_10_unreal_unreal_tools_asset_transfer_adapter_registry_readback', 'host': 'unreal', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step10_started) * 1000.0, 3), 'rollback': step10_result.get('rollback') if isinstance(step10_result, dict) else None, 'outputs': step10_outputs, 'result': step10_result})
    except Exception as e:
        print(f'[Pipeline 10/10] FAILED UNREAL: stage_10_unreal_unreal_tools_asset_transfer_adapter_registry_readback - {e}')
        trace.append({'step': 10, 'name': 'stage_10_unreal_unreal_tools_asset_transfer_adapter_registry_readback', 'host': 'unreal', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step10_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 10 failed: {e}')
        traceback.print_exc()
        raise

    print('[Pipeline] COMPLETE: 10 stage(s) succeeded')
    return results.get('step10')