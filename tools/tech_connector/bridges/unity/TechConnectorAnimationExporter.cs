#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;

namespace TechConnector
{
    /// <summary>Exports supported AnimatorController data without parsing Unity's private YAML format.</summary>
    public static class TechConnectorAnimationExporter
    {
        [Serializable] private sealed class Document { public string unity_version; public Clip[] animation_clips; public Mask[] animation_masks; public Controller[] controllers; }
        [Serializable] private sealed class Controller { public string name; public string guid; public Parameter[] parameters; public Layer[] layers; }
        [Serializable] private sealed class Clip { public string name; public string guid; public string asset_path; public float duration; public float frame_rate; public bool is_looping; public Event[] events; }
        [Serializable] private sealed class Event { public string name; public float time; public string payload; }
        [Serializable] private sealed class Mask { public string name; public string guid; public TransformMask[] transforms; }
        [Serializable] private sealed class TransformMask { public string path; public bool active; }
        [Serializable] private sealed class Parameter { public string name; public string type; public float default_float; public int default_int; public bool default_bool; public object DefaultValue() { if (type == "Float") return default_float; if (type == "Int") return default_int; return default_bool; } }
        [Serializable] private sealed class Layer { public string id; public string name; public float defaultWeight; public string blendingMode; public string mask; public int syncedLayerIndex; public Machine stateMachine; }
        [Serializable] private sealed class Machine { public string defaultState; public State[] states; public Transition[] transitions; public string[] nested_state_machines; }
        [Serializable] private sealed class State { public string id; public string name; public float speed; public bool writeDefaultValues; public MotionData motion; public string[] behaviours; }
        [Serializable] private sealed class MotionData { public string type; public string id; public string name; public string clip; public string blendType; public string blendParameter; public string blendParameterY; public bool useAutomaticThresholds; public Child[] children; }
        [Serializable] private sealed class Child { public string id; public string motion; public float threshold; public float[] position; public float timeScale; public bool mirror; }
        [Serializable] private sealed class Transition { public string id; public string from; public string to; public float duration; public float offset; public bool hasExitTime; public float exitTime; public string interruptionSource; public bool orderedInterruption; public bool any_state; public Condition[] conditions; }
        [Serializable] private sealed class Condition { public string parameter; public string mode; public float threshold; }

        [MenuItem("Tools/Tech Connector/Animation/Export Selected Animator Controller")]
        private static void ExportSelected()
        {
            AnimatorController controller = Selection.activeObject as AnimatorController;
            if (controller == null) throw new InvalidOperationException("Select an Animator Controller first.");
            string suggested = Path.Combine(Directory.GetParent(Application.dataPath).FullName, "Library", controller.name + ".tc-animation.json");
            string destination = EditorUtility.SaveFilePanel("Export for Tech Connector", Path.GetDirectoryName(suggested), Path.GetFileName(suggested), "json");
            if (string.IsNullOrWhiteSpace(destination)) return;
            File.WriteAllText(destination, ExportController(AssetDatabase.GetAssetPath(controller)));
            EditorUtility.RevealInFinder(destination);
        }

        [MenuItem("Tools/Tech Connector/Animation/Export Selected Animator Controller", true)]
        private static bool CanExportSelected() { return Selection.activeObject is AnimatorController; }

        public static string ExportController(string assetPath)
        {
            AnimatorController controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(assetPath);
            if (controller == null) throw new InvalidOperationException("Animator Controller was not found: " + assetPath);
            string guid = AssetDatabase.AssetPathToGUID(assetPath);
            var clips = new Dictionary<string, Clip>();
            var masks = new Dictionary<string, Mask>();
            var parameters = new List<Parameter>();
            foreach (AnimatorControllerParameter item in controller.parameters)
            {
                parameters.Add(new Parameter { name = item.name, type = item.type.ToString(), default_float = item.defaultFloat, default_int = item.defaultInt, default_bool = item.defaultBool });
            }
            var layers = new List<Layer>();
            for (int index = 0; index < controller.layers.Length; ++index)
            {
                AnimatorControllerLayer source = controller.layers[index];
                CollectMachineAssets(source.stateMachine, clips);
                if (source.avatarMask != null)
                {
                    string maskPath = AssetDatabase.GetAssetPath(source.avatarMask); string maskGuid = AssetDatabase.AssetPathToGUID(maskPath);
                    var transforms = new List<TransformMask>();
                    for (int transformIndex = 0; transformIndex < source.avatarMask.transformCount; ++transformIndex)
                        transforms.Add(new TransformMask { path = source.avatarMask.GetTransformPath(transformIndex), active = source.avatarMask.GetTransformActive(transformIndex) });
                    masks[maskGuid] = new Mask { name = source.avatarMask.name, guid = maskGuid, transforms = transforms.ToArray() };
                }
                layers.Add(new Layer {
                    id = guid + ":layer:" + index, name = source.name, defaultWeight = source.defaultWeight,
                    blendingMode = source.blendingMode.ToString(), mask = source.avatarMask == null ? "" : AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(source.avatarMask)),
                    syncedLayerIndex = source.syncedLayerIndex, stateMachine = SerializeMachine(source.stateMachine, guid + ":layer:" + index),
                });
            }
            return JsonUtility.ToJson(new Document { unity_version = Application.unityVersion, animation_clips = new List<Clip>(clips.Values).ToArray(), animation_masks = new List<Mask>(masks.Values).ToArray(), controllers = new[] { new Controller { name = controller.name, guid = guid, parameters = parameters.ToArray(), layers = layers.ToArray() } } }, true);
        }

        private static void CollectMachineAssets(AnimatorStateMachine machine, Dictionary<string, Clip> clips)
        {
            foreach (ChildAnimatorState child in machine.states) CollectMotionAssets(child.state.motion, clips);
            foreach (ChildAnimatorStateMachine child in machine.stateMachines) CollectMachineAssets(child.stateMachine, clips);
        }

        private static void CollectMotionAssets(Motion motion, Dictionary<string, Clip> clips)
        {
            if (motion == null) return;
            AnimationClip clip = motion as AnimationClip;
            if (clip != null)
            {
                string path = AssetDatabase.GetAssetPath(clip); string guid = AssetDatabase.AssetPathToGUID(path);
                var events = new List<Event>();
                foreach (AnimationEvent item in AnimationUtility.GetAnimationEvents(clip))
                    events.Add(new Event { name = item.functionName, time = item.time, payload = item.stringParameter });
                clips[guid] = new Clip { name = clip.name, guid = guid, asset_path = path, duration = clip.length, frame_rate = clip.frameRate, is_looping = clip.isLooping, events = events.ToArray() };
                return;
            }
            BlendTree tree = motion as BlendTree;
            if (tree != null) foreach (ChildMotion child in tree.children) CollectMotionAssets(child.motion, clips);
        }

        private static Machine SerializeMachine(AnimatorStateMachine machine, string prefix)
        {
            var states = new List<State>(); var transitions = new List<Transition>(); var stateIds = new Dictionary<AnimatorState, string>();
            foreach (ChildAnimatorState child in machine.states) stateIds[child.state] = prefix + ":state:" + child.state.name;
            foreach (ChildAnimatorState child in machine.states)
            {
                AnimatorState state = child.state; string id = stateIds[state]; var behaviours = new List<string>();
                foreach (StateMachineBehaviour behaviour in state.behaviours) if (behaviour != null) behaviours.Add(behaviour.GetType().AssemblyQualifiedName);
                states.Add(new State { id = id, name = state.name, speed = state.speed, writeDefaultValues = state.writeDefaultValues, motion = SerializeMotion(state.motion, prefix + ":motion:" + state.name), behaviours = behaviours.ToArray() });
                foreach (AnimatorStateTransition transition in state.transitions) transitions.Add(SerializeTransition(transition, id, stateIds, false));
            }
            foreach (AnimatorStateTransition transition in machine.anyStateTransitions) transitions.Add(SerializeTransition(transition, "any", stateIds, true));
            var nested = new List<string>(); foreach (ChildAnimatorStateMachine child in machine.stateMachines) nested.Add(child.stateMachine.name);
            string defaultState = machine.defaultState != null && stateIds.ContainsKey(machine.defaultState) ? stateIds[machine.defaultState] : "";
            return new Machine { defaultState = defaultState, states = states.ToArray(), transitions = transitions.ToArray(), nested_state_machines = nested.ToArray() };
        }

        private static MotionData SerializeMotion(Motion motion, string id)
        {
            if (motion == null) return null;
            AnimationClip clip = motion as AnimationClip;
            if (clip != null) return new MotionData { type = "Clip", id = AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(clip)), name = clip.name, clip = AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(clip)), children = new Child[0] };
            BlendTree tree = motion as BlendTree;
            if (tree == null) return new MotionData { type = motion.GetType().Name, id = id, name = motion.name, children = new Child[0] };
            var children = new List<Child>(); int index = 0;
            foreach (ChildMotion child in tree.children)
            {
                string childId = child.motion == null ? "" : AssetDatabase.AssetPathToGUID(AssetDatabase.GetAssetPath(child.motion));
                children.Add(new Child { id = id + ":child:" + index++, motion = childId, threshold = child.threshold, position = new[] { child.position.x, child.position.y }, timeScale = child.timeScale, mirror = child.mirror });
            }
            return new MotionData { type = "BlendTree", id = id, name = tree.name, blendType = tree.blendType.ToString(), blendParameter = tree.blendParameter, blendParameterY = tree.blendParameterY, useAutomaticThresholds = tree.useAutomaticThresholds, children = children.ToArray() };
        }

        private static Transition SerializeTransition(AnimatorStateTransition source, string from, Dictionary<AnimatorState, string> ids, bool anyState)
        {
            var conditions = new List<Condition>(); foreach (AnimatorCondition item in source.conditions) conditions.Add(new Condition { parameter = item.parameter, mode = item.mode.ToString(), threshold = item.threshold });
            string target = source.destinationState != null && ids.ContainsKey(source.destinationState) ? ids[source.destinationState] : "";
            return new Transition { id = from + ":to:" + target, from = from, to = target, duration = source.duration, offset = source.offset, hasExitTime = source.hasExitTime, exitTime = source.exitTime, interruptionSource = source.interruptionSource.ToString(), orderedInterruption = source.orderedInterruption, any_state = anyState, conditions = conditions.ToArray() };
        }
    }
}
#endif
