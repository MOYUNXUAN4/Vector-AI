using UnityEngine;

[RequireComponent(typeof(Rigidbody))]
public class runningballPlayerContral : MonoBehaviour
{
    [Header("移动设置")]
    public float moveSpeed = 10f;

    [Header("环境关联")]
    public PathGenerator pathGenerator; 
    public Collider physicsFloor;       

    private Rigidbody rb;
    private bool isDead = false;
    private float safeTimer = 1.5f; 

    // === 动态难度(DDA)监控变量 ===
    private float checkInterval = 4.0f; 
    private float timer = 0f;
    private float totalMovementX = 0f; 
    private float lastXPosition = 0f;  

    // 【新增】UI 数据：记录玩家行驶的总距离
    private float distanceTraveled = 0f;

    void Start()
    {
        rb = GetComponent<Rigidbody>();
        lastXPosition = transform.position.x;
    }

    // 【新增】我们在 Update 里处理 UI 和距离的实时计算
    void Update()
    {
        if (isDead || pathGenerator == null) return;

        // 1. 计算行驶距离：距离 = 道路后退的速度 * 每一帧的时间
        distanceTraveled += pathGenerator.currentSpeed * Time.deltaTime;

        // 2. 将计算好的距离，发送给我们刚刚写好的 runningbollUiManager
        if (runningbollUiManager.Instance != null)
        {
            runningbollUiManager.Instance.UpdateHUD(distanceTraveled);
        }
    }

    void FixedUpdate()
    {
        if (isDead || pathGenerator == null || physicsFloor == null) return;

        // 获取输入与移动
        float moveX = Input.GetAxis("Horizontal"); 
        float moveZ = Input.GetAxis("Vertical");   
        rb.linearVelocity = new Vector3(moveX * moveSpeed, rb.linearVelocity.y, 0f);

        // 控制速度感
        pathGenerator.SetTargetSpeed(moveZ);

        if (safeTimer > 0f)
        {
            safeTimer -= Time.fixedDeltaTime;
            lastXPosition = transform.position.x;
            return; 
        }

        float currentX = transform.position.x;

        // 核心：计算玩家的“重心转移幅度”
        float frameMovement = Mathf.Abs(currentX - lastXPosition);
        totalMovementX += frameMovement;
        lastXPosition = currentX; 

        timer += Time.fixedDeltaTime;

        if (timer >= checkInterval)
        {
            float averageMovementSpeed = totalMovementX / checkInterval;
            pathGenerator.UpdateDifficulty(averageMovementSpeed);

            timer = 0f;
            totalMovementX = 0f;
        }

        // 掉落判定 
        float pathCenterX = pathGenerator.GetPathCenterX(transform.position.z);
        float currentDeviation = Mathf.Abs(currentX - pathCenterX) / (pathGenerator.pathWidth * 0.5f);
        
        if (currentDeviation > 1.15f) 
        {
            FallOffThePath();
        }
    }

    void FallOffThePath()
    {
        if (isDead) return; // 防止重复触发

        isDead = true; 
        if (physicsFloor != null) physicsFloor.enabled = false; 
        Debug.Log("GAME OVER: 偏离轨道！");

        // 【新增】玩家掉落时，呼叫 runningbollUiManager 弹出游戏结束面板！
        // 我们把跑出的总距离（向下取整）作为 Final Score 传给 UI
        if (runningbollUiManager.Instance != null)
        {
            int finalScore = Mathf.FloorToInt(distanceTraveled);
            runningbollUiManager.Instance.ShowGameOver(finalScore, 1, false);
        }
    }
}