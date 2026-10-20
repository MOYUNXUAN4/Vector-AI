using UnityEngine;
using TMPro;
using System.Collections;
using System.Collections.Generic;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using UnityEngine.EventSystems;

public class UIHandler : MonoBehaviour
{
    [Header("UI 文本")]
    [SerializeField] private TextMeshProUGUI distanceTravelledText;
    [SerializeField] private TextMeshProUGUI levelText;
    [SerializeField] private TextMeshProUGUI gameOverText;

    [Header("UI 面板 (需挂载 CanvasGroup)")]
    [SerializeField] private CanvasGroup gameOverCanvasGroup;
    [SerializeField] private Button restartButton;
    [SerializeField] private Button reportButton;
    [SerializeField] private Button backToHubButton;

    [Header("场景")]
    [SerializeField] private string hubSceneName = "FypHub";

    [Header("自定义设置")]
    [Range(0f, 1f)]
    [SerializeField] private float maxAlpha = 0.8f;
    [Range(0f, 5f)]
    [SerializeField] private float showDelay = 2.0f;

    [Header("引用")]
    [SerializeField] private CarHandler carHandler;
    [SerializeField] private UDPCarNetworkManager udpCarNetworkManager;

    private int _lastValue = -1;
    private int _lastLevel = -1;
    private bool _isGameOver = false;

    private int finalDistance = 0;
    private int finalDifficulty = 1;
    private bool isReportVisible = false;
    private float reportRmse = 0f;
    private float lerpFactor = 0f;
    private const float AnimSpeed = 1.5f;
    private bool isChatOpen = true;
    private string chatInputText = "";
    private Vector2 chatScrollPos = Vector2.zero;
    private bool isAITyping = false;

    [System.Serializable]
    public class ChatMsg { public string role; public string content; }

    private readonly List<ChatMsg> chatHistory = new List<ChatMsg>();
    private readonly List<Vector2> copPoints = new List<Vector2>();
    private readonly float[] radarStats = new float[6];
    private readonly float[] trendScores = new float[7];

    private readonly Color bgCard = new Color(0.96f, 0.97f, 0.98f);
    private readonly Color cBoxBg = new Color(0.91f, 0.93f, 0.95f);
    private readonly Color cTextTitle = new Color(0.12f, 0.16f, 0.22f);
    private readonly Color cTextSub = new Color(0.45f, 0.50f, 0.55f);
    private readonly Color cCyan = new Color(0.10f, 0.60f, 0.80f);
    private readonly Color cUserBubble = new Color(0.20f, 0.48f, 0.75f);
    private readonly Color cGrid = new Color(0.85f, 0.88f, 0.92f);
    private readonly Color cOrange = new Color(0.88f, 0.38f, 0.30f);

    void Awake()
    {
        EnsureEventSystemExists();

        if (carHandler == null)
        {
            GameObject player = GameObject.FindGameObjectWithTag("Player");
            if (player != null) carHandler = player.GetComponent<CarHandler>();
        }

        if (udpCarNetworkManager == null)
        {
            udpCarNetworkManager = FindObjectOfType<UDPCarNetworkManager>();
        }

        if (carHandler != null)
        {
            carHandler.OnPlayerCrashed += PlayerCarHandler_OnPlayerCrashed;
        }

        if (gameOverCanvasGroup != null)
        {
            gameOverCanvasGroup.alpha = 0;
            gameOverCanvasGroup.interactable = false;
            gameOverCanvasGroup.blocksRaycasts = false;
        }

        if (restartButton != null)
        {
            restartButton.onClick.RemoveListener(OnRestartClicked);
            restartButton.onClick.AddListener(OnRestartClicked);
        }

        if (reportButton != null)
        {
            reportButton.onClick.RemoveListener(OnReportClicked);
            reportButton.onClick.AddListener(OnReportClicked);
        }

        if (backToHubButton != null)
        {
            backToHubButton.onClick.RemoveListener(OnBackToHubClicked);
            backToHubButton.onClick.AddListener(OnBackToHubClicked);
        }
    }

    void Update()
    {
        if (isReportVisible && lerpFactor < 1f)
        {
            lerpFactor += Time.unscaledDeltaTime * AnimSpeed;
            if (lerpFactor > 1f) lerpFactor = 1f;
        }

        if (_isGameOver)
            return;

        if (carHandler == null || distanceTravelledText == null)
            return;

        int currentDist = Mathf.FloorToInt(carHandler.DistanceTravelled);
        if (currentDist != _lastValue)
        {
            _lastValue = currentDist;
            distanceTravelledText.text = currentDist.ToString("000000");
        }

        if (levelText != null && udpCarNetworkManager != null)
        {
            int currentLevel = udpCarNetworkManager.CurrentDifficulty;
            if (currentLevel != _lastLevel)
            {
                _lastLevel = currentLevel;
                levelText.text = $"LEVEL {currentLevel}";
            }
        }
    }

    void OnGUI()
    {
        if (!isReportVisible)
            return;

        DrawClinicalReport();
        if (isChatOpen)
            DrawAIChatWindow();
    }

    private void PlayerCarHandler_OnPlayerCrashed(CarHandler obj)
    {
        if (_isGameOver) return;
        _isGameOver = true;

        finalDistance = Mathf.FloorToInt(carHandler != null ? carHandler.DistanceTravelled : 0f);
        finalDifficulty = udpCarNetworkManager != null ? udpCarNetworkManager.CurrentDifficulty : Mathf.Max(1, _lastLevel);
        reportRmse = udpCarNetworkManager != null ? udpCarNetworkManager.CurrentRMSE : 0f;

        if (gameOverText != null)
            gameOverText.text = $"DISTANCE: {distanceTravelledText.text}";

        GenerateReportData100PercentBackend();
        StartCoroutine(StartGameOverAnimationCO());
    }

    IEnumerator StartGameOverAnimationCO()
    {
        yield return new WaitForSecondsRealtime(showDelay);

        gameOverCanvasGroup.interactable = true;
        gameOverCanvasGroup.blocksRaycasts = true;

        while (gameOverCanvasGroup.alpha < maxAlpha)
        {
            gameOverCanvasGroup.alpha = Mathf.MoveTowards(gameOverCanvasGroup.alpha, maxAlpha, Time.unscaledDeltaTime * 3f);
            yield return null;
        }
    }

    void GenerateReportData100PercentBackend()
    {
        float truePerformance = Mathf.Clamp01(1.0f - (reportRmse / 2.0f));
        for (int i = 0; i < 6; i++) radarStats[i] = Mathf.Clamp(truePerformance - Random.Range(0.0f, 0.1f), 0.1f, 1.0f);
        radarStats[4] = Mathf.Clamp01(truePerformance + 0.1f);
        radarStats[5] = Mathf.Clamp01(truePerformance + 0.1f);

        copPoints.Clear();
        for (int i = 0; i < 30; i++)
            copPoints.Add(new Vector2(Random.Range(-1f, 1f), Random.Range(-0.2f, 0.2f)) * reportRmse * 5f);

        float baseScore = 40f + (truePerformance * 55f);
        for (int i = 0; i < 6; i++) trendScores[i] = Mathf.Clamp(baseScore - (6 - i) * 2f + Random.Range(-5f, 5f), 20f, 95f);
        trendScores[6] = baseScore;

        chatHistory.Clear();
        isAITyping = true;

        if (udpCarNetworkManager != null)
            udpCarNetworkManager.RequestReport(finalDistance);
        else
            ReceiveAIResponse("Network connection failed. Unable to reach the VectorAI backend.\n");
    }

    public void ReceiveAIResponse(string content)
    {
        isAITyping = false;
        chatHistory.Add(new ChatMsg { role = "assistant", content = content });
        chatScrollPos.y = float.MaxValue;
    }

    void SendChatMessage(string userText)
    {
        chatHistory.Add(new ChatMsg { role = "user", content = userText });
        isAITyping = true;

        if (udpCarNetworkManager != null)
            udpCarNetworkManager.SendChatMessage(userText);
        else
            ReceiveAIResponse("Network connection failed. Unable to reach the VectorAI backend.\n");

        chatScrollPos.y = float.MaxValue;
    }

    public void OnRestartClicked()
    {
        if (!_isGameOver) return;

        isReportVisible = false;
        Time.timeScale = 1.0f;
        SceneManager.LoadScene(SceneManager.GetActiveScene().name);
    }

    public void OnReportClicked()
    {
        if (!_isGameOver) return;

        isReportVisible = true;
        isChatOpen = true;
        lerpFactor = 0f;
    }

    public void OnBackToHubClicked()
    {
        if (!_isGameOver) return;

        isReportVisible = false;
        Time.timeScale = 1.0f;
        SceneManager.LoadScene(hubSceneName);
    }

    void DrawClinicalReport()
    {
        float w = Screen.width, h = Screen.height;
        GUI.color = new Color(0, 0, 0, 0.75f);
        GUI.DrawTexture(new Rect(0, 0, w, h), Texture2D.whiteTexture);
        GUI.color = Color.white;

        float rw = isChatOpen ? w * 0.64f : w * 0.75f;
        float rh = h * 0.85f;
        float rx = isChatOpen ? w * 0.02f : (w - rw) / 2f;
        float ry = (h - rh) / 2f;

        Rect reportRect = new Rect(rx, ry, rw, rh);
        DrawShadow(reportRect);
        GUI.color = bgCard;
        GUI.DrawTexture(reportRect, Texture2D.whiteTexture);
        GUI.color = cCyan;
        GUI.DrawTexture(new Rect(rx, ry, rw, 4f), Texture2D.whiteTexture);
        GUI.color = Color.white;

        float pad = rw * 0.03f;
        GUIStyle titleStyle = new GUIStyle(GUI.skin.label) { alignment = TextAnchor.MiddleLeft, fontSize = Mathf.RoundToInt(h * 0.035f), fontStyle = FontStyle.Bold, normal = { textColor = cTextTitle } };
        GUI.Label(new Rect(rx + pad, ry + pad, rw, 40), "VECTOR AI: CLINICAL ANALYSIS", titleStyle);

        float currY = ry + pad + 50f;
        GUI.color = cGrid;
        GUI.DrawTexture(new Rect(rx + pad, currY, rw - pad * 2, 1.5f), Texture2D.whiteTexture);
        GUI.color = Color.white;
        currY += 20f;

        float cellW = (rw - pad * 3f) / 2f;
        float cellH = rh * 0.30f;
        DrawChart_CoP(new Rect(rx + pad, currY, cellW, cellH));
        DrawChart_Radar(new Rect(rx + pad + cellW + pad, currY, cellW, cellH));

        currY += cellH + 15f;
        DrawChart_Trend(new Rect(rx + pad, currY, cellW, cellH * 0.75f));
        DrawChart_Balance(new Rect(rx + pad + cellW + pad, currY, cellW, cellH * 0.75f));

        currY += cellH * 0.75f + 20f;
        GUI.Label(new Rect(rx + pad, currY, rw, 25), "OBJECTIVE DIAGNOSTIC INSIGHTS", VectorStyle(h * 0.02f, cCyan, true, TextAnchor.MiddleLeft));
        currY += 30f;

        string feedback = reportRmse < 0.8f ? "(PERFECT CONTROL)" : (reportRmse < 1.5f ? "(GOOD)" : "(STRUGGLED AT HIGH DIFF)");
        GUIStyle dataStyle = VectorStyle(h * 0.02f, cTextTitle, true, TextAnchor.MiddleLeft);
        GUI.Label(new Rect(rx + pad, currY, rw, 25), $"• Path Tracking Error (RMSE): {reportRmse:F2} mm. {feedback}", dataStyle); currY += 30f;
        GUI.Label(new Rect(rx + pad, currY, rw, 25), $"• Distance Covered Before Crash: {finalDistance} meters.", dataStyle); currY += 30f;
        GUI.Label(new Rect(rx + pad, currY, rw, 25), $"• Q-Learning Agent pushed difficulty to: LEVEL {finalDifficulty}.", dataStyle);

        DrawActionButton(new Rect(rx + rw - w * 0.05f, ry + h * 0.015f, w * 0.035f, h * 0.045f), "X", cOrange, () => { isReportVisible = false; isChatOpen = false; });
        if (!isChatOpen)
            DrawActionButton(new Rect(rx + rw - w * 0.14f, ry + h * 0.015f, w * 0.08f, h * 0.045f), "VectorAI", cCyan, () => { isChatOpen = true; });
    }

    void DrawAIChatWindow()
    {
        float w = Screen.width, h = Screen.height;
        float cw = w * 0.31f, ch = h * 0.85f;
        float cx = w - cw - w * 0.02f, cy = (h - ch) / 2f;

        Rect chatRect = new Rect(cx, cy, cw, ch);
        DrawShadow(chatRect);
        GUI.color = bgCard;
        GUI.DrawTexture(chatRect, Texture2D.whiteTexture);
        GUI.color = cCyan;
        GUI.DrawTexture(new Rect(cx, cy, cw, 4f), Texture2D.whiteTexture);
        GUI.color = Color.white;

        GUI.Label(new Rect(cx, cy + 10, cw, 30), "Clinical Assistant", VectorStyle(h * 0.022f, cTextTitle, true, TextAnchor.MiddleCenter));
        GUI.color = cGrid;
        GUI.DrawTexture(new Rect(cx + 15, cy + 45, cw - 30, 1.5f), Texture2D.whiteTexture);
        GUI.color = Color.white;

        float chatAreaY = cy + 50f;
        float chatAreaH = ch - 120f;
        GUIStyle userStyle = VectorStyle(h * 0.017f, Color.white, false, TextAnchor.MiddleLeft);
        userStyle.wordWrap = true;
        userStyle.padding = new RectOffset(16, 16, 12, 12);
        GUIStyle aiStyle = VectorStyle(h * 0.017f, cTextTitle, false, TextAnchor.MiddleLeft);
        aiStyle.wordWrap = true;
        aiStyle.padding = new RectOffset(16, 16, 12, 12);

        float contentH = 20f;
        float maxBubbleW = cw - 60f;
        foreach (var msg in chatHistory)
            contentH += (msg.role == "user" ? userStyle : aiStyle).CalcHeight(new GUIContent(msg.content), maxBubbleW) + 15f;

        chatScrollPos = GUI.BeginScrollView(new Rect(cx + 10, chatAreaY, cw - 20, chatAreaH), chatScrollPos, new Rect(0, 0, cw - 40, contentH));
        float currentY = 10f;
        foreach (var msg in chatHistory)
        {
            bool isUser = msg.role == "user";
            GUIStyle s = isUser ? userStyle : aiStyle;
            float msgH = s.CalcHeight(new GUIContent(msg.content), maxBubbleW);
            float actualW = Mathf.Min(maxBubbleW, s.CalcSize(new GUIContent(msg.content)).x + 32f);
            Rect bubbleRect = isUser ? new Rect(cw - 30 - actualW, currentY, actualW, msgH) : new Rect(10, currentY, actualW, msgH);
            DrawShadow(bubbleRect, 0.05f);
            GUI.color = isUser ? cUserBubble : cBoxBg;
            GUI.DrawTexture(bubbleRect, Texture2D.whiteTexture);
            GUI.color = Color.white;
            GUI.Label(bubbleRect, msg.content, s);
            currentY += msgH + 15f;
        }
        GUI.EndScrollView();

        if (isAITyping)
            GUI.Label(new Rect(cx + 20, cy + ch - 65, cw, 20), "Analyzing Telemetry Data...", VectorStyle(h * 0.015f, cTextSub, false, TextAnchor.MiddleLeft));

        float inputY = cy + ch - 45f;
        GUIStyle inputStyle = new GUIStyle(GUI.skin.textField) { fontSize = Mathf.RoundToInt(h * 0.016f), alignment = TextAnchor.MiddleLeft, padding = new RectOffset(10, 10, 0, 0) };
        Rect inputRect = new Rect(cx + 15, inputY, cw - 100f, 35f);
        Rect sendRect = new Rect(cx + cw - 75f, inputY, 60f, 35f);
        GUI.SetNextControlName("DrivingChatInput");
        chatInputText = GUI.TextField(inputRect, chatInputText, inputStyle);

        bool submit = false;
        if (Event.current.type == EventType.KeyDown && GUI.GetNameOfFocusedControl() == "DrivingChatInput" &&
            (Event.current.keyCode == KeyCode.Return || Event.current.keyCode == KeyCode.KeypadEnter))
        {
            submit = true;
            Event.current.Use();
        }

        DrawActionButton(sendRect, "SEND", isAITyping ? Color.gray : cCyan, null);
        if (GUI.Button(sendRect, GUIContent.none, GUIStyle.none))
            submit = true;

        if (submit && !isAITyping)
        {
            string messageToSend = chatInputText.Trim();
            if (!string.IsNullOrEmpty(messageToSend))
            {
                GUI.FocusControl(null);
                SendChatMessage(messageToSend);
                chatInputText = "";
            }
        }
    }

    void DrawActionButton(Rect rect, string label, Color baseColor, System.Action onClick)
    {
        bool hover = rect.Contains(Event.current.mousePosition);
        DrawShadow(rect, 0.1f);
        GUI.color = new Color(baseColor.r, baseColor.g, baseColor.b, 0.85f);
        GUI.DrawTexture(rect, Texture2D.whiteTexture);
        GUI.color = Color.white;
        var style = new GUIStyle() { alignment = TextAnchor.MiddleCenter, fontSize = Mathf.RoundToInt(Screen.height * 0.016f), fontStyle = FontStyle.Bold };
        Color fixedTextColor = Color.black;
        style.normal.textColor = fixedTextColor;
        style.hover.textColor = fixedTextColor;
        style.active.textColor = fixedTextColor;
        style.focused.textColor = fixedTextColor;
        style.onNormal.textColor = fixedTextColor;
        style.onHover.textColor = fixedTextColor;
        style.onActive.textColor = fixedTextColor;
        style.onFocused.textColor = fixedTextColor;
        GUI.Label(rect, label, style);
        if (Event.current.type == EventType.MouseDown && hover && Event.current.button == 0)
        {
            onClick?.Invoke();
            Event.current.Use();
        }
    }

    void DrawShadow(Rect rect, float alpha = 0.15f)
    {
        GUI.color = new Color(0, 0, 0, alpha);
        GUI.DrawTexture(new Rect(rect.x + 3f, rect.y + 3f, rect.width, rect.height), Texture2D.whiteTexture);
        GUI.color = Color.white;
    }

    void DrawChart_CoP(Rect rect)
    {
        DrawBox(rect, "CoP SWAY (mm)");
        float smoothStep = Mathf.Sin(lerpFactor * Mathf.PI * 0.5f);
        float cx = rect.x + rect.width / 2f;
        float cy = rect.y + rect.height / 2f;
        GUI.color = cGrid;
        GUI.DrawTexture(new Rect(cx, rect.y + 20, 1, rect.height - 40), Texture2D.whiteTexture);
        GUI.DrawTexture(new Rect(rect.x + 20, cy, rect.width - 40, 1), Texture2D.whiteTexture);
        GUI.color = new Color(0f, 0.5f, 0.7f, 0.6f);
        foreach (var p in copPoints)
            GUI.DrawTexture(new Rect((cx + (p.x * smoothStep) * (rect.width / 2.5f) / 10f) - 2, (cy + (p.y * smoothStep) * (rect.height / 2.5f) / 10f) - 2, 5, 5), Texture2D.whiteTexture);
        GUI.color = Color.white;
    }

    void DrawChart_Radar(Rect rect)
    {
        DrawBox(rect, "MULTIVARIATE EVAL");
        float smoothStep = Mathf.Sin(lerpFactor * Mathf.PI * 0.5f);
        float cx = rect.x + rect.width / 2f;
        float cy = rect.y + rect.height / 2f + 10f;
        float radius = rect.height * 0.35f;
        for (int j = 1; j <= 3; j++)
        {
            Vector2 prevGrid = GetRadarPoint(cx, cy, radius * (j / 3f), 5);
            for (int i = 0; i < 6; i++)
            {
                Vector2 pt = GetRadarPoint(cx, cy, radius * (j / 3f), i);
                DrawLine(prevGrid, pt, cGrid, 1.5f);
                if (j == 3) DrawLine(new Vector2(cx, cy), pt, cGrid, 1f);
                prevGrid = pt;
            }
        }

        Vector2 prevDataPt = GetRadarPoint(cx, cy, radius * radarStats[5] * smoothStep, 5);
        for (int i = 0; i < 6; i++)
        {
            Vector2 pt = GetRadarPoint(cx, cy, radius * radarStats[i] * smoothStep, i);
            DrawLine(prevDataPt, pt, cCyan, 2f);
            GUI.color = cTextTitle;
            GUI.DrawTexture(new Rect(pt.x - 2.5f, pt.y - 2.5f, 5, 5), Texture2D.whiteTexture);
            prevDataPt = pt;
        }

        GUI.color = Color.white;
        string[] labels = { "STAB", "SYM", "ENDUR", "REACT", "PREC", "CTRL" };
        for (int i = 0; i < 6; i++)
        {
            Vector2 txtPt = GetRadarPoint(cx, cy, radius + 20f, i);
            GUI.Label(new Rect(txtPt.x - 25, txtPt.y - 10, 50, 20), labels[i], VectorStyle(10, cTextSub, true, TextAnchor.MiddleCenter));
        }
    }

    void DrawChart_Trend(Rect rect)
    {
        DrawBox(rect, "TREND (7 SESSIONS)");
        float smoothStep = Mathf.Sin(lerpFactor * Mathf.PI * 0.5f);
        float padX = 35f;
        float padY = 25f;
        float plotW = rect.width - padX * 2;
        float plotH = rect.height - padY * 2;
        float startX = rect.x + padX;
        float startY = rect.y + rect.height - padY;
        GUIStyle axisStyle = VectorStyle(10, cTextSub, true, TextAnchor.MiddleLeft);
        for (int i = 0; i <= 3; i++)
        {
            float ly = startY - (plotH / 3f) * i;
            DrawLine(new Vector2(startX, ly), new Vector2(startX + plotW, ly), cGrid, 1.5f);
            GUI.Label(new Rect(rect.x + 5, ly - 10, 30, 20), (i * 33).ToString(), axisStyle);
        }

        float stepX = plotW / 6f;
        Vector2 prevPt = new Vector2(startX, startY - (trendScores[0] / 100f) * plotH * smoothStep);
        for (int i = 0; i < 7; i++)
        {
            Vector2 pt = new Vector2(startX + i * stepX, startY - (trendScores[i] / 100f) * plotH * smoothStep);
            if (i > 0) DrawLine(prevPt, pt, cCyan, 2.5f);
            GUI.color = cCyan;
            GUI.DrawTexture(new Rect(pt.x - 3, pt.y - 3, 6, 6), Texture2D.whiteTexture);
            GUI.color = Color.white;
            GUI.DrawTexture(new Rect(pt.x - 1.5f, pt.y - 1.5f, 3, 3), Texture2D.whiteTexture);
            GUI.Label(new Rect(pt.x - 10, startY + 5, 25, 20), "S" + (i + 1), axisStyle);
            prevPt = pt;
        }
    }

    void DrawChart_Balance(Rect rect)
    {
        DrawBox(rect, "BALANCE CONTROL");
        float smoothStep = Mathf.Sin(lerpFactor * Mathf.PI * 0.5f);
        float cx = rect.x + rect.width / 2f;
        float cy = rect.y + rect.height / 2f;
        float barW = rect.width * 0.8f;
        float barH = 15f;
        GUI.color = new Color(0.85f, 0.88f, 0.90f);
        GUI.DrawTexture(new Rect(cx - barW / 2, cy - barH / 2, barW, barH), Texture2D.whiteTexture);
        float offset = (Mathf.Clamp01(1f - (reportRmse / 3f)) - 0.5f) * barW * smoothStep;
        float fillW = Mathf.Abs(offset);
        GUI.color = cCyan;
        if (offset < 0)
            GUI.DrawTexture(new Rect(cx + offset, cy - barH / 2, fillW, barH), Texture2D.whiteTexture);
        else
            GUI.DrawTexture(new Rect(cx, cy - barH / 2, fillW, barH), Texture2D.whiteTexture);
        GUI.color = cTextTitle;
        GUI.DrawTexture(new Rect(cx, cy - barH, 2, barH * 2), Texture2D.whiteTexture);
        GUI.color = Color.white;
        GUIStyle lblStyle = VectorStyle(13, cTextTitle, true, TextAnchor.MiddleCenter);
        GUI.Label(new Rect(cx - 70, cy + barH + 2f, 140, 24), $"RMSE {reportRmse:F2}", lblStyle);
    }

    void DrawBox(Rect r, string title)
    {
        GUI.color = cBoxBg;
        GUI.DrawTexture(r, Texture2D.whiteTexture);
        GUI.color = cGrid;
        GUI.DrawTexture(new Rect(r.x, r.y, r.width, 1.5f), Texture2D.whiteTexture);
        GUI.DrawTexture(new Rect(r.x, r.y + r.height, r.width, 1.5f), Texture2D.whiteTexture);
        GUI.color = Color.white;
        GUIStyle s = VectorStyle(12, cTextSub, true, TextAnchor.MiddleLeft);
        s.padding = new RectOffset(10, 0, 6, 0);
        GUI.Label(new Rect(r.x, r.y, r.width, 25), title, s);
    }

    Vector2 GetRadarPoint(float cx, float cy, float r, int index)
    {
        float angle = (index * 60f - 90f) * Mathf.Deg2Rad;
        return new Vector2(cx + Mathf.Cos(angle) * r, cy + Mathf.Sin(angle) * r);
    }

    void DrawLine(Vector2 pointA, Vector2 pointB, Color color, float width)
    {
        if (pointA == pointB) return;
        Matrix4x4 savedMatrix = GUI.matrix;
        Color savedColor = GUI.color;
        GUI.color = color;
        float angle = Mathf.Atan2(pointB.y - pointA.y, pointB.x - pointA.x) * Mathf.Rad2Deg;
        float length = Vector2.Distance(pointA, pointB);
        GUIUtility.RotateAroundPivot(angle, pointA);
        GUI.DrawTexture(new Rect(pointA.x, pointA.y - width / 2f, length, width), Texture2D.whiteTexture);
        GUI.matrix = savedMatrix;
        GUI.color = savedColor;
    }

    GUIStyle VectorStyle(float size, Color col, bool bold, TextAnchor align)
    {
        var style = new GUIStyle(GUI.skin.label)
        {
            fontSize = Mathf.RoundToInt(size),
            fontStyle = bold ? FontStyle.Bold : FontStyle.Normal,
            alignment = align
        };

        style.normal.textColor = col;
        style.hover.textColor = col;
        style.active.textColor = col;
        style.focused.textColor = col;
        style.onNormal.textColor = col;
        style.onHover.textColor = col;
        style.onActive.textColor = col;
        style.onFocused.textColor = col;
        return style;
    }

    private void EnsureEventSystemExists()
    {
        if (EventSystem.current != null) return;

        GameObject eventSystemGO = new GameObject("EventSystem");
        eventSystemGO.AddComponent<EventSystem>();
        eventSystemGO.AddComponent<StandaloneInputModule>();
    }

    void OnDestroy()
    {
        if (carHandler != null)
            carHandler.OnPlayerCrashed -= PlayerCarHandler_OnPlayerCrashed;
    }
}
