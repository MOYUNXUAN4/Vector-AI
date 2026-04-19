using UnityEngine;
using TMPro;
using System.Collections;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using UnityEngine.EventSystems;

public class UIHandler : MonoBehaviour
{
    [Header("UI 文本")]
    [SerializeField] private TextMeshProUGUI distanceTravelledText;
    [SerializeField] private TextMeshProUGUI gameOverText;

    [Header("UI 面板 (需挂载 CanvasGroup)")]
    [SerializeField] private CanvasGroup gameOverCanvasGroup;
    [SerializeField] private RectTransform gameOverClickArea;
    [SerializeField] private Button restartButton;

    [Header("自定义设置")]
    [Tooltip("游戏结束面板最终的透明度")]
    [Range(0f, 1f)] 
    [SerializeField] private float maxAlpha = 0.8f; // 在 Inspector 里可以直接调

    [Tooltip("撞车后延迟多久显示菜单")]
    [Range(0f, 5f)]
    [SerializeField] private float showDelay = 2.0f; // 滑块控制延迟秒数

    [Header("引用")]
    [SerializeField] private CarHandler carHandler; 

    private int _lastValue = -1;
    private bool _isGameOver = false;
    private bool _canRestart = false;

    void Awake()
    {
        EnsureEventSystemExists();

        // 自动寻找 Player
        if (carHandler == null)
        {
            GameObject player = GameObject.FindGameObjectWithTag("Player");
            if (player != null) carHandler = player.GetComponent<CarHandler>();
        }

        // 订阅撞车事件
        if (carHandler != null)
        {
            carHandler.OnPlayerCrashed += PlayerCarHandler_OnPlayerCrashed;
        }

        // 初始化：强制隐藏面板
        if (gameOverCanvasGroup != null)
        {
            gameOverCanvasGroup.alpha = 0;
            gameOverCanvasGroup.interactable = false;
            gameOverCanvasGroup.blocksRaycasts = false;

            // 没有手动指定时，默认用 GameOver 面板 Rect 作为点击区域
            if (gameOverClickArea == null)
            {
                gameOverClickArea = gameOverCanvasGroup.GetComponent<RectTransform>();
            }
        }

        // 避免 Inspector 没绑 onClick 导致按钮失效，启动时自动绑定
        if (restartButton == null && gameOverCanvasGroup != null)
        {
            restartButton = gameOverCanvasGroup.GetComponentInChildren<Button>(true);
        }

        if (restartButton != null)
        {
            restartButton.onClick.RemoveListener(OnRestartClicked);
            restartButton.onClick.AddListener(OnRestartClicked);
        }
    }

    void Update()
    {
        if (_isGameOver)
        {
            if (_canRestart && IsClickOnGameOverArea())
            {
                OnRestartClicked();
            }
            return;
        }

        if (carHandler == null || distanceTravelledText == null) return;

        int currentDist = Mathf.FloorToInt(carHandler.DistanceTravelled);
        if (currentDist != _lastValue)
        {
            _lastValue = currentDist;
            distanceTravelledText.text = currentDist.ToString("000000");
        }
    }

    private void PlayerCarHandler_OnPlayerCrashed(CarHandler obj)
    {
        if (_isGameOver) return;
        _isGameOver = true;

        if (gameOverText != null)
        {
            gameOverText.text = $"DISTANCE: {distanceTravelledText.text}";
        }

        // 执行带延迟的显示协程
        StartCoroutine(StartGameOverAnimationCO());
    }

    IEnumerator StartGameOverAnimationCO()
    {
        // --- 核心修复：使用滑块设置的延迟时间 ---
        yield return new WaitForSecondsRealtime(showDelay);

        gameOverCanvasGroup.interactable = true;
        gameOverCanvasGroup.blocksRaycasts = true;

        // 渐显到指定的 maxAlpha
        while (gameOverCanvasGroup.alpha < maxAlpha)
        {
            // 这里的 3f 是渐变速度，可以根据喜好调整
            gameOverCanvasGroup.alpha = Mathf.MoveTowards(gameOverCanvasGroup.alpha, maxAlpha, Time.unscaledDeltaTime * 3f);
            yield return null;
        }

        _canRestart = true;
    }

    public void OnRestartClicked()
    {
        if (!_isGameOver) return;

        Time.timeScale = 1.0f; 
        SceneManager.LoadScene(SceneManager.GetActiveScene().name);
    }

    private bool IsClickOnGameOverArea()
    {
        if (gameOverClickArea == null) return false;

        if (!IsPointerPressedDown()) return false;

        return RectTransformUtility.RectangleContainsScreenPoint(gameOverClickArea, Input.mousePosition, null);
    }

    private bool IsPointerPressedDown()
    {
        if (Input.GetMouseButtonDown(0)) return true;
        if (Input.touchCount > 0 && Input.GetTouch(0).phase == TouchPhase.Began) return true;
        return false;
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
        {
            carHandler.OnPlayerCrashed -= PlayerCarHandler_OnPlayerCrashed;
        }
    }
}