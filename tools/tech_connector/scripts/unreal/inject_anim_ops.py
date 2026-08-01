"""
Inserts anim_graph.* operations into the UNREAL_OPERATIONS registry.
These map to the existing unreal_tools/animation.py callables.
"""
import re

content = open('tech_connector/services/unreal/unreal_operation_service.py', encoding='utf-8', errors='ignore').read()

NEW_OPS = '''    "anim_graph.add_state_machine": UnrealOperation(
        key="anim_graph.add_state_machine",
        label="Unreal Anim Graph Add State Machine",
        function="unreal_tools.animation.add_state_machine",
        required=("anim_bp_path", "state_machine_name"),
        mutates_project=True,
        description="Add a new State Machine node to the AnimGraph of an Animation Blueprint.",
    ),
    "anim_graph.add_state": UnrealOperation(
        key="anim_graph.add_state",
        label="Unreal Anim Graph Add State",
        function="unreal_tools.animation.add_state",
        required=("anim_bp_path", "state_machine_name", "state_name"),
        optional={"animation_asset_path": ""},
        mutates_project=True,
        description="Add a state (with optional animation asset) to a State Machine inside an Animation Blueprint.",
    ),
    "anim_graph.add_transition_rule": UnrealOperation(
        key="anim_graph.add_transition_rule",
        label="Unreal Anim Graph Add Transition Rule",
        function="unreal_tools.animation.add_transition_rule",
        required=("anim_bp_path", "state_machine_name", "from_state", "to_state", "rule_expression"),
        mutates_project=True,
        description="Add a transition rule between two states inside an Animation Blueprint State Machine.",
    ),
    "anim_graph.wire_state_machine_to_output_pose": UnrealOperation(
        key="anim_graph.wire_state_machine_to_output_pose",
        label="Unreal Anim Graph Wire State Machine to Output Pose",
        function="unreal_tools.animation.wire_state_machine_to_output_pose",
        required=("anim_bp_path", "state_machine_name"),
        mutates_project=True,
        description="Wire a State Machine node's output to the Output Pose node in an Animation Blueprint.",
    ),
    "anim_graph.synthesize_transition_rule_expression": UnrealOperation(
        key="anim_graph.synthesize_transition_rule_expression",
        label="Unreal Anim Graph Synthesize Transition Rule Expression",
        function="unreal_tools.animation.synthesize_transition_rule_expression",
        required=("anim_bp_path", "state_machine_name", "from_state", "to_state", "rule_expression"),
        mutates_project=True,
        description="Synthesize and apply a transition rule expression (e.g. variable comparison) between two states.",
    ),
'''

# Insert these after the opening brace of UNREAL_OPERATIONS
marker = 'UNREAL_OPERATIONS: dict[str, UnrealOperation] = {\n'
if marker in content:
    new_content = content.replace(marker, marker + NEW_OPS, 1)
    with open('tech_connector/services/unreal/unreal_operation_service.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Done')
else:
    print('MARKER NOT FOUND')
