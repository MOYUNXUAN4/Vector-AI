using UnityEngine;
using UnityEngine.SceneManagement;

public class InfiniteFallGameController : MonoBehaviour
{
    private enum GameState
    {
        Running,
        GameOver
    }

    [Header("Scene Routing")]
    [SerializeField] private string menuSceneName = "FypHub";

    [Header("References")]
    [SerializeField] private InfiniteFallConfig config;
    [SerializeField] private Transform ball;
    [SerializeField] private Transform platformPrefab;
    [SerializeField] private Camera gameplayCamera;

    private InfiniteFallBallMotor _ballMotor;
    private InfiniteFallPlatformManager _platformManager;
    private InfiniteFallCameraFollow _cameraFollow;
    private InfiniteFallUIController _uiController;

    private Transform _spawnRoot;
    private GameState _state;
    private bool _ready;
    private int _score;
    private int _depth;

    private void Awake()
    {
        ResolveReferences();
        if (!_ready) return;

        _ballMotor = GetOrAdd<InfiniteFallBallMotor>(ball.gameObject);
        _platformManager = GetOrAdd<InfiniteFallPlatformManager>(gameObject);
        _cameraFollow = GetOrAdd<InfiniteFallCameraFollow>(gameObject);
        _uiController = GetOrAdd<InfiniteFallUIController>(gameObject);

        _ballMotor.Initialize(config);
        _platformManager.Initialize(config, platformPrefab, _spawnRoot);
        _cameraFollow.Initialize(gameplayCamera, ball, config);
        _uiController.Initialize(transform, ExitToMenu, RestartGame);

        RestartGame();
    }

    private void Update()
    {
        if (!_ready) return;

        if (_state == GameState.Running)
        {
            _platformManager.Tick(_ballMotor.Position.y);
            _score += _platformManager.ConsumePendingScore();
            _depth = _platformManager.GetDepth(_ballMotor.Position.y);

            bool outsideSupport = !_platformManager.IsInsideSupport(_ballMotor.Position, _ballMotor.WorldRadius);
            if (outsideSupport && _ballMotor.Position.y < _cameraFollow.VisualY - config.gameOverDropDistance)
            {
                _state = GameState.GameOver;
            }
        }

        _platformManager.ApplyTilt(_ballMotor.CurrentTilt);
        _cameraFollow.Tick(Time.deltaTime, _state == GameState.GameOver);
        _uiController.Refresh(_depth, _score, _state == GameState.GameOver);

        if (_state == GameState.GameOver && IsPrimaryClickDown())
            RestartGame();
    }

    private void FixedUpdate()
    {
        if (!_ready || _state != GameState.Running) return;
        _ballMotor.TickInput(Time.fixedDeltaTime);

        Vector3 pos = _ballMotor.Position;
        Vector3 vel = _ballMotor.Velocity;
        if (_platformManager.ResolveBallPenetration(ref pos, ref vel, _ballMotor.WorldRadius))
        {
            _ballMotor.SetState(pos, vel);
        }
    }

    public void RestartGame()
    {
        if (!_ready) return;
        _state = GameState.Running;
        _score = 0;
        _depth = 0;
        _platformManager.ResetPlatforms();
        Vector3 spawn = new Vector3(config.holeRadius + config.ballRadius + 0.7f, 2f, 0f);
        _ballMotor.Respawn(spawn);
    }

    public void ExitToMenu()
    {
        if (string.IsNullOrWhiteSpace(menuSceneName)) return;
        SceneManager.LoadScene(menuSceneName, LoadSceneMode.Single);
    }

    private void ResolveReferences()
    {
        if (config == null)
            config = ScriptableObject.CreateInstance<InfiniteFallConfig>();

        if (ball == null)
        {
            GameObject ballGo = FindSceneObjectByName("PF_Ball");
            if (ballGo == null) ballGo = FindSceneObjectByTag("Player");
            if (ballGo != null) ball = ballGo.transform;
            if (ball == null)
            {
                GameObject fallbackBall = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                fallbackBall.name = "PF_Ball";
                ball = fallbackBall.transform;
                ball.SetParent(transform, false);
                ball.localPosition = new Vector3(1.8f, 2f, 0f);
                Debug.LogWarning("[InfiniteFallGameController] PF_Ball not found. Created a temporary sphere.");
            }
        }

        if (platformPrefab == null)
        {
            GameObject template = FindSceneObjectByName("PF_PlatformRing");
            if (template != null)
            {
                platformPrefab = template.transform;
                template.SetActive(false);
            }
            else
            {
                GameObject fallbackPlatform = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                fallbackPlatform.name = "PF_PlatformRing";
                fallbackPlatform.transform.SetParent(transform, false);
                fallbackPlatform.transform.localScale = new Vector3(config.platformRadius * 2f, config.layerThickness * 0.5f, config.platformRadius * 2f);
                platformPrefab = fallbackPlatform.transform;
                fallbackPlatform.SetActive(false);
                Debug.LogWarning("[InfiniteFallGameController] PF_PlatformRing not found. Created a temporary cylinder platform template.");
            }
        }

        if (gameplayCamera == null)
        {
            gameplayCamera = Camera.main;
            if (gameplayCamera == null)
            {
                GameObject camGo = new GameObject("InfiniteFallCamera");
                gameplayCamera = camGo.AddComponent<Camera>();
            }
            gameplayCamera.clearFlags = CameraClearFlags.Skybox;
            gameplayCamera.tag = "MainCamera";
        }

        Transform found = transform.Find("SpawnRoot");
        if (found == null)
        {
            GameObject spawnRootGo = new GameObject("SpawnRoot");
            spawnRootGo.transform.SetParent(transform, false);
            _spawnRoot = spawnRootGo.transform;
        }
        else
        {
            _spawnRoot = found;
        }

        _ready = ball != null && platformPrefab != null && gameplayCamera != null;
        if (!_ready)
            Debug.LogError("[InfiniteFallGameController] Missing critical references: ball/platformPrefab/camera.");
    }

    private static T GetOrAdd<T>(GameObject go) where T : Component
    {
        T comp = go.GetComponent<T>();
        if (comp == null) comp = go.AddComponent<T>();
        return comp;
    }

    private GameObject FindSceneObjectByName(string objectName)
    {
        Transform[] all = Resources.FindObjectsOfTypeAll<Transform>();
        for (int i = 0; i < all.Length; i++)
        {
            Transform t = all[i];
            if (t == null || t.name != objectName) continue;
            if (!t.gameObject.scene.IsValid()) continue;
            if (t.gameObject.scene != gameObject.scene) continue;
            return t.gameObject;
        }
        return null;
    }

    private GameObject FindSceneObjectByTag(string tag)
    {
        Transform[] all = Resources.FindObjectsOfTypeAll<Transform>();
        for (int i = 0; i < all.Length; i++)
        {
            Transform t = all[i];
            if (t == null) continue;
            if (!t.gameObject.scene.IsValid()) continue;
            if (t.gameObject.scene != gameObject.scene) continue;
            if (t.CompareTag(tag)) return t.gameObject;
        }
        return null;
    }

    private static bool IsPrimaryClickDown()
    {
        if (Input.GetMouseButtonDown(0)) return true;
        return Input.touchCount > 0 && Input.GetTouch(0).phase == TouchPhase.Began;
    }
}
