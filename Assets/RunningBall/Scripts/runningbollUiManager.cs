using UnityEngine;
using TMPro;
using UnityEngine.UI;
using UnityEngine.SceneManagement;

public class runningbollUiManager : MonoBehaviour
{
    // 【修改】单例的名字也跟着改了
    public static runningbollUiManager Instance;
    private const float UiAlpha = 0.8f;

    [Header("HUD Layout (Inspector Quick Tuning)")]
    [SerializeField] private bool showTopTitle = false;
    [SerializeField] private Vector2 hudGroupAnchor = new Vector2(0.03f, 0.10f);
    [SerializeField] private Vector2 hudCardSize = new Vector2(0.19f, 0.10f);

    [Header("Legacy HUD (Can be left empty)")]
    public TextMeshProUGUI distanceText; 

    [Header("Game Over Panel")]
    public GameObject gameOverPanel;
    public TextMeshProUGUI finalScoreText;
    public TextMeshProUGUI finalLevelText;
    public Button restartButton;
    public Button hubButton;

    // 记录行驶距离
    private float hudDistance = 0f;
    
    private int finalScore = 0;
    private int finalDifficulty = 1;
    private bool isGameOverVisible = false;
    private bool isWin = false;

    void Awake()
    {
        Instance = this;
        if (gameOverPanel != null) gameOverPanel.SetActive(false);
        DisableLegacyHudObjects();
    }

    void Start()
    {
        if (restartButton != null) restartButton.onClick.AddListener(RestartGame);
        if (hubButton != null) hubButton.onClick.AddListener(GoToHub);
        SetButtonLabel(restartButton, "RESTART");
        SetButtonLabel(hubButton, "BACK TO MAIN MENU");
        DisableLegacyHudObjects();
    }

    public void UpdateHUD(float distance)
    {
        hudDistance = Mathf.Max(0f, distance);

        if (distanceText != null) 
        {
            distanceText.text = "DISTANCE: " + hudDistance.ToString("F0") + "m"; 
        }
    }

    public void ShowGameOver(int score, int difficultyLevel, bool win = false)
    {
        isGameOverVisible = true;
        isWin = win;
        finalScore = Mathf.Max(0, score);
        finalDifficulty = Mathf.Max(1, difficultyLevel);

        if (gameOverPanel != null) gameOverPanel.SetActive(false);
        if (finalScoreText != null) finalScoreText.text = "FINAL SCORE: " + finalScore;
        if (finalLevelText != null)
        {
            finalLevelText.text = win
                ? "STAGE COMPLETED - LEVEL " + finalDifficulty
                : "MAX DIFFICULTY REACHED: LEVEL " + finalDifficulty;
        }
    }

    void RestartGame()
    {
        Time.timeScale = 1f; 
        SceneManager.LoadScene(SceneManager.GetActiveScene().buildIndex);
    }

    void GoToHub()
    {
        Time.timeScale = 1f; 
        SceneManager.LoadScene("FypHub");
    }

    void SetButtonLabel(Button button, string label)
    {
        if (button == null) return;
        TextMeshProUGUI tmp = button.GetComponentInChildren<TextMeshProUGUI>(true);
        if (tmp != null) tmp.text = label;
    }

    void OnGUI()
    {
        DrawRuntimeHud();
    }

    void DrawRuntimeHud()
    {
        float w = Screen.width;
        float h = Screen.height;

        if (showTopTitle)
        {
            GUIStyle titleStyle = new GUIStyle(GUI.skin.label)
            {
                alignment = TextAnchor.UpperCenter,
                fontSize = Mathf.RoundToInt(h * 0.055f),
                fontStyle = FontStyle.Bold,
                normal = { textColor = WithAlpha(new Color(0.12f, 0.2f, 0.25f), UiAlpha) }
            };

            GUIStyle subtitleStyle = new GUIStyle(GUI.skin.label)
            {
                alignment = TextAnchor.UpperCenter,
                fontSize = Mathf.RoundToInt(h * 0.02f),
                normal = { textColor = WithAlpha(new Color(0.35f, 0.45f, 0.5f), UiAlpha) }
            };

            GUI.Label(new Rect(0f, h * 0.03f, w, h * 0.08f), "INFINITE FALL", titleStyle);
            GUI.Label(new Rect(0f, h * 0.09f, w, h * 0.04f), "NEUROMOTOR BALANCE TRAINING", subtitleStyle);
        }

        float cardW = w * Mathf.Clamp(hudCardSize.x, 0.08f, 0.6f);
        float cardH = h * Mathf.Clamp(hudCardSize.y, 0.06f, 0.3f);
        float left = w * Mathf.Clamp(hudGroupAnchor.x, 0f, 0.9f);
        float top = h * Mathf.Clamp(hudGroupAnchor.y, 0f, 0.9f);

        DrawInfoCard(new Rect(left, top, cardW, cardH), "DISTANCE", hudDistance.ToString("F0") + " m", new Color(0.0f, 0.62f, 0.70f));

        if (!isGameOverVisible) return;

        Color prevColor = GUI.color;
        Rect panel = new Rect(w * 0.32f, h * 0.25f, w * 0.36f, h * 0.45f);
        GUI.color = WithAlpha(Color.white, UiAlpha);
        GUI.DrawTexture(panel, Texture2D.whiteTexture);
        GUI.color = prevColor;

        GUI.color = WithAlpha(isWin ? new Color(0.0f, 0.62f, 0.70f) : new Color(0.90f, 0.35f, 0.24f), UiAlpha);
        GUI.DrawTexture(new Rect(panel.x, panel.y, 8f, panel.height), Texture2D.whiteTexture);
        GUI.color = prevColor;

        GUIStyle endTitle = new GUIStyle(GUI.skin.label)
        {
            alignment = TextAnchor.MiddleCenter,
            fontSize = Mathf.RoundToInt(h * 0.042f),
            fontStyle = FontStyle.Bold,
            normal = { textColor = WithAlpha(isWin ? new Color(0.0f, 0.55f, 0.45f) : new Color(0.85f, 0.2f, 0.2f), UiAlpha) }
        };
        GUIStyle endText = new GUIStyle(GUI.skin.label)
        {
            alignment = TextAnchor.MiddleCenter,
            fontSize = Mathf.RoundToInt(h * 0.028f),
            fontStyle = FontStyle.Bold,
            normal = { textColor = WithAlpha(new Color(0.15f, 0.2f, 0.25f), UiAlpha) }
        };

        GUI.Label(new Rect(panel.x, panel.y + panel.height * 0.12f, panel.width, panel.height * 0.15f), isWin ? "STAGE CLEARED" : "SESSION ENDED", endTitle);
        GUI.Label(new Rect(panel.x, panel.y + panel.height * 0.36f, panel.width, panel.height * 0.12f), "FINAL SCORE: " + finalScore, endText);
        GUI.Label(new Rect(panel.x, panel.y + panel.height * 0.50f, panel.width, panel.height * 0.12f), "MAX DIFFICULTY: LEVEL " + finalDifficulty, endText);

        Rect restartRect = new Rect(panel.x + panel.width * 0.15f, panel.y + panel.height * 0.74f, panel.width * 0.28f, panel.height * 0.16f);
        Rect hubRect = new Rect(panel.x + panel.width * 0.57f, panel.y + panel.height * 0.74f, panel.width * 0.28f, panel.height * 0.16f);
        DrawActionButton(restartRect, "RESTART", new Color(0.0f, 0.62f, 0.70f), RestartGame);
        DrawActionButton(hubRect, "BACK TO MENU", new Color(0.35f, 0.45f, 0.5f), GoToHub);
    }

    void DrawInfoCard(Rect rect, string label, string value, Color accentColor)
    {
        Color prev = GUI.color;
        GUI.color = WithAlpha(Color.white, UiAlpha);
        GUI.DrawTexture(rect, Texture2D.whiteTexture);
        GUI.color = WithAlpha(accentColor, UiAlpha);
        GUI.DrawTexture(new Rect(rect.x, rect.y, 6f, rect.height), Texture2D.whiteTexture);
        GUI.color = prev;

        GUIStyle labelStyle = new GUIStyle(GUI.skin.label)
        {
            alignment = TextAnchor.UpperLeft,
            fontSize = Mathf.RoundToInt(Screen.height * 0.018f),
            normal = { textColor = WithAlpha(new Color(0.45f, 0.52f, 0.58f), UiAlpha) }
        };
        GUIStyle valueStyle = new GUIStyle(GUI.skin.label)
        {
            alignment = TextAnchor.MiddleCenter,
            fontSize = Mathf.RoundToInt(Screen.height * 0.036f),
            fontStyle = FontStyle.Bold,
            normal = { textColor = WithAlpha(new Color(0.12f, 0.2f, 0.25f), UiAlpha) }
        };

        GUI.Label(new Rect(rect.x + 16f, rect.y + 10f, rect.width - 20f, rect.height * 0.28f), label, labelStyle);
        GUI.Label(new Rect(rect.x, rect.y + rect.height * 0.28f, rect.width, rect.height * 0.64f), value, valueStyle);
    }

    void DisableLegacyHudObjects()
    {
        HideLegacyRoot(distanceText);
        HideLegacyRoot(finalScoreText);
        HideLegacyRoot(finalLevelText);
        HideLegacyRoot(restartButton);
        HideLegacyRoot(hubButton);
        if (gameOverPanel != null) gameOverPanel.SetActive(false);
    }

    void HideLegacyRoot(Component component)
    {
        if (component == null) return;
        Transform t = component.transform;
        while (t.parent != null)
        {
            if (t.parent.GetComponent<Canvas>() != null) break;
            t = t.parent;
        }
        t.gameObject.SetActive(false);
    }

    void DrawActionButton(Rect rect, string label, Color color, System.Action onClick)
    {
        Color prev = GUI.color;
        bool hover = rect.Contains(Event.current.mousePosition);
        GUI.color = WithAlpha(hover ? Color.Lerp(color, Color.white, 0.18f) : color, UiAlpha);
        GUI.DrawTexture(rect, Texture2D.whiteTexture);
        GUI.color = prev;

        GUIStyle style = new GUIStyle(GUI.skin.label)
        {
            alignment = TextAnchor.MiddleCenter,
            fontSize = Mathf.RoundToInt(Screen.height * 0.022f),
            fontStyle = FontStyle.Bold,
            normal = { textColor = WithAlpha(Color.white, UiAlpha) }
        };
        GUI.Label(rect, label, style);

        if (Event.current.type == EventType.MouseDown && rect.Contains(Event.current.mousePosition) && Event.current.button == 0)
        {
            onClick?.Invoke();
            Event.current.Use();
        }
    }

    Color WithAlpha(Color baseColor, float alpha)
    {
        return new Color(baseColor.r, baseColor.g, baseColor.b, Mathf.Clamp01(alpha));
    }
}