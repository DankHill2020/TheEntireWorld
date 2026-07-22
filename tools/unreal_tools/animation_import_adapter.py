"""Version-aware verification adapter for the established sequence importer."""

from __future__ import annotations


def import_animation_verified(*args, **kwargs):
    """Use sequence_importer while forcing UE 5.8's explicit animation mode."""
    import unreal
    from unreal_tools import sequence_importer

    original_builder = sequence_importer.build_import_options

    def build_animation_options(skeleton_path):
        options = original_builder(skeleton_path)
        options.mesh_type_to_import = unreal.FBXImportType.FBXIT_ANIMATION
        options.anim_sequence_import_data.set_editor_property(
            "snap_to_closest_frame_boundary", True
        )
        return options

    sequence_importer.build_import_options = build_animation_options
    try:
        kwargs["structured"] = True
        return sequence_importer.import_animation(*args, **kwargs)
    finally:
        sequence_importer.build_import_options = original_builder
