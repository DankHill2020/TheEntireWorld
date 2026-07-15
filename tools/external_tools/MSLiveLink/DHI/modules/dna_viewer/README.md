# API

## Getting the DNA ([`load_dna`](../dna_viewer/reader/dna.py#L28))

Loads the DNA and returns a `DNA` object.

```
from dna_viewer import load_dna

dna_ada = load_dna(DNA_PATH_ADA)
dna_taro = load_dna(DNA_PATH_TARO)
```
 
The parameters are the following:
- `dna: DNA` - Instance of DNA got with `load_dna`.

## Mesh Utilities

The purpose of the following methods is to provide a simple mechanism for building meshes from a given DNA file path, or to return and print information about the meshes contained in the DNA file.

### Importing

```
from dna_viewer import build_meshes, create_build_options, get_mesh_index, get_mesh_lods, get_mesh_names, print_meshes, print_mesh_indices_containing_string
```

```
DNA_PATH_ADA = "Ada.dna"  # add you path to dna file
DNA_PATH_TARO = "Taro.dna"  # add you path to dna file
```

### Create build options ([`create_build_options`](../dna_viewer/util/mesh.py#L31))

Used to create a configuration object that will be used in the mesh building process.

```
build_options = create_build_options(
    add_joints=True, 
    add_normals=False, 
    add_blend_shapes=False, 
    add_skin=False,
    add_ctrl_attributes_on_root_joint=False,
    add_animated_map_attributes_on_root_joint=False
)
```

The parameters are the following:
- `add_joints: bool` - A flag representing if joints should be added, defaults to `False`.
- `add_normals: bool` - A flag representing if normals from the DNA file should be added, defaults to `False`.
- `add_blend_shapes: bool` - A flag representing if blend shapes should be added, defaults to `False`.
- `add_skin: bool` - A flag representing if skin clusters should be added, defaults to `False`.
- `add_ctrl_attributes_on_root_joint: bool` - A flag representing if control attributes should be added to the root joint as attributes, defaults to `False`. They are used as animation curves for Rig Logic inputs in the engine.
- `add_animated_map_attributes_on_root_joint: bool` - A flag representing if animated map attributes should be added to the root joint as attributes, defaults to `False`. They are used as animation curves for animated maps in the engine.

### Building the meshes ([`build_meshes`](../dna_viewer/util/mesh.py#L49))

Used for building rig elements(joints, meshes, blend shapes and skin clusters) without Rig Logic.
It returns long names of meshes that have been added to the scene.

```
mesh_names = build_meshes(
    dna=dna_ada,
    options=build_options,
    group_by_lod=True,
    lod_list=[0, 1],
    mesh_list=[38],
    create_new_scene=True
)
```


The parameters are the following:
- `dna: DNA` - Instance of DNA got with `load_dna`.
- `lod_list: List[int]` - A list of LODs for which we want to build all meshes.
- `mesh_list: List[int]` - A list of mesh indices which we want to build.
- `group_by_lod: bool` - A flag representing if the built meshes should be added to a MetaHuman group hierarchy in the scene, defaults to `False`. If the value is `False`, all of the created rig elements will be added to the root of the scene.
- `options: BuildOptions` - Sets the [build options](../dna_viewer/README.md#L61).
- `create_new_scene: bool` - If `True`, new scene will be opened before creating rig elements. Defaults to `False`.

If `lod_list` and `mesh_list` are not set, all the meshes will be built.

The method can also be called with only a DNA file path:

```
mesh_names = build_meshes(dna=dna_ada)
```

Which defaults to adding all the meshes within the DNA file.


### Getting the mesh index for a given string contained in the mesh name and the lod([`get_mesh_index`](../dna_viewer/util/mesh.py#L120))

Returns the mesh index of the mesh that contains the search string. If multiple matches are found, returns the first one.

```
mesh_id = get_mesh_index("eye", 0, dna_ada)
```

The parameters are the following:
- `mesh_name: str` - A search string used for getting the mesh index of the mesh name that contains it.
- `lod: int` - The LOD where the mesh is searched for.
- `dna: DNA` - Instance of DNA got with `load_dna`.

### Getting a list of all mesh names([`get_mesh_names`](../dna_viewer/util/mesh.py#L13)))

Returns a list of all the mesh names in the DNA.

```
mesh_names = get_mesh_names(dna_ada)
```

The parameters are the following:
- `dna: DNA` - Instance of DNA got with `load_dna`.

### Getting a list of mesh indices organized per LODs ([`get_mesh_lods`](../dna_viewer/util/mesh.py#L17))

Returns a list of mesh indices grouped by the LOD number

```
mesh_indices_by_lod = get_mesh_lods(dna_ada)
```

The parameters are the following:
- `dna: DNA` - Instance of DNA got with `load_dna`.

### Printing all the meshes ([`print_meshes`](../dna_viewer/util/mesh_helper.py#L8))

Prints the mesh indices and names grouped by LODs:

```
print_meshes(dna_ada)
```

The parameters are the following:
- `dna: DNA` - Instance of DNA got with `load_dna`.

### Print all mesh indices with names containing the search string ([`print_mesh_indices_containing_string`](../dna_viewer/util/mesh_helper.py#L18))

Prints all the meshes and their indices which have names that contain the given search string in a given LOD.

```
print_mesh_indices_containing_string("eye", 3, dna_ada)
```


### Example

```
from dna_viewer import build_meshes, create_build_options
from dna_viewer import print_meshes
from dna_viewer import load_dna

# Sets DNA file path
DNA_PATH_ADA = "Ada.dna"  # add you path to dna file
dna_ada = load_dna(DNA_PATH_ADA)
# Prints the mesh ids and names grouped by lods
print_meshes(dna_ada)

# Starts the mesh build process with all the default values
build_meshes(dna=dna_ada)

# Creates the options to be passed in `build_meshes`
build_options = create_build_options(
    add_joints=True, 
    add_normals=True, 
    add_blend_shapes=True, 
    add_skin=True,
    add_ctrl_attributes_on_root_joint=True,
    add_animated_map_attributes_on_root_joint=True
)

# Starts the mesh building process with the provided parameters
# In this case it will create every mesh contained in LODs 0 and 1, 
# it also adds the mesh with the mesh index value of 38
build_meshes(
    dna=dna_ada,
    options=build_options,
    group_by_lod=True,
    lod_list=[0, 1],
    mesh_list=[38],
    create_new_scene=True
)
```

## Rig Assembly

The assemble APIs purpose is to be used for easy assembly of the character rig from a given DNA instance.

### Importing

```
from dna_viewer import assemble_rig
```

The parameters are the following:
- `dna: DNA` - Instance of DNA got with `load_dna`.
- `analog_gui_path: str` - The analog GUI file path.
- `gui_path: str` - The GUI file path, defaults to `None`.
- `gui: Gui` - Instead of only specifying the GUI file path we can give pass it the GUI configuration object, defaults to `None`.
- `aas_path: str` - The additional assembly script path, defaults to `None`.
- `lights_path: str` - The path of the file containing the lights, defaults to `None`.
- `shaders_config: ShadersConfig` - The shader configuration of the scene to be assembled. Defaults to `None`.
- `aas_fn: str` - The method name that should be called from the additional assembly script.
- `with_attributes_on_root_joint: bool` - A flag representing if attributes should be added on the root joint, defaults to `False`.
- `with_key_frames: bool` - A flag representing if key frames should be added, defaults to `False`.

### Example

```
from dna_viewer import assemble_rig, load_dna, RigConfig

# Sets the values that will used
DNA_PATH_ADA = "Ada.dna"  # add you path to dna file
dna_ada = load_dna(DNA_PATH_ADA)
GUI_PATH = "gui.ma"  # add you path to gui.ma file
ANALOG_GUI_PATH = "analog_gui.ma"  # add you path to analog_gui.ma file
AAS_PATH = "additional_assemble_script.py"  # add you path to additional_assemble_script.py file

config = RigConfig(
    gui_path=GUI_PATH,
    analog_gui_path=ANALOG_GUI_PATH,
    aas_path=AAS_PATH,
)

# Creates the rig
build_rig(dna=dna_ada, config=config)
```