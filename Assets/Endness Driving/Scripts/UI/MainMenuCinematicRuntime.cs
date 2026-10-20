using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using System.Collections.Generic;

public class MainMenuCinematicRuntime : MonoBehaviour
{
    [Header("--- 科技感立方体 (Cubes) ---")]
    [Tooltip("立方体的颜色 (纯白 + 低透明度)")]
    public Color cubeColor = new Color(1f, 1f, 1f, 0.15f);
    [Tooltip("中间留出的干净通道宽度 (数值越大，立方体离中间越远)")]
    public float centerClearance = 18f;
    [Tooltip("道路中心线的水平偏移，0 为正中")]
    public float roadCenterOffset = 0f;
    [Tooltip("立方体的飞行速度 (越小越慢)")]
    public float cubeSpeed = 12f;

    private readonly Color32 _bgBottom = new Color32(20, 35, 50, 255);
    private readonly Color32 _bgTop = new Color32(180, 220, 235, 255);

    private GameObject _menuCameraGo;
    private GameObject _bgCanvasGo;
    private GameObject _cubesRootGo;

    private readonly List<Image> _lines = new List<Image>();
    private readonly List<float> _lineDepth = new List<float>();
    private readonly List<float> _linePhase = new List<float>();

    private readonly List<Transform> _cubeTransforms = new List<Transform>();
    private readonly List<float> _cubeBaseScale = new List<float>();
    private readonly List<Vector3> _cubeSpin = new List<Vector3>();

    private readonly List<RectTransform> _rulerTicks = new List<RectTransform>();
    private float _rulerOffset = 0f;

    private RectTransform _titleRect;
    private Vector2 _titleBasePosition;

    private bool _isReady = false;

    private void Start()
    {
        Time.timeScale = 1f;
        CleanupLegacyHubGameplay();
        EnsureEventSystem();
        RebuildMenuVisuals();
        _isReady = true;
    }

    private void Update()
    {
        if (!_isReady) return;

        AnimateRoadLines();
        AnimateDecorCubes();
        AnimateRulers();
        AnimateTitle();
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
        if (_cubesRootGo != null) Destroy(_cubesRootGo);

        _lines.Clear();
        _lineDepth.Clear();
        _linePhase.Clear();
        _cubeTransforms.Clear();
        _cubeBaseScale.Clear();
        _cubeSpin.Clear();
        _rulerTicks.Clear();
        _rulerOffset = 0f;
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
        bgS.enabled = false;

        BuildGradientBackground();
        BuildRoadLines();
        BuildTrue3DCubes();
        BuildSideRulers();
        CacheSceneTitle();
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
        rt.anchorMin = new Vector2(anchorX, 0f);
        rt.anchorMax = new Vector2(anchorX, 1f);
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
            if (yPos < -540f) yPos += halfCount * spacing;

            float alpha = Mathf.InverseLerp(540f, 0f, Mathf.Abs(yPos));

            _rulerTicks[i].anchoredPosition = new Vector2(0, yPos);
            _rulerTicks[i].GetComponent<Image>().color = new Color(1f, 1f, 1f, alpha * 0.8f);

            _rulerTicks[i + halfCount].anchoredPosition = new Vector2(0, yPos);
            _rulerTicks[i + halfCount].GetComponent<Image>().color = new Color(1f, 1f, 1f, alpha * 0.8f);
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
        float centerX = w * 0.5f + roadCenterOffset;

        for (int i = 0; i < _lines.Count; i++)
        {
            _lineDepth[i] += Time.unscaledDeltaTime * 0.085f;
            if (_lineDepth[i] >= 1f) _lineDepth[i] -= 1f;

            float p = _lineDepth[i] * _lineDepth[i] * _lineDepth[i];
            float y = Mathf.Lerp(horizonY, nearY, p);
            float width = Mathf.Lerp(2.5f, halfNearWidth, p) * 2f;
            float drift = Mathf.Sin(Time.unscaledTime * 0.18f + _linePhase[i]) * Mathf.Lerp(0.6f, 6f, p);

            RectTransform rt = _lines[i].rectTransform;
            rt.anchorMin = Vector2.zero;
            rt.anchorMax = Vector2.zero;
            rt.pivot = new Vector2(0.5f, 0.5f);
            rt.anchoredPosition = new Vector2(centerX + drift, y);
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
                float zOver = t.position.z + 10f;
                ResetCubeXAndY(i, 79f + zOver);
            }

            float scaleProg = Mathf.Clamp01(Mathf.InverseLerp(79f, 68f, t.position.z));
            t.localScale = Vector3.one * (_cubeBaseScale[i] * scaleProg);
        }
    }

    private void CacheSceneTitle()
    {
        var title = GameObject.Find("Title");
        if (title == null)
        {
            _titleRect = null;
            return;
        }

        _titleRect = title.transform as RectTransform;
        if (_titleRect != null)
            _titleBasePosition = _titleRect.anchoredPosition;
    }

    private void AnimateTitle()
    {
        if (_titleRect == null) return;
        _titleRect.anchoredPosition = _titleBasePosition + new Vector2(0f, Mathf.Sin(Time.unscaledTime * 0.7f) * 5f);
    }

    private static Texture2D CreateVerticalGradientTexture(Color32 bottom, Color32 top, int height)
    {
        Texture2D tex = new Texture2D(1, height, TextureFormat.RGBA32, false);
        for (int y = 0; y < height; y++) tex.SetPixel(0, y, Color.Lerp(bottom, top, y / (height - 1f)));
        tex.Apply();
        return tex;
    }

    private static GameObject CreateUIObject(string name, Transform parent)
    {
        GameObject go = new GameObject(name);
        go.layer = 5;
        RectTransform rt = go.AddComponent<RectTransform>();
        rt.SetParent(parent, false);
        return go;
    }

    private static void StretchFull(RectTransform rt)
    {
        rt.anchorMin = Vector2.zero;
        rt.anchorMax = Vector2.one;
        rt.offsetMin = Vector2.zero;
        rt.offsetMax = Vector2.zero;
        rt.anchoredPosition = Vector2.zero;
        rt.localScale = Vector3.one;
    }

    private void CleanupLegacyHubGameplay()
    {
        DestroyIfExists("PathBall");
        DestroyIfExists("EndlessPath");
        DestroyIfExists("FypPathBallGame");
    }

    private static void DestroyIfExists(string name)
    {
        GameObject go = GameObject.Find(name);
        if (go != null) Destroy(go);
    }
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

    public void SetupBaseColors(Color baseBgCol, Text txt, Color baseTxtCol)
    {
        if (_bg == null) _bg = gameObject.GetComponent<Image>();
        _baseBgColor = baseBgCol;
        if (_bg != null) _bg.color = _baseBgColor;

        _txt = txt;
        _baseTxtColor = baseTxtCol;
        if (_txt != null) _txt.color = _baseTxtColor;
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