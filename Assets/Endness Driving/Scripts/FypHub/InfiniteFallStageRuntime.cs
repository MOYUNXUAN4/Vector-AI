using UnityEngine;

/// <summary>
/// Legacy bridge for old scene component bindings.
/// Keeps existing scene objects working while new modular scripts drive gameplay.
/// </summary>
public class InfiniteFallStageRuntime : MonoBehaviour
{
    [SerializeField] private InfiniteFallGameController controller;

    private void Awake()
    {
        if (controller == null)
            controller = FindObjectOfType<InfiniteFallGameController>();

        if (controller == null)
        {
            GameObject root = new GameObject("GameRoot");
            controller = root.AddComponent<InfiniteFallGameController>();
        }

        enabled = false;
    }
}
#if false
using UnityEngine;

/// <summary>
/// Legacy bridge for older scene bindings.
/// This component now forwards to the new modular Infinite Fall stack.
/// </summary>
public class InfiniteFallStageRuntime : MonoBehaviour
{
    [SerializeField] private InfiniteFallGameController controller;

    private void Awake()
    {
        if (controller == null)
            controller = FindObjectOfType<InfiniteFallGameController>();

        if (controller == null)
        {
            GameObject root = new GameObject("GameRoot");
            controller = root.AddComponent<InfiniteFallGameController>();
        }

        enabled = false;
    }
}
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

public class InfiniteFallStageRuntime : MonoBehaviour
{
    [Header("Scene Routing")]
    [SerializeField] private string menuSceneName = "FypHub";

    [Header("Gameplay")]
    [SerializeField] private Transform platformPrefab;
    [SerializeField] private float platformRadius = 3.8f;
    [SerializeField] private float holeRadius = 0.85f;
    [SerializeField] private float layerThickness = 0.4f;
    [SerializeField] private float layerGap = 12f;
    [SerializeField] private int initialLayerCount = 6;

    [SerializeField] private float gravity = -20f;
    [SerializeField] private float bounceUp = 0.35f;
    [SerializeField] private float horizontalFriction = 0.995f;
    [SerializeField] private float groundControlForce = 8f;
    [SerializeField] private float airControlForce = 1.5f;
    [SerializeField] private float platformSpreadRadius = 1.8f;
    [SerializeField] private float platformTopOffset = 0f;
    [SerializeField] private float tiltSlopeForce = 14f;
    [SerializeField] private float tiltCarryForce = 24f;
    [SerializeField] private float minHorizontalSpeedForAssist = 0.2f;
    [SerializeField] private float assistSlideSpeed = 2.8f;

    [Header("Ball and Camera")]
    [SerializeField] private bool requireSceneBall = true;
    [SerializeField] private string requiredBallName = "PF_Ball";
    [SerializeField] private float ballSize = 0.5f;
    [SerializeField] private Vector3 ballSpawnPosition = new Vector3(1.8f, 2f, 0f);
    [SerializeField] private bool overrideSceneBallScale = false;
    [SerializeField] private Transform ballVisual;
    [SerializeField] private Camera gameplayCamera;
    [SerializeField] private bool forceDedicatedCamera = true;
    [SerializeField] private Vector3 cameraOffset = new Vector3(0f, 15f, -14f);
    [SerializeField] private float cameraSmooth = 6f;

    private readonly List<PlatformData> _platforms = new List<PlatformData>();

    private Vector3 _ballPos;
    private Vector3 _ballVel;
    private float _prevBallY;
    private float _tiltX;
    private float _tiltZ;
    private float _visualCamY;
    private float _rollX;
    private float _rollZ;

    private int _score;
    private int _currentLayerIndex;
    private bool _isGameOver;
    private bool _isFallingOffEdge;
    private bool _runtimeReady;

    private Material _platformMaterial;
    private Material _sideMaterial;
    private Material _holeMaterial;
    private Material _ballMaterial;
    private Rigidbody _ballRb;
    private SphereCollider _ballCollider;

    private struct PlatformData
    {
        public float y;
        public Vector2 center;
        public Vector2 holeCenter;
        public Transform root;
    }

    private void Start()
    {
        AutoBindSceneReferences();
        _runtimeReady = EnsureRuntimeObjects();
        if (!_runtimeReady) return;
        CreateMaterials();
        ResetGame();
    }

    private void Update()
    {
        if (!_runtimeReady) return;
        float dt = Time.deltaTime;
        if (dt <= 0f) return;

        if (!_isGameOver)
        {
            ManagePlatforms();
        }

        UpdateCamera(dt);
        UpdateVisuals(dt);

        if (_isGameOver && IsPrimaryClickDown())
            ResetGame();
    }

    private void FixedUpdate()
    {
        if (!_runtimeReady || _isGameOver) return;
        UpdatePhysics(Time.fixedDeltaTime);
    }

    private void AutoBindSceneReferences()
    {
        if (platformPrefab == null)
        {
            GameObject platformTemplate = GameObject.Find("PF_PlatformRing");
            if (platformTemplate != null)
            {
                platformPrefab = platformTemplate.transform;
                // Hide template in scene to avoid "extra platform at start".
                platformTemplate.SetActive(false);
            }
        }

        if (ballVisual == null)
        {
            string[] candidateNames = { requiredBallName, "PF_Ball", "Ball", "ball" };
            for (int i = 0; i < candidateNames.Length; i++)
            {
                GameObject candidate = GameObject.Find(candidateNames[i]);
                if (candidate != null)
                {
                    ballVisual = candidate.transform;
                    break;
                }
            }

            if (ballVisual == null)
            {
                GameObject[] allRoots = gameObject.scene.GetRootGameObjects();
                for (int i = 0; i < allRoots.Length; i++)
                {
                    Transform[] allChildren = allRoots[i].GetComponentsInChildren<Transform>(true);
                    for (int j = 0; j < allChildren.Length; j++)
                    {
                        string n = allChildren[j].name;
                        if (n.Contains("PF_Ball") || n.Contains("pf_ball") || n.Contains(requiredBallName))
                        {
                            ballVisual = allChildren[j];
                            break;
                        }
                    }
                    if (ballVisual != null) break;
                }
            }
        }
    }

    private bool EnsureRuntimeObjects()
    {
        if (ballVisual == null)
        {
            Debug.LogError($"[InfiniteFallStageRuntime] 没找到场景球。请将你的球命名为 '{requiredBallName}' 或手动拖到 ballVisual。");
            return false;
        }

        if (forceDedicatedCamera)
        {
            Camera[] allCameras = FindObjectsOfType<Camera>(true);
            for (int i = 0; i < allCameras.Length; i++)
            {
                if (allCameras[i] != gameplayCamera)
                    allCameras[i].enabled = false;
            }

            if (gameplayCamera == null)
            {
                GameObject go = new GameObject("InfiniteFallCamera");
                gameplayCamera = go.AddComponent<Camera>();
            }
            gameplayCamera.enabled = true;
            gameplayCamera.transform.position = new Vector3(0f, 15f, -14f);
            gameplayCamera.transform.rotation = Quaternion.Euler(35f, 0f, 0f);
            gameplayCamera.tag = "MainCamera";
            gameplayCamera.clearFlags = CameraClearFlags.Skybox;
        }
        else if (gameplayCamera == null)
        {
            Camera cam = Camera.main;
            if (cam == null)
            {
                GameObject go = new GameObject("InfiniteFallCamera");
                cam = go.AddComponent<Camera>();
            }
            gameplayCamera = cam;
        }

        if (FindObjectOfType<Light>() == null)
        {
            GameObject lightGo = new GameObject("InfiniteFallDirectionalLight");
            Light light = lightGo.AddComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = 1.2f;
            light.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
        }

        _ballRb = ballVisual.GetComponent<Rigidbody>();
        if (_ballRb == null) _ballRb = ballVisual.gameObject.AddComponent<Rigidbody>();
        _ballRb.isKinematic = false;
        _ballRb.useGravity = false;
        _ballRb.mass = 1f;
        _ballRb.linearDamping = 0f;
        _ballRb.angularDamping = 0.05f;
        _ballRb.interpolation = RigidbodyInterpolation.Interpolate;
        _ballRb.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic;
        _ballRb.constraints = RigidbodyConstraints.FreezeRotation;

        _ballCollider = ballVisual.GetComponent<SphereCollider>();
        if (_ballCollider == null) _ballCollider = ballVisual.gameObject.AddComponent<SphereCollider>();
        _ballCollider.isTrigger = false;
        _ballCollider.radius = 0.5f;

        return true;
    }

    private void CreateMaterials()
    {
        Shader shader = Shader.Find("Universal Render Pipeline/Lit");
        if (shader == null) shader = Shader.Find("Standard");

        _platformMaterial = new Material(shader) { color = new Color(0.94f, 0.96f, 0.97f) };
        _sideMaterial = new Material(shader) { color = new Color(0.50f, 0.59f, 0.64f) };
        _holeMaterial = new Material(shader) { color = new Color(0.31f, 0.43f, 0.47f) };
        _ballMaterial = new Material(shader) { color = new Color(0.16f, 0.39f, 0.55f) };
    }

    private void ResetGame()
    {
        for (int i = 0; i < _platforms.Count; i++)
        {
            if (_platforms[i].root != null) Destroy(_platforms[i].root.gameObject);
        }
        _platforms.Clear();

        _ballPos = ballSpawnPosition;
        if (platformPrefab != null && new Vector2(_ballPos.x, _ballPos.z).magnitude < holeRadius + ballSize * 0.6f)
        {
            // Prevent spawn over the center hole on prefab platforms.
            _ballPos.x = holeRadius + ballSize + 0.5f;
            _ballPos.z = 0f;
        }
        _ballVel = Vector3.zero;
        _prevBallY = _ballPos.y;
        _tiltX = 0f;
        _tiltZ = 0f;
        _rollX = 0f;
        _rollZ = 0f;
        _score = 0;
        _currentLayerIndex = 0;
        _isGameOver = false;
        _isFallingOffEdge = false;
        _visualCamY = _ballPos.y;

        int safeLayerCount = Mathf.Max(3, initialLayerCount);
        for (int i = 0; i < safeLayerCount; i++)
            _platforms.Add(CreatePlatform(-i * layerGap));
        Debug.Log($"[InfiniteFallStageRuntime] Spawned platforms: {_platforms.Count}");

        if (!requireSceneBall || overrideSceneBallScale)
        {
            ballVisual.localScale = Vector3.one * ballSize;
        }
        ballVisual.position = _ballPos;
        if (_ballRb != null)
        {
            _ballRb.linearVelocity = Vector3.zero;
            _ballRb.angularVelocity = Vector3.zero;
            _ballRb.position = _ballPos;
        }
        if (!requireSceneBall)
        {
            Renderer ballRenderer = ballVisual.GetComponent<Renderer>();
            if (ballRenderer != null) ballRenderer.sharedMaterial = _ballMaterial;
        }
    }

    private void UpdatePhysics(float dt)
    {
        _ballPos = _ballRb != null ? _ballRb.position : ballVisual.position;
        _ballVel = _ballRb != null ? _ballRb.linearVelocity : _ballVel;

        bool pressing = Input.GetMouseButton(0);
        if (pressing)
        {
            float inputX = (Input.mousePosition.x - Screen.width * 0.5f) * 0.002f;
            float inputY = (Input.mousePosition.y - Screen.height * 0.5f) * 0.002f;
            _tiltX = Mathf.Lerp(_tiltX, Mathf.Clamp(-inputY * 1.5f, -0.4f, 0.4f), 0.1f);
            _tiltZ = Mathf.Lerp(_tiltZ, Mathf.Clamp(inputX * 1.5f, -0.4f, 0.4f), 0.1f);
        }
        else
        {
            _tiltX = Mathf.Lerp(_tiltX, 0f, 0.1f);
            _tiltZ = Mathf.Lerp(_tiltZ, 0f, 0.1f);
        }

        _prevBallY = _ballPos.y;
        if (_ballRb != null) _ballRb.AddForce(Vector3.up * gravity, ForceMode.Acceleration);
        _ballVel = _ballRb != null ? _ballRb.linearVelocity : _ballVel;
        bool onGround = false;

        if (!_isFallingOffEdge)
        {
            for (int i = 0; i < _platforms.Count; i++)
            {
                PlatformData p = _platforms[i];
                float surfaceY = p.y + layerThickness * 0.5f + ballSize * 0.5f + platformTopOffset;

                float passBand = Mathf.Max(0.8f, Mathf.Abs(_ballVel.y) * dt * 1.5f);
                bool crossingSurface = _ballVel.y < 0f &&
                                       _prevBallY >= surfaceY - 0.1f &&
                                       _ballPos.y <= surfaceY + 0.2f &&
                                       _ballPos.y >= surfaceY - passBand;
                if (!crossingSurface) continue;

                Vector2 xz = new Vector2(_ballPos.x, _ballPos.z);
                Vector2 localXZ = xz - p.center;
                float distHole = Vector2.Distance(p.holeCenter, localXZ);
                float distCenter = localXZ.magnitude;

                if (distHole < holeRadius * 0.85f)
                    continue;

                if (distCenter < platformRadius)
                {
                    _ballPos.y = surfaceY;
                    _ballVel.y = Mathf.Abs(_ballVel.y) * bounceUp;
                    onGround = true;
                    if (_ballRb != null)
                    {
                        _ballRb.position = _ballPos;
                        _ballRb.linearVelocity = _ballVel;
                    }

                    int layerIdx = Mathf.RoundToInt(Mathf.Abs(p.y) / layerGap);
                    if (layerIdx > _currentLayerIndex) _currentLayerIndex = layerIdx;
                }
            }
        }

        float controlForce = onGround ? groundControlForce : airControlForce;
        Vector3 controlAccel = new Vector3(Mathf.Sin(_tiltZ), 0f, -Mathf.Sin(_tiltX)) * controlForce;
        if (_ballRb != null) _ballRb.AddForce(controlAccel, ForceMode.Acceleration);
        _ballVel = _ballRb != null ? _ballRb.linearVelocity : _ballVel;

        // Always apply tilt carry so rotating platform can move the ball clearly.
        Vector3 tiltCarryAccel = new Vector3(Mathf.Sin(_tiltZ), 0f, -Mathf.Sin(_tiltX)) * tiltCarryForce;
        if (_ballRb != null) _ballRb.AddForce(tiltCarryAccel, ForceMode.Acceleration);
        _ballVel = _ballRb != null ? _ballRb.linearVelocity : _ballVel;
        if (onGround)
        {
            Vector3 slopeAccel = new Vector3(Mathf.Sin(_tiltZ), 0f, -Mathf.Sin(_tiltX)) * tiltSlopeForce;
            if (_ballRb != null) _ballRb.AddForce(slopeAccel, ForceMode.Acceleration);
            _ballVel = _ballRb != null ? _ballRb.linearVelocity : _ballVel;

            Vector3 hv = new Vector3(_ballVel.x, 0f, _ballVel.z);
            if (_ballRb != null && hv.magnitude < minHorizontalSpeedForAssist)
            {
                Vector3 assistDir = new Vector3(Mathf.Sin(_tiltZ), 0f, -Mathf.Sin(_tiltX));
                if (assistDir.sqrMagnitude > 0.0001f)
                {
                    assistDir.Normalize();
                    _ballRb.MovePosition(_ballRb.position + assistDir * assistSlideSpeed * dt);
                    _ballPos = _ballRb.position;
                }
            }
        }
        _ballVel.x *= horizontalFriction;
        _ballVel.z *= horizontalFriction;
        if (_ballRb != null)
        {
            _ballRb.linearVelocity = _ballVel;
            _ballPos = _ballRb.position;
            _ballVel = _ballRb.linearVelocity;
        }
        else
        {
            _ballPos += _ballVel * dt;
        }

        bool hasRelevantPlatform = false;
        bool insideAnyPlatform = false;
        Vector2 ballXZ = new Vector2(_ballPos.x, _ballPos.z);
        for (int i = 0; i < _platforms.Count; i++)
        {
            float surfaceY = _platforms[i].y + layerThickness * 0.5f + ballSize * 0.5f;
            float yBand = layerGap * 0.65f;
            if (Mathf.Abs(_ballPos.y - surfaceY) > yBand) continue;

            hasRelevantPlatform = true;
            if (Vector2.Distance(ballXZ, _platforms[i].center) <= platformRadius + 0.1f)
            {
                insideAnyPlatform = true;
                break;
            }
        }
        if (hasRelevantPlatform && !insideAnyPlatform) _isFallingOffEdge = true;

        if (_isFallingOffEdge && _ballPos.y < _visualCamY - 20f)
            _isGameOver = true;
    }

    private void ManagePlatforms()
    {
        PlatformData last = _platforms[_platforms.Count - 1];
        if (_ballPos.y < last.y + layerGap * 3f)
        {
            PlatformData next = CreatePlatform(last.y - layerGap);
            _platforms.Add(next);
            if (!_isFallingOffEdge) _score += 500;
        }

        PlatformData first = _platforms[0];
        if (first.y > _visualCamY + layerGap * 3f)
        {
            if (first.root != null) Destroy(first.root.gameObject);
            _platforms.RemoveAt(0);
        }
    }

    private void UpdateCamera(float dt)
    {
        float targetCamY = _ballPos.y;
        if (_isFallingOffEdge) targetCamY = _ballPos.y + 6f;
        _visualCamY = Mathf.Lerp(_visualCamY, targetCamY, 1f - Mathf.Exp(-cameraSmooth * dt));

        Vector3 lookTarget = new Vector3(0f, _visualCamY, 0f);
        gameplayCamera.transform.position = lookTarget + cameraOffset;
        gameplayCamera.transform.LookAt(lookTarget + Vector3.up * 0.7f);
    }

    private void UpdateVisuals(float dt)
    {
        _rollX += Time.time * 0.05f + _ballVel.z * 0.2f * dt;
        _rollZ += -_ballVel.x * 0.2f * dt;

        ballVisual.position = _ballPos;
        ballVisual.rotation = Quaternion.Euler(_rollX * Mathf.Rad2Deg, 0f, _rollZ * Mathf.Rad2Deg);

        Quaternion tilt = Quaternion.Euler(_tiltX * Mathf.Rad2Deg, 0f, _tiltZ * Mathf.Rad2Deg);
        for (int i = 0; i < _platforms.Count; i++)
        {
            if (_platforms[i].root != null)
                _platforms[i].root.rotation = tilt;
        }
    }

    private PlatformData CreatePlatform(float yPos)
    {
        GameObject root = new GameObject($"Platform_{yPos:0.00}");
        Vector2 platformCenter = Vector2.zero;
        if (!Mathf.Approximately(yPos, 0f))
        {
            platformCenter = Random.insideUnitCircle * platformSpreadRadius;
        }
        root.transform.position = new Vector3(platformCenter.x, yPos, platformCenter.y);

        Vector2 holeCenter;
        // 当使用建模 Prefab 时，默认采用中心洞，避免视觉和判定不一致。
        if (platformPrefab != null)
        {
            holeCenter = Vector2.zero;
        }
        else if (Mathf.Approximately(yPos, 0f))
        {
            holeCenter = new Vector2(1.8f, 0f);
        }
        else
        {
            float angle = Random.Range(0f, Mathf.PI * 2f);
            float r = Random.Range(1f, platformRadius - holeRadius - 0.4f);
            holeCenter = new Vector2(Mathf.Cos(angle) * r, Mathf.Sin(angle) * r);
        }

        if (platformPrefab != null)
        {
            Transform model = Instantiate(platformPrefab, root.transform);
            model.name = "PlatformModel";
            model.gameObject.SetActive(true);
            model.localPosition = Vector3.zero;
            model.localRotation = Quaternion.identity;
            model.localScale = Vector3.one;

            Collider[] colliders = model.GetComponentsInChildren<Collider>(true);
            if (colliders.Length == 0)
            {
                MeshFilter mf = model.GetComponentInChildren<MeshFilter>(true);
                if (mf != null && mf.sharedMesh != null)
                {
                    MeshCollider mc = mf.gameObject.AddComponent<MeshCollider>();
                    mc.sharedMesh = mf.sharedMesh;
                    mc.convex = false;
                }
            }
        }
        else
        {
            CreateRingRenderer(root.transform, holeCenter);
        }
        return new PlatformData { y = yPos, center = platformCenter, holeCenter = holeCenter, root = root.transform };
    }

    private void CreateRingRenderer(Transform parent, Vector2 holeCenter)
    {
        const int segs = 48;

        GameObject top = new GameObject("TopRing");
        top.transform.SetParent(parent, false);
        MeshFilter topMf = top.AddComponent<MeshFilter>();
        MeshRenderer topMr = top.AddComponent<MeshRenderer>();
        topMr.sharedMaterial = _platformMaterial;
        topMf.sharedMesh = BuildRingStripMesh(platformRadius, holeRadius, holeCenter, -layerThickness * 0.5f, segs);

        GameObject outer = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        outer.name = "OuterWall";
        Destroy(outer.GetComponent<Collider>());
        outer.transform.SetParent(parent, false);
        outer.transform.localScale = new Vector3(platformRadius * 2f, layerThickness * 0.5f, platformRadius * 2f);
        outer.GetComponent<Renderer>().sharedMaterial = _sideMaterial;

        GameObject hole = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        hole.name = "HoleWall";
        Destroy(hole.GetComponent<Collider>());
        hole.transform.SetParent(parent, false);
        hole.transform.localPosition = new Vector3(holeCenter.x, 0f, holeCenter.y);
        hole.transform.localScale = new Vector3(holeRadius * 2f, layerThickness * 0.55f, holeRadius * 2f);
        hole.GetComponent<Renderer>().sharedMaterial = _holeMaterial;
    }

    private static Mesh BuildRingStripMesh(float outerRadius, float innerRadius, Vector2 innerCenter, float y, int segs)
    {
        List<Vector3> verts = new List<Vector3>((segs + 1) * 2);
        List<int> tris = new List<int>(segs * 6);

        for (int i = 0; i <= segs; i++)
        {
            float t = i / (float)segs;
            float a = t * Mathf.PI * 2f;
            float ca = Mathf.Cos(a);
            float sa = Mathf.Sin(a);
            verts.Add(new Vector3(ca * outerRadius, y, sa * outerRadius));
            verts.Add(new Vector3(innerCenter.x + ca * innerRadius, y, innerCenter.y + sa * innerRadius));
        }

        for (int i = 0; i < segs; i++)
        {
            int idx = i * 2;
            tris.Add(idx);
            tris.Add(idx + 1);
            tris.Add(idx + 2);

            tris.Add(idx + 1);
            tris.Add(idx + 3);
            tris.Add(idx + 2);
        }

        Mesh mesh = new Mesh { name = "RingStrip" };
        mesh.SetVertices(verts);
        mesh.SetTriangles(tris, 0);
        mesh.RecalculateNormals();
        return mesh;
    }

    private bool IsPrimaryClickDown()
    {
        if (Input.GetMouseButtonDown(0)) return true;
        return Input.touchCount > 0 && Input.GetTouch(0).phase == TouchPhase.Began;
    }

    private void OnGUI()
    {
        GUIStyle titleStyle = new GUIStyle(GUI.skin.label)
        {
            alignment = TextAnchor.MiddleCenter,
            fontSize = 36,
            fontStyle = FontStyle.Bold,
            normal = { textColor = new Color(0.12f, 0.2f, 0.25f) }
        };

        GUIStyle hudStyle = new GUIStyle(GUI.skin.label)
        {
            alignment = TextAnchor.UpperLeft,
            fontSize = 24,
            fontStyle = FontStyle.Bold,
            normal = { textColor = new Color(0.15f, 0.2f, 0.25f) }
        };

        GUI.Label(new Rect(0f, 12f, Screen.width, 42f), "INFINITE FALL", titleStyle);
        GUI.Label(new Rect(20f, 70f, 420f, 32f), $"DEPTH: {_currentLayerIndex}", hudStyle);
        GUI.Label(new Rect(Screen.width - 260f, 70f, 240f, 32f), $"SCORE: {_score}", hudStyle);

        if (GUI.Button(new Rect(Screen.width - 120f, 20f, 100f, 36f), "EXIT"))
        {
            if (!string.IsNullOrWhiteSpace(menuSceneName))
                SceneManager.LoadScene(menuSceneName, LoadSceneMode.Single);
        }

        if (!_isGameOver) return;

        GUIStyle overStyle = new GUIStyle(GUI.skin.label)
        {
            alignment = TextAnchor.MiddleCenter,
            fontSize = 28,
            fontStyle = FontStyle.Bold,
            normal = { textColor = new Color(0.9f, 0.2f, 0.2f) }
        };

        GUI.Box(new Rect(Screen.width * 0.5f - 220f, Screen.height * 0.5f - 120f, 440f, 220f), "");
        GUI.Label(new Rect(Screen.width * 0.5f - 200f, Screen.height * 0.5f - 90f, 400f, 60f), "SESSION ENDED", overStyle);
        GUI.Label(new Rect(Screen.width * 0.5f - 200f, Screen.height * 0.5f - 20f, 400f, 40f), $"FINAL SCORE: {_score}", hudStyle);
        GUI.Label(new Rect(Screen.width * 0.5f - 200f, Screen.height * 0.5f + 30f, 400f, 40f), "CLICK TO RESTART", overStyle);
    }
}
#endif
