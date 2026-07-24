# Pipeline View Python Tab Examples

These examples are shaped like the Pipeline View code generator output. Paste one whole block into the Pipeline Python tab. The first function is the entry point.

## 1. Maya HIK Mocap Rig To MotionBuilder Review

```python
"""Generated pipeline.
Goal: Create a mocap HIK rig mapping in Maya, export an FBX for MotionBuilder, then open/review it in MotionBuilder.

Flow edges control execution order only.
Data edges bind return/output values into downstream function arguments.
"""

import importlib
import traceback

def maya_hik_mocap_to_motionbuilder(step1_root_joint=None, step2_character_name='AIStudio_MocapCharacter', step2_fbx_export_path='C:/tmp/ai_studio_mocap_character.fbx', step2_namespace='', step3_host='127.0.0.1', step3_timeout=10):
    results = {}
    outputs = {}
    flow_links = [{'from': 'step1', 'to': 'step2', 'type': 'flow'}, {'from': 'step2', 'to': 'step3', 'type': 'flow'}]

    # Step 1: create_rig_mapping (function)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('step1_mod', 'C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = getattr(module, 'create_rig_mapping')
        create_rig_mapping = target
        step1_result = create_rig_mapping(root_joint=step1_root_joint)
        step1_outputs = {}
        if not isinstance(step1_result, (tuple, list)):
            raise RuntimeError('Step 1 expected multiple outputs but returned a single value')
        body_joint_map = step1_result[0]
        step1_outputs['body_joint_map'] = body_joint_map
        face_joint_map = step1_result[1]
        step1_outputs['face_joint_map'] = face_joint_map
        outputs['step1'] = step1_outputs
        results['step1'] = step1_result
    except Exception as e:
        print(f'Step 1 failed: {e}')
        traceback.print_exc()
        raise

    # Step 2: setup_hik_character (function)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('step2_mod', 'C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = getattr(module, 'setup_hik_character')
        setup_hik_character = target
        step2_result = setup_hik_character(character_name=step2_character_name, joint_map=outputs['step1']['body_joint_map'], fbx_export_path=step2_fbx_export_path, namespace=step2_namespace)
        step2_outputs = {'result': step2_result, 'fbx_export_path': step2_fbx_export_path}
        outputs['step2'] = step2_outputs
        results['step2'] = step2_result
    except Exception as e:
        print(f'Step 2 failed: {e}')
        traceback.print_exc()
        raise

    # Step 3: send_to_motionbuilder (function)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('step3_mod', 'C:/depot/tools/tech_connector/bridges/motionbuilder/motionbuilder_mcp_server.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = getattr(module, 'send_to_motionbuilder')
        send_to_motionbuilder = target
        step3_code = (
            "import json, os\\n"
            "from pyfbsdk import FBApplication, FBSystem\\n"
            "fbx_path = " + repr(outputs['step2']['fbx_export_path']) + "\\n"
            "result = {'ok': False, 'fbx_path': fbx_path, 'takes': [], 'error': ''}\\n"
            "try:\\n"
            "    if not os.path.exists(fbx_path):\\n"
            "        raise RuntimeError('FBX file does not exist: ' + fbx_path)\\n"
            "    app = FBApplication()\\n"
            "    app.FileOpen(fbx_path)\\n"
            "    result['takes'] = [take.Name for take in FBSystem().Scene.Takes]\\n"
            "    result['ok'] = True\\n"
            "except Exception as exc:\\n"
            "    result['error'] = str(exc)\\n"
            "print(json.dumps(result, default=str))\\n"
        )
        step3_result = send_to_motionbuilder(code=step3_code, host=step3_host, timeout=step3_timeout)
        step3_outputs = {'result': step3_result}
        outputs['step3'] = step3_outputs
        results['step3'] = step3_result
    except Exception as e:
        print(f'Step 3 failed: {e}')
        traceback.print_exc()
        raise

    return results.get('step3')
```

## 2. Maya Rig Mapping To Project Rig

```python
"""Generated pipeline.
Goal: Create a Maya rig mapping and build the project rig from mapped body and face joints.

Flow edges control execution order only.
Data edges bind return/output values into downstream function arguments.
"""

import importlib
import traceback

def maya_mapping_to_project_rig(step1_root_joint=None):
    results = {}
    outputs = {}
    flow_links = [{'from': 'step1', 'to': 'step2', 'type': 'flow'}]

    # Step 1: create_rig_mapping (function)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('step1_mod', 'C:/depot/tools/maya_tools/Rigging/mocap/setup_hik.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = getattr(module, 'create_rig_mapping')
        create_rig_mapping = target
        step1_result = create_rig_mapping(root_joint=step1_root_joint)
        step1_outputs = {}
        if not isinstance(step1_result, (tuple, list)):
            raise RuntimeError('Step 1 expected multiple outputs but returned a single value')
        body_joint_map = step1_result[0]
        step1_outputs['body_joint_map'] = body_joint_map
        face_joint_map = step1_result[1]
        step1_outputs['face_joint_map'] = face_joint_map
        outputs['step1'] = step1_outputs
        results['step1'] = step1_result
    except Exception as e:
        print(f'Step 1 failed: {e}')
        traceback.print_exc()
        raise

    # Step 2: create_rig_from_mapping (function)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('step2_mod', 'C:/depot/tools/maya_tools/Rigging/create_rig.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = getattr(module, 'create_rig_from_mapping')
        create_rig_from_mapping = target
        step2_result = create_rig_from_mapping(body_joint_map=outputs['step1']['body_joint_map'], face_joint_map=outputs['step1']['face_joint_map'])
        step2_outputs = {'result': step2_result}
        outputs['step2'] = step2_outputs
        results['step2'] = step2_result
    except Exception as e:
        print(f'Step 2 failed: {e}')
        traceback.print_exc()
        raise

    return results.get('step2')
```

## 3. Unreal Niagara Weapon FX

```python
"""Generated pipeline.
Goal: Create Niagara muzzle/impact emitters, inspect weapon/enemy Blueprints, compile them, and return the FX asset results.

Flow edges control execution order only.
Data edges bind return/output values into downstream function arguments.
"""

import importlib
import traceback

def unreal_niagara_weapon_fx_pipeline(step1_asset_path='/Game/AIStudio/FX/NE_MuzzleFlash', step1_template='empty', step1_parameters=None, step2_asset_path='/Game/AIStudio/FX/NE_BulletImpact', step2_template='empty', step2_parameters=None, step3_asset_path='/Game/Weapons/BP_Rifle.BP_Rifle', step4_asset_path='/Game/Characters/BP_Enemy.BP_Enemy'):
    results = {}
    outputs = {}
    flow_links = [{'from': 'step1', 'to': 'step2', 'type': 'flow'}, {'from': 'step2', 'to': 'step3', 'type': 'flow'}, {'from': 'step3', 'to': 'step4', 'type': 'flow'}, {'from': 'step4', 'to': 'step5', 'type': 'flow'}, {'from': 'step5', 'to': 'step6', 'type': 'flow'}]

    # Step 1: create_emitter (function)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('step1_mod', 'C:/depot/tools/unreal_tools/niagara.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = getattr(module, 'create_emitter')
        create_emitter = target
        step1_result = create_emitter(asset_path=step1_asset_path, template=step1_template, parameters=step1_parameters)
        step1_outputs = {'muzzle_emitter_result': step1_result}
        outputs['step1'] = step1_outputs
        results['step1'] = step1_result
    except Exception as e:
        print(f'Step 1 failed: {e}')
        traceback.print_exc()
        raise

    # Step 2: create_emitter (function)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('step2_mod', 'C:/depot/tools/unreal_tools/niagara.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = getattr(module, 'create_emitter')
        create_emitter = target
        step2_result = create_emitter(asset_path=step2_asset_path, template=step2_template, parameters=step2_parameters)
        step2_outputs = {'impact_emitter_result': step2_result}
        outputs['step2'] = step2_outputs
        results['step2'] = step2_result
    except Exception as e:
        print(f'Step 2 failed: {e}')
        traceback.print_exc()
        raise

    # Step 3: scan_blueprint (function)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('step3_mod', 'C:/depot/tools/unreal_tools/blueprint.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = getattr(module, 'scan_blueprint')
        scan_blueprint = target
        step3_result = scan_blueprint(asset_path=step3_asset_path, include_graphs=True, include_defaults=True)
        step3_outputs = {'rifle_scan': step3_result}
        outputs['step3'] = step3_outputs
        results['step3'] = step3_result
    except Exception as e:
        print(f'Step 3 failed: {e}')
        traceback.print_exc()
        raise

    # Step 4: scan_blueprint (function)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('step4_mod', 'C:/depot/tools/unreal_tools/blueprint.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = getattr(module, 'scan_blueprint')
        scan_blueprint = target
        step4_result = scan_blueprint(asset_path=step4_asset_path, include_graphs=True, include_defaults=True)
        step4_outputs = {'enemy_scan': step4_result}
        outputs['step4'] = step4_outputs
        results['step4'] = step4_result
    except Exception as e:
        print(f'Step 4 failed: {e}')
        traceback.print_exc()
        raise

    # Step 5: compile_blueprint (function)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('step5_mod', 'C:/depot/tools/unreal_tools/blueprint.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = getattr(module, 'compile_blueprint')
        compile_blueprint = target
        step5_result = compile_blueprint(asset_path=step3_asset_path)
        step5_outputs = {'rifle_compile': step5_result}
        outputs['step5'] = step5_outputs
        results['step5'] = step5_result
    except Exception as e:
        print(f'Step 5 failed: {e}')
        traceback.print_exc()
        raise

    # Step 6: compile_blueprint (function)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('step6_mod', 'C:/depot/tools/unreal_tools/blueprint.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = getattr(module, 'compile_blueprint')
        compile_blueprint = target
        step6_result = compile_blueprint(asset_path=step4_asset_path)
        step6_outputs = {'enemy_compile': step6_result}
        outputs['step6'] = step6_outputs
        results['step6'] = step6_result
    except Exception as e:
        print(f'Step 6 failed: {e}')
        traceback.print_exc()
        raise

    return results.get('step6')
```

## 4. Unreal Retarget And BlendSpace

```python
"""Generated pipeline.
Goal: Retarget an animation to a target skeletal mesh and create a BlendSpace asset from the retargeted result.

Flow edges control execution order only.
Data edges bind return/output values into downstream function arguments.
"""

import importlib
import traceback

def unreal_retarget_to_blendspace_pipeline(step1_source_animation='', step1_source_skeletal_mesh_path='', step1_target_skeletal_mesh_path='/Game/Characters/Mannequins/Meshes/SKM_Manny.SKM_Manny', step1_output_path='/Game/AIStudio/Animations/Retargeted', step1_retargeter_path='', step1_destination_suffix='_Retargeted', step2_asset_path='/Game/AIStudio/Animations/BS_Crawl', step2_skeleton_path='/Game/Characters/Mannequins/Meshes/SK_Mannequin.SK_Mannequin', step2_axis_x=None, step2_axis_y=None):
    results = {}
    outputs = {}
    flow_links = [{'from': 'step1', 'to': 'step2', 'type': 'flow'}]

    # Step 1: retarget_animation (function)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('step1_mod', 'C:/depot/tools/unreal_tools/animation.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = getattr(module, 'retarget_animation')
        retarget_animation = target
        step1_result = retarget_animation(source_animation=step1_source_animation, source_skeletal_mesh_path=step1_source_skeletal_mesh_path, target_skeletal_mesh_path=step1_target_skeletal_mesh_path, output_path=step1_output_path, retargeter_path=step1_retargeter_path, destination_suffix=step1_destination_suffix, save=True)
        step1_outputs = {'retarget_result': step1_result}
        outputs['step1'] = step1_outputs
        results['step1'] = step1_result
    except Exception as e:
        print(f'Step 1 failed: {e}')
        traceback.print_exc()
        raise

    # Step 2: create_blendspace (function)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('step2_mod', 'C:/depot/tools/unreal_tools/animation.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = getattr(module, 'create_blendspace')
        create_blendspace = target
        step2_samples = [{'animation': outputs['step1']['retarget_result'], 'x': 50.0, 'y': 0.0}]
        step2_result = create_blendspace(asset_path=step2_asset_path, skeleton_path=step2_skeleton_path, samples=step2_samples, axis_x=step2_axis_x, axis_y=step2_axis_y, save=True)
        step2_outputs = {'blendspace_result': step2_result}
        outputs['step2'] = step2_outputs
        results['step2'] = step2_result
    except Exception as e:
        print(f'Step 2 failed: {e}')
        traceback.print_exc()
        raise

    return results.get('step2')
```
