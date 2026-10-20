using UnityEngine;

public class CameraController : MonoBehaviour
{
    [Header("跟随目标")]
    public Transform target;

    [Header("位置参数")]
    public Vector3 offset = new Vector3(0, 8f, -6f); 
    public float smoothSpeed = 10f; // 【调整】稍微调快一点平滑速度，防止小球掉落太快把摄像机甩开

    [Header("角度与镜头参数")]
    [Range(10f, 85f)]
    public float pitchAngle = 55f; 

    [Range(30f, 120f)]
    public float fieldOfView = 60f; 

    private Camera cam;

    void Start()
    {
        cam = GetComponent<Camera>();

        if (target != null)
        {
            // 【修复】初始位置也要加上 target 的 X 和 Z
            transform.position = target.position + offset;
            transform.rotation = Quaternion.Euler(pitchAngle, 0, 0);
        }
    }

    void LateUpdate()
    {
        if (target == null) return;

        // 【核心修复】：让摄像机在 X、Y、Z 三个轴上都完全跟随小球！
        // 如果你想让摄像机在 X 轴居中，不随小球左右晃动，可以改成：
        // Vector3 targetPosition = new Vector3(0, target.position.y + offset.y, target.position.z + offset.z);
        Vector3 targetPosition = target.position + offset;
        
        transform.position = Vector3.Lerp(transform.position, targetPosition, smoothSpeed * Time.deltaTime);
        transform.rotation = Quaternion.Euler(pitchAngle, 0, 0);

        if (cam != null)
        {
            cam.fieldOfView = fieldOfView;
        }
    }
}