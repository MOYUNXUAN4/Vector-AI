#if UNITY_EDITOR
using UnityEngine;
using UnityEditor;
using TMPro;
using UnityEngine.UI;

public class EndnessFallingEditor
{
    [MenuItem("Endness Falling/Auto-Build Beautiful UI")]
    public static void BuildAndBindEndnessUI()
    {
        UIManager endlessUIManager = GameObject.FindObjectOfType<UIManager>();
        if (endlessUIManager == null)
        {
            EditorUtility.DisplayDialog("Error", "Cannot find UIManager in scene!", "OK");
            return;
        }

        // 防堆叠：如果已经存在生成的UI，先把它删掉，保持场景干净
        GameObject oldCanvas = GameObject.Find("Endness_Main_Canvas");
        if (oldCanvas != null) GameObject.DestroyImmediate(oldCanvas);
        GameObject oldEvent = GameObject.Find("Endness_EventSystem");
        if (oldEvent != null) GameObject.DestroyImmediate(oldEvent);

        // 1. 创建主画布
        GameObject endlessCanvasObj = new GameObject("Endness_Main_Canvas");
        Canvas mainCanvas = endlessCanvasObj.AddComponent<Canvas>();
        mainCanvas.renderMode = RenderMode.ScreenSpaceOverlay;
        CanvasScaler canvasScaler = endlessCanvasObj.AddComponent<CanvasScaler>();
        canvasScaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        canvasScaler.referenceResolution = new Vector2(1920, 1080);
        endlessCanvasObj.AddComponent<GraphicRaycaster>();

        GameObject eventSysObj = new GameObject("Endness_EventSystem");
        eventSysObj.AddComponent<UnityEngine.EventSystems.EventSystem>();
        eventSysObj.AddComponent<UnityEngine.EventSystems.StandaloneInputModule>();

        // 2. HUD 背景板 (增加半透明黑底，提升高级感)
        GameObject hudContainer = new GameObject("HUD_Background");
        hudContainer.transform.SetParent(endlessCanvasObj.transform, false);
        RectTransform hudRect = hudContainer.AddComponent<RectTransform>();
        hudRect.anchorMin = new Vector2(0, 1); hudRect.anchorMax = new Vector2(0, 1);
        hudRect.pivot = new Vector2(0, 1);
        hudRect.anchoredPosition = new Vector2(40, -40);
        hudRect.sizeDelta = new Vector2(350, 180);
        Image hudBg = hudContainer.AddComponent<Image>();
        hudBg.color = new Color(0.05f, 0.05f, 0.05f, 0.7f); // 半透明深空灰

        // 纯英文 HUD 文本
        TextMeshProUGUI txtPassedLayers = CreateEndnessText(hudContainer.transform, "Txt_Passed", "Passed: 0", new Vector2(20, -20), 32);
        TextMeshProUGUI txtCurrentDiff = CreateEndnessText(hudContainer.transform, "Txt_Diff", "Difficulty: Lvl 1", new Vector2(20, -70), 32);
        TextMeshProUGUI txtRemaining = CreateEndnessText(hudContainer.transform, "Txt_Rem", "Next Lvl In: 10", new Vector2(20, -120), 32);

        // 3. 结算面板 (全屏黑底 + 中央对齐)
        GameObject settlementPanel = new GameObject("Settlement_Panel");
        settlementPanel.transform.SetParent(endlessCanvasObj.transform, false);
        RectTransform settlementRect = settlementPanel.AddComponent<RectTransform>();
        settlementRect.anchorMin = Vector2.zero; settlementRect.anchorMax = Vector2.one; 
        settlementRect.offsetMin = Vector2.zero; settlementRect.offsetMax = Vector2.zero;
        Image settlementBg = settlementPanel.AddComponent<Image>();
        settlementBg.color = new Color(0.1f, 0.1f, 0.15f, 0.95f); // 极深蓝灰遮罩

        // 标题
        TextMeshProUGUI txtTitle = CreateEndnessText(settlementPanel.transform, "Txt_Title", "GAME OVER", new Vector2(0, 250), 100);
        txtTitle.alignment = TextAlignmentOptions.Center;
        txtTitle.color = new Color(1f, 0.3f, 0.3f); // 红色高亮

        TextMeshProUGUI txtFinalScore = CreateEndnessText(settlementPanel.transform, "Txt_FinalLayers", "Total Passed: 50", new Vector2(0, 80), 50);
        txtFinalScore.alignment = TextAlignmentOptions.Center;

        TextMeshProUGUI txtFinalLevel = CreateEndnessText(settlementPanel.transform, "Txt_MaxDiff", "Max Difficulty: Lvl 5", new Vector2(0, 0), 40);
        txtFinalLevel.alignment = TextAlignmentOptions.Center;

        // 现代化按钮
        Button btnRestart = CreateModernButton(settlementPanel.transform, "Btn_Restart", "RESTART", new Vector2(-220, -150), new Color(0.2f, 0.6f, 1f));
        Button btnBackToHub = CreateModernButton(settlementPanel.transform, "Btn_Hub", "FYP HUB", new Vector2(220, -150), new Color(0.4f, 0.4f, 0.4f));

        // 4. 全自动连线
        endlessUIManager.levelText = txtPassedLayers;
        endlessUIManager.difficultyText = txtCurrentDiff;
        endlessUIManager.remainingText = txtRemaining;

        endlessUIManager.gameOverPanel = settlementPanel;
        endlessUIManager.finalScoreText = txtFinalScore;
        endlessUIManager.finalLevelText = txtFinalLevel;
        endlessUIManager.restartButton = btnRestart;
        endlessUIManager.hubButton = btnBackToHub;

        settlementPanel.SetActive(false);

        EditorUtility.SetDirty(endlessUIManager);
        UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(UnityEngine.SceneManagement.SceneManager.GetActiveScene());
        EditorUtility.DisplayDialog("Success", "Modern English UI Generated successfully!", "Awesome");
    }

    static TextMeshProUGUI CreateEndnessText(Transform parentObj, string objName, string defaultContent, Vector2 position, int fontSize)
    {
        GameObject newObj = new GameObject(objName);
        newObj.transform.SetParent(parentObj, false);
        RectTransform rectTrans = newObj.AddComponent<RectTransform>();
        rectTrans.anchoredPosition = position;
        rectTrans.sizeDelta = new Vector2(800, 100);
        TextMeshProUGUI tmpComponent = newObj.AddComponent<TextMeshProUGUI>();
        tmpComponent.text = defaultContent;
        tmpComponent.fontSize = fontSize;
        tmpComponent.color = Color.white;
        tmpComponent.fontStyle = FontStyles.Bold;
        tmpComponent.raycastTarget = false; // 优化性能
        return tmpComponent;
    }

    // 生成更好看的带颜色扁平化按钮
    static Button CreateModernButton(Transform parentObj, string objName, string btnLabel, Vector2 position, Color bgColor)
    {
        GameObject newObj = new GameObject(objName);
        newObj.transform.SetParent(parentObj, false);
        RectTransform rectTrans = newObj.AddComponent<RectTransform>();
        rectTrans.anchoredPosition = position;
        rectTrans.sizeDelta = new Vector2(300, 90); // 按钮变宽变大气
        Image imgComponent = newObj.AddComponent<Image>();
        imgComponent.color = bgColor;
        Button btnComponent = newObj.AddComponent<Button>();

        TextMeshProUGUI tmpComponent = CreateEndnessText(newObj.transform, "Text", btnLabel, Vector2.zero, 35);
        tmpComponent.color = Color.white; // 白色文字
        tmpComponent.alignment = TextAlignmentOptions.Center;
        
        // 让文字填满按钮居中
        tmpComponent.GetComponent<RectTransform>().sizeDelta = rectTrans.sizeDelta; 
        return btnComponent;
    }
}
#endif