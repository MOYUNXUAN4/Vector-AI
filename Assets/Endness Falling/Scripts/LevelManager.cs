using UnityEngine;
using System.Collections.Generic;

public class LevelManager : MonoBehaviour
{
    private const int MaxDifficultyLevel = 5;

    [Header("Platform Settings")]
    public GameObject[] platformPrefabs; 
    public int platformCount = 6;      
    public float verticalGap = 10f;    

    [Header("References")]
    public Transform player;

    [Header("Progression Settings")]
    public int currentLevel = 1;         // 当前 Level (1-5)
    public int platformsPerLevel = 10;   // 每 10 层升一级
    private int platformsPassed = 0;     // 总计通过层数

    [Header("Difficulty Tuning (Array Size 5)")]
    public float[] scaleByDifficulty = { 1.2f, 1.0f, 0.85f, 0.7f, 0.6f };
    public float[] deathRadiusByLevel = { 10.3f, 8.6f, 7.3f, 6.0f, 5.2f };

    private List<GameObject> activePlatforms = new List<GameObject>(); 
    private float nextSpawnY = 0f;
    private float lastHoleAngle = 0f; 
    private bool stageCompleted = false;

    void Start()
    {
        EnsureVisualTheme();
        for (int i = 0; i < platformCount; i++)
        {
            SpawnPlatform(true); 
        }
    }

    void Update()
    {
        if (stageCompleted) return;
        if (player == null || activePlatforms.Count == 0) return;
        
        // 当球掉过平台中点，回收并复用
        if (player.position.y < activePlatforms[0].transform.position.y - (verticalGap * 0.5f))
        {
            RecyclePlatform();
        }
    }

    void SpawnPlatform(bool isInitialSpawn)
    {
        int randomIndex = Random.Range(0, platformPrefabs.Length);
        GameObject newPlatform = Instantiate(platformPrefabs[randomIndex], new Vector3(0, nextSpawnY, 0), platformPrefabs[randomIndex].transform.rotation);
        
        ApplyDifficultyToPlatform(newPlatform);
        activePlatforms.Add(newPlatform);
        nextSpawnY -= verticalGap;
    }

    void RecyclePlatform()
    {
        if (stageCompleted) return;
        platformsPassed++;
        
        // 自动升级逻辑
        if (platformsPassed % platformsPerLevel == 0)
        {
            currentLevel++;
            if (currentLevel > MaxDifficultyLevel)
            {
                stageCompleted = true;
                EndlessPlayerController ctrl = FindObjectOfType<EndlessPlayerController>();
                if(ctrl != null) ctrl.TriggerWin();
                return;
            }
        }

        GameObject recycledPlatform = activePlatforms[0];
        activePlatforms.RemoveAt(0);

        recycledPlatform.transform.position = new Vector3(0, nextSpawnY, 0);
        recycledPlatform.transform.rotation = platformPrefabs[0].transform.rotation;

        ApplyDifficultyToPlatform(recycledPlatform);

        activePlatforms.Add(recycledPlatform);
        nextSpawnY -= verticalGap;
    }

    void ApplyDifficultyToPlatform(GameObject platform)
    {
        int idx = Mathf.Clamp(currentLevel - 1, 0, Mathf.Min(scaleByDifficulty.Length, deathRadiusByLevel.Length) - 1);
        float currentScale = scaleByDifficulty[idx];
        platform.transform.localScale = new Vector3(currentScale, currentScale, currentScale);

        float newAngle = GetSmartHoleAngle(idx + 1);
        platform.transform.Rotate(Vector3.up, newAngle, Space.World);
        lastHoleAngle = newAngle;
    }

    float GetSmartHoleAngle(int level)
    {
        float offset = 0f;
        float sign = Random.value > 0.5f ? 1f : -1f; 

        switch (level)
        {
            case 1: offset = Random.value > 0.2f ? Random.Range(20f, 40f) : Random.Range(100f, 120f); break;
            case 2: offset = Random.value > 0.4f ? Random.Range(30f, 60f) : Random.Range(120f, 150f); break;
            case 3: offset = Random.Range(80f, 150f); break;
            case 4: offset = Random.Range(130f, 170f); break;
            case 5: offset = Random.Range(160f, 180f); break;
        }
        return lastHoleAngle + (offset * sign);
    }

    // --- 给外部脚本调用的公共接口 ---

    public float GetCurrentDeathRadius()
    {
        int idx = Mathf.Clamp(currentLevel - 1, 0, deathRadiusByLevel.Length - 1);
        return deathRadiusByLevel[idx];
    }
    
    public int GetPassedCount() { return platformsPassed; }

    public int GetCurrentLayer()
    {
        // Layers are 1-based for UI display.
        return platformsPassed + 1;
    }

    // 【核心修复点】
    public int GetRemainingInPart()
    {
        if (currentLevel >= MaxDifficultyLevel) return 0;
        return platformsPerLevel - (platformsPassed % platformsPerLevel);
    }
    
    public float GetCurrentPlatformScale()
    {
        int idx = Mathf.Clamp(currentLevel - 1, 0, scaleByDifficulty.Length - 1);
        return scaleByDifficulty[idx];
    }

    void EnsureVisualTheme()
    {
        EndlessVisualTheme theme = FindObjectOfType<EndlessVisualTheme>();
        if (theme != null) return;
        GameObject go = new GameObject("EndlessVisualTheme");
        go.AddComponent<EndlessVisualTheme>();
    }
}