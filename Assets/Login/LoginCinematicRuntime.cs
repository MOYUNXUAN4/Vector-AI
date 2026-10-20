using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading.Tasks;

public class LoginCinematicRuntime : MonoBehaviour
{
    [Header("--- 1. Colors & Layouts ---")]
    public Color primaryColor = new Color(0, 0.75f, 1f, 1f);       // 科技蓝
    public Color secondaryColor = new Color(0.9f, 0.95f, 1f, 0.85f); // 浅灰白
    public Color textColorDark = new Color(0.15f, 0.2f, 0.25f, 1f);  // 深色文字
    public Color cubeColor = new Color(1f, 1f, 1f, 0.15f);           // 玻璃方块
    public float cubeSpeed = 12f;

    [Header("--- 2. Routing ---")]
    [Tooltip("登录/注册成功后要跳转的场景名字 (注意：如果这里没改，请去 Inspector 面板手动改)")]
    public string mainMenuSceneName = "fyphub"; 

    // 后台视觉组件
    private readonly Color32 _bgBottom = new Color32(20, 35, 50, 255);
    private readonly Color32 _bgTop = new Color32(180, 220, 235, 255);
    private GameObject _bgCanvasGo;
    private GameObject _uiCanvasGo;
    private GameObject _cubesRootGo;

    private readonly List<Image> _lines = new List<Image>();
    private readonly List<float> _lineDepth = new List<float>();
    private readonly List<float> _linePhase = new List<float>();
    private readonly List<Transform> _cubeTransforms = new List<Transform>();
    private readonly List<float> _cubeBaseScale = new List<float>();
    private readonly List<Vector3> _cubeSpin = new List<Vector3>();

    private Text _titleText;
    private Text _subTitleText;
    private bool _isReady = false;

    // --- 【核心修改】主线程跳转信使 ---
    private bool _readyToLoadScene = false; 

    // 动态 UI 组件引用
    private RectTransform _rtNickname;
    public InputField inputNickname;
    public InputField inputAgeGroup;
    public InputField inputHeight;
    public InputField inputWeight;

    private Button _btnPrimary;
    private Text _txtPrimary;
    private Image _bgPrimary;

    private Button _btnSecondary;
    private Text _txtSecondary;
    private Image _bgSecondary;
    private RectTransform _rtButtonsContainer;
    private GameObject _popupOverlay;
    private Text _popupMessageText;

    private bool _isRegisterMode = false;

    // --- UDP 网络通信组件 ---
    private UdpClient _udpClient;
    private IPEndPoint _serverEndPoint;

    private void Start()
    {
        EnsureEventSystem();
        RebuildLoginVisuals();
        SetToLoginState();
        inputNickname.text = PlayerPrefs.GetString("CurrentPlayer", string.Empty).Trim();
        _isReady = true;
    }

    private void Update()
    {
        if (!_isReady) return;
        
        AnimateRoadLines();
        AnimateDecorCubes();
        AnimateTitle(); 

        // 【终极诊断版】主线程跳转逻辑与安全检查
        if (_readyToLoadScene)
        {
            _readyToLoadScene = false; // 重置信使
            Debug.Log($"[Unity 主线程] 开始执行跳转！当前试图加载的场景名字是: [{mainMenuSceneName}]");

            if (string.IsNullOrEmpty(mainMenuSceneName))
            {
                Debug.LogError("❌ 跳转失败：场景名字是空的！请在 Unity 编辑器里选中脚本，在 Inspector 面板手动填入 fyphub！");
                return;
            }

            if (mainMenuSceneName == SceneManager.GetActiveScene().name)
            {
                Debug.LogError("❌ 跳转失败：你正在试图跳入当前所在的场景！画面原地刷新了。请在 Inspector 面板检查名字！");
                return;
            }

            AsyncOperation asyncLoad = SceneManager.LoadSceneAsync(mainMenuSceneName);
            if (asyncLoad == null)
            {
                Debug.LogError($"❌ Unity 引擎拒绝加载场景 [{mainMenuSceneName}]！请检查：1.名字拼写是否完全一致 2.是否拖入了 Build Settings！");
            }
            else
            {
                asyncLoad.completed += (op) => { 
                    Debug.Log("✅ 场景异步加载已彻底完成，画面应该已经切换！"); 
                };
            }
        }
    }

    private void EnsureEventSystem()
    {
        if (EventSystem.current != null) return;
        GameObject es = new GameObject("EventSystem");
        es.AddComponent<EventSystem>();
        es.AddComponent<StandaloneInputModule>();
    }

    // ========================================================
    // 核心 UI 构建
    // ========================================================
    public void RebuildLoginVisuals()
    {
        GameObject camGo = new GameObject("LoginCamera");
        Camera cam = camGo.AddComponent<Camera>();
        cam.backgroundColor = _bgBottom;
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.depth = 50; 

        _bgCanvasGo = new GameObject("LoginBGCanvas");
        Canvas bgC = _bgCanvasGo.AddComponent<Canvas>();
        bgC.renderMode = RenderMode.ScreenSpaceCamera;
        bgC.worldCamera = cam;
        bgC.planeDistance = 90f; 
        
        BuildGradientBackground();
        BuildRoadLines();
        BuildTrue3DCubes(); 

        _uiCanvasGo = new GameObject("LoginUICanvas");
        Canvas uiC = _uiCanvasGo.AddComponent<Canvas>();
        uiC.renderMode = RenderMode.ScreenSpaceOverlay; 
        CanvasScaler uiS = _uiCanvasGo.AddComponent<CanvasScaler>();
        uiS.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        uiS.referenceResolution = new Vector2(1920, 1080);
        _uiCanvasGo.AddComponent<GraphicRaycaster>();

        BuildMinimalistInterface();
    }

    private void BuildMinimalistInterface()
    {
        _titleText = CreateUIObject("Title", _uiCanvasGo.transform).AddComponent<Text>();
        _titleText.text = "VECTOR AI"; 
        _titleText.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        _titleText.fontSize = 90; 
        _titleText.fontStyle = FontStyle.Bold;
        _titleText.alignment = TextAnchor.MiddleCenter;
        _titleText.color = Color.white;
        RectTransform rtTitle = _titleText.rectTransform;
        rtTitle.anchorMin = new Vector2(0.5f, 0.5f); rtTitle.anchorMax = new Vector2(0.5f, 0.5f);
        rtTitle.anchoredPosition = new Vector2(0, 320); 
        rtTitle.sizeDelta = new Vector2(1200, 120);

        _subTitleText = CreateUIObject("SubTitle", _uiCanvasGo.transform).AddComponent<Text>();
        _subTitleText.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        _subTitleText.fontSize = 22;
        _subTitleText.fontStyle = FontStyle.Bold;
        _subTitleText.alignment = TextAnchor.MiddleCenter;
        _subTitleText.color = new Color32(200, 230, 255, 255);
        RectTransform rtSub = _subTitleText.rectTransform;
        rtSub.anchorMin = new Vector2(0.5f, 0.5f); rtSub.anchorMax = new Vector2(0.5f, 0.5f);
        rtSub.anchoredPosition = new Vector2(0, 240); 
        rtSub.sizeDelta = new Vector2(1000, 50);

        inputNickname = CreateInputField("Enter NICKNAME or Patient ID...", out _rtNickname);
        inputAgeGroup = CreateInputField("Age Group (e.g., 65+)", out _);
        inputHeight   = CreateInputField("Height (cm)", out _);
        inputWeight   = CreateInputField("Weight (kg)", out _);

        GameObject btnContainer = CreateUIObject("Button_Container", _uiCanvasGo.transform);
        _rtButtonsContainer = btnContainer.GetComponent<RectTransform>();
        _rtButtonsContainer.anchorMin = new Vector2(0.5f, 0.5f); _rtButtonsContainer.anchorMax = new Vector2(0.5f, 0.5f);
        _rtButtonsContainer.sizeDelta = new Vector2(500, 80);

        CreateButtons(btnContainer.transform);
        BuildPopup();
    }

    private InputField CreateInputField(string placeholderEnglish, out RectTransform bgRt)
    {
        GameObject bgGo = CreateUIObject("Input_" + placeholderEnglish, _uiCanvasGo.transform);
        Image bgImg = bgGo.AddComponent<Image>();
        bgImg.color = new Color32(255, 255, 255, 240); 
        bgRt = bgGo.GetComponent<RectTransform>();
        bgRt.anchorMin = new Vector2(0.5f, 0.5f); bgRt.anchorMax = new Vector2(0.5f, 0.5f);
        bgRt.sizeDelta = new Vector2(450, 65); 

        GameObject phGo = CreateUIObject("Placeholder", bgGo.transform);
        Text phTxt = phGo.AddComponent<Text>();
        phTxt.text = placeholderEnglish; 
        phTxt.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        phTxt.fontSize = 20;
        phTxt.color = new Color32(120, 120, 120, 200); 
        phTxt.alignment = TextAnchor.MiddleLeft;
        StretchWithMargin(phTxt.rectTransform, 20f);

        GameObject txtGo = CreateUIObject("Text", bgGo.transform);
        Text valTxt = txtGo.AddComponent<Text>();
        valTxt.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        valTxt.fontSize = 22;
        valTxt.color = new Color32(10, 10, 10, 255); 
        valTxt.alignment = TextAnchor.MiddleLeft;
        StretchWithMargin(valTxt.rectTransform, 20f);

        InputField input = bgGo.AddComponent<InputField>();
        input.textComponent = valTxt;
        input.placeholder = phTxt;
        return input;
    }

    private void BuildPopup()
    {
        _popupOverlay = CreateUIObject("PopupOverlay", _uiCanvasGo.transform);
        _popupOverlay.SetActive(false);

        Image overlayImage = _popupOverlay.AddComponent<Image>();
        overlayImage.color = new Color(0f, 0f, 0f, 0.55f);
        StretchFull(_popupOverlay.GetComponent<RectTransform>());

        GameObject panel = CreateUIObject("PopupPanel", _popupOverlay.transform);
        Image panelImage = panel.AddComponent<Image>();
        panelImage.color = new Color32(245, 248, 252, 255);
        RectTransform panelRt = panel.GetComponent<RectTransform>();
        panelRt.anchorMin = new Vector2(0.5f, 0.5f);
        panelRt.anchorMax = new Vector2(0.5f, 0.5f);
        panelRt.pivot = new Vector2(0.5f, 0.5f);
        panelRt.sizeDelta = new Vector2(520f, 240f);

        _popupMessageText = CreateUIObject("PopupMessage", panel.transform).AddComponent<Text>();
        _popupMessageText.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        _popupMessageText.fontSize = 24;
        _popupMessageText.alignment = TextAnchor.MiddleCenter;
        _popupMessageText.color = textColorDark;
        _popupMessageText.horizontalOverflow = HorizontalWrapMode.Wrap;
        _popupMessageText.verticalOverflow = VerticalWrapMode.Overflow;
        RectTransform messageRt = _popupMessageText.rectTransform;
        messageRt.anchorMin = new Vector2(0.5f, 0.5f);
        messageRt.anchorMax = new Vector2(0.5f, 0.5f);
        messageRt.pivot = new Vector2(0.5f, 0.5f);
        messageRt.anchoredPosition = new Vector2(0f, 30f);
        messageRt.sizeDelta = new Vector2(420f, 100f);

        GameObject okButton = CreateUIObject("PopupOkButton", panel.transform);
        Image okButtonImage = okButton.AddComponent<Image>();
        okButtonImage.color = primaryColor;
        Button ok = okButton.AddComponent<Button>();
        ok.targetGraphic = okButtonImage;
        ok.onClick.AddListener(HidePopup);
        RectTransform okRt = okButton.GetComponent<RectTransform>();
        okRt.anchorMin = new Vector2(0.5f, 0.5f);
        okRt.anchorMax = new Vector2(0.5f, 0.5f);
        okRt.pivot = new Vector2(0.5f, 0.5f);
        okRt.anchoredPosition = new Vector2(0f, -65f);
        okRt.sizeDelta = new Vector2(160f, 56f);

        Text okText = CreateUIObject("Label", okButton.transform).AddComponent<Text>();
        okText.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        okText.fontSize = 22;
        okText.fontStyle = FontStyle.Bold;
        okText.alignment = TextAnchor.MiddleCenter;
        okText.color = Color.white;
        okText.text = "OK";
        StretchWithMargin(okText.rectTransform, 0f);
    }

    private void CreateButtons(Transform parent)
    {
        GameObject btnPrimaryGo = CreateUIObject("Btn_Primary", parent);
        _bgPrimary = btnPrimaryGo.AddComponent<Image>();
        _btnPrimary = btnPrimaryGo.AddComponent<Button>();
        _btnPrimary.targetGraphic = _bgPrimary;
        RectTransform rtP = btnPrimaryGo.GetComponent<RectTransform>();
        rtP.anchorMin = new Vector2(0f, 0.5f); rtP.anchorMax = new Vector2(0f, 0.5f);
        rtP.anchoredPosition = new Vector2(110f, 0); 
        rtP.sizeDelta = new Vector2(200f, 65f); 
        _txtPrimary = CreateUIObject("Label", btnPrimaryGo.transform).AddComponent<Text>();
        _txtPrimary.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        _txtPrimary.fontSize = 20; _txtPrimary.fontStyle = FontStyle.Bold; _txtPrimary.alignment = TextAnchor.MiddleCenter;
        StretchWithMargin(_txtPrimary.rectTransform, 0f);
        btnPrimaryGo.AddComponent<LoginButtonPulse>().SetupText(_txtPrimary, Color.white);

        GameObject btnSecGo = CreateUIObject("Btn_Secondary", parent);
        _bgSecondary = btnSecGo.AddComponent<Image>();
        _btnSecondary = btnSecGo.AddComponent<Button>();
        _btnSecondary.targetGraphic = _bgSecondary;
        RectTransform rtS = btnSecGo.GetComponent<RectTransform>();
        rtS.anchorMin = new Vector2(1f, 0.5f); rtS.anchorMax = new Vector2(1f, 0.5f);
        rtS.anchoredPosition = new Vector2(-110f, 0); 
        rtS.sizeDelta = new Vector2(200f, 65f); 
        _txtSecondary = CreateUIObject("Label", btnSecGo.transform).AddComponent<Text>();
        _txtSecondary.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        _txtSecondary.fontSize = 20; _txtSecondary.fontStyle = FontStyle.Bold; _txtSecondary.alignment = TextAnchor.MiddleCenter;
        StretchWithMargin(_txtSecondary.rectTransform, 0f);
        btnSecGo.AddComponent<LoginButtonPulse>().SetupText(_txtSecondary, textColorDark);
    }

    // ========================================================
    // 状态机切换逻辑 
    // ========================================================
    private void SetToLoginState()
    {
        _isRegisterMode = false;
        _subTitleText.text = "USER LOGIN / ACCESS IDENTIFICATION";

        inputAgeGroup.gameObject.SetActive(false);
        inputHeight.gameObject.SetActive(false);
        inputWeight.gameObject.SetActive(false);

        _rtNickname.anchoredPosition = new Vector2(0, 50f);
        _rtButtonsContainer.anchoredPosition = new Vector2(0, -60f);

        _txtPrimary.text = "CONFIRM";
        _bgPrimary.color = primaryColor;
        _btnPrimary.onClick.RemoveAllListeners();
        _btnPrimary.onClick.AddListener(AttemptLogin);

        _txtSecondary.text = "REGISTER";
        _bgSecondary.color = secondaryColor;
        _btnSecondary.onClick.RemoveAllListeners();
        _btnSecondary.onClick.AddListener(SetToRegisterState); 
    }

    private void SetToRegisterState()
    {
        _isRegisterMode = true;
        _subTitleText.text = "NEW PATIENT REGISTRATION";

        inputAgeGroup.gameObject.SetActive(true);
        inputHeight.gameObject.SetActive(true);
        inputWeight.gameObject.SetActive(true);

        _rtNickname.anchoredPosition = new Vector2(0, 120f);
        inputAgeGroup.GetComponent<RectTransform>().anchoredPosition = new Vector2(0, 40f);
        inputHeight.GetComponent<RectTransform>().anchoredPosition = new Vector2(0, -40f);
        inputWeight.GetComponent<RectTransform>().anchoredPosition = new Vector2(0, -120f);
        _rtButtonsContainer.anchoredPosition = new Vector2(0, -220f);

        _txtPrimary.text = "SUBMIT";
        _bgPrimary.color = primaryColor;
        _btnPrimary.onClick.RemoveAllListeners();
        _btnPrimary.onClick.AddListener(AttemptRegister);

        _txtSecondary.text = "CANCEL";
        _bgSecondary.color = secondaryColor;
        _btnSecondary.onClick.RemoveAllListeners();
        _btnSecondary.onClick.AddListener(SetToLoginState); 
    }

    // ========================================================
    // 核心 UDP 通信逻辑 (加入 PlayerPrefs 跨场景记忆)
    // ========================================================
    private void AttemptLogin()
    {
        string nick = inputNickname.text;
        if (string.IsNullOrWhiteSpace(nick))
        {
            ShowPopup("Please enter your name or patient ID.");
            return;
        }
        
        nick = nick.Trim();
        inputNickname.text = nick;
        
        // 【新增】：记住玩家的名字，传给后面的游戏场景！
        PlayerPrefs.SetString("CurrentPlayer", nick); 
        PlayerPrefs.Save();

        string jsonMsg = $"{{\"type\": \"LOGIN\", \"nickname\": \"{nick}\"}}";
        SendUdpMessageAsync(jsonMsg);
    }

    private void AttemptRegister()
    {
        string nick = inputNickname.text;
        if (string.IsNullOrWhiteSpace(nick))
        {
            ShowPopup("Please enter your name or patient ID.");
            return;
        }
        
        nick = nick.Trim();
        inputNickname.text = nick;
        
        // 【新增】：记住玩家的名字，传给后面的游戏场景！
        PlayerPrefs.SetString("CurrentPlayer", nick);
        PlayerPrefs.Save();

        string age = inputAgeGroup.text;
        string height = inputHeight.text;
        string weight = inputWeight.text;

        string jsonMsg = $"{{\"type\": \"REGISTER\", \"nickname\": \"{nick}\", \"age_group\": \"{age}\", \"height\": \"{height}\", \"weight\": \"{weight}\"}}";
        SendUdpMessageAsync(jsonMsg);
    }

    private async void SendUdpMessageAsync(string jsonMessage)
    {
        try
        {
            if (_udpClient == null)
            {
                _udpClient = new UdpClient();
                _serverEndPoint = new IPEndPoint(IPAddress.Parse("127.0.0.1"), 6000); 
            }

            byte[] sendBytes = Encoding.UTF8.GetBytes(jsonMessage);
            await _udpClient.SendAsync(sendBytes, sendBytes.Length, _serverEndPoint);
            Debug.Log($"[UDP Sending]: {jsonMessage}");

            var receiveTask = _udpClient.ReceiveAsync();
            if (await Task.WhenAny(receiveTask, Task.Delay(2000)) == receiveTask)
            {
                UdpReceiveResult result = receiveTask.Result;
                string responseJson = Encoding.UTF8.GetString(result.Buffer);
                Debug.Log($"[UDP Received]: {responseJson}");

                if (responseJson.Contains("\"status\": \"success\""))
                {
                    Debug.Log("✅ 后端验证成功！通知主线程准备跳转...");
                    await Task.Delay(500); 
                    _readyToLoadScene = true; 
                }
                else
                {
                    Debug.LogWarning("Login rejected by backend: " + responseJson);
                    ShowPopup(ParseBackendErrorMessage(responseJson));
                }
            }
            else
            {
                Debug.LogWarning("UDP Timeout: Backend server is not responding.");
                ShowPopup("Connection timed out. Please try again.");
            }
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"UDP Communication Error: {e.Message}");
            ShowPopup("Unable to contact the server. Please try again.");
        }
    }

    private void HidePopup()
    {
        if (_popupOverlay != null) _popupOverlay.SetActive(false);

        if (_isRegisterMode)
        {
            if (inputAgeGroup != null) inputAgeGroup.text = string.Empty;
            if (inputHeight != null) inputHeight.text = string.Empty;
            if (inputWeight != null) inputWeight.text = string.Empty;
        }

        if (inputNickname != null)
        {
            inputNickname.ActivateInputField();
            inputNickname.Select();
        }
    }

    private void ShowPopup(string message)
    {
        if (_popupMessageText != null) _popupMessageText.text = message;
        if (_popupOverlay != null) _popupOverlay.SetActive(true);
    }

    private string ParseBackendErrorMessage(string responseJson)
    {
        string lower = responseJson.ToLowerInvariant();

        if (lower.Contains("用户不存在") || lower.Contains("\u7528\u6237\u4e0d\u5b58\u5728") || lower.Contains("not exist") || lower.Contains("not found") || lower.Contains("no such user"))
            return "Name does not exist.";

        if (lower.Contains("已注册") || lower.Contains("\u5df2\u6ce8\u518c") || lower.Contains("exists") || lower.Contains("already registered") || lower.Contains("duplicate"))
            return "This name is already registered.";

        if (lower.Contains("invalid") || lower.Contains("error"))
            return "Invalid request. Please check your input and try again.";

        return "Request failed. Please try again.";
    }

    private void OnDestroy()
    {
        if (_udpClient != null)
        {
            _udpClient.Close(); 
        }
    }

    // ========================================================
    // 视觉特效动画 (URP 兼容)
    // ========================================================
    private void BuildGradientBackground()
    {
        GameObject bg = CreateUIObject("Background", _bgCanvasGo.transform);
        RawImage raw = bg.AddComponent<RawImage>();
        Texture2D tex = new Texture2D(1, 256, TextureFormat.RGBA32, false);
        for (int y = 0; y < 256; y++) tex.SetPixel(0, y, Color.Lerp(_bgBottom, _bgTop, y / 255f));
        tex.Apply();
        raw.texture = tex;
        raw.raycastTarget = false;
        StretchFull(bg.GetComponent<RectTransform>());
    }

    private void BuildRoadLines()
    {
        GameObject lr = CreateUIObject("RoadLines", _bgCanvasGo.transform);
        StretchFull(lr.GetComponent<RectTransform>());
        for (int i = 0; i < 32; i++)
        {
            Image line = CreateUIObject("Line_" + i, lr.transform).AddComponent<Image>();
            line.raycastTarget = false;
            _lines.Add(line);
            _lineDepth.Add((i + 1) / 32f);
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

        GameObject lightGo = new GameObject("CubeLight");
        lightGo.transform.SetParent(_cubesRootGo.transform);
        Light l = lightGo.AddComponent<Light>();
        l.type = LightType.Directional;
        l.color = Color.white;
        l.intensity = 1.0f;
        lightGo.transform.rotation = Quaternion.Euler(50, -30, 0);

        for (int i = 0; i < 50; i++)
        {
            GameObject c = GameObject.CreatePrimitive(PrimitiveType.Cube);
            Destroy(c.GetComponent<Collider>()); 
            c.GetComponent<MeshRenderer>().material = glassMat;
            c.transform.SetParent(_cubesRootGo.transform);
            _cubeTransforms.Add(c.transform);
            _cubeBaseScale.Add(Random.Range(0.8f, 2.5f));
            _cubeSpin.Add(new Vector3(Random.Range(-50f, 50f), Random.Range(-50f, 50f), Random.Range(-50f, 50f))); 
            
            float side = Random.value < 0.5f ? -1f : 1f;
            float x = side * Random.Range(18f, 36f); 
            float y = Random.Range(-5f, 15f);
            float z = Mathf.Lerp(-10f, 79f, (float)i / 50f);
            c.transform.position = new Vector3(x, y, z);
        }
    }

    private void AnimateRoadLines()
    {
        float h = Screen.height, w = Screen.width;
        float horizonY = h * 0.56f, nearY = h * 0.03f, halfNearWidth = w * 0.58f;

        for (int i = 0; i < _lines.Count; i++)
        {
            _lineDepth[i] += Time.unscaledDeltaTime * 0.085f;
            if (_lineDepth[i] >= 1f) _lineDepth[i] -= 1f;
            float p = _lineDepth[i] * _lineDepth[i] * _lineDepth[i];
            float y = Mathf.Lerp(horizonY, nearY, p);
            float width = Mathf.Lerp(2.5f, halfNearWidth, p) * 2f;
            float drift = Mathf.Sin(Time.unscaledTime * 0.18f + _linePhase[i]) * Mathf.Lerp(0.6f, 6f, p);

            RectTransform rt = _lines[i].rectTransform;
            rt.anchorMin = Vector2.zero; rt.anchorMax = Vector2.zero;
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
                float side = t.position.x < 0 ? -1f : 1f;
                t.position = new Vector3(side * Random.Range(18f, 36f), Random.Range(-5f, 15f), 79f + (t.position.z - (-10f)));
            }
            float scaleProg = Mathf.Clamp01(Mathf.InverseLerp(79f, 68f, t.position.z));
            t.localScale = Vector3.one * (_cubeBaseScale[i] * scaleProg);
        }
    }

    private void AnimateTitle()
    {
        if (_titleText != null) _titleText.rectTransform.anchoredPosition = new Vector2(0f, 320f + Mathf.Sin(Time.unscaledTime * 0.7f) * 5f);
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
    }

    private static void StretchWithMargin(RectTransform rt, float margin)
    {
        rt.anchorMin = Vector2.zero; rt.anchorMax = Vector2.one;
        rt.offsetMin = new Vector2(margin, margin); rt.offsetMax = new Vector2(-margin, -margin);
    }
}

public class LoginButtonPulse : MonoBehaviour, IPointerEnterHandler, IPointerExitHandler
{
    private Vector3 _targetScale = Vector3.one;
    private RectTransform _rt;
    private Image _bg;
    private Text _txt;
    private Color _baseTxtColor;
    
    private void Awake() { _rt = transform as RectTransform; _bg = GetComponent<Image>(); }
    
    public void SetupText(Text txt, Color baseTxtCol) 
    { 
        _txt = txt; 
        _baseTxtColor = baseTxtCol; 
        if (_txt != null) _txt.color = _baseTxtColor;
    }
    
    private void Update() { if (_rt != null) _rt.localScale = Vector3.Lerp(_rt.localScale, _targetScale, Time.unscaledDeltaTime * 15f); }
    
    public void OnPointerEnter(PointerEventData e) 
    { 
        _targetScale = new Vector3(1.05f, 1.05f, 1f); 
        if (_txt != null) _txt.color = new Color32(0, 0, 0, 255); 
    }
    
    public void OnPointerExit(PointerEventData e) 
    { 
        _targetScale = Vector3.one; 
        if (_txt != null) _txt.color = _baseTxtColor;
    }
}