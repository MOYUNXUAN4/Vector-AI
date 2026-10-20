using System.Collections;
using UnityEngine;
using UnityEngine.UI;

public class FypHubSensitivityMenu : MonoBehaviour
{
    Canvas rootCanvas;
    Transform buttonStack;
    GameObject overlay;
    Slider fallingSlider;
    Slider pathSlider;
    Slider driverSlider;
    Text fallingValueText;
    Text pathValueText;
    Text driverValueText;

    void Awake()
    {
        rootCanvas = GetComponent<Canvas>();
        if (rootCanvas == null) return;

        buttonStack = transform.Find("MainMenuLayout/ButtonStack");
        if (buttonStack == null) return;

        RefreshUiState();
    }

    void OnEnable()
    {
        if (rootCanvas == null)
            rootCanvas = GetComponent<Canvas>();
        if (buttonStack == null)
            buttonStack = transform.Find("MainMenuLayout/ButtonStack");
        if (rootCanvas == null || buttonStack == null)
            return;

        RefreshUiState();
        StopAllCoroutines();
        StartCoroutine(EnsureSettingsButtonAfterFrames());
    }

    void RefreshUiState()
    {
        EnsureSettingsButton();
        EnsureShutdownButton();
        EnsureOverlay();
        RefreshSliderValuesFromPrefs();
        UpdateValueTexts();
    }

    IEnumerator EnsureSettingsButtonAfterFrames()
    {
        yield return null;
        RefreshUiState();
        yield return null;
        RefreshUiState();
    }

    void EnsureSettingsButton()
    {
        Transform settingsTransform = buttonStack.Find("Btn_Settings");
        GameObject buttonObject;

        if (settingsTransform != null)
        {
            buttonObject = settingsTransform.gameObject;
        }
        else
        {
            Transform template = buttonStack.Find("Btn_EndlessDriver");
            if (template == null) return;

            buttonObject = Instantiate(template.gameObject, buttonStack);
            buttonObject.name = "Btn_Settings";
        }

        Button button = buttonObject.GetComponent<Button>();
        if (button != null)
        {
            button.onClick.RemoveAllListeners();
            button.onClick.AddListener(OpenPanel);
        }

        Color settingsBgColor = new Color(0.66f, 0.60f, 0.74f, 0.92f);
        Color settingsTextColor = new Color(0.20f, 0.16f, 0.26f, 1f);

        Image image = buttonObject.GetComponent<Image>();
        if (image != null)
            image.color = settingsBgColor;

        Text label = null;
        Transform labelTransform = buttonObject.transform.Find("Label");
        if (labelTransform != null)
        {
            label = labelTransform.GetComponent<Text>();
            if (label != null)
            {
                label.text = "SETTINGS";
                label.color = settingsTextColor;
            }
        }

        MenuButtonPulse pulse = buttonObject.GetComponent<MenuButtonPulse>();
        if (pulse != null)
            pulse.SetupBaseColors(settingsBgColor, label, settingsTextColor);

        Transform shutdownTransform = buttonStack.Find("Btn_ShutdownSystem");
        if (shutdownTransform != null)
        {
            shutdownTransform.SetAsLastSibling();
            buttonObject.transform.SetSiblingIndex(Mathf.Max(0, shutdownTransform.GetSiblingIndex() - 1));
        }
        else
        {
            buttonObject.transform.SetAsLastSibling();
        }
    }

    void EnsureShutdownButton()
    {
        Transform shutdownTransform = buttonStack.Find("Btn_ShutdownSystem");
        if (shutdownTransform == null) return;

        Button shutdownButton = shutdownTransform.GetComponent<Button>();
        if (shutdownButton == null) return;

        shutdownButton.onClick.RemoveAllListeners();
        shutdownButton.onClick.AddListener(Application.Quit);
    }

    void EnsureOverlay()
    {
        Transform existing = transform.Find("SensitivityOverlay");
        if (existing != null)
        {
            overlay = existing.gameObject;
            CacheControls();
            return;
        }

        Font font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");

        overlay = CreateUiObject("SensitivityOverlay", transform);
        Image overlayImage = overlay.AddComponent<Image>();
        overlayImage.color = new Color(0f, 0f, 0f, 0.68f);
        RectTransform overlayRect = overlay.GetComponent<RectTransform>();
        StretchFull(overlayRect);

        GameObject panel = CreateUiObject("Panel", overlay.transform);
        Image panelImage = panel.AddComponent<Image>();
        panelImage.color = new Color(0.93f, 0.95f, 0.98f, 0.98f);
        RectTransform panelRect = panel.GetComponent<RectTransform>();
        panelRect.anchorMin = new Vector2(0.5f, 0.5f);
        panelRect.anchorMax = new Vector2(0.5f, 0.5f);
        panelRect.pivot = new Vector2(0.5f, 0.5f);
        panelRect.sizeDelta = new Vector2(760f, 460f);

        Text title = CreateText("Title", panel.transform, font, 34, FontStyle.Bold, new Color(0.12f, 0.18f, 0.24f));
        title.text = "GAME SENSITIVITY";
        RectTransform titleRect = title.rectTransform;
        titleRect.anchorMin = new Vector2(0.5f, 1f);
        titleRect.anchorMax = new Vector2(0.5f, 1f);
        titleRect.pivot = new Vector2(0.5f, 1f);
        titleRect.anchoredPosition = new Vector2(0f, -34f);
        titleRect.sizeDelta = new Vector2(600f, 50f);

        Text subtitle = CreateText("Subtitle", panel.transform, font, 18, FontStyle.Normal, new Color(0.38f, 0.44f, 0.52f));
        subtitle.text = "Tune each mini-game separately";
        RectTransform subtitleRect = subtitle.rectTransform;
        subtitleRect.anchorMin = new Vector2(0.5f, 1f);
        subtitleRect.anchorMax = new Vector2(0.5f, 1f);
        subtitleRect.pivot = new Vector2(0.5f, 1f);
        subtitleRect.anchoredPosition = new Vector2(0f, -76f);
        subtitleRect.sizeDelta = new Vector2(600f, 30f);

        CreateSliderRow(panel.transform, font, "FallingSliderRow", "FALLING GAME", 0, out fallingSlider, out fallingValueText);
        CreateSliderRow(panel.transform, font, "PathSliderRow", "PATH FOLLOWING", 1, out pathSlider, out pathValueText);
        CreateSliderRow(panel.transform, font, "DriverSliderRow", "ENDLESS DRIVER", 2, out driverSlider, out driverValueText);

        Button saveButton = CreateActionButton(panel.transform, font, "SaveButton", "SAVE", new Color(0.20f, 0.48f, 0.75f));
        RectTransform saveRect = saveButton.GetComponent<RectTransform>();
        saveRect.anchorMin = new Vector2(0.5f, 0f);
        saveRect.anchorMax = new Vector2(0.5f, 0f);
        saveRect.pivot = new Vector2(0.5f, 0f);
        saveRect.anchoredPosition = new Vector2(-110f, 36f);
        saveRect.sizeDelta = new Vector2(180f, 54f);
        saveButton.onClick.AddListener(SaveAndClose);

        Button closeButton = CreateActionButton(panel.transform, font, "CloseButton", "CLOSE", new Color(0.45f, 0.50f, 0.58f));
        RectTransform closeRect = closeButton.GetComponent<RectTransform>();
        closeRect.anchorMin = new Vector2(0.5f, 0f);
        closeRect.anchorMax = new Vector2(0.5f, 0f);
        closeRect.pivot = new Vector2(0.5f, 0f);
        closeRect.anchoredPosition = new Vector2(110f, 36f);
        closeRect.sizeDelta = new Vector2(180f, 54f);
        closeButton.onClick.AddListener(ClosePanel);

        fallingSlider.onValueChanged.AddListener(_ => UpdateValueTexts());
        pathSlider.onValueChanged.AddListener(_ => UpdateValueTexts());
        driverSlider.onValueChanged.AddListener(_ => UpdateValueTexts());

        overlay.SetActive(false);
    }

    void CacheControls()
    {
        fallingSlider = transform.Find("SensitivityOverlay/Panel/FallingSliderRow/Slider")?.GetComponent<Slider>();
        pathSlider = transform.Find("SensitivityOverlay/Panel/PathSliderRow/Slider")?.GetComponent<Slider>();
        driverSlider = transform.Find("SensitivityOverlay/Panel/DriverSliderRow/Slider")?.GetComponent<Slider>();
        fallingValueText = transform.Find("SensitivityOverlay/Panel/FallingSliderRow/Value")?.GetComponent<Text>();
        pathValueText = transform.Find("SensitivityOverlay/Panel/PathSliderRow/Value")?.GetComponent<Text>();
        driverValueText = transform.Find("SensitivityOverlay/Panel/DriverSliderRow/Value")?.GetComponent<Text>();
    }

    void OpenPanel()
    {
        RefreshSliderValuesFromPrefs();
        UpdateValueTexts();
        if (overlay != null) overlay.SetActive(true);
    }

    void ClosePanel()
    {
        if (overlay != null) overlay.SetActive(false);
    }

    void SaveAndClose()
    {
        GameSensitivitySettings.SetFalling(fallingSlider.value);
        GameSensitivitySettings.SetPath(pathSlider.value);
        GameSensitivitySettings.SetDriver(driverSlider.value);
        GameSensitivitySettings.Save();
        ClosePanel();
    }

    void RefreshSliderValuesFromPrefs()
    {
        if (fallingSlider != null)
        {
            fallingSlider.minValue = GameSensitivitySettings.FallingMin;
            fallingSlider.maxValue = GameSensitivitySettings.FallingMax;
            fallingSlider.value = GameSensitivitySettings.GetFalling();
        }

        if (pathSlider != null)
        {
            pathSlider.minValue = GameSensitivitySettings.PathMin;
            pathSlider.maxValue = GameSensitivitySettings.PathMax;
            pathSlider.value = GameSensitivitySettings.GetPath();
        }

        if (driverSlider != null)
        {
            driverSlider.minValue = GameSensitivitySettings.DriverMin;
            driverSlider.maxValue = GameSensitivitySettings.DriverMax;
            driverSlider.value = GameSensitivitySettings.GetDriver();
        }
    }

    void UpdateValueTexts()
    {
        if (fallingValueText != null) fallingValueText.text = fallingSlider.value.ToString("0.00");
        if (pathValueText != null) pathValueText.text = pathSlider.value.ToString("0.0");
        if (driverValueText != null) driverValueText.text = driverSlider.value.ToString("0.0");
    }

    void CreateSliderRow(Transform parent, Font font, string rowName, string labelText, int rowIndex, out Slider slider, out Text valueText)
    {
        GameObject row = CreateUiObject(rowName, parent);
        RectTransform rowRect = row.GetComponent<RectTransform>();
        rowRect.anchorMin = new Vector2(0.5f, 1f);
        rowRect.anchorMax = new Vector2(0.5f, 1f);
        rowRect.pivot = new Vector2(0.5f, 1f);
        rowRect.anchoredPosition = new Vector2(0f, -140f - rowIndex * 92f);
        rowRect.sizeDelta = new Vector2(640f, 70f);

        Text label = CreateText("Label", row.transform, font, 24, FontStyle.Bold, new Color(0.15f, 0.20f, 0.28f));
        label.text = labelText;
        RectTransform labelRect = label.rectTransform;
        labelRect.anchorMin = new Vector2(0f, 0.5f);
        labelRect.anchorMax = new Vector2(0f, 0.5f);
        labelRect.pivot = new Vector2(0f, 0.5f);
        labelRect.anchoredPosition = new Vector2(0f, 0f);
        labelRect.sizeDelta = new Vector2(220f, 40f);

        valueText = CreateText("Value", row.transform, font, 22, FontStyle.Bold, new Color(0.20f, 0.48f, 0.75f));
        RectTransform valueRect = valueText.rectTransform;
        valueRect.anchorMin = new Vector2(1f, 0.5f);
        valueRect.anchorMax = new Vector2(1f, 0.5f);
        valueRect.pivot = new Vector2(1f, 0.5f);
        valueRect.anchoredPosition = new Vector2(0f, 0f);
        valueRect.sizeDelta = new Vector2(90f, 40f);

        slider = CreateSlider(row.transform, new Vector2(250f, 0f), new Vector2(300f, 24f));
    }

    Slider CreateSlider(Transform parent, Vector2 anchoredPosition, Vector2 size)
    {
        GameObject sliderObject = CreateUiObject("Slider", parent);
        RectTransform sliderRect = sliderObject.GetComponent<RectTransform>();
        sliderRect.anchorMin = new Vector2(0f, 0.5f);
        sliderRect.anchorMax = new Vector2(0f, 0.5f);
        sliderRect.pivot = new Vector2(0f, 0.5f);
        sliderRect.anchoredPosition = anchoredPosition;
        sliderRect.sizeDelta = size;

        Image background = sliderObject.AddComponent<Image>();
        background.color = new Color(0.80f, 0.84f, 0.88f, 1f);

        Slider slider = sliderObject.AddComponent<Slider>();
        slider.direction = Slider.Direction.LeftToRight;

        GameObject fillArea = CreateUiObject("Fill Area", sliderObject.transform);
        RectTransform fillAreaRect = fillArea.GetComponent<RectTransform>();
        fillAreaRect.anchorMin = new Vector2(0f, 0.25f);
        fillAreaRect.anchorMax = new Vector2(1f, 0.75f);
        fillAreaRect.offsetMin = new Vector2(0f, 0f);
        fillAreaRect.offsetMax = new Vector2(0f, 0f);

        GameObject fill = CreateUiObject("Fill", fillArea.transform);
        Image fillImage = fill.AddComponent<Image>();
        fillImage.color = new Color(0.20f, 0.48f, 0.75f, 1f);
        RectTransform fillRect = fill.GetComponent<RectTransform>();
        fillRect.anchorMin = new Vector2(0f, 0f);
        fillRect.anchorMax = new Vector2(1f, 1f);
        fillRect.offsetMin = Vector2.zero;
        fillRect.offsetMax = Vector2.zero;

        GameObject handleSlideArea = CreateUiObject("Handle Slide Area", sliderObject.transform);
        RectTransform handleAreaRect = handleSlideArea.GetComponent<RectTransform>();
        handleAreaRect.anchorMin = new Vector2(0f, 0f);
        handleAreaRect.anchorMax = new Vector2(1f, 1f);
        handleAreaRect.offsetMin = new Vector2(0f, 0f);
        handleAreaRect.offsetMax = new Vector2(0f, 0f);

        GameObject handle = CreateUiObject("Handle", handleSlideArea.transform);
        Image handleImage = handle.AddComponent<Image>();
        handleImage.color = Color.white;
        RectTransform handleRect = handle.GetComponent<RectTransform>();
        handleRect.sizeDelta = new Vector2(24f, 36f);

        slider.fillRect = fillRect;
        slider.handleRect = handleRect;
        slider.targetGraphic = handleImage;
        slider.minValue = 0f;
        slider.maxValue = 1f;

        return slider;
    }

    Button CreateActionButton(Transform parent, Font font, string objectName, string labelText, Color color)
    {
        GameObject buttonObject = CreateUiObject(objectName, parent);
        Image image = buttonObject.AddComponent<Image>();
        image.color = color;
        Button button = buttonObject.AddComponent<Button>();

        Text label = CreateText("Label", buttonObject.transform, font, 24, FontStyle.Bold, Color.white);
        label.text = labelText;
        RectTransform labelRect = label.rectTransform;
        StretchFull(labelRect);

        return button;
    }

    Text CreateText(string objectName, Transform parent, Font font, int fontSize, FontStyle fontStyle, Color color)
    {
        GameObject textObject = CreateUiObject(objectName, parent);
        Text text = textObject.AddComponent<Text>();
        text.font = font;
        text.fontSize = fontSize;
        text.fontStyle = fontStyle;
        text.alignment = TextAnchor.MiddleCenter;
        text.color = color;
        return text;
    }

    GameObject CreateUiObject(string objectName, Transform parent)
    {
        GameObject go = new GameObject(objectName, typeof(RectTransform));
        go.transform.SetParent(parent, false);
        return go;
    }

    static void StretchFull(RectTransform rect)
    {
        rect.anchorMin = Vector2.zero;
        rect.anchorMax = Vector2.one;
        rect.offsetMin = Vector2.zero;
        rect.offsetMax = Vector2.zero;
    }
}
