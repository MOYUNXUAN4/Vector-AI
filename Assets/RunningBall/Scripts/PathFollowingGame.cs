using System.Collections.Generic;
using UnityEngine;

public class PathFollowingGame : MonoBehaviour
{
    public enum PathState
    {
        Waiting = 0,
        Playing = 1,
        GameOver = 2
    }

    [Header("引用")]
    [SerializeField] Transform ball;
    [SerializeField] Camera gameCamera;

    [Header("可选")]
    [SerializeField] string menuSceneName = "";

    [Header("配色")]
    [SerializeField] Color pathColor = new Color(1f, 1f, 1f, 1f);
    [SerializeField] Color accentColor = new Color(0f, 120f / 255f, 210f / 255f, 190f / 255f);
    [SerializeField] Color hudAccent = new Color(0f, 120f / 255f, 210f / 255f, 1f);
    [SerializeField] Color hudText = new Color(20f / 255f, 30f / 255f, 40f / 255f, 1f);
    [SerializeField] Color hudWarn = new Color(1f, 60f / 255f, 60f / 255f, 1f);

    [Header("游戏参数")]
    [SerializeField] float baseSpeed = 24f;
    [SerializeField] float speedLerp = 0.06f;
    
    // AI 动态控制的目标参数，用来做平滑过渡
    [SerializeField] float pathWidth = 4.3f;
    private float targetPathWidth = 4.3f;
    [SerializeField] float turnAmplitude = 26f;
    private float targetTurnAmplitude = 26f;

    [SerializeField] float ballRadius = 0.25f;
    [SerializeField] float ballFixedZ = -2.6f;
    [SerializeField] float steerLerp = 0.14f;
    [SerializeField] float steerScreenNormDiv = 0.5f;
    [SerializeField] float steerMaxOffsetMul = 1.2f;
    [SerializeField] float offTrackExtra = 0.18f;

    [Header("路径生成")]
    [SerializeField] float turnNoiseStep = 0.012f;
    [SerializeField] float turnLerp = 0.26f;
    [SerializeField] float turnBaseStrength = 0.85f;
    [SerializeField] float segStep = 1f;
    [SerializeField] float frontZ = 75f;
    [SerializeField] float backZTarget = -280f;

    [Header("相机")]
    [SerializeField] Vector3 cameraLocalOffset = new Vector3(0f, 2.8f, -5.2f);
    [SerializeField] Vector3 lookLocalOffset = new Vector3(0f, 0.6f, 17f);
    [SerializeField] float camFollowLerpWaiting = 0.08f;
    [SerializeField] float camFollowLerpPlaying = 0.10f;

    [Header("路径网格")]
    [SerializeField] int subNear = 6;
    [SerializeField] int subMid = 2;
    [SerializeField] int subFar = 1;
    [SerializeField] float hideBehindBallZ = 3.8f;
    [SerializeField] float fadeStartDist = 26f;
    [SerializeField] float fadeEndDist = 110f;
    [SerializeField] float zCullAheadOfCamera = 60f;
    [SerializeField] float roadSurfaceY = 0.02f;

    PathState pathState = PathState.Waiting;

    readonly List<Vector3> pathSegments = new List<Vector3>(512);
    float noiseOffset;
    float currentSpeed;
    float playerX;
    float inputZeroX;
    float camFollowX;
    int distanceTravelled;
    float startTime;
    float timeSeconds;

    float ballBaseY;
    Mesh roadMesh;
    MeshFilter roadMeshFilter;
    MeshRenderer roadMeshRenderer;
    Material roadMaterial;
    Material lineMaterial;
    LineRenderer centerLine;

    readonly List<Vector3> meshVerts = new List<Vector3>(4096);
    readonly List<int> meshTris = new List<int>(8192);
    readonly List<Color32> meshColors = new List<Color32>(4096);
    readonly List<Vector2> meshUvs = new List<Vector2>(4096);

    GUIStyle titleStyle;
    GUIStyle boxStyle;
    GUIStyle bigStyle;
    GUIStyle smallStyle;
    bool guiStylesReady;

    void Awake()
    {
        if (gameCamera == null) gameCamera = Camera.main;

        if (!enabled)
        {
            DisableGeneratedRoadVisuals();
            return;
        }

        EnsureRoadRenderer();
        targetPathWidth = pathWidth;
        targetTurnAmplitude = turnAmplitude;
    }

    void Start()
    {
        if (ball != null) ballBaseY = ball.position.y;
        ResetPathGame();
    }

    void Update()
    {
        // 平滑插值难度参数，防止画面突变
        pathWidth = Mathf.Lerp(pathWidth, targetPathWidth, Time.deltaTime * 2f);
        turnAmplitude = Mathf.Lerp(turnAmplitude, targetTurnAmplitude, Time.deltaTime * 1.5f);

        UpdatePathGameLogic();
        UpdateRoadMesh();
        UpdateCenterLine();
        HandleMouse();
    }

    void LateUpdate()
    {
        UpdateBallTransform();
        UpdateCameraTransform();
    }

    void EnsureRoadRenderer()
    {
        Transform existing = transform.Find("_PathRoadMesh");
        GameObject go = existing != null ? existing.gameObject : new GameObject("_PathRoadMesh");
        go.transform.SetParent(transform, false);
        go.transform.localPosition = Vector3.zero;
        go.transform.localRotation = Quaternion.identity;
        go.transform.localScale = Vector3.one;
        go.SetActive(true);

        roadMeshFilter = go.GetComponent<MeshFilter>();
        if (roadMeshFilter == null) roadMeshFilter = go.AddComponent<MeshFilter>();
        roadMeshRenderer = go.GetComponent<MeshRenderer>();
        if (roadMeshRenderer == null) roadMeshRenderer = go.AddComponent<MeshRenderer>();

        roadMesh = roadMeshFilter.sharedMesh;
        if (roadMesh == null)
        {
            roadMesh = new Mesh { name = "PathRoadRuntime" };
            roadMesh.MarkDynamic();
            roadMeshFilter.sharedMesh = roadMesh;
        }

        Shader roadShader = PickRoadShader();
        roadMaterial = new Material(roadShader);
        ApplyOpaqueRoadMaterial(roadMaterial);
        roadMeshRenderer.sharedMaterial = roadMaterial;

        GameObject lineGo = transform.Find("_PathCenterLine") != null
            ? transform.Find("_PathCenterLine").gameObject
            : new GameObject("_PathCenterLine");
        lineGo.transform.SetParent(transform, false);
        lineGo.SetActive(true);
        centerLine = lineGo.GetComponent<LineRenderer>();
        if (centerLine == null) centerLine = lineGo.AddComponent<LineRenderer>();
        centerLine.loop = false;
        centerLine.useWorldSpace = true;
        centerLine.widthMultiplier = 0.03f;
        centerLine.numCornerVertices = 2;
        lineMaterial = new Material(roadShader);
        lineMaterial.color = accentColor;
        if (lineMaterial.HasProperty("_BaseColor")) lineMaterial.SetColor("_BaseColor", accentColor);
        centerLine.sharedMaterial = lineMaterial;
    }

    void DisableGeneratedRoadVisuals()
    {
        Transform roadMeshTransform = transform.Find("_PathRoadMesh");
        if (roadMeshTransform != null) roadMeshTransform.gameObject.SetActive(false);

        Transform centerLineTransform = transform.Find("_PathCenterLine");
        if (centerLineTransform != null) centerLineTransform.gameObject.SetActive(false);
    }

    static Shader PickRoadShader()
    {
        Shader s = Shader.Find("Universal Render Pipeline/Unlit");
        if (s == null) s = Shader.Find("Universal Render Pipeline/Particles/Unlit");
        if (s == null) s = Shader.Find("Particles/Standard Unlit");
        if (s == null) s = Shader.Find("Unlit/Color");
        return s;
    }

    void ApplyOpaqueRoadMaterial(Material m)
    {
        if (m == null) return;
        m.color = pathColor;
        if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", pathColor);
        if (m.HasProperty("_Surface")) m.SetFloat("_Surface", 0f);
        if (m.HasProperty("_Blend")) m.SetFloat("_Blend", 0f);
        m.renderQueue = 2000;
    }

    public void ResetPathGame()
    {
        pathSegments.Clear();
        noiseOffset = Random.Range(0f, 1000f);
        float prevX = 0f;

        for (float z = frontZ; z > backZTarget; z -= segStep)
        {
            float n = (Mathf.PerlinNoise(noiseOffset, 0f) - 0.5f) * turnAmplitude * turnBaseStrength;
            float x = Mathf.Lerp(prevX, n, turnLerp);
            pathSegments.Add(new Vector3(x, 0f, z));
            prevX = x;
            noiseOffset += turnNoiseStep;
        }

        camFollowX = GetPathXAt(ballFixedZ);
        playerX = 0f;
        inputZeroX = Screen.width * 0.5f;
        distanceTravelled = 0;
        currentSpeed = 0f;
        timeSeconds = 0f;
        startTime = Time.time;
        pathState = PathState.Waiting;
    }

    void UpdatePathGameLogic()
    {
        if (pathSegments.Count < 2) return;

        float camZ = gameCamera != null ? gameCamera.transform.position.z : cameraLocalOffset.z;
        float zCullQueueHead = camZ + zCullAheadOfCamera;

        if (pathState == PathState.Waiting)
        {
            camFollowX = Mathf.Lerp(camFollowX, GetPathXAt(ballFixedZ), camFollowLerpWaiting);

            float dx = Input.mousePosition.x - inputZeroX;
            float norm = dx / (Screen.width * steerScreenNormDiv);
            norm = Mathf.Clamp(norm, -1f, 1f);
            float targetX = norm * (pathWidth * steerMaxOffsetMul);
            playerX = Mathf.Lerp(playerX, targetX, steerLerp);

            currentSpeed = Mathf.Lerp(currentSpeed, 0f, 0.25f);
            timeSeconds = 0f;
        }
        else if (pathState == PathState.Playing)
        {
            currentSpeed = Mathf.Lerp(currentSpeed, baseSpeed, speedLerp);
            timeSeconds = Time.time - startTime;
            distanceTravelled++;

            float dx = Input.mousePosition.x - inputZeroX;
            float norm = dx / (Screen.width * steerScreenNormDiv);
            norm = Mathf.Clamp(norm, -1f, 1f);
            float targetX = norm * (pathWidth * steerMaxOffsetMul);
            playerX = Mathf.Lerp(playerX, targetX, steerLerp);

            float dt = Time.deltaTime;
            for (int i = 0; i < pathSegments.Count; i++)
            {
                Vector3 p = pathSegments[i];
                p.z += currentSpeed * dt;
                pathSegments[i] = p;
            }

            Vector3 lastP = pathSegments[pathSegments.Count - 1];
            if (lastP.z > backZTarget)
            {
                float strength = 0.55f + 0.45f * Mathf.Min(1f, distanceTravelled / 600f);
                noiseOffset += turnNoiseStep;
                float n = (Mathf.PerlinNoise(noiseOffset, 0f) - 0.5f) * turnAmplitude * strength;
                float newX = Mathf.Lerp(lastP.x, n, turnLerp);
                pathSegments.Add(new Vector3(newX, 0f, lastP.z - segStep));
            }

            camFollowX = Mathf.Lerp(camFollowX, GetPathXAt(ballFixedZ), camFollowLerpPlaying);

            while (pathSegments.Count > 2 && pathSegments[0].z > zCullQueueHead)
                pathSegments.RemoveAt(0);

            float pathX = GetPathXAt(ballFixedZ);
            if (Mathf.Abs(playerX - pathX) > pathWidth * 0.5f + offTrackExtra)
                pathState = PathState.GameOver;
        }
    }

    void HandleMouse()
    {
        if (!Input.GetMouseButtonDown(0)) return;

        if (IsPointerOverExitButton())
        {
            TryExitToMenu();
            return;
        }

        if (pathState == PathState.Waiting)
        {
            inputZeroX = Input.mousePosition.x;
            pathState = PathState.Playing;
            startTime = Time.time;
        }
        else if (pathState == PathState.GameOver)
        {
            ResetPathGame();
        }
    }

    bool IsPointerOverExitButton()
    {
        Vector3 mp = Input.mousePosition;
        float x = mp.x;
        float y = Screen.height - mp.y;
        return x > Screen.width - 120 && x < Screen.width - 20 && y > 20 && y < 60;
    }

    void TryExitToMenu()
    {
        if (!string.IsNullOrEmpty(menuSceneName))
            UnityEngine.SceneManagement.SceneManager.LoadScene(menuSceneName);
        else
            Debug.Log("[PathFollowingGame] EXIT：未配置 menuSceneName，未加载场景。");
    }

    void UpdateBallTransform()
    {
        if (ball == null) return;
        ball.position = new Vector3(playerX, ballBaseY, ballFixedZ);
    }

    void UpdateCameraTransform()
    {
        if (gameCamera == null) return;
        float bx = camFollowX;
        float bz = ball != null ? ball.position.z : ballFixedZ;
        float by = ball != null ? ball.position.y : ballBaseY;

        Vector3 camPos = new Vector3(bx + cameraLocalOffset.x, by + cameraLocalOffset.y, bz + cameraLocalOffset.z);
        Vector3 look = new Vector3(bx + lookLocalOffset.x, by + lookLocalOffset.y, bz + lookLocalOffset.z);
        gameCamera.transform.position = camPos;
        gameCamera.transform.rotation = Quaternion.LookRotation(look - camPos, Vector3.up);
    }

    float GetPathXAt(float zQuery)
    {
        if (pathSegments.Count < 2) return 0f;
        for (int i = 0; i < pathSegments.Count - 1; i++)
        {
            Vector3 p1 = pathSegments[i];
            Vector3 p2 = pathSegments[i + 1];
            if (p1.z >= zQuery && p2.z <= zQuery)
            {
                float denom = p1.z - p2.z;
                float t = denom == 0f ? 0f : (p1.z - zQuery) / denom;
                t = Mathf.Clamp01(t);
                return CatmullXAtSegment(i, t);
            }
        }

        return pathSegments[pathSegments.Count - 1].x;
    }

    float CatmullXAtSegment(int i, float t)
    {
        int i0 = Mathf.Max(i - 1, 0);
        int i1 = i;
        int i2 = Mathf.Min(i + 1, pathSegments.Count - 1);
        int i3 = Mathf.Min(i + 2, pathSegments.Count - 1);
        return Catmull(
            pathSegments[i0].x,
            pathSegments[i1].x,
            pathSegments[i2].x,
            pathSegments[i3].x,
            t);
    }

    static float Catmull(float p0, float p1, float p2, float p3, float t)
    {
        float t2 = t * t;
        float t3 = t2 * t;
        return 0.5f * ((2f * p1) + (-p0 + p2) * t + (2f * p0 - 5f * p1 + 4f * p2 - p3) * t2 + (-p0 + 3f * p1 - 3f * p2 + p3) * t3);
    }

    void UpdateRoadMesh()
    {
        if (roadMesh == null || pathSegments.Count < 2) return;

        float camZ = gameCamera != null ? gameCamera.transform.position.z : 0f;
        float zSkipBothVeryHigh = camZ + (gameCamera != null ? gameCamera.farClipPlane : 500f);
        float zHideBothAbove = Mathf.Max(120f, ballFixedZ + hideBehindBallZ + frontZ);

        meshVerts.Clear();
        meshTris.Clear();
        meshColors.Clear();
        meshUvs.Clear();

        for (int i = pathSegments.Count - 2; i >= 0; i--)
        {
            Vector3 p1 = pathSegments[i];
            Vector3 p2 = pathSegments[i + 1];
            if (p1.z > zSkipBothVeryHigh && p2.z > zSkipBothVeryHigh) continue;
            if (p1.z > zHideBothAbove && p2.z > zHideBothAbove) continue;

            float zMid = (p1.z + p2.z) * 0.5f;
            float distForward = Mathf.Abs(zMid - ballFixedZ);
            int sub = distForward < 25f ? subNear : (distForward < 90f ? subMid : subFar);

            for (int s = 0; s <= sub; s++)
            {
                float tt = sub == 0 ? 0f : s / (float)sub;
                float z = Mathf.Lerp(p1.z, p2.z, tt);
                if (z > zHideBothAbove) continue;
                float x = CatmullXAtSegment(i, tt);
                float a = 1f;
                if (distForward > fadeStartDist)
                    a = Mathf.Clamp01(Mathf.InverseLerp(fadeEndDist, fadeStartDist, distForward));

                byte ab = (byte)(a * 255f);
                Color32 c = new Color32(255, 255, 255, ab);
                float half = pathWidth * 0.5f;
                int baseIndex = meshVerts.Count;
                meshVerts.Add(new Vector3(x - half, roadSurfaceY, z));
                meshVerts.Add(new Vector3(x + half, roadSurfaceY, z));
                meshColors.Add(c);
                meshColors.Add(c);
                meshUvs.Add(Vector2.zero);
                meshUvs.Add(Vector2.right);

                if (baseIndex >= 2)
                {
                    meshTris.Add(baseIndex - 2);
                    meshTris.Add(baseIndex - 1);
                    meshTris.Add(baseIndex);
                    meshTris.Add(baseIndex - 1);
                    meshTris.Add(baseIndex + 1);
                    meshTris.Add(baseIndex);
                }
            }
        }

        roadMesh.Clear();
        if (meshVerts.Count < 4) return;

        roadMesh.SetVertices(meshVerts);
        roadMesh.SetTriangles(meshTris, 0, true);
        roadMesh.SetColors(meshColors);
        roadMesh.SetUVs(0, meshUvs);
        roadMesh.RecalculateNormals();
        roadMesh.RecalculateBounds();
    }

    void UpdateCenterLine()
    {
        if (centerLine == null || pathSegments.Count < 2) return;

        float camZ = gameCamera != null ? gameCamera.transform.position.z : 0f;
        float zSkipVeryHigh = camZ + (gameCamera != null ? gameCamera.farClipPlane : 500f);
        float zHideAbove = Mathf.Max(120f, ballFixedZ + hideBehindBallZ + frontZ);

        int stride = 2;
        int count = 0;
        for (int i = pathSegments.Count - 1; i >= 0; i -= stride)
        {
            Vector3 p = pathSegments[i];
            if (p.z > zSkipVeryHigh) continue;
            if (p.z > zHideAbove) continue;
            count++;
        }

        if (count < 2)
        {
            centerLine.positionCount = 0;
            return;
        }

        centerLine.positionCount = count;
        int idx = 0;
        for (int i = pathSegments.Count - 1; i >= 0; i -= stride)
        {
            Vector3 p = pathSegments[i];
            if (p.z > zSkipVeryHigh) continue;
            if (p.z > zHideAbove) continue;
            centerLine.SetPosition(idx++, new Vector3(p.x, roadSurfaceY + 0.01f, p.z));
        }

        lineMaterial.color = accentColor;
    }

    void OnGUI()
    {
        EnsureGuiStyles();

        float cx = Screen.width * 0.5f;
        float cy = Screen.height * 0.5f;
        float topMargin = 30f;

        GUI.color = new Color(1f, 1f, 1f, 0.94f);
        GUI.Box(new Rect(cx - 170f, topMargin, 340f, 50f), GUIContent.none, boxStyle);
        GUI.color = hudAccent;
        GUI.Label(new Rect(cx - 160f, topMargin + 8f, 320f, 40f), "PATH FOLLOWING MODULE", titleStyle);

        DrawMetricCard(40f + 125f, cy, 250f, 130f, "TIME", $"{timeSeconds:0.0} s", hudText);
        DrawMetricCard(Screen.width - 40f - 125f, cy, 250f, 130f, "DISTANCE", $"{Mathf.FloorToInt(distanceTravelled / 10f)} m", hudAccent);

        if (pathState == PathState.Waiting)
            DrawCenterBanner("CLICK TO START", "Move mouse to steer");
        else if (pathState == PathState.GameOver)
            DrawGameOverBanner();

        GUI.color = new Color(1f, 1f, 1f, 0.5f);
        GUI.Box(new Rect(Screen.width - 120f, 20f, 100f, 40f), GUIContent.none);
        GUI.color = new Color(0.2f, 0.2f, 0.2f, 1f);
        GUI.Label(new Rect(Screen.width - 120f, 20f, 100f, 40f), "EXIT", titleStyle);
        GUI.color = Color.white;
    }

    void EnsureGuiStyles()
    {
        if (guiStylesReady) return;
        guiStylesReady = true;

        titleStyle = new GUIStyle(GUI.skin.label)
        {
            fontSize = 20,
            alignment = TextAnchor.MiddleCenter,
            fontStyle = FontStyle.Bold
        };

        boxStyle = new GUIStyle(GUI.skin.box) { border = new RectOffset(6, 6, 6, 6) };

        bigStyle = new GUIStyle(GUI.skin.label)
        {
            fontSize = 40,
            alignment = TextAnchor.MiddleCenter,
            fontStyle = FontStyle.Bold
        };

        smallStyle = new GUIStyle(GUI.skin.label)
        {
            fontSize = 20,
            alignment = TextAnchor.MiddleCenter
        };
    }

    void DrawMetricCard(float centerX, float centerY, float w, float h, string label, string value, Color valueColor)
    {
        GUI.color = new Color(1f, 1f, 1f, 0.86f);
        GUI.Box(new Rect(centerX - w * 0.5f, centerY - h * 0.5f, w, h), GUIContent.none);
        GUI.color = new Color(0.47f, 0.47f, 0.47f, 1f);
        GUI.Label(new Rect(centerX - w * 0.5f + 25f, centerY - h * 0.5f + 20f, w - 40f, 28f), label, titleStyle);
        GUI.contentColor = valueColor;
        GUI.Label(new Rect(centerX - w * 0.5f + 25f, centerY + h * 0.5f - 62f, w - 40f, 52f), value, bigStyle);
        GUI.contentColor = Color.white;
        GUI.color = Color.white;
    }

    void DrawCenterBanner(string title, string sub)
    {
        float cy = Screen.height * 0.5f;
        GUI.color = new Color(0f, 0f, 0f, 0.59f);
        GUI.Box(new Rect(0f, cy - 60f, Screen.width, 120f), GUIContent.none);
        GUI.color = Color.white;
        GUI.Label(new Rect(0f, cy - 48f, Screen.width, 44f), title, bigStyle);
        GUI.color = new Color(0.86f, 0.86f, 0.86f, 1f);
        GUI.Label(new Rect(0f, cy + 8f, Screen.width, 30f), sub, smallStyle);
        GUI.color = Color.white;
    }

    void DrawGameOverBanner()
    {
        GUI.color = new Color(0f, 0f, 0f, 0.78f);
        GUI.Box(new Rect(0f, 0f, Screen.width, Screen.height), GUIContent.none);
        GUI.contentColor = hudWarn;
        GUI.Label(new Rect(0f, Screen.height * 0.5f - 80f, Screen.width, 70f), "OFF TRACK", bigStyle);
        GUI.contentColor = Color.white;
        GUI.Label(new Rect(0f, Screen.height * 0.5f, Screen.width, 40f), $"Distance: {Mathf.FloorToInt(distanceTravelled / 10f)}m", smallStyle);
        GUI.contentColor = hudAccent;
        GUI.Label(new Rect(0f, Screen.height * 0.5f + 60f, Screen.width, 36f), "Click to Retry", smallStyle);
        GUI.contentColor = Color.white;
        GUI.color = Color.white;
    }

    // ==============================================================
    // [新增] 专门给网络层暴露的接口，让 Python 后端能拿到数据并修改游戏
    // ==============================================================
    public float GetPlayerX() { return playerX; }
    
    public float GetTargetX() { return GetPathXAt(ballFixedZ); }
    
    public int GetDistance() { return distanceTravelled; }

    public void ApplyAIDifficulty(int level)
    {
        level = Mathf.Clamp(level, 1, 5);
        
        // Level 1 最简单: 宽路面(8f)，极缓的弯道(10f)
        // Level 5 最困难: 窄路面(2.5f)，极急的弯道(45f)
        targetPathWidth = Mathf.Lerp(8f, 2.5f, (level - 1) / 4f);
        targetTurnAmplitude = Mathf.Lerp(10f, 45f, (level - 1) / 4f);
    }
}