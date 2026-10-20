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

    // 记录玩家行驶的总距离
    private float distanceTraveled = 0f;

    void Start()
    {
        moveSpeed = GameSensitivitySettings.GetPath();
        rb = GetComponent<Rigidbody>();

        if (pathGenerator != null)
            pathGenerator.SetTargetSpeed(0f);
    }

    void Update()
    {
        if (isDead || pathGenerator == null) return;

        // 计算行驶距离并更新 UI
        distanceTraveled += pathGenerator.currentSpeed * Time.deltaTime;

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
        float rawMoveZ = Input.GetAxisRaw("Vertical");
        float speedInput = rawMoveZ > 0f ? 1f : (rawMoveZ < 0f ? -1f : 0f);
        rb.linearVelocity = new Vector3(moveX * moveSpeed, rb.linearVelocity.y, 0f);

        pathGenerator.SetTargetSpeed(speedInput);

        if (safeTimer > 0f)
        {
            safeTimer -= Time.fixedDeltaTime;
            return; 
        }

        // 掉落判定：允许玩家在路面宽度的范围内活动
        float currentX = transform.position.x;
        float pathCenterX = pathGenerator.GetPathCenterX(transform.position.z);
        float currentDeviation = Mathf.Abs(currentX - pathCenterX) / (pathGenerator.pathWidth * 0.5f);
        
        if (currentDeviation > 1.15f) 
        {
            FallOffThePath();
        }
    }

    void FallOffThePath()
    {
        if (isDead) return; 

        isDead = true; 
        if (physicsFloor != null) physicsFloor.enabled = false; 
        Debug.Log("GAME OVER: You left the track!");

        if (runningbollUiManager.Instance != null)
        {
            int finalScore = Mathf.FloorToInt(distanceTraveled);
            runningbollUiManager.Instance.ShowGameOver(finalScore, 1, false);
        }
    }

    // ==============================================================
    // 提供给网络的接口，AI 靠这三个数据来算 RMSE 和 考核进度
    // ==============================================================
    public float GetPlayerX() { return transform.position.x; }
    
    public float GetTargetX() { return pathGenerator != null ? pathGenerator.GetPathCenterX(transform.position.z) : 0f; }
    
    public int GetDistance() { return Mathf.FloorToInt(distanceTraveled); }
}