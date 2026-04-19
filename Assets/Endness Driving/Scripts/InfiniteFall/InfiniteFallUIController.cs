using UnityEngine;
using UnityEngine.UI;

public class InfiniteFallUIController : MonoBehaviour
{
    private Text _depthText;
    private Text _scoreText;
    private GameObject _gameOverPanel;
    private Text _finalScoreText;

    public void Initialize(Transform parent, System.Action onExit, System.Action onRestart)
    {
        Canvas canvas = new GameObject("InfiniteFallCanvas").AddComponent<Canvas>();
        canvas.transform.SetParent(parent, false);
        canvas.renderMode = RenderMode.ScreenSpaceOverlay;
        CanvasScaler scaler = canvas.gameObject.AddComponent<CanvasScaler>();
        scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        scaler.referenceResolution = new Vector2(1920, 1080);
        canvas.gameObject.AddComponent<GraphicRaycaster>();

        CreateLabel(canvas.transform, "Title", "INFINITE FALL", new Vector2(0.5f, 1f), new Vector2(0, -24), 42, TextAnchor.UpperCenter, new Color(0.12f, 0.2f, 0.25f));
        _depthText = CreateLabel(canvas.transform, "Depth", "DEPTH: 0", new Vector2(0f, 1f), new Vector2(24, -70), 24, TextAnchor.UpperLeft, new Color(0.15f, 0.2f, 0.25f));
        _scoreText = CreateLabel(canvas.transform, "Score", "SCORE: 0", new Vector2(1f, 1f), new Vector2(-260, -70), 24, TextAnchor.UpperLeft, new Color(0.15f, 0.2f, 0.25f));

        CreateButton(canvas.transform, "ExitButton", "EXIT", new Vector2(1f, 1f), new Vector2(-130, -20), new Vector2(100, 36), onExit);

        _gameOverPanel = new GameObject("GameOverPanel");
        _gameOverPanel.transform.SetParent(canvas.transform, false);
        Image panelImage = _gameOverPanel.AddComponent<Image>();
        panelImage.color = new Color(1f, 1f, 1f, 0.88f);
        RectTransform prt = _gameOverPanel.GetComponent<RectTransform>();
        prt.anchorMin = prt.anchorMax = new Vector2(0.5f, 0.5f);
        prt.sizeDelta = new Vector2(460, 240);

        CreateLabel(_gameOverPanel.transform, "Ended", "SESSION ENDED", new Vector2(0.5f, 0.5f), new Vector2(0, 62), 38, TextAnchor.MiddleCenter, new Color(0.9f, 0.2f, 0.2f));
        _finalScoreText = CreateLabel(_gameOverPanel.transform, "FinalScore", "FINAL SCORE: 0", new Vector2(0.5f, 0.5f), new Vector2(0, 8), 26, TextAnchor.MiddleCenter, new Color(0.12f, 0.2f, 0.25f));
        CreateButton(_gameOverPanel.transform, "RestartButton", "RESTART", new Vector2(0.5f, 0.5f), new Vector2(0, -70), new Vector2(200, 44), onRestart);
        _gameOverPanel.SetActive(false);
    }

    public void Refresh(int depth, int score, bool isGameOver)
    {
        if (_depthText != null) _depthText.text = $"DEPTH: {depth}";
        if (_scoreText != null) _scoreText.text = $"SCORE: {score}";
        if (_finalScoreText != null) _finalScoreText.text = $"FINAL SCORE: {score}";
        if (_gameOverPanel != null) _gameOverPanel.SetActive(isGameOver);
    }

    private static Text CreateLabel(Transform parent, string name, string value, Vector2 anchor, Vector2 anchoredPos, int size, TextAnchor align, Color color)
    {
        GameObject go = new GameObject(name);
        go.transform.SetParent(parent, false);
        Text txt = go.AddComponent<Text>();
        txt.text = value;
        txt.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
        txt.fontSize = size;
        txt.fontStyle = FontStyle.Bold;
        txt.alignment = align;
        txt.color = color;
        RectTransform rt = txt.rectTransform;
        rt.anchorMin = rt.anchorMax = anchor;
        rt.anchoredPosition = anchoredPos;
        rt.sizeDelta = new Vector2(700, 80);
        return txt;
    }

    private static void CreateButton(Transform parent, string name, string label, Vector2 anchor, Vector2 anchoredPos, Vector2 size, System.Action onClick)
    {
        GameObject go = new GameObject(name);
        go.transform.SetParent(parent, false);
        Image bg = go.AddComponent<Image>();
        bg.color = new Color(1f, 1f, 1f, 0.92f);
        Button btn = go.AddComponent<Button>();
        btn.onClick.AddListener(() => onClick?.Invoke());
        RectTransform rt = go.GetComponent<RectTransform>();
        rt.anchorMin = rt.anchorMax = anchor;
        rt.anchoredPosition = anchoredPos;
        rt.sizeDelta = size;

        Text txt = CreateLabel(go.transform, "Label", label, new Vector2(0.5f, 0.5f), Vector2.zero, 18, TextAnchor.MiddleCenter, new Color(0.05f, 0.1f, 0.15f));
        txt.rectTransform.sizeDelta = size;
    }
}
