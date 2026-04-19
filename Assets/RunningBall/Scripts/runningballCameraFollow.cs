using UnityEngine;

public class runningballCameraFollow : MonoBehaviour
{
    public Transform target;        
    public PathGenerator pathGenerator; // 【新增】需要拖入 PathManager 以获取当前速度

    [Header("位置偏移")]
    public Vector3 offset = new Vector3(0, 5, -7);

    [Header("视角调节")]
    [Range(0, 90)] public float pitch = 20f;         
    
    [Header("速度感(FOV)控制")]
    public float baseFOV = 60f;     // 正常速度的 FOV
    public float fastFOV = 85f;     // 加速时的 FOV (广角拉扯感)
    public float slowFOV = 50f;     // 减速时的 FOV

    [Header("平滑度")]
    public float smoothSpeed = 0.125f; 

    private Camera cam;

    void Start()
    {
        cam = GetComponent<Camera>();
    }

    void LateUpdate()
    {
        if (target == null) return;

        // 1. 跟随与旋转
        Vector3 desiredPosition = target.position + offset;
        transform.position = Vector3.Lerp(transform.position, desiredPosition, smoothSpeed);
        transform.rotation = Quaternion.Euler(pitch, 0, 0);

        // 2. 动态速度感 FOV 调整
        if (pathGenerator != null)
        {
            float targetFOV = baseFOV;
            // 根据道路速度决定镜头的广角程度
            if (pathGenerator.currentSpeed > 10.5f) 
            {
                // 加速状态
                float speedRatio = (pathGenerator.currentSpeed - 10f) / (pathGenerator.maxSpeed - 10f);
                targetFOV = Mathf.Lerp(baseFOV, fastFOV, speedRatio);
            }
            else if (pathGenerator.currentSpeed < 9.5f)
            {
                // 减速状态
                float speedRatio = (10f - pathGenerator.currentSpeed) / (10f - pathGenerator.minSpeed);
                targetFOV = Mathf.Lerp(baseFOV, slowFOV, speedRatio);
            }

            // 平滑改变 FOV
            cam.fieldOfView = Mathf.Lerp(cam.fieldOfView, targetFOV, Time.deltaTime * 3f);
        }
    }
}