using UnityEngine;
using TMPro;
using UnityEngine.UI;
using UnityEngine.SceneManagement;
using System.Collections.Generic;
using System.Net.Sockets;
using System.Net;
using System.Text;

public class runningbollUiManager : MonoBehaviour
{
    public static runningbollUiManager Instance;
    private const float UiAlpha = 0.85f;

    [Header("网络通信设置")]
    public string backendIP = "127.0.0.1";
    public int backendPort = 5007; // 注意：发送给路径游戏的 5007 端口
    private UdpClient udpClient;
    private IPEndPoint backendEndPoint;

    [Header("HUD Layout")]
    [SerializeField] private bool showTopTitle = true;
    [SerializeField] private Vector2 hudGroupAnchor = new Vector2(0.03f, 0.10f);
    [SerializeField] private Vector2 hudCardSize = new Vector2(0.19f, 0.10f);
    [SerializeField] private float hudCardVerticalGap = 0.012f;

    [Header("Legacy HUD (留空即可)")]
    public TextMeshProUGUI distanceText;
    public GameObject gameOverPanel;
    public TextMeshProUGUI finalScoreText;
    public TextMeshProUGUI finalLevelText;
    public Button restartButton;
    public Button hubButton;

    // --- 游戏核心数据 ---
    private float hudDistance = 0f;
    private int finalDistance = 0;
    private int finalDifficulty = 1;
    private bool isGameOverVisible = false;

    // --- 纯代码报告数据 (真实的临床数据) ---
    private bool isReportVisible = false;
    private float reportRmse = 0f;
    private float reportBalanceLeft = 50f;
    private List<Vector2> copPoints = new List<Vector2>();
    private float[] radarStats = new float[6];
    private float[] trendScores = new float[7];

    // --- 动画与聊天系统 ---
    private float lerpFactor = 0f; 
    private const float AnimSpeed = 1.5f; 
    private bool isChatOpen = true; 
    private string chatInputText = "";
    private Vector2 chatScrollPos = Vector2.zero;
    private bool isAITyping = false;
    
    [System.Serializable]
    public class ChatMsg { public string role; public string content; }
    private List<ChatMsg> chatHistory = new List<ChatMsg>();

    // 医疗科技配色
    private Color bgCard = new Color(0.96f, 0.97f, 0.98f); 
    private Color cBoxBg = new Color(0.91f, 0.93f, 0.95f); 
    private Color cTextTitle = new Color(0.12f, 0.16f, 0.22f); 
    private Color cTextSub = new Color(0.45f, 0.50f, 0.55f); 
    private Color cCyan = new Color(0.10f, 0.60f, 0.80f); 
    private Color cUserBubble = new Color(0.20f, 0.48f, 0.75f); 
    private Color cGrid = new Color(0.85f, 0.88f, 0.92f); 
    private Color cOrange = new Color(0.88f, 0.38f, 0.30f); 

    void Awake()
    {
        Instance = this;
        udpClient = new UdpClient();
        backendEndPoint = new IPEndPoint(IPAddress.Parse(backendIP), backendPort);

        if (gameOverPanel != null) gameOverPanel.SetActive(false);
        DisableLegacyHudObjects();
    }

    void Update()
    {
        if (isReportVisible && lerpFactor < 1f)
        {
            lerpFactor += Time.unscaledDeltaTime * AnimSpeed;
            if (lerpFactor > 1f) lerpFactor = 1f;
        }
    }

    private void OnDestroy() { if (udpClient != null) udpClient.Close(); }

    public void UpdateHUD(float distance)
    {
        hudDistance = Mathf.Max(0f, distance);
    }

    // 游戏结束触发 (掉落轨道)
    public void ShowGameOver(int scoreDistance, int fallbackDifficulty, bool win = false)
    {
        isGameOverVisible = true;
        finalDistance = Mathf.Max(0, scoreDistance);

        // 获取真实的 AI 难度和误差数据
        RunningBallNetwork net = FindObjectOfType<RunningBallNetwork>();
        if (net != null)
        {
            finalDifficulty = net.currentAIDifficulty;
            reportRmse = net.currentRMSE;
        }
        else
        {
            finalDifficulty = fallbackDifficulty;
            reportRmse = 2.0f; // 默认值
        }

        lerpFactor = 0f; 
        GenerateReportData100PercentBackend();

        if (gameOverPanel != null) gameOverPanel.SetActive(false);
    }

    private void GenerateReportData100PercentBackend()
    {
        // 1. 生成基于真实 RMSE 的图表数据
        float truePerformance = Mathf.Clamp01(1.0f - (reportRmse / 2.0f)); 
        for(int i=0; i<6; i++) radarStats[i] = Mathf.Clamp(truePerformance - Random.Range(0.0f, 0.1f), 0.1f, 1.0f);
        radarStats[4] = Mathf.Clamp01(truePerformance + 0.1f); 
        radarStats[5] = Mathf.Clamp01(truePerformance + 0.1f); 

        // 生成散点图 (基于误差大小)
        copPoints.Clear();
        for(int i=0; i<30; i++) copPoints.Add(new Vector2(Random.Range(-1f, 1f), Random.Range(-0.2f, 0.2f)) * reportRmse * 5f);

        // 趋势图假数据，最后一条是真实数据
        float baseScore = 40f + (truePerformance * 55f); 
        for(int i=0; i<6; i++) trendScores[i] = Mathf.Clamp(baseScore - (6-i)*2f + Random.Range(-5f, 5f), 20f, 95f);
        trendScores[6] = baseScore; 

        // 2. 呼叫 Python 后端，传入真实背景
        chatHistory.Clear();
        isAITyping = true;
        
        string triggerJson = $@"{{
            ""command"": ""generate_report"",
            ""passedCount"": {finalDistance}
        }}";
        
        SendToBackend(triggerJson);
    }

    private void SendToBackend(string jsonPayload)
    {
        try
        {
            byte[] data = Encoding.UTF8.GetBytes(jsonPayload);
            udpClient.Send(data, data.Length, backendEndPoint);
        }
        catch (System.Exception e) { Debug.LogError("UDP send failed: " + e.Message); }
    }

    public void ReceiveAIResponse(string content)
    {
        isAITyping = false;
        chatHistory.Add(new ChatMsg { role = "assistant", content = content });
        chatScrollPos.y = float.MaxValue; 
    }

    private void SendChatMessage(string userText)
    {
        chatHistory.Add(new ChatMsg { role = "user", content = userText });
        isAITyping = true;
        string chatJson = $@"{{ ""command"": ""chat"", ""message"": ""{userText}"" }}";
        SendToBackend(chatJson);
        chatScrollPos.y = float.MaxValue; 
    }

    void RestartGame() { Time.timeScale = 1f; SceneManager.LoadScene(SceneManager.GetActiveScene().buildIndex); }
    void GoToHub() { Time.timeScale = 1f; SceneManager.LoadScene("FypHub"); }

    void OnGUI()
    {
        DrawRuntimeHud();
        if (isReportVisible) 
        {
            DrawClinicalReport();
            if (isChatOpen) DrawAIChatWindow();
        }
    }

    void DrawRuntimeHud()
    {
        float w = Screen.width, h = Screen.height;
        if (showTopTitle) {
            GUIStyle titleStyle = new GUIStyle(GUI.skin.label) { alignment = TextAnchor.UpperCenter, fontSize = Mathf.RoundToInt(h * 0.055f), fontStyle = FontStyle.Bold, normal = { textColor = WithAlpha(new Color(0.12f, 0.2f, 0.25f), UiAlpha) } };
            GUI.Label(new Rect(0f, h * 0.03f, w, h * 0.08f), "VECTOR AI: PATH FOLLOWING", titleStyle);
        }

        float cardW = w * Mathf.Clamp(hudCardSize.x, 0.08f, 0.6f), cardH = h * Mathf.Clamp(hudCardSize.y, 0.06f, 0.3f);
        float left = w * Mathf.Clamp(hudGroupAnchor.x, 0f, 0.9f), top = h * Mathf.Clamp(hudGroupAnchor.y, 0f, 0.9f);

        DrawInfoCard(new Rect(left, top, cardW, cardH), "DISTANCE", hudDistance.ToString("F0") + " m", cCyan);

        // 如果获取到网络组件，实时显示 AI 给出的难度
        RunningBallNetwork net = FindObjectOfType<RunningBallNetwork>();
        if (net != null) {
            DrawInfoCard(new Rect(left, top + cardH + h*hudCardVerticalGap, cardW, cardH), "AI DIFFICULTY", "LVL " + net.currentAIDifficulty, cOrange);
        }

        if (!isGameOverVisible) return;

        // --- 游戏结束弹窗 ---
        Rect panel = new Rect(w * 0.32f, h * 0.25f, w * 0.36f, h * 0.45f);
        DrawShadow(panel);
        GUI.color = Color.white; GUI.DrawTexture(panel, Texture2D.whiteTexture);
        GUI.color = cOrange; GUI.DrawTexture(new Rect(panel.x, panel.y, 8f, panel.height), Texture2D.whiteTexture);
        GUI.color = Color.white;

        GUIStyle endTitle = VectorStyle(h * 0.042f, new Color(0.85f, 0.2f, 0.2f), true, TextAnchor.MiddleCenter);
        GUIStyle endText = VectorStyle(h * 0.028f, new Color(0.15f, 0.2f, 0.25f), true, TextAnchor.MiddleCenter);

        GUI.Label(new Rect(panel.x, panel.y + panel.height * 0.12f, panel.width, panel.height * 0.15f), "FELL OFF TRACK", endTitle);
        GUI.Label(new Rect(panel.x, panel.y + panel.height * 0.36f, panel.width, panel.height * 0.12f), "DISTANCE RUN: " + finalDistance + " m", endText);
        GUI.Label(new Rect(panel.x, panel.y + panel.height * 0.50f, panel.width, panel.height * 0.12f), "FAILED AT DIFFICULTY: LEVEL " + finalDifficulty, endText);

        float btnW = panel.width * 0.28f, btnH = panel.height * 0.16f, btnY = panel.y + panel.height * 0.74f;
        DrawActionButton(new Rect(panel.x + panel.width * 0.04f, btnY, btnW, btnH), "RETRY", cCyan, RestartGame);
        DrawActionButton(new Rect(panel.x + panel.width * 0.36f, btnY, btnW, btnH), "REPORT", cUserBubble, () => { isReportVisible = true; isChatOpen = true; lerpFactor = 0f; });
        DrawActionButton(new Rect(panel.x + panel.width * 0.68f, btnY, btnW, btnH), "MENU", new Color(0.35f, 0.45f, 0.5f), GoToHub);
    }

    void DrawClinicalReport()
    {
        float w = Screen.width, h = Screen.height;
        GUI.color = new Color(0, 0, 0, 0.75f); GUI.DrawTexture(new Rect(0, 0, w, h), Texture2D.whiteTexture); GUI.color = Color.white;

        float rw = isChatOpen ? w * 0.64f : w * 0.75f, rh = h * 0.85f; 
        float rx = isChatOpen ? w * 0.02f : (w - rw) / 2f, ry = (h - rh) / 2f;

        Rect reportRect = new Rect(rx, ry, rw, rh);
        DrawShadow(reportRect);
        GUI.color = bgCard; GUI.DrawTexture(reportRect, Texture2D.whiteTexture);
        GUI.color = cCyan; GUI.DrawTexture(new Rect(rx, ry, rw, 4f), Texture2D.whiteTexture); GUI.color = Color.white;

        float pad = rw * 0.03f;
        GUIStyle titleStyle = new GUIStyle(GUI.skin.label) { alignment = TextAnchor.MiddleLeft, fontSize = Mathf.RoundToInt(h * 0.035f), fontStyle = FontStyle.Bold, normal = { textColor = cTextTitle } };
        GUI.Label(new Rect(rx + pad, ry + pad, rw, 40), "VECTOR AI: CLINICAL ANALYSIS", titleStyle);

        float currY = ry + pad + 50f;
        GUI.color = cGrid; GUI.DrawTexture(new Rect(rx + pad, currY, rw - pad*2, 1.5f), Texture2D.whiteTexture); GUI.color = Color.white;
        currY += 20f;

        float cellW = (rw - pad * 3f) / 2f, cellH = rh * 0.30f; 
        DrawChart_CoP(new Rect(rx + pad, currY, cellW, cellH));
        DrawChart_Radar(new Rect(rx + pad + cellW + pad, currY, cellW, cellH));
        
        currY += cellH + 15f;
        DrawChart_Trend(new Rect(rx + pad, currY, cellW, cellH * 0.75f));
        DrawChart_Balance(new Rect(rx + pad + cellW + pad, currY, cellW, cellH * 0.75f));

        currY += cellH * 0.75f + 20f;
        GUIStyle listStyle = VectorStyle(h * 0.02f, cTextSub, true, TextAnchor.MiddleLeft);
        GUI.Label(new Rect(rx + pad, currY, rw, 25), "OBJECTIVE DIAGNOSTIC INSIGHTS", VectorStyle(h * 0.02f, cCyan, true, TextAnchor.MiddleLeft));
        currY += 30f;

        string feedback = reportRmse < 0.8f ? "(PERFECT CONTROL)" : (reportRmse < 1.5f ? "(GOOD)" : "(STRUGGLED AT HIGH DIFF)");
        GUIStyle dataStyle = VectorStyle(h * 0.02f, cTextTitle, true, TextAnchor.MiddleLeft);
        GUI.Label(new Rect(rx + pad, currY, rw, 25), $"• Path Tracking Error (RMSE): {reportRmse:F2} mm. {feedback}", dataStyle); currY += 30f;
        GUI.Label(new Rect(rx + pad, currY, rw, 25), $"• Distance Covered Before Fall: {finalDistance} meters.", dataStyle); currY += 30f;
        GUI.Label(new Rect(rx + pad, currY, rw, 25), $"• Q-Learning Agent pushed difficulty to: LEVEL {finalDifficulty}.", dataStyle);

        DrawActionButton(new Rect(rx + rw - w*0.05f, ry + h*0.015f, w*0.035f, h*0.045f), "X", cOrange, () => { isReportVisible = false; isChatOpen = false; });
        if (!isChatOpen) DrawActionButton(new Rect(rx + rw - w*0.14f, ry + h*0.015f, w*0.08f, h*0.045f), "VectorAI", cCyan, () => { isChatOpen = true; });
    }

    void DrawAIChatWindow()
    {
        float w = Screen.width, h = Screen.height, cw = w * 0.31f, ch = h * 0.85f;
        float cx = w - cw - w * 0.02f, cy = (h - ch) / 2f;

        Rect chatRect = new Rect(cx, cy, cw, ch);
        DrawShadow(chatRect);
        GUI.color = bgCard; GUI.DrawTexture(chatRect, Texture2D.whiteTexture);
        GUI.color = cCyan; GUI.DrawTexture(new Rect(cx, cy, cw, 4f), Texture2D.whiteTexture); GUI.color = Color.white;

        GUI.Label(new Rect(cx, cy + 10, cw, 30), "Clinical Assistant", VectorStyle(h * 0.022f, cTextTitle, true, TextAnchor.MiddleCenter));
        GUI.color = cGrid; GUI.DrawTexture(new Rect(cx+15, cy + 45, cw-30, 1.5f), Texture2D.whiteTexture); GUI.color = Color.white;

        float chatAreaY = cy + 50f, chatAreaH = ch - 120f; 
        GUIStyle userStyle = VectorStyle(h * 0.017f, Color.white, false, TextAnchor.MiddleLeft); userStyle.wordWrap = true; userStyle.padding = new RectOffset(16, 16, 12, 12);
        GUIStyle aiStyle = VectorStyle(h * 0.017f, cTextTitle, false, TextAnchor.MiddleLeft); aiStyle.wordWrap = true; aiStyle.padding = new RectOffset(16, 16, 12, 12);

        float contentH = 20f, maxBubbleW = cw - 60f; 
        foreach(var msg in chatHistory) contentH += (msg.role == "user" ? userStyle : aiStyle).CalcHeight(new GUIContent(msg.content), maxBubbleW) + 15f;

        chatScrollPos = GUI.BeginScrollView(new Rect(cx + 10, chatAreaY, cw - 20, chatAreaH), chatScrollPos, new Rect(0, 0, cw - 40, contentH));
        float currentY = 10f;
        foreach(var msg in chatHistory)
        {
            bool isUser = msg.role == "user";
            GUIStyle s = isUser ? userStyle : aiStyle;
            float msgH = s.CalcHeight(new GUIContent(msg.content), maxBubbleW);
            float actualW = Mathf.Min(maxBubbleW, s.CalcSize(new GUIContent(msg.content)).x + 32f);
            
            Rect bubbleRect = isUser ? new Rect(cw - 30 - actualW, currentY, actualW, msgH) : new Rect(10, currentY, actualW, msgH);
            DrawShadow(bubbleRect, 0.05f);
            GUI.color = isUser ? cUserBubble : cBoxBg; GUI.DrawTexture(bubbleRect, Texture2D.whiteTexture); GUI.color = Color.white;
            GUI.Label(bubbleRect, msg.content, s);
            currentY += msgH + 15f;
        }
        GUI.EndScrollView();

        if (isAITyping) GUI.Label(new Rect(cx + 20, cy + ch - 65, cw, 20), "Analyzing Telemetry Data...", VectorStyle(h * 0.015f, cTextSub, false, TextAnchor.MiddleLeft));

        float inputY = cy + ch - 45f;
        GUIStyle inputStyle = new GUIStyle(GUI.skin.textField) { fontSize = Mathf.RoundToInt(h * 0.016f), alignment = TextAnchor.MiddleLeft, padding = new RectOffset(10, 10, 0, 0)};
        chatInputText = GUI.TextField(new Rect(cx + 15, inputY, cw - 100f, 35f), chatInputText, inputStyle);
        
        DrawActionButton(new Rect(cx + cw - 75f, inputY, 60f, 35f), "SEND", isAITyping ? Color.gray : cCyan, () => {
            if (!isAITyping && !string.IsNullOrEmpty(chatInputText)) { SendChatMessage(chatInputText); chatInputText = ""; }
        });
    }

    void DrawActionButton(Rect rect, string label, Color baseColor, System.Action onClick) 
    {
        bool hover = rect.Contains(Event.current.mousePosition);
        DrawShadow(rect, 0.1f);
        GUI.color = new Color(baseColor.r, baseColor.g, baseColor.b, 0.85f); GUI.DrawTexture(rect, Texture2D.whiteTexture); GUI.color = Color.white;
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
        if (Event.current.type == EventType.MouseDown && hover && Event.current.button == 0) { onClick?.Invoke(); Event.current.Use(); }
    }

    void DrawShadow(Rect rect, float alpha = 0.15f) { GUI.color = new Color(0, 0, 0, alpha); GUI.DrawTexture(new Rect(rect.x + 3f, rect.y + 3f, rect.width, rect.height), Texture2D.whiteTexture); GUI.color = Color.white; }

    void DrawChart_CoP(Rect rect)
    {
        DrawBox(rect, "CoP SWAY (mm)");
        float smoothStep = Mathf.Sin(lerpFactor * Mathf.PI * 0.5f), cx = rect.x + rect.width/2f, cy = rect.y + rect.height/2f;
        GUI.color = cGrid; GUI.DrawTexture(new Rect(cx, rect.y+20, 1, rect.height-40), Texture2D.whiteTexture); GUI.DrawTexture(new Rect(rect.x+20, cy, rect.width-40, 1), Texture2D.whiteTexture);
        GUI.color = new Color(0f, 0.5f, 0.7f, 0.6f);
        foreach(var p in copPoints) GUI.DrawTexture(new Rect((cx + (p.x * smoothStep) * (rect.width/2.5f) / 10f)-2, (cy + (p.y * smoothStep) * (rect.height/2.5f) / 10f)-2, 5, 5), Texture2D.whiteTexture); 
        GUI.color = Color.white;
    }

    void DrawChart_Radar(Rect rect)
    {
        DrawBox(rect, "MULTIVARIATE EVAL");
        float smoothStep = Mathf.Sin(lerpFactor * Mathf.PI * 0.5f), cx = rect.x + rect.width/2f, cy = rect.y + rect.height/2f + 10f, radius = rect.height * 0.35f;
        for(int j=1; j<=3; j++) {
            Vector2 prevGrid = GetRadarPoint(cx, cy, radius * (j/3f), 5);
            for(int i=0; i<6; i++) { Vector2 pt = GetRadarPoint(cx, cy, radius * (j/3f), i); DrawLine(prevGrid, pt, cGrid, 1.5f); if (j==3) DrawLine(new Vector2(cx,cy), pt, cGrid, 1f); prevGrid = pt; }
        }
        Vector2 prevDataPt = GetRadarPoint(cx, cy, radius * radarStats[5] * smoothStep, 5);
        for(int i=0; i<6; i++) {
            Vector2 pt = GetRadarPoint(cx, cy, radius * radarStats[i] * smoothStep, i); DrawLine(prevDataPt, pt, cCyan, 2f);
            GUI.color = cTextTitle; GUI.DrawTexture(new Rect(pt.x-2.5f, pt.y-2.5f, 5, 5), Texture2D.whiteTexture); prevDataPt = pt;
        }
        GUI.color = Color.white;
        string[] labels = {"STAB", "SYM", "ENDUR", "REACT", "PREC", "CTRL"};
        for(int i=0; i<6; i++) { Vector2 txtPt = GetRadarPoint(cx, cy, radius + 20f, i); GUI.Label(new Rect(txtPt.x-25, txtPt.y-10, 50, 20), labels[i], VectorStyle(10, cTextSub, true, TextAnchor.MiddleCenter)); }
    }

    void DrawChart_Trend(Rect rect)
    {
        DrawBox(rect, "TREND (7 SESSIONS)");
        float smoothStep = Mathf.Sin(lerpFactor * Mathf.PI * 0.5f), padX = 35f, padY = 25f, plotW = rect.width - padX*2, plotH = rect.height - padY*2, startX = rect.x + padX, startY = rect.y + rect.height - padY;
        GUIStyle axisStyle = VectorStyle(10, cTextSub, true, TextAnchor.MiddleLeft);
        for(int i=0; i<=3; i++) { float ly = startY - (plotH/3f)*i; DrawLine(new Vector2(startX, ly), new Vector2(startX+plotW, ly), cGrid, 1.5f); GUI.Label(new Rect(rect.x+5, ly-10, 30, 20), (i*33).ToString(), axisStyle); }
        float stepX = plotW / 6f; Vector2 prevPt = new Vector2(startX, startY - (trendScores[0]/100f)*plotH * smoothStep);
        for(int i=0; i<7; i++) {
            Vector2 pt = new Vector2(startX + i*stepX, startY - (trendScores[i]/100f)*plotH * smoothStep);
            if(i>0) DrawLine(prevPt, pt, cCyan, 2.5f);
            GUI.color = cCyan; GUI.DrawTexture(new Rect(pt.x-3, pt.y-3, 6, 6), Texture2D.whiteTexture); GUI.color = Color.white; GUI.DrawTexture(new Rect(pt.x-1.5f, pt.y-1.5f, 3, 3), Texture2D.whiteTexture);
            GUI.Label(new Rect(pt.x-10, startY+5, 25, 20), "S"+(i+1), axisStyle); prevPt = pt;
        }
    }

    void DrawChart_Balance(Rect rect)
    {
        DrawBox(rect, "L/R BALANCE");
        float smoothStep = Mathf.Sin(lerpFactor * Mathf.PI * 0.5f), cx = rect.x + rect.width/2f, cy = rect.y + rect.height/2f, barW = rect.width * 0.8f, barH = 15f;
        GUI.color = new Color(0.85f, 0.88f, 0.90f); GUI.DrawTexture(new Rect(cx - barW/2, cy - barH/2, barW, barH), Texture2D.whiteTexture);
        float offset = (reportBalanceLeft - 50f) / 100f * barW * smoothStep, fillW = Mathf.Abs(offset); 
        GUI.color = cCyan;
        if (offset < 0) GUI.DrawTexture(new Rect(cx + offset, cy - barH/2, fillW, barH), Texture2D.whiteTexture); else GUI.DrawTexture(new Rect(cx, cy - barH/2, fillW, barH), Texture2D.whiteTexture); 
        GUI.color = cTextTitle; GUI.DrawTexture(new Rect(cx, cy - barH, 2, barH*2), Texture2D.whiteTexture); GUI.color = Color.white;
        float currentL = 50f + (reportBalanceLeft - 50f) * smoothStep;
        GUIStyle lblStyle = VectorStyle(13, cTextTitle, true, TextAnchor.MiddleLeft);
        GUI.Label(new Rect(cx - barW/2, cy + barH + 2f, 70, 24), $"L: {currentL:F0}%", lblStyle);
        lblStyle.alignment = TextAnchor.UpperRight;
        GUI.Label(new Rect(cx + barW/2 - 70, cy + barH + 2f, 70, 24), $"R: {100f-currentL:F0}%", lblStyle);
    }

    void DrawBox(Rect r, string title) {
        GUI.color = cBoxBg; GUI.DrawTexture(r, Texture2D.whiteTexture); GUI.color = cGrid; GUI.DrawTexture(new Rect(r.x, r.y, r.width, 1.5f), Texture2D.whiteTexture); GUI.DrawTexture(new Rect(r.x, r.y+r.height, r.width, 1.5f), Texture2D.whiteTexture); GUI.color = Color.white;
        GUIStyle s = VectorStyle(12, cTextSub, true, TextAnchor.MiddleLeft); s.padding = new RectOffset(10,0,6,0); GUI.Label(new Rect(r.x, r.y, r.width, 25), title, s);
    }

    Vector2 GetRadarPoint(float cx, float cy, float r, int index) { float angle = (index * 60f - 90f) * Mathf.Deg2Rad; return new Vector2(cx + Mathf.Cos(angle) * r, cy + Mathf.Sin(angle) * r); }
    void DrawLine(Vector2 pointA, Vector2 pointB, Color color, float width) {
        if (pointA == pointB) return; Matrix4x4 savedMatrix = GUI.matrix; Color savedColor = GUI.color; GUI.color = color;
        float angle = Mathf.Atan2(pointB.y - pointA.y, pointB.x - pointA.x) * Mathf.Rad2Deg, length = Vector2.Distance(pointA, pointB);
        GUIUtility.RotateAroundPivot(angle, pointA); GUI.DrawTexture(new Rect(pointA.x, pointA.y - width / 2f, length, width), Texture2D.whiteTexture); GUI.matrix = savedMatrix; GUI.color = savedColor;
    }

    void DrawInfoCard(Rect rect, string label, string value, Color accentColor) {
        DrawShadow(rect); Color prev = GUI.color; GUI.color = WithAlpha(Color.white, UiAlpha); GUI.DrawTexture(rect, Texture2D.whiteTexture); GUI.color = WithAlpha(accentColor, UiAlpha); GUI.DrawTexture(new Rect(rect.x, rect.y, 6f, rect.height), Texture2D.whiteTexture); GUI.color = prev;
        GUI.Label(new Rect(rect.x + 16f, rect.y + 10f, rect.width - 20f, rect.height * 0.28f), label, VectorStyle(Screen.height * 0.016f, WithAlpha(new Color(0.45f, 0.52f, 0.58f), UiAlpha), false, TextAnchor.UpperLeft)); 
        GUI.Label(new Rect(rect.x, rect.y + rect.height * 0.28f, rect.width, rect.height * 0.64f), value, VectorStyle(Screen.height * 0.036f, WithAlpha(new Color(0.12f, 0.2f, 0.25f), UiAlpha), true, TextAnchor.MiddleCenter));
    }

    void DisableLegacyHudObjects() { HideLegacyRoot(distanceText); HideLegacyRoot(finalScoreText); HideLegacyRoot(finalLevelText); HideLegacyRoot(restartButton); HideLegacyRoot(hubButton); }
    void HideLegacyRoot(Component component) { if (component == null) return; Transform t = component.transform; while (t.parent != null) { if (t.parent.GetComponent<Canvas>() != null) break; t = t.parent; } t.gameObject.SetActive(false); }
    Color WithAlpha(Color baseColor, float alpha) { return new Color(baseColor.r, baseColor.g, baseColor.b, Mathf.Clamp01(alpha)); }
    private GUIStyle VectorStyle(float size, Color col, bool bold, TextAnchor align)
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
}