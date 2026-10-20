using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class AICarSpawner : MonoBehaviour
{
    [Header("🧠 AI 后端控制输入")]
    [Tooltip("接收来自 Python 后端的难度等级 (1:最简单 -> 5:最困难)")]
    [Range(1, 5)] public int currentDifficultyLevel = 1; 

    [Header("🎯 SMART 核心输入 (发给后端)")]
    [Range(0, 100)] public float playerCopJitter = 0f;
    public float transitionSpeed = 3f;

    [Header("🚶‍♂️ 真实躲避 vs 摇晃判定 (核心算法)")]
    public float unstableDistanceThreshold = 0.9f; 
    public float unstablePenaltyMultiplier = 40f;
    public float normalDodgePenalty = 2f;
    public float wobbleDecayRate = 20f;

    private float rawAccumulatedJitter = 0f;
    private float lastPlayerX = 0f;
    private float currentStrokeDistance = 0f;
    private float lastMoveDirection = 0f;
    private float stopTimer = 0f;

    [Header("⏱️ 动态频率（单次波次的冷却时间）")]
    public float minCooldown = 0.8f; 
    public float maxCooldown = 3.5f; 
    [SerializeField] private float currentSpawnCooldown = 1.5f;

    [Header("🏎️ 动态车速")]
    public float maxTrafficSpeed = 18f; 
    public float minTrafficSpeed = 6f;  
    [SerializeField] private float currentTrafficSpeed = 10f;

    [Header("路况视觉缩短")]
    public float spawnAheadDistance = 20f; 

    [Header("🛣️ 车道坐标 (4个独立车道)")]
    public float[] lanePositionsX = new float[] { -1.5f, -0.5f, 0.5f, 1.5f };

    [Header("🚗 对象池与物理设置")]
    [Tooltip("初始车辆数。如果不够用会自动造新车扩容！")]
    public int maxCarsInPool = 40;
    [SerializeField] private int maxActiveCars = 15;
    [SerializeField] private float minSpawnZSpacing = 24f;
    [SerializeField] GameObject[] carAIPrefabs;
    [SerializeField] LayerMask otherCarsLayerMask;

    // 【核心修复 1：把定长数组变成可无限扩容的动态列表 List】
    private List<GameObject> carAIPool = new List<GameObject>();
    private Transform playerCarTransform;
    private float timeLastCarSpawned = 0;

    void Start()
    {
        playerCarTransform = GameObject.FindGameObjectWithTag("Player").transform;
        lastPlayerX = playerCarTransform.position.x;

        currentDifficultyLevel = 1;
        currentSpawnCooldown = maxCooldown;  
        currentTrafficSpeed = minTrafficSpeed; 
        timeLastCarSpawned = Time.time + 3f; 

        // 【防御性检测】：防止 Inspector 面板里的车道数据不对
        if (lanePositionsX.Length < 3)
        {
            Debug.LogError("🚨 严重警告：Inspector 面板里的 Lane Positions X 数组长度少于3！无法生成并排车墙！");
        }

        InitPool();
        StartCoroutine(SpawnLoop());
    }

    void InitPool()
    {
        for (int i = 0; i < maxCarsInPool; i++)
        {
            AddCarToPool(i);
        }
    }

    // 【核心修复 2：造车工厂方法】
    GameObject AddCarToPool(int index)
    {
        GameObject car = Instantiate(carAIPrefabs[index % carAIPrefabs.Length]);
        car.SetActive(false);
        carAIPool.Add(car);
        return car;
    }

    public void SetDifficultyFromBackend(int backendDifficulty)
    {
        currentDifficultyLevel = Mathf.Clamp(backendDifficulty, 1, 5);
    }

    void Update()
    {
        float currentPlayerX = playerCarTransform.position.x;
        float deltaX = currentPlayerX - lastPlayerX;

        if (Mathf.Abs(deltaX) > 0.001f)
        {
            stopTimer = 0f; 
            float currentDir = Mathf.Sign(deltaX);

            if (currentDir == lastMoveDirection || lastMoveDirection == 0f)
                currentStrokeDistance += Mathf.Abs(deltaX);
            else
            {
                EvaluateMovementStroke(currentStrokeDistance);
                currentStrokeDistance = Mathf.Abs(deltaX); 
            }
            lastMoveDirection = currentDir;
        }
        else
        {
            stopTimer += Time.deltaTime;
            if (stopTimer > 0.1f && currentStrokeDistance > 0f)
            {
                EvaluateMovementStroke(currentStrokeDistance);
                currentStrokeDistance = 0f;
                lastMoveDirection = 0f; 
            }
        }
        lastPlayerX = currentPlayerX;

        rawAccumulatedJitter -= wobbleDecayRate * Time.deltaTime;
        rawAccumulatedJitter = Mathf.Clamp(rawAccumulatedJitter, 0f, 100f);
        playerCopJitter = Mathf.Lerp(playerCopJitter, rawAccumulatedJitter, Time.deltaTime * 5f);

        float t = (currentDifficultyLevel - 1f) / 4f; 
        float targetCooldown = Mathf.Lerp(maxCooldown, minCooldown, t);
        float targetSpeed = Mathf.Lerp(minTrafficSpeed, maxTrafficSpeed, t);

        currentSpawnCooldown = Mathf.Lerp(currentSpawnCooldown, targetCooldown, Time.deltaTime * transitionSpeed);
        currentTrafficSpeed = Mathf.Lerp(currentTrafficSpeed, targetSpeed, Time.deltaTime * transitionSpeed);

        foreach (GameObject aiCar in carAIPool)
        {
            if (aiCar.activeInHierarchy)
                aiCar.transform.Translate(Vector3.forward * currentTrafficSpeed * Time.deltaTime);
        }
    }

    void EvaluateMovementStroke(float distance)
    {
        if (distance < 0.1f) return; 

        if (distance > unstableDistanceThreshold)
        {
            float excess = distance - unstableDistanceThreshold;
            float penalty = excess * unstablePenaltyMultiplier; 
            rawAccumulatedJitter += penalty;
            Debug.Log($"<color=orange>🚨 Movement destabilized! Crossed {distance:F2}. (Jitter +{penalty:F1})</color>");
        }
        else
        {
            rawAccumulatedJitter += normalDodgePenalty;
        }
    }

    IEnumerator SpawnLoop()
    {
        while (true)
        {
            if (Time.time - timeLastCarSpawned > currentSpawnCooldown)
            {
                SpawnCarWaveBasedOnDifficulty();
                timeLastCarSpawned = Time.time;
            }
            CleanUp();
            yield return new WaitForSeconds(0.05f);
        }
    }

    void SpawnCarWaveBasedOnDifficulty()
    {
        if (lanePositionsX.Length == 0) return;

        int carsToSpawn = GetCarsToSpawnForCurrentDifficulty();
        int remainingActiveSlots = maxActiveCars - GetActiveCarCount();
        if (remainingActiveSlots <= 0) return;

        carsToSpawn = Mathf.Min(carsToSpawn, remainingActiveSlots);
        List<float> availableLanes = new List<float>(lanePositionsX);

        for (int i = 0; i < carsToSpawn; i++)
        {
            if (availableLanes.Count == 0) break;

            GameObject car = GetPooledCar();
            if (car == null) break;
            
            int randIndex = Random.Range(0, availableLanes.Count);
            float spawnX = availableLanes[randIndex];
            availableLanes.RemoveAt(randIndex); 

            float zOffset = carsToSpawn > 1 ? (((carsToSpawn - 1) * 0.5f) - i) * minSpawnZSpacing : 0f;
            float spawnZ = playerCarTransform.position.z + spawnAheadDistance + zOffset;
            if (!CanSpawnAtPosition(spawnX, spawnZ))
            {
                car.SetActive(false);
                continue;
            }

            Vector3 spawnPos = new Vector3(spawnX, 0, spawnZ);

            ResetCarPhysics(car);
            car.transform.position = spawnPos;
            car.transform.rotation = Quaternion.identity;
            car.SetActive(true);
        }
    }

    int GetCarsToSpawnForCurrentDifficulty()
    {
        switch (currentDifficultyLevel)
        {
            case 3:
                return Random.value < 0.3f ? 2 : 1;
            case 4:
                return Random.value < 0.4f ? 2 : 1;
            case 5:
                return Random.value < 0.25f ? 2 : 1;
            default:
                return 1;
        }
    }

    bool CanSpawnAtPosition(float spawnX, float spawnZ)
    {
        foreach (var c in carAIPool)
        {
            if (!c.activeInHierarchy) continue;
            if (!Mathf.Approximately(c.transform.position.x, spawnX)) continue;
            if (Mathf.Abs(c.transform.position.z - spawnZ) < minSpawnZSpacing)
                return false;
        }

        return true;
    }

    int GetActiveCarCount()
    {
        int activeCount = 0;

        foreach (var c in carAIPool)
        {
            if (c.activeInHierarchy)
                activeCount++;
        }

        return activeCount;
    }

    void ResetCarPhysics(GameObject car)
    {
        Rigidbody rb = car.GetComponent<Rigidbody>();
        if (rb) { rb.linearVelocity = Vector3.zero; rb.angularVelocity = Vector3.zero; }
    }

    // 【核心修复 3：智能对象池获取机制】
    GameObject GetPooledCar()
    {
        foreach (var c in carAIPool) 
        {
            if (!c.activeInHierarchy) return c;
        }

        Debug.LogWarning($"<color=yellow>🚗 对象池已满 ({carAIPool.Count} / {maxCarsInPool})，本波跳过生成。</color>");
        return null;
    }

    void CleanUp()
    {
        foreach (var c in carAIPool)
        {
            if (c.activeInHierarchy && (c.transform.position.z - playerCarTransform.position.z > 120 || c.transform.position.z - playerCarTransform.position.z < -15))
                c.SetActive(false);
        }
    }
}