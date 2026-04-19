using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using System.Collections.Generic;

public class MainMenuCinematicRuntime : MonoBehaviour
{
    private const string DefaultFallbackSceneName = "Stage";

    [Header("--- 1. 布局调整 (UI Layout) ---")]
    [Tooltip("左右控制台距离中心的宽度 (数值越大越靠边)")]
    public float panelOffset = 220f; 
    [Tooltip("底部 UKM 2026 文字的高度")]
    public float footerYOffset = 60f;

    [Header("--- 2. 颜色调整 (Colors) ---")]
    [Tooltip("按钮的浅色半透明背景")]
    public Color buttonBgColor = new Color(0.9f, 0.95f, 1f, 0.85f);
    [Tooltip("按钮上的文字颜色 (深色)")]
    public Color buttonTextColor = new Color(0.15f, 0.2f, 0.25f, 1f);

    [Header("--- 3. 科技感立方体 (Cubes) ---")]
    [Tooltip("立方体的颜色 (纯白 + 低透明度)")]
    public Color cubeColor = new Color(1f, 1f, 1f, 0.15f);
    [Tooltip("中间留出的干净通道宽度 (数值越大，立方体离中间越远)")]
    public float centerClearance = 18f;
    [Tooltip("立方体的飞行速度 (越小越慢)")]
    public float cubeSpeed = 12f;

    // 【核心修改点】=================================================
    [Header("--- 4. 场景跳转 (Scene Routing) ---")]
    [SerializeField] private string pathFollowingSceneName = "PathFolling";     // 修改为你要求的名字
    [SerializeField] private string infiniteFallSceneName = "EndlessfALLING";   // 修改为你要求的名字
    [SerializeField] private string endlessDrivingSceneName = "stage";          // 修改为你要求的名字
    [SerializeField] private string posturoScanSceneName = "Stage";
    // ===============================================================

    private readonly Color32 _bgBottom = new Color32(20, 35, 50, 255);
    private readonly Color32 _bgTop = new Color32(180, 220, 235, 255);

    private GameObject _menuCameraGo;
    private GameObject _bgCanvasGo;
    private GameObject _uiCanvasGo;
    private GameObject _cubesRootGo;
    private CanvasGroup _rootGroup;

    private readonly List<Image> _lines = new List<Image>();
    private readonly List<float> _lineDepth = new List<float>();
    private readonly List<float> _linePhase = new List<float>();

    private readonly List<Transform> _cubeTransforms = new List<Transform>();
    private readonly List<float> _cubeBaseScale = new List<float>();
    private readonly List<Vector3> _cubeSpin = new List<Vector3>();

    private readonly List<RectTransform> _rulerTicks = new List<RectTransform>();
    private float _rulerOffset = 0f;

    private Text _titleText;
    private Text _subTitleText;

    private bool _isReady = false;

    private void Start()
    {
        Time.timeScale = 1f;
        NormalizeSceneRouting();
        CleanupLegacyHubGameplay();
        EnsureEventSystem();
        RebuildMenuVisuals();
        
        if (_rootGroup != null) _rootGroup.alpha = 0f;
        _isReady = true;
    }

    private void Update()
    {
        if (!_isReady) return;
        
        if (_rootGroup != null) 
            _rootGroup.alpha = Mathf.MoveTowards(_rootGroup.alpha, 1f, Time.unscaledDeltaTime * 1.7f);
            
        AnimateRoadLines();
        AnimateDecorCubes();
        AnimateRulers();
        AnimateTitleAndButton(); 
    }

    private void EnsureEventSystem()
    {
        if (EventSystem.current != null) return;
        GameObject es = new GameObject("EventSystem");
        es.AddComponent<EventSystem>();
        es.AddComponent<StandaloneInputModule>();
    }

    private void CleanupVisuals()
    {
        if (_menuCameraGo != null) Destroy(_menuCameraGo);
        if (_bgCanvasGo != null) Destroy(_bgCanvasGo);
        if (_uiCanvasGo != null) Destroy(_uiCanvasGo);
        if (_cubesRootGo != null) Destroy(_cubesRootGo);

        _lines.Clear();
        _lineDepth.Clear();
        _linePhase.Clear();
        _cubeTransforms.Clear();
        _cubeBaseScale.Clear();
        _cubeSpin.Clear();
        _rulerTicks.Clear();
    }

    public void RebuildMenuVisuals()
    {
        CleanupVisuals();

        _menuCameraGo = new GameObject("MenuCinematicCamera");
        Camera cam = _menuCameraGo.AddComponent<Camera>();
        cam.transform.position = new Vector3(0, 1, -10);
        cam.backgroundColor = _bgBottom;
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.depth = 100; 

        _bgCanvasGo = new GameObject("CinematicBGCanvas");
        Canvas bgC = _bgCanvasGo.AddComponent<Canvas>();
        bgC.renderMode = RenderMode.ScreenSpaceCamera;
        bgC.worldCamera = cam;
        bgC.planeDistance = 90f; 
        CanvasScaler bgS = _bgCanvasGo.AddComponent<CanvasScaler>();
        bgS.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        bgS.referenceResolution = new Vector2(1920, 1080);
        
        BuildGradientBackground();
        BuildRoadLines();
        BuildTrue3DCubes();

        _uiCanvasGo = new GameObject("CinematicUICanvas");
        Canvas uiC = _uiCanvasGo.AddComponent<Canvas>();
        uiC.renderMode = RenderMode.ScreenSpaceOverlay; 
        CanvasScaler uiS = _uiCanvasGo.AddComponent<CanvasScaler>();
        uiS.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        uiS.referenceResolution = new Vector2(1920, 1080);
        _uiCanvasGo.AddComponent<GraphicRaycaster>();
        _rootGroup = _uiCanvasGo.AddComponent<CanvasGroup>();

        BuildDashboardUI();
    }

    private void BuildDashboardUI()
    {
        BuildTitle();
        BuildSideRulers();

        Color32 cModA  = new Color32(0, 190, 255, 255);   
        Color32 cModB  = new Color32(255, 140, 0, 255);   
        Color32 cModC  = new Color32(50, 220, 50, 255);   
        Color32 cModD  = new Color32(140, 80, 255, 255);  

        Color32 cUser  = new Color32(255, 200, 0, 255);   
        Color32 cData  = new Color32(0, 140, 180, 255);   
        Color32 cRepo  = new Color32(255, 0, 120, 255);   
        Color32 cExit  = new Color32(255, 60, 60, 255);   

        float leftX = -panelOffset;  
        float rightX = panelOffset;  
        float startY = 120f;  
        float gap = 85f;      

        CreateSectionHeader("TRAINING MODULES", leftX, startY + 60f);
        CreateDashButton("PATH FOLLOWING", cModA, new Vector2(leftX, startY), () => LoadGame(1));
        CreateDashButton("ENDLESS FALLING", cModB, new Vector2(leftX, startY - gap), () => LoadGame(2));
        CreateDashButton("ENDLESS DRIVING", cModC, new Vector2(leftX, startY - gap * 2), () => LoadGame(3)); 
        CreateDashButton("POSTURO SCAN", cModD, new Vector2(leftX, startY - gap * 3), () => LoadGame(4));

        CreateSectionHeader("SYSTEM CONTROL", rightX, startY + 60f);
        CreateDashButton("USER LOGIN", cUser, new Vector2(rightX, startY), () => Debug.Log("Login"));
        CreateDashButton("DATA LOGS", cData, new Vector2(rightX, startY - gap), () => Debug.Log("Logs"));
        CreateDashButton("GENERATE REPORT", cRepo, new Vector2(rightX, startY - gap * 2), () => Debug.Log("Report"));
        CreateDashButton("SHUTDOWN SYSTEM", cExit, new Vector2(rightX, startY - gap * 3), () => Application.Quit());

        BuildFooter();
    }

    private void CreateSectionHeader(string title, float x, float y)
    {
        Text txt = CreateUIObject("Header_" + title, _uiCanvasGo.transform).AddComponent<Text>();
        txt.text = title;
        txt.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        txt.fontSize = 18;
        txt.fontStyle = FontStyle.Bold;
        txt.color = Color.white;
        txt.alignment = TextAnchor.MiddleCenter;
        
        RectTransform rt = txt.rectTransform;
        rt.anchorMin = new Vector2(0.5f, 0.5f); rt.anchorMax = new Vector2(0.5f, 0.5f);
        rt.anchoredPosition = new Vector2(x, y);
        rt.sizeDelta = new Vector2(300, 30);

        Image line = CreateUIObject("Line", txt.transform).AddComponent<Image>();
        line.color = new Color32(255, 255, 255, 80);
        RectTransform lrt = line.rectTransform;
        lrt.anchorMin = new Vector2(0.5f, 0f); lrt.anchorMax = new Vector2(0.5f, 0f);
        lrt.anchoredPosition = new Vector2(0, -5);
        lrt.sizeDelta = new Vector2(150, 2);
    }

    private void CreateDashButton(string label, Color32 accentColor, Vector2 pos, UnityEngine.Events.UnityAction action)
    {
        GameObject btnGo = CreateUIObject("Btn_" + label, _uiCanvasGo.transform);
        Image bgImg = btnGo.AddComponent<Image>();
        
        bgImg.color = buttonBgColor;

        Button btn = btnGo.AddComponent<Button>();
        btn.targetGraphic = bgImg;
        btn.onClick.AddListener(action);

        RectTransform rt = btnGo.GetComponent<RectTransform>();
        rt.anchorMin = new Vector2(0.5f, 0.5f); rt.anchorMax = new Vector2(0.5f, 0.5f);
        rt.anchoredPosition = pos;
        rt.sizeDelta = new Vector2(320f, 65f); 

        Image accentImg = CreateUIObject("Accent", btnGo.transform).AddComponent<Image>();
        accentImg.color = accentColor;
        RectTransform art = accentImg.rectTransform;
        art.anchorMin = new Vector2(0f, 0f); art.anchorMax = new Vector2(0f, 1f);
        art.pivot = new Vector2(0f, 0.5f);
        art.anchoredPosition = Vector2.zero;
        art.sizeDelta = new Vector2(12f, 0f); 

        Text txt = CreateUIObject("Label", btnGo.transform).AddComponent<Text>();
        txt.text = label;
        txt.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        txt.fontSize = 18;
        txt.fontStyle = FontStyle.Bold;
        txt.color = buttonTextColor;
        txt.alignment = TextAnchor.MiddleLeft;
        RectTransform trt = txt.rectTransform;
        trt.anchorMin = new Vector2(0f, 0f); trt.anchorMax = new Vector2(1f, 1f);
        trt.offsetMin = new Vector2(30f, 0f); trt.offsetMax = Vector2.zero;

        var pulse = btnGo.AddComponent<MenuButtonPulse>();
        pulse.SetupText(txt, buttonTextColor);
    }

    private void BuildTitle()
    {
        _titleText = CreateUIObject("Title", _uiCanvasGo.transform).AddComponent<Text>();
        _titleText.text = "VECTOR AI";
        _titleText.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        _titleText.fontSize = 90; 
        _titleText.fontStyle = FontStyle.Bold;
        _titleText.alignment = TextAnchor.MiddleCenter;
        _titleText.color = Color.white;

        RectTransform rt = _titleText.rectTransform;
        rt.anchorMin = new Vector2(0.5f, 0.5f); rt.anchorMax = new Vector2(0.5f, 0.5f);
        rt.anchoredPosition = new Vector2(0, 320); 
        rt.sizeDelta = new Vector2(1200f, 120f);

        _subTitleText = CreateUIObject("SubTitle", _uiCanvasGo.transform).AddComponent<Text>();
        _subTitleText.text = "C L I N I C A L    D A S H B O A R D";
        _subTitleText.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        _subTitleText.fontSize = 22;
        _subTitleText.fontStyle = FontStyle.Bold;
        _subTitleText.alignment = TextAnchor.MiddleCenter;
        _subTitleText.color = Color.white;

        RectTransform srt = _subTitleText.rectTransform;
        srt.anchorMin = new Vector2(0.5f, 0.5f); srt.anchorMax = new Vector2(0.5f, 0.5f);
        srt.anchoredPosition = new Vector2(0, 260); 
        srt.sizeDelta = new Vector2(1000f, 50f);
    }

    private void BuildFooter()
    {
        Text txt = CreateUIObject("Footer", _uiCanvasGo.transform).AddComponent<Text>();
        txt.text = "UNIVERSITI KEBANGSAAN MALAYSIA  |  2026";
        txt.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        txt.fontSize = 18;
        txt.color = new Color32(200, 210, 220, 255);
        txt.alignment = TextAnchor.LowerCenter;
        
        RectTransform rt = txt.rectTransform;
        rt.anchorMin = new Vector2(0f, 0f); rt.anchorMax = new Vector2(1f, 0f);
        rt.anchoredPosition = new Vector2(0, footerYOffset);
        rt.sizeDelta = new Vector2(0, 50);
    }

    private void BuildSideRulers()
    {
        _rulerTicks.Clear();
        CreateRulerLine(0f, true);
        CreateRulerLine(1f, false);
    }

    private void CreateRulerLine(float anchorX, bool isLeft)
    {
        Image line = CreateUIObject(isLeft ? "LeftRuler" : "RightRuler", _bgCanvasGo.transform).AddComponent<Image>();
        line.color = new Color32(255, 255, 255, 100);
        RectTransform rt = line.rectTransform;
        rt.anchorMin = new Vector2(anchorX, 0f); rt.anchorMax = new Vector2(anchorX, 1f);
        rt.anchoredPosition = new Vector2(isLeft ? 50f : -50f, 0);
        rt.sizeDelta = new Vector2(2f, 0f);

        for (int i = 0; i < 25; i++)
        {
            Image tick = CreateUIObject("Tick", line.transform).AddComponent<Image>();
            tick.color = new Color32(255, 255, 255, 150);
            RectTransform trt = tick.rectTransform;
            trt.anchorMin = new Vector2(isLeft ? 0f : 1f, 0.5f);
            trt.anchorMax = new Vector2(isLeft ? 0f : 1f, 0.5f);
            trt.pivot = new Vector2(isLeft ? 0f : 1f, 0.5f);
            
            bool isMajor = i % 4 == 0;
            trt.sizeDelta = new Vector2(isMajor ? 35f : 20f, isMajor ? 2f : 1f);
            _rulerTicks.Add(trt);
        }
    }

    private void AnimateRulers()
    {
        _rulerOffset -= Time.unscaledDeltaTime * 60f; 
        if (_rulerOffset <= -200f) _rulerOffset += 200f; 

        float spacing = 50f;
        int halfCount = _rulerTicks.Count / 2;

        for (int i = 0; i < halfCount; i++)
        {
            float yPos = _rulerOffset + (i * spacing);
            if (yPos < -540f) yPos += (halfCount * spacing); 

            float alpha = Mathf.InverseLerp(540f, 0f, Mathf.Abs(yPos)); 
            
            _rulerTicks[i].anchoredPosition = new Vector2(0, yPos);
            _rulerTicks[i].GetComponent<Image>().color = new Color(1, 1, 1, alpha * 0.8f);
            
            _rulerTicks[i + halfCount].anchoredPosition = new Vector2(0, yPos);
            _rulerTicks[i + halfCount].GetComponent<Image>().color = new Color(1, 1, 1, alpha * 0.8f);
        }
    }

    private void BuildGradientBackground()
    {
        GameObject bg = CreateUIObject("Background", _bgCanvasGo.transform);
        RawImage raw = bg.AddComponent<RawImage>();
        raw.texture = CreateVerticalGradientTexture(_bgBottom, _bgTop, 256);
        raw.raycastTarget = false;
        StretchFull(bg.GetComponent<RectTransform>());
    }

    private void BuildRoadLines()
    {
        GameObject lr = CreateUIObject("RoadLines", _bgCanvasGo.transform);
        StretchFull(lr.GetComponent<RectTransform>());

        const int count = 32;
        for (int i = 0; i < count; i++)
        {
            Image line = CreateUIObject("Line_" + i, lr.transform).AddComponent<Image>();
            line.raycastTarget = false;
            _lines.Add(line);
            _lineDepth.Add((i + 1) / (float)count);
            _linePhase.Add(Random.Range(0f, Mathf.PI * 2f));
        }
    }

    private void BuildTrue3DCubes()
    {
        _cubesRootGo = new GameObject("True3DCubesRoot");

        Material glassMat;
        Shader urpShader = Shader.Find("Universal Render Pipeline/Lit");
        if (urpShader != null)
        {
            glassMat = new Material(urpShader);
            glassMat.SetFloat("_Surface", 1.0f); 
            glassMat.SetColor("_BaseColor", cubeColor); 
            glassMat.SetFloat("_Smoothness", 0.95f);
            glassMat.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
            glassMat.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
            glassMat.SetInt("_ZWrite", 0);
            glassMat.renderQueue = 3000;
        }
        else
        {
            glassMat = new Material(Shader.Find("Standard"));
            glassMat.SetFloat("_Mode", 3); 
            glassMat.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
            glassMat.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
            glassMat.SetInt("_ZWrite", 0);
            glassMat.EnableKeyword("_ALPHABLEND_ON");
            glassMat.color = cubeColor; 
            glassMat.SetFloat("_Glossiness", 0.95f);
            glassMat.renderQueue = 3000;
        }

        GameObject l1 = new GameObject("LightA");
        l1.transform.SetParent(_cubesRootGo.transform);
        Light lightA = l1.AddComponent<Light>();
        lightA.type = LightType.Directional;
        lightA.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
        lightA.color = new Color(1f, 0.95f, 0.9f);
        lightA.intensity = 1.0f;

        const int cubeCount = 50; 
        for (int i = 0; i < cubeCount; i++)
        {
            GameObject c = GameObject.CreatePrimitive(PrimitiveType.Cube);
            Destroy(c.GetComponent<Collider>()); 
            c.GetComponent<MeshRenderer>().material = glassMat;
            c.transform.SetParent(_cubesRootGo.transform);

            _cubeTransforms.Add(c.transform);
            _cubeBaseScale.Add(Random.Range(0.8f, 2.5f));
            _cubeSpin.Add(new Vector3(Random.Range(-50f, 50f), Random.Range(-50f, 50f), Random.Range(-50f, 50f))); 
            
            float initialZ = Mathf.Lerp(-10f, 79f, (float)i / cubeCount);
            ResetCubeXAndY(i, initialZ);
        }
    }

    private void ResetCubeXAndY(int index, float zPos)
    {
        float side = Random.value < 0.5f ? -1f : 1f;
        float x = side * Random.Range(centerClearance, centerClearance + 18f); 
        float y = Random.Range(-5f, 15f);
        _cubeTransforms[index].position = new Vector3(x, y, zPos);
    }

    private void AnimateRoadLines()
    {
        if (_bgCanvasGo == null) return;
        float h = Screen.height;
        float w = Screen.width;
        float horizonY = h * 0.56f;
        float nearY = h * 0.03f;
        float halfNearWidth = w * 0.58f;

        for (int i = 0; i < _lines.Count; i++)
        {
            _lineDepth[i] += Time.unscaledDeltaTime * 0.085f;
            if (_lineDepth[i] >= 1f) _lineDepth[i] -= 1f;

            float p = _lineDepth[i] * _lineDepth[i] * _lineDepth[i];
            float y = Mathf.Lerp(horizonY, nearY, p);
            float width = Mathf.Lerp(2.5f, halfNearWidth, p) * 2f;
            float drift = Mathf.Sin(Time.unscaledTime * 0.18f + _linePhase[i]) * Mathf.Lerp(0.6f, 6f, p);

            RectTransform rt = _lines[i].rectTransform;
            rt.anchorMin = new Vector2(0f, 0f); rt.anchorMax = new Vector2(0f, 0f);
            rt.pivot = new Vector2(0.5f, 0.5f);
            rt.anchoredPosition = new Vector2(w * 0.5f + drift, y);
            rt.sizeDelta = new Vector2(width, Mathf.Lerp(0.7f, 2.2f, p));

            Color c = _lines[i].color;
            c.a = Mathf.Lerp(0.02f, 0.24f, p);
            _lines[i].color = c;
        }
    }

    private void AnimateDecorCubes()
    {
        for (int i = 0; i < _cubeTransforms.Count; i++)
        {
            Transform t = _cubeTransforms[i];
            t.Translate(0, 0, -cubeSpeed * Time.unscaledDeltaTime, Space.World); 
            t.Rotate(_cubeSpin[i] * Time.unscaledDeltaTime, Space.Self);

            if (t.position.z < -10f) 
            {
                float zOver = t.position.z - (-10f); 
                ResetCubeXAndY(i, 79f + zOver);
            }

            float scaleProg = Mathf.Clamp01(Mathf.InverseLerp(79f, 68f, t.position.z));
            t.localScale = Vector3.one * (_cubeBaseScale[i] * scaleProg);
        }
    }

    private void AnimateTitleAndButton()
    {
        float t = Time.unscaledTime;
        if (_titleText != null)
        {
            _titleText.rectTransform.anchoredPosition = new Vector2(0f, 320f + Mathf.Sin(t * 0.7f) * 5f);
        }
    }

    private void LoadGame(int modeIndex)
    {
        Time.timeScale = 1f;
        string targetScene = modeIndex switch
        {
            1 => pathFollowingSceneName,
            2 => infiniteFallSceneName,
            3 => endlessDrivingSceneName,
            4 => posturoScanSceneName,
            _ => pathFollowingSceneName
        };

        if (string.IsNullOrWhiteSpace(targetScene))
        {
            Debug.LogError($"[MainMenuCinematicRuntime] Invalid target scene for mode {modeIndex}.");
            return;
        }

        if (!Application.CanStreamedLevelBeLoaded(targetScene))
        {
            Debug.LogWarning(
                $"[MainMenuCinematicRuntime] Scene '{targetScene}' is not in Build Profiles/Shared Scene List. " +
                $"Falling back to '{DefaultFallbackSceneName}'.");

            if (!Application.CanStreamedLevelBeLoaded(DefaultFallbackSceneName))
            {
                Debug.LogError(
                    $"[MainMenuCinematicRuntime] Fallback scene '{DefaultFallbackSceneName}' is also unavailable. " +
                    "Please add required scenes in File -> Build Profiles.");
                return;
            }

            targetScene = DefaultFallbackSceneName;
        }

        SceneManager.LoadScene(targetScene, LoadSceneMode.Single);
    }

    private static Texture2D CreateVerticalGradientTexture(Color32 bottom, Color32 top, int height)
    {
        Texture2D tex = new Texture2D(1, height, TextureFormat.RGBA32, false);
        for (int y = 0; y < height; y++) tex.SetPixel(0, y, Color.Lerp(bottom, top, y / (height - 1f)));
        tex.Apply(); return tex;
    }

    private static GameObject CreateUIObject(string name, Transform parent)
    {
        GameObject go = new GameObject(name); go.layer = 5;
        RectTransform rt = go.AddComponent<RectTransform>(); rt.SetParent(parent, false);
        return go;
    }

    private static void StretchFull(RectTransform rt)
    {
        rt.anchorMin = Vector2.zero; rt.anchorMax = Vector2.one;
        rt.offsetMin = Vector2.zero; rt.offsetMax = Vector2.zero;
        rt.anchoredPosition = Vector2.zero; rt.localScale = Vector3.one;
    }

    private void CleanupLegacyHubGameplay()
    {
        DestroyIfExists("PathBall");
        DestroyIfExists("EndlessPath");
        DestroyIfExists("FypPathBallGame");
    }

    private void NormalizeSceneRouting()
    {
        // 【已清理】删除了强制覆盖场景名字的代码，现在完全按照你在上面填写的名字来跳转！
    }

    private static void DestroyIfExists(string name) { GameObject go = GameObject.Find(name); if (go != null) Destroy(go); }
}

public class MenuButtonPulse : MonoBehaviour, IPointerEnterHandler, IPointerExitHandler
{
    private Vector3 _targetScale = Vector3.one;
    private RectTransform _rt;
    private Image _bg;
    private Text _txt;
    private Color _baseBgColor;
    private Color _baseTxtColor;
    
    private void Awake() 
    { 
        _rt = transform as RectTransform; 
        _bg = GetComponent<Image>();
        if (_bg != null) _baseBgColor = _bg.color;
    }

    public void SetupText(Text txt, Color baseTxtCol)
    {
        _txt = txt;
        _baseTxtColor = baseTxtCol;
    }
    
    private void Update() 
    { 
        if (_rt != null) _rt.localScale = Vector3.Lerp(_rt.localScale, _targetScale, Time.unscaledDeltaTime * 15f); 
    }
    
    public void OnPointerEnter(PointerEventData e) 
    { 
        _targetScale = new Vector3(1.03f, 1.03f, 1f); 
        if (_bg != null) _bg.color = new Color32(255, 255, 255, 240); 
        if (_txt != null) _txt.color = new Color32(0, 0, 0, 255); 
    }
    
    public void OnPointerExit(PointerEventData e) 
    { 
        _targetScale = Vector3.one; 
        if (_bg != null) _bg.color = _baseBgColor;
        if (_txt != null) _txt.color = _baseTxtColor;
    }
}