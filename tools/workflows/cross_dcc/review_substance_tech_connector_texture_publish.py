"""Generated pipeline.
Goal: Create a Substance Painter to Tech Connector texture publishing pipeline. Export the current texture sets and import the texture images into project folder Assets/Materials.

Flow edges control execution order only.
Data edges bind return/output values into downstream function arguments.
"""
import importlib
import json
import time
import traceback

def review_substance_tech_connector_texture_publish(response):
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

def review_substance_tech_connector_texture_publish(session_ports=None, require_live_preflight=True, operation_timeout_seconds=120.0, step2_type_id=None):
    global _TC_PIPELINE_LAST_TRACE
    results = {}
    outputs = {}
    trace = []
    _TC_PIPELINE_LAST_TRACE = trace
    _tc_pipeline_hosts = ['substance_painter']
    _tc_pipeline_callables = {'substance_painter': ['substance_painter_tools.textures.export_textures']}
    _tc_session_ports = dict(session_ports or {})
    if require_live_preflight and _tc_pipeline_hosts:
        from tech_connector.game_engine.integration.pipeline_execution_preflight_service import resolve_pipeline_session_ports
        _tc_session_ports = resolve_pipeline_session_ports(_tc_pipeline_hosts, session_ports=_tc_session_ports, callables_by_host=_tc_pipeline_callables, timeout_seconds=operation_timeout_seconds)
    flow_links = [{'from': 'step1', 'to': 'step2'}]
    print('[Pipeline 1/2] START SUBSTANCE_PAINTER: stage_01_substance_painter_textures_export')
    try:
        _step1_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'output_path': '${pipeline_workspace}/stage_01_substance_painter_textures_export', 'preset_name': 'PBR Metallic Roughness', 'resolution': 2048}
        step1_result = execute_pipeline_operation('substance_painter', 'textures.export', 'substance_painter_tools.textures.export_textures', _operation_params, session_port=_tc_session_ports.get('substance_painter'), timeout_seconds=operation_timeout_seconds)
        step1_outputs = {}
        step1_outputs['texture_paths'] = step1_result.get('texture_paths', None)
        if step1_outputs['texture_paths'] is None:
            raise RuntimeError('DCC stage did not return required output: texture_paths')
        outputs['step1'] = step1_outputs
        results['step1'] = step1_result
        print(f'[Pipeline 1/2] COMPLETE SUBSTANCE_PAINTER: stage_01_substance_painter_textures_export ({(time.perf_counter() - _step1_started) * 1000.0:.1f} ms)')
        trace.append({'step': 1, 'name': 'stage_01_substance_painter_textures_export', 'host': 'substance_painter', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': step1_result.get('rollback') if isinstance(step1_result, dict) else None, 'outputs': step1_outputs, 'result': step1_result})
    except Exception as e:
        print(f'[Pipeline 1/2] FAILED SUBSTANCE_PAINTER: stage_01_substance_painter_textures_export - {e}')
        trace.append({'step': 1, 'name': 'stage_01_substance_painter_textures_export', 'host': 'substance_painter', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step1_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 1 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline 2/2] START TECH_CONNECTOR: stage_02_tech_connector_asset_import_interchange')
    try:
        _step2_started = time.perf_counter()
        from tech_connector.game_engine.integration.pipeline_operation_runtime_service import execute_pipeline_operation
        _operation_params = {'source_file': outputs['step1']['texture_paths'], 'project_root': 'C:\\depot\\tools', 'folder': 'Assets', 'type_id': step2_type_id, 'importer_settings': {}}
        step2_result = execute_pipeline_operation('tech_connector', 'asset.import_interchange', 'tech_connector.game_engine.integration.tech_connector_pipeline_adapter.import_interchange_asset', _operation_params, session_port=_tc_session_ports.get('tech_connector'), timeout_seconds=operation_timeout_seconds)
        step2_outputs = {}
        step2_outputs['asset_id'] = step2_result.get('asset_id', None)
        if step2_outputs['asset_id'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_id')
        step2_outputs['asset_path'] = step2_result.get('asset_path', None)
        if step2_outputs['asset_path'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_path')
        step2_outputs['asset_type'] = step2_result.get('asset_type', None)
        if step2_outputs['asset_type'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_type')
        step2_outputs['asset_ids'] = step2_result.get('asset_ids', None)
        if step2_outputs['asset_ids'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_ids')
        step2_outputs['asset_paths'] = step2_result.get('asset_paths', None)
        if step2_outputs['asset_paths'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_paths')
        step2_outputs['asset_types'] = step2_result.get('asset_types', None)
        if step2_outputs['asset_types'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_types')
        step2_outputs['asset_count'] = step2_result.get('asset_count', None)
        if step2_outputs['asset_count'] is None:
            raise RuntimeError('DCC stage did not return required output: asset_count')
        step2_outputs['imported_paths'] = step2_result.get('imported_paths', None)
        if step2_outputs['imported_paths'] is None:
            raise RuntimeError('DCC stage did not return required output: imported_paths')
        outputs['step2'] = step2_outputs
        results['step2'] = step2_result
        print(f'[Pipeline 2/2] COMPLETE TECH_CONNECTOR: stage_02_tech_connector_asset_import_interchange ({(time.perf_counter() - _step2_started) * 1000.0:.1f} ms)')
        trace.append({'step': 2, 'name': 'stage_02_tech_connector_asset_import_interchange', 'host': 'tech_connector', 'ok': True, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': step2_result.get('rollback') if isinstance(step2_result, dict) else None, 'outputs': step2_outputs, 'result': step2_result})
    except Exception as e:
        print(f'[Pipeline 2/2] FAILED TECH_CONNECTOR: stage_02_tech_connector_asset_import_interchange - {e}')
        trace.append({'step': 2, 'name': 'stage_02_tech_connector_asset_import_interchange', 'host': 'tech_connector', 'ok': False, 'elapsed_ms': round((time.perf_counter() - _step2_started) * 1000.0, 3), 'rollback': getattr(e, 'rollback', None), 'error': str(e)})
        print(f'Step 2 failed: {e}')
        traceback.print_exc()
        raise
    print('[Pipeline] COMPLETE: 2 stage(s) succeeded')
    return results.get('step2')
