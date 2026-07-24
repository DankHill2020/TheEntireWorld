import subprocess

content = subprocess.check_output(
    'git show HEAD:tools/unreal_tools/blueprint.py', shell=True
).decode('utf-8', errors='ignore')

new_fn = """
def compile_and_save_blueprint(asset_path):
    \"\"\"Compile a Blueprint and save it to disk if compilation succeeds.\"\"\"
    import unreal

    bp = _load_blueprint(unreal, asset_path)
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    errors = unreal.BlueprintEditorLibrary.get_compiler_results(bp) if hasattr(
        unreal.BlueprintEditorLibrary, 'get_compiler_results'
    ) else []
    if errors:
        return __import__('json').dumps(
            {'asset_path': asset_path, 'compiled': False, 'errors': list(errors)}, indent=2
        )
    unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=False)
    return __import__('json').dumps(
        {'asset_path': asset_path, 'compiled': True, 'saved': True}, indent=2
    )

"""

marker = 'def _graph_editor(unreal, blueprint, graph_name):'
if marker in content:
    new_content = content.replace(marker, new_fn + marker, 1)
    with open('unreal_tools/blueprint.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Done, lines:', new_content.count('\n'))
else:
    print('MARKER NOT FOUND')
    import re
    fns = re.findall(r'^def \w+', content, re.M)
    print(fns)
