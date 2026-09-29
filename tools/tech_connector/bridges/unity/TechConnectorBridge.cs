#if UNITY_EDITOR
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace TechConnector
{
    [InitializeOnLoad]
    public static class TechConnectorBridge
    {
        private const int FirstPort = 7041;
        private const int PortCount = 20;
        private const int MaxRequestCharacters = 1024 * 1024;
        private const int MaxInFlightRequests = 8;
        private static readonly ConcurrentQueue<WorkItem> Pending = new ConcurrentQueue<WorkItem>();
        private static readonly SemaphoreSlim InFlight = new SemaphoreSlim(MaxInFlightRequests, MaxInFlightRequests);
        private static TcpListener listener;
        private static Thread listenerThread;
        private static int activePort;
        private static string bridgeSessionPath;

        [Serializable]
        private sealed class Request
        {
            public string command;
            public string code;
            public string bridge_session;
            public string filepath;
            public string destination_folder;
            public string gameobject_name;
            public string destination_path;
            public string material_name;
            public string material_path;
            public string shader_name;
            public string model_path;
            public string prefab_path;
            public string instance_name;
            public float[] position;
            public bool instantiate;
            public bool selected_only;
            public bool include_materials = true;
            public int limit = 500;
        }

        [Serializable]
        private sealed class Response
        {
            public bool ok;
            public string result;
            public string error;
            public string code;
        }

        [Serializable]
        private sealed class BridgeSessionFile
        {
            public string schema;
            public string session_token;
            public string issued_at;
            public string expires_at;
            public string[] hosts;
        }

        [Serializable]
        private sealed class SessionInfo
        {
            public string project;
            public string project_path;
            public string scene;
            public int process_id;
            public string unity_version;
            public int active_port;
        }

        [Serializable]
        private sealed class SceneObjectInfo
        {
            public string id;
            public string native_id;
            public string name;
            public string parent_id;
            public string type;
            public string[] shape_types;
            public float[] bbox;
            public float[] position;
            public float[] translation;
            public float[] rotation;
            public float[] scale;
            public bool active;
            public bool visible;
            public List<MaterialInfo> materials = new List<MaterialInfo>();
            public List<MaterialAssignmentInfo> material_assignments = new List<MaterialAssignmentInfo>();
        }

        [Serializable]
        private sealed class MaterialInfo
        {
            public string name;
            public string source_material_id;
            public string source_shader;
            public float[] color;
            public float roughness;
            public float metalness;
            public float specular;
            public float opacity;
            public float[] emission_color;
            public List<TextureBindingInfo> textures = new List<TextureBindingInfo>();
        }

        [Serializable]
        private sealed class TextureBindingInfo
        {
            public string channel;
            public string path;
            public string color_space;
            public string uv_set = "uv0";
            public string source_channel;
        }

        [Serializable]
        private sealed class MaterialAssignmentInfo
        {
            public string material_id;
            public int slot_index;
            public int[] face_indices = new int[0];
            public string uv_set = "uv0";
        }

        [Serializable]
        private sealed class SnapshotIsolation
        {
            public bool selected_only;
            public bool include_geometry;
            public bool include_materials;
        }

        [Serializable]
        private sealed class SceneSnapshot
        {
            public string schema = "tech_connector.unity.scene_snapshot.v1";
            public string provider_id = "unity";
            public string scene;
            public bool scene_modified;
            public string application_version;
            public string unit_linear = "meters";
            public string up_axis = "y";
            public float current_time;
            public float fps;
            public string[] selection;
            public SnapshotIsolation isolation;
            public List<SceneObjectInfo> objects = new List<SceneObjectInfo>();
        }

        private sealed class WorkItem
        {
            public string Json;
            public readonly ManualResetEventSlim Completed = new ManualResetEventSlim(false);
            public string ResponseJson;
            public int State;
        }

        static TechConnectorBridge()
        {
            EditorApplication.update += ProcessPending;
            AssemblyReloadEvents.beforeAssemblyReload += Stop;
            EditorApplication.quitting += Stop;
            Start();
        }

        [MenuItem("Tools/Tech Connector/Restart Bridge")]
        public static void Restart()
        {
            Stop();
            Start();
        }

        private static void Start()
        {
            if (listener != null)
                return;
            bridgeSessionPath = ResolveBridgeSessionPath();
            for (int port = FirstPort; port < FirstPort + PortCount; port++)
            {
                try
                {
                    listener = new TcpListener(IPAddress.Loopback, port);
                    listener.Start();
                    activePort = port;
                    WritePortFile(port);
                    listenerThread = new Thread(ListenLoop) { IsBackground = true, Name = "TechConnectorUnityBridge" };
                    listenerThread.Start();
                    Debug.Log("Tech Connector Unity bridge listening on 127.0.0.1:" + port);
                    return;
                }
                catch (SocketException)
                {
                    if (listener != null)
                        listener.Stop();
                    listener = null;
                }
            }
            Debug.LogError("Tech Connector could not find an available Unity bridge port.");
        }

        private static void Stop()
        {
            TcpListener current = listener;
            listener = null;
            activePort = 0;
            if (current != null)
                current.Stop();
        }

        private static void ListenLoop()
        {
            while (listener != null)
            {
                try
                {
                    TcpClient client = listener.AcceptTcpClient();
                    if (!InFlight.Wait(0))
                    {
                        WriteImmediateResponse(client, Error("Unity bridge is busy; retry after the active Editor operations finish."));
                        continue;
                    }
                    ThreadPool.QueueUserWorkItem(_ => HandleClient(client));
                }
                catch (Exception exception)
                {
                    if (listener != null)
                        Debug.LogWarning("Tech Connector bridge request failed: " + exception.Message);
                }
            }
        }

        private static void HandleClient(TcpClient client)
        {
            try
            {
                client.ReceiveTimeout = 15000;
                client.SendTimeout = 15000;
                using (client)
                using (NetworkStream stream = client.GetStream())
                using (StreamReader reader = new StreamReader(stream, Encoding.UTF8, false, 4096, true))
                using (StreamWriter writer = new StreamWriter(stream, new UTF8Encoding(false), 4096, true))
                {
                    string json = reader.ReadLine() ?? "{}";
                    if (json.Length > MaxRequestCharacters)
                    {
                        writer.WriteLine(Error("Unity bridge request exceeded the 1 MiB limit."));
                        writer.Flush();
                        return;
                    }
                    Request request = JsonUtility.FromJson<Request>(json) ?? new Request();
                    if (!BridgeAuthorized(request.bridge_session))
                    {
                        writer.WriteLine(AuthorizationError());
                        writer.Flush();
                        return;
                    }
                    WorkItem item = new WorkItem { Json = json };
                    Pending.Enqueue(item);
                    if (!item.Completed.Wait(TimeSpan.FromSeconds(120)))
                    {
                        if (Interlocked.CompareExchange(ref item.State, 2, 0) == 0)
                            item.ResponseJson = Error("Unity command timed out before main-thread execution and was cancelled.");
                        else
                            item.ResponseJson = Error("Unity command exceeded 120 seconds after execution began; inspect the Editor before retrying.");
                    }
                    writer.WriteLine(item.ResponseJson ?? Error("Unity returned no response."));
                    writer.Flush();
                }
            }
            catch (Exception exception)
            {
                if (listener != null)
                    Debug.LogWarning("Tech Connector client request failed: " + exception.Message);
            }
            finally
            {
                InFlight.Release();
            }
        }

        private static void WriteImmediateResponse(TcpClient client, string response)
        {
            try
            {
                using (client)
                using (StreamWriter writer = new StreamWriter(client.GetStream(), new UTF8Encoding(false)))
                {
                    writer.WriteLine(response);
                    writer.Flush();
                }
            }
            catch (Exception)
            {
            }
        }

        private static string ResolveBridgeSessionPath()
        {
            string configured = (Environment.GetEnvironmentVariable("TECH_CONNECTOR_BRIDGE_SESSION_FILE") ?? "").Trim();
            if (!string.IsNullOrEmpty(configured))
                return configured;
            if (Application.platform == RuntimePlatform.WindowsEditor)
            {
                string basePath = (Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? "").Trim();
                if (string.IsNullOrEmpty(basePath))
                    basePath = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                return Path.Combine(basePath, "TechConnector", "licensing", "bridge_session.json");
            }
            if (Application.platform == RuntimePlatform.OSXEditor)
            {
                string home = Environment.GetFolderPath(Environment.SpecialFolder.Personal);
                return Path.Combine(home, "Library", "Application Support", "TechConnector", "licensing", "bridge_session.json");
            }
            string stateHome = (Environment.GetEnvironmentVariable("XDG_STATE_HOME") ?? "").Trim();
            if (string.IsNullOrEmpty(stateHome))
                stateHome = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Personal), ".local", "state");
            return Path.Combine(stateHome, "tech_connector", "licensing", "bridge_session.json");
        }

        private static bool BridgeAuthorized(string suppliedToken)
        {
            if (string.IsNullOrEmpty(suppliedToken) || string.IsNullOrEmpty(bridgeSessionPath))
                return false;
            try
            {
                BridgeSessionFile session = JsonUtility.FromJson<BridgeSessionFile>(File.ReadAllText(bridgeSessionPath));
                DateTimeOffset issuedAt;
                DateTimeOffset expiresAt;
                if (session == null
                    || session.schema != "tech_connector.bridge_session.v1"
                    || string.IsNullOrEmpty(session.session_token)
                    || session.session_token.Length < 32
                    || !DateTimeOffset.TryParse(session.issued_at, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out issuedAt)
                    || !DateTimeOffset.TryParse(session.expires_at, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out expiresAt))
                    return false;
                DateTimeOffset now = DateTimeOffset.UtcNow;
                if (issuedAt >= expiresAt || issuedAt > now || now >= expiresAt)
                    return false;
                bool hostAllowed = false;
                foreach (string host in session.hosts ?? new string[0])
                {
                    if (string.Equals((host ?? "").Trim(), "unity", StringComparison.OrdinalIgnoreCase))
                    {
                        hostAllowed = true;
                        break;
                    }
                }
                return hostAllowed && ConstantTimeEquals(session.session_token, suppliedToken);
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static bool ConstantTimeEquals(string expected, string supplied)
        {
            byte[] left = Encoding.UTF8.GetBytes(expected ?? "");
            byte[] right = Encoding.UTF8.GetBytes(supplied ?? "");
            int difference = left.Length ^ right.Length;
            int length = Math.Min(left.Length, right.Length);
            for (int index = 0; index < length; index++)
                difference |= left[index] ^ right[index];
            return difference == 0;
        }

        private static string AuthorizationError()
        {
            return JsonUtility.ToJson(new Response
            {
                ok = false,
                error = "Tech Connector activation is required for this DCC bridge.",
                code = "bridge_authorization_required",
            });
        }

        private static void ProcessPending()
        {
            WorkItem item;
            if (Pending.TryDequeue(out item))
            {
                if (Interlocked.CompareExchange(ref item.State, 1, 0) != 0)
                {
                    item.Completed.Set();
                    return;
                }
                try
                {
                    item.ResponseJson = Dispatch(item.Json);
                }
                catch (Exception exception)
                {
                    item.ResponseJson = Error(exception.ToString());
                }
                finally
                {
                    Interlocked.Exchange(ref item.State, 3);
                    item.Completed.Set();
                }
            }
        }

        private static string Dispatch(string json)
        {
            Request request = JsonUtility.FromJson<Request>(json) ?? new Request();
            switch (request.command ?? "")
            {
                case "session.info":
                    return Success(JsonUtility.ToJson(new SessionInfo
                    {
                        project = Path.GetFileName(Directory.GetParent(Application.dataPath).FullName),
                        project_path = Directory.GetParent(Application.dataPath).FullName,
                        scene = SceneManager.GetActiveScene().path,
                        process_id = System.Diagnostics.Process.GetCurrentProcess().Id,
                        unity_version = Application.unityVersion,
                        active_port = activePort,
                    }));
                case "scene.snapshot":
                    return Success(BuildSceneSnapshot(request));
                case "assets.import_fbx":
                    return Success(ImportFbx(request));
                case "material.create":
                    return Success(CreateMaterial(request));
                case "material.assign":
                    return Success(AssignMaterial(request));
                case "prefab.create":
                    return Success(CreatePrefab(request));
                case "scene.add_prefab":
                    return Success(AddPrefab(request));
                case "workflow.inspect_prefab_asset":
                    return Success(InspectPrefabWorkflow(request));
                case "animation.export_controller":
                    return Success(TechConnectorAnimationExporter.ExportController(RequireText(request.filepath, "filepath")));
                default:
                    if (!string.IsNullOrEmpty(request.code))
                        return Error("Arbitrary C# evaluation is disabled. Use a typed Unity command.");
                    return Error("Unknown Unity bridge command: " + request.command);
            }
        }

        private static string ImportFbx(Request request)
        {
            string source = RequireFile(request.filepath, ".fbx");
            string destination = string.IsNullOrWhiteSpace(request.destination_path)
                ? NormalizeAssetFolder(request.destination_folder, "Assets/Models") + "/" + Path.GetFileName(source)
                : NormalizeAssetPath(request.destination_path);
            if (!string.Equals(Path.GetExtension(destination), ".fbx", StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("Unity FBX destination_path must end with .fbx.");
            string folder = destination.Substring(0, destination.LastIndexOf('/'));
            EnsureAssetFolder(folder);
            string absolutePath = AbsoluteAssetPath(destination);
            if (!string.Equals(source, absolutePath, StringComparison.OrdinalIgnoreCase))
                File.Copy(source, absolutePath, true);
            AssetDatabase.ImportAsset(destination, ImportAssetOptions.ForceSynchronousImport);
            UnityEngine.Object asset = AssetDatabase.LoadMainAssetAtPath(destination);
            if (asset == null)
                throw new InvalidOperationException("Unity did not import the FBX asset: " + destination);
            string objectId = "";
            if (request.instantiate)
            {
                GameObject model = asset as GameObject;
                if (model == null)
                    throw new InvalidOperationException("Imported FBX does not contain a GameObject root: " + destination);
                string objectName = string.IsNullOrWhiteSpace(request.gameobject_name) ? model.name : request.gameobject_name.Trim();
                GameObject previous = GameObject.Find(objectName);
                if (previous != null)
                    UnityEngine.Object.DestroyImmediate(previous);
                GameObject instance = PrefabUtility.InstantiatePrefab(model) as GameObject;
                if (instance == null)
                    throw new InvalidOperationException("Unity failed to instantiate imported FBX: " + destination);
                instance.name = objectName;
                objectId = GlobalObjectId.GetGlobalObjectIdSlow(instance).ToString();
                EditorSceneManager.MarkSceneDirty(instance.scene);
            }
            return JsonUtility.ToJson(new AssetResult
            {
                asset_path = destination,
                absolute_path = absolutePath,
                name = asset.name,
                object_id = objectId,
            });
        }

        private static string CreateMaterial(Request request)
        {
            string name = RequireText(request.material_name, "material_name");
            string shaderName = string.IsNullOrWhiteSpace(request.shader_name) ? "Standard" : request.shader_name;
            Shader shader = Shader.Find(shaderName);
            if (shader == null)
                throw new InvalidOperationException("Unity shader was not found: " + shaderName);
            string path = string.IsNullOrWhiteSpace(request.destination_path)
                ? "Assets/Materials/" + SafeFileName(name) + ".mat"
                : NormalizeAssetPath(request.destination_path);
            if (!string.Equals(Path.GetExtension(path), ".mat", StringComparison.OrdinalIgnoreCase))
                path = path.TrimEnd('/') + "/" + SafeFileName(name) + ".mat";
            string folder = path.Substring(0, path.LastIndexOf('/'));
            EnsureAssetFolder(folder);
            Material material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                material = new Material(shader) { name = name };
                AssetDatabase.CreateAsset(material, path);
            }
            else
            {
                material.shader = shader;
                material.name = name;
                EditorUtility.SetDirty(material);
            }
            AssetDatabase.SaveAssets();
            return JsonUtility.ToJson(new AssetResult { asset_path = path, absolute_path = AbsoluteAssetPath(path), name = name });
        }

        private static string AssignMaterial(Request request)
        {
            string name = RequireText(request.gameobject_name, "gameobject_name");
            string path = NormalizeAssetPath(RequireText(request.material_path, "material_path"));
            GameObject root = GameObject.Find(name);
            if (root == null)
                throw new InvalidOperationException("Scene GameObject was not found: " + name);
            Material material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
                throw new InvalidOperationException("Material asset was not found: " + path);
            Renderer[] renderers = root.GetComponentsInChildren<Renderer>(true);
            if (renderers.Length == 0)
                throw new InvalidOperationException("No Renderer exists below GameObject: " + name);
            foreach (Renderer renderer in renderers)
                renderer.sharedMaterial = material;
            EditorSceneManager.MarkSceneDirty(root.scene);
            return JsonUtility.ToJson(new AssignmentResult { gameobject_name = name, material_path = path, renderer_count = renderers.Length });
        }

        private static string CreatePrefab(Request request)
        {
            string name = RequireText(request.gameobject_name, "gameobject_name");
            GameObject source = GameObject.Find(name);
            if (source == null)
                throw new InvalidOperationException("Scene GameObject was not found: " + name);
            string path = string.IsNullOrWhiteSpace(request.destination_path)
                ? "Assets/Prefabs/" + SafeFileName(name) + ".prefab"
                : NormalizeAssetPath(request.destination_path);
            if (!string.Equals(Path.GetExtension(path), ".prefab", StringComparison.OrdinalIgnoreCase))
                path = path.TrimEnd('/') + "/" + SafeFileName(name) + ".prefab";
            string folder = path.Substring(0, path.LastIndexOf('/'));
            EnsureAssetFolder(folder);
            GameObject prefab = PrefabUtility.SaveAsPrefabAsset(source, path);
            if (prefab == null)
                throw new InvalidOperationException("Unity failed to create prefab: " + path);
            return JsonUtility.ToJson(new AssetResult
            {
                asset_path = path,
                absolute_path = AbsoluteAssetPath(path),
                name = prefab.name,
            });
        }

        private static string AddPrefab(Request request)
        {
            string path = NormalizeAssetPath(RequireText(request.prefab_path, "prefab_path"));
            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            if (prefab == null)
                throw new InvalidOperationException("Prefab asset was not found: " + path);
            string instanceName = string.IsNullOrWhiteSpace(request.instance_name) ? prefab.name : request.instance_name.Trim();
            GameObject previous = GameObject.Find(instanceName);
            if (previous != null)
                UnityEngine.Object.DestroyImmediate(previous);
            GameObject instance = PrefabUtility.InstantiatePrefab(prefab) as GameObject;
            if (instance == null)
                throw new InvalidOperationException("Unity failed to instantiate prefab: " + path);
            instance.name = instanceName;
            if (request.position != null && request.position.Length >= 3)
                instance.transform.position = new Vector3(request.position[0], request.position[1], request.position[2]);
            EditorSceneManager.MarkSceneDirty(instance.scene);
            return JsonUtility.ToJson(new SceneResult { object_id = GlobalObjectId.GetGlobalObjectIdSlow(instance).ToString(), name = instance.name });
        }

        private static string InspectPrefabWorkflow(Request request)
        {
            string modelPath = NormalizeAssetPath(RequireText(request.model_path, "model_path"));
            string materialPath = NormalizeAssetPath(RequireText(request.material_path, "material_path"));
            string prefabPath = NormalizeAssetPath(RequireText(request.prefab_path, "prefab_path"));
            string instanceName = RequireText(request.instance_name, "instance_name");
            GameObject model = AssetDatabase.LoadAssetAtPath<GameObject>(modelPath);
            Material material = AssetDatabase.LoadAssetAtPath<Material>(materialPath);
            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
            GameObject instance = GameObject.Find(instanceName);
            bool meshImport = model != null && AssetImporter.GetAtPath(modelPath) is ModelImporter;
            Renderer[] renderers = prefab == null ? new Renderer[0] : prefab.GetComponentsInChildren<Renderer>(true);
            bool materialBindings = material != null && renderers.Length > 0;
            foreach (Renderer renderer in renderers)
                materialBindings &= renderer.sharedMaterial == material;
            bool prefabHierarchy = prefab != null && prefab.GetComponentsInChildren<Transform>(true).Length > 0;
            Vector3 expected = request.position != null && request.position.Length >= 3
                ? new Vector3(request.position[0], request.position[1], request.position[2])
                : Vector3.zero;
            bool sceneTransform = instance != null && Vector3.Distance(instance.transform.position, expected) < 0.0001f;
            return "{\"parity_checks\":{" +
                "\"mesh import settings\":" + JsonBool(meshImport) + "," +
                "\"material bindings\":" + JsonBool(materialBindings) + "," +
                "\"prefab hierarchy\":" + JsonBool(prefabHierarchy) + "," +
                "\"scene instance transform\":" + JsonBool(sceneTransform) + "}," +
                "\"model_guid\":\"" + AssetDatabase.AssetPathToGUID(modelPath) + "\"," +
                "\"material_guid\":\"" + AssetDatabase.AssetPathToGUID(materialPath) + "\"," +
                "\"prefab_guid\":\"" + AssetDatabase.AssetPathToGUID(prefabPath) + "\"}";
        }

        private static string BuildSceneSnapshot(Request request)
        {
            Scene scene = SceneManager.GetActiveScene();
            SceneSnapshot snapshot = new SceneSnapshot
            {
                scene = scene.path,
                scene_modified = scene.isDirty,
                application_version = Application.unityVersion,
                current_time = (float)EditorApplication.timeSinceStartup,
                fps = Application.targetFrameRate > 0 ? Application.targetFrameRate : 60.0f,
                selection = Array.ConvertAll(Selection.gameObjects, value => GlobalObjectId.GetGlobalObjectIdSlow(value).ToString()),
                isolation = new SnapshotIsolation
                {
                    selected_only = request.selected_only,
                    include_geometry = false,
                    include_materials = request.include_materials,
                },
            };
            GameObject[] objects = request.selected_only ? Selection.gameObjects : UnityEngine.Object.FindObjectsOfType<GameObject>();
            int count = Math.Min(objects.Length, Math.Max(1, request.limit));
            for (int index = 0; index < count; index++)
            {
                GameObject value = objects[index];
                Transform transform = value.transform;
                Renderer renderer = value.GetComponent<Renderer>();
                Bounds bounds = renderer == null
                    ? new Bounds(transform.position, Vector3.one * 0.1f)
                    : renderer.bounds;
                string objectId = GlobalObjectId.GetGlobalObjectIdSlow(value).ToString();
                SceneObjectInfo info = new SceneObjectInfo
                {
                    id = objectId,
                    native_id = objectId,
                    name = value.name,
                    parent_id = transform.parent == null ? "" : GlobalObjectId.GetGlobalObjectIdSlow(transform.parent.gameObject).ToString(),
                    type = renderer == null ? "game_object" : renderer.GetType().Name,
                    shape_types = renderer == null ? new[] { "game_object" } : new[] { renderer.GetType().Name, "renderer" },
                    bbox = BoundsArray(bounds),
                    position = Vector(transform.position),
                    translation = Vector(transform.position),
                    rotation = Vector(transform.eulerAngles),
                    scale = Vector(transform.lossyScale),
                    active = value.activeInHierarchy,
                    visible = value.activeInHierarchy && (renderer == null || renderer.enabled),
                };
                if (request.include_materials && renderer != null)
                    CaptureRendererMaterials(renderer, info);
                snapshot.objects.Add(info);
            }
            return JsonUtility.ToJson(snapshot);
        }

        private static void CaptureRendererMaterials(Renderer renderer, SceneObjectInfo info)
        {
            Material[] materials = renderer.sharedMaterials ?? new Material[0];
            for (int slotIndex = 0; slotIndex < materials.Length; slotIndex++)
            {
                Material material = materials[slotIndex];
                if (material == null)
                    continue;
                string assetPath = AssetDatabase.GetAssetPath(material);
                string materialId = string.IsNullOrWhiteSpace(assetPath)
                    ? material.GetInstanceID().ToString()
                    : AssetDatabase.AssetPathToGUID(assetPath);
                Color color = ReadMaterialColor(material);
                MaterialInfo materialInfo = new MaterialInfo
                {
                    name = material.name,
                    source_material_id = materialId,
                    source_shader = material.shader == null ? "unknown" : material.shader.name,
                    color = ColorArray(color),
                    roughness = 1.0f - ReadFloat(material, new[] { "_Smoothness", "_Glossiness" }, 0.5f),
                    metalness = ReadFloat(material, new[] { "_Metallic" }, 0.0f),
                    specular = ReadColor(material, new[] { "_SpecColor" }, Color.gray).maxColorComponent,
                    opacity = color.a,
                    emission_color = ColorArray(ReadColor(material, new[] { "_EmissionColor" }, Color.black)),
                };
                AddTextureBinding(material, materialInfo, "base_color", new[] { "_BaseMap", "_BaseColorMap", "_MainTex" }, "sRGB - Texture");
                AddTextureBinding(material, materialInfo, "normal", new[] { "_BumpMap", "_NormalMap" }, "Raw");
                AddTextureBinding(material, materialInfo, "metalness", new[] { "_MetallicGlossMap", "_MaskMap" }, "Raw");
                AddTextureBinding(material, materialInfo, "specular_roughness", new[] { "_SpecGlossMap", "_MaskMap" }, "Raw");
                AddTextureBinding(material, materialInfo, "emission_color", new[] { "_EmissionMap" }, "sRGB - Texture");
                AddTextureBinding(material, materialInfo, "opacity", new[] { "_BaseMap", "_MainTex" }, "Raw");
                info.materials.Add(materialInfo);
                info.material_assignments.Add(new MaterialAssignmentInfo
                {
                    material_id = materialId,
                    slot_index = slotIndex,
                });
            }
        }

        private static void AddTextureBinding(
            Material material,
            MaterialInfo target,
            string channel,
            string[] propertyNames,
            string colorSpace)
        {
            foreach (string propertyName in propertyNames)
            {
                if (!material.HasProperty(propertyName))
                    continue;
                Texture texture = material.GetTexture(propertyName);
                if (texture == null)
                    continue;
                string assetPath = AssetDatabase.GetAssetPath(texture);
                if (string.IsNullOrWhiteSpace(assetPath))
                    continue;
                target.textures.Add(new TextureBindingInfo
                {
                    channel = channel,
                    path = AbsoluteAssetPath(assetPath),
                    color_space = colorSpace,
                    source_channel = propertyName,
                });
                return;
            }
        }

        private static Color ReadMaterialColor(Material material)
        {
            return ReadColor(material, new[] { "_BaseColor", "_Color" }, Color.gray);
        }

        private static Color ReadColor(Material material, string[] propertyNames, Color fallback)
        {
            foreach (string propertyName in propertyNames)
                if (material.HasProperty(propertyName))
                    return material.GetColor(propertyName);
            return fallback;
        }

        private static float ReadFloat(Material material, string[] propertyNames, float fallback)
        {
            foreach (string propertyName in propertyNames)
                if (material.HasProperty(propertyName))
                    return material.GetFloat(propertyName);
            return fallback;
        }

        private static float[] BoundsArray(Bounds value)
        {
            return new[] { value.min.x, value.min.y, value.min.z, value.max.x, value.max.y, value.max.z };
        }

        private static float[] ColorArray(Color value)
        {
            return new[] { value.r, value.g, value.b, value.a };
        }

        [Serializable]
        private sealed class AssetResult { public string asset_path; public string absolute_path; public string name; public string object_id; }
        [Serializable]
        private sealed class AssignmentResult { public string gameobject_name; public string material_path; public int renderer_count; }
        [Serializable]
        private sealed class SceneResult { public string object_id; public string name; }

        private static float[] Vector(Vector3 value)
        {
            return new[] { value.x, value.y, value.z };
        }

        private static string JsonBool(bool value)
        {
            return value ? "true" : "false";
        }

        private static string RequireFile(string value, string extension)
        {
            string path = Path.GetFullPath(RequireText(value, "filepath"));
            if (!File.Exists(path))
                throw new FileNotFoundException("Source file was not found.", path);
            if (!string.Equals(Path.GetExtension(path), extension, StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("Expected a " + extension + " file.");
            return path;
        }

        private static string RequireText(string value, string name)
        {
            if (string.IsNullOrWhiteSpace(value))
                throw new ArgumentException(name + " is required.");
            return value.Trim();
        }

        private static string NormalizeAssetFolder(string value, string fallback)
        {
            string path = string.IsNullOrWhiteSpace(value) ? fallback : value;
            path = NormalizeAssetPath(path).TrimEnd('/');
            if (Path.HasExtension(path))
                path = path.Substring(0, path.LastIndexOf('/'));
            return path;
        }

        private static string NormalizeAssetPath(string value)
        {
            string path = value.Replace('\\', '/').Trim();
            if (!path.StartsWith("Assets", StringComparison.Ordinal))
                throw new ArgumentException("Unity asset paths must begin with Assets: " + path);
            if (path.Contains(".."))
                throw new ArgumentException("Unity asset paths cannot contain '..'.");
            return path;
        }

        private static void EnsureAssetFolder(string folder)
        {
            string current = "Assets";
            string[] parts = folder.Split('/');
            for (int index = 1; index < parts.Length; index++)
            {
                string next = current + "/" + parts[index];
                if (!AssetDatabase.IsValidFolder(next))
                    AssetDatabase.CreateFolder(current, parts[index]);
                current = next;
            }
        }

        private static string AbsoluteAssetPath(string assetPath)
        {
            string projectRoot = Directory.GetParent(Application.dataPath).FullName;
            return Path.Combine(projectRoot, assetPath.Replace('/', Path.DirectorySeparatorChar));
        }

        private static string SafeFileName(string value)
        {
            foreach (char invalid in Path.GetInvalidFileNameChars())
                value = value.Replace(invalid, '_');
            return value;
        }

        private static string Success(string result)
        {
            return JsonUtility.ToJson(new Response { ok = true, result = result ?? "" });
        }

        private static string Error(string message)
        {
            return JsonUtility.ToJson(new Response { ok = false, error = message ?? "Unknown Unity bridge error." });
        }

        private static void WritePortFile(int port)
        {
            try
            {
                string root = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                string folder = Path.Combine(root, "TA_AI_Studio_MCPHost");
                Directory.CreateDirectory(folder);
                File.WriteAllText(Path.Combine(folder, "unity_port.txt"), port.ToString());
            }
            catch (Exception exception)
            {
                Debug.LogWarning("Tech Connector could not write the Unity port file: " + exception.Message);
            }
        }
    }
}
#endif
