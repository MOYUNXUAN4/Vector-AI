using System.Collections;
using UnityEngine;

public class AICarSpawner : MonoBehaviour
{
    [Header("🎯 SMART 核心输入")]
    [Range(0, 100)] public float playerCopJitter = 50f;
    [Tooltip("灵敏度：决定难度跟随摇晃度变化的快慢")]
    public float transitionSpeed = 3f;

    [Header("⌨️ WASD 体感模拟算法 (真实单位时间抖动)")]
    public bool enableKeyboardTest = true;
    [Tooltip("键盘灵敏度：按键切换时的抖动增加量")]
    public float wobbleSensitivity = 80f;
    [Tooltip("抖动衰减率：如果不晃了，每秒钟下降的数值")]
    public float wobbleDecayRate = 40f;

    // 内部算法变量
    private float lastInput = 0f;
    private float rawAccumulatedJitter = 0f;

    [Header("🛡️ 保护期 (秒)")]
    public float warmUpDuration = 5f;
    private bool isWarmUp = true;
    private float gameStartTime;

    [Header("⏱️ 动态频率 (控制有多密)")]
    public float minCooldown = 0.4f; // 极稳时：疯狗模式
    public float maxCooldown = 3.5f; // 极晃时：散步模式
    [SerializeField] private float currentSpawnCooldown = 1.5f;

    [Header("🏎️ 动态车速 (已整体调慢)")]
    [Tooltip("极稳(困难)时的最快车速")]
    public float maxTrafficSpeed = 20f; // 【修改点】从35降到了20
    [Tooltip("极晃(简单)时的最慢车速")]
    public float minTrafficSpeed = 5f;  // 【修改点】从10降到了5
    [SerializeField] private float currentTrafficSpeed = 10f;

    [Header("🛣️ 车道坐标 (确保面板里填了4个不一样的数)")]
    public float[] lanePositionsX = new float[] { -1.5f, -0.5f, 0.5f, 1.5f };

    [Header("🚗 对象池与物理设置")]
    public int maxCarsInPool = 40;
    [SerializeField] GameObject[] carAIPrefabs;
    [SerializeField] LayerMask otherCarsLayerMask;

    private GameObject[] carAIPool;
    private Transform playerCarTransform;
    private float timeLastCarSpawned = 0;

    void Start()
    {
        playerCarTransform = GameObject.FindGameObjectWithTag("Player").transform;
        gameStartTime = Time.time;
        InitPool();
        StartCoroutine(SpawnLoop());
    }

    void InitPool()
    {
        carAIPool = new GameObject[maxCarsInPool];
        for (int i = 0; i < maxCarsInPool; i++)
        {
            carAIPool[i] = Instantiate(carAIPrefabs[i % carAIPrefabs.Length]);
            carAIPool[i].SetActive(false);
        }
    }

    void Update()
    {
        // ==========================================
        // 0. 体感抖动积分算法 (仅计算单位时间的"变化量")
        // ==========================================
        if (enableKeyboardTest)
        {
            float currentInput = Input.GetAxis("Horizontal");

            // 核心算法：只计算“输入差值”。长按不动差值为0，疯狂按A和D差值极大
            float inputDelta = Mathf.Abs(currentInput - lastInput);
            lastInput = currentInput;

            // 每侦累加抖动值
            rawAccumulatedJitter += inputDelta * wobbleSensitivity;

            // 随时间自然衰减（模拟人慢慢站稳的过程）
            rawAccumulatedJitter -= wobbleDecayRate * Time.deltaTime;

            // 严格限制在 0 - 100 之间
            rawAccumulatedJitter = Mathf.Clamp(rawAccumulatedJitter, 0f, 100f);

            // 平滑赋值给面板上的最终摇晃度
            playerCopJitter = Mathf.Lerp(playerCopJitter, rawAccumulatedJitter, Time.deltaTime * 5f);
        }

        // ==========================================
        // 1. 无级变速核心逻辑
        // ==========================================
        float targetCooldown;
        float targetSpeed;

        if (isWarmUp && Time.time - gameStartTime < warmUpDuration)
        {
            targetCooldown = 1.5f;
            targetSpeed = minTrafficSpeed;
        }
        else
        {
            isWarmUp = false;

            float t = playerCopJitter / 100f;
            targetCooldown = Mathf.Lerp(minCooldown, maxCooldown, t);
            targetSpeed = Mathf.Lerp(maxTrafficSpeed, minTrafficSpeed, t);
        }

        // ==========================================
        // 2. 平滑追赶目标数值
        // ==========================================
        currentSpawnCooldown = Mathf.Lerp(currentSpawnCooldown, targetCooldown, Time.deltaTime * transitionSpeed);
        currentTrafficSpeed = Mathf.Lerp(currentTrafficSpeed, targetSpeed, Time.deltaTime * transitionSpeed);

        // ==========================================
        // 3. 驱动存活车辆向前开
        // ==========================================
        foreach (GameObject aiCar in carAIPool)
        {
            if (aiCar.activeInHierarchy)
                aiCar.transform.Translate(Vector3.forward * currentTrafficSpeed * Time.deltaTime);
        }
    }

    IEnumerator SpawnLoop()
    {
        while (true)
        {
            if (Time.time - timeLastCarSpawned > currentSpawnCooldown)
            {
                SpawnCar();
                timeLastCarSpawned = Time.time;
            }
            CleanUp();
            yield return new WaitForSeconds(0.1f);
        }
    }

    void SpawnCar()
    {
        GameObject car = GetPooledCar();
        if (car == null) return;

        if (lanePositionsX.Length == 0) return;
        float spawnX = lanePositionsX[Random.Range(0, lanePositionsX.Length)];

        Vector3 pos = new Vector3(spawnX, 0, playerCarTransform.position.z + 100);

        if (Physics.OverlapBox(pos, new Vector3(0.8f, 1f, 4f), Quaternion.identity, otherCarsLayerMask).Length > 0) return;

        ResetCarPhysics(car);
        car.transform.position = pos;
        car.transform.rotation = Quaternion.identity;
        car.SetActive(true);
    }

    void ResetCarPhysics(GameObject car)
    {
        Rigidbody rb = car.GetComponent<Rigidbody>();
        if (rb) { rb.linearVelocity = Vector3.zero; rb.angularVelocity = Vector3.zero; }
    }

    GameObject GetPooledCar()
    {
        foreach (var c in carAIPool) if (!c.activeInHierarchy) return c;
        return null;
    }

    void CleanUp()
    {
        foreach (var c in carAIPool)
        {
            if (c.activeInHierarchy && (c.transform.position.z - playerCarTransform.position.z > 200 || c.transform.position.z - playerCarTransform.position.z < -20))
                c.SetActive(false);
        }
    }
}