using System.Collections.Generic;
using UnityEngine;

[RequireComponent(typeof(LineRenderer))]
public class PathGenerator : MonoBehaviour
{
    [Header("实时速度控制")]
    public float currentSpeed = 10f;  
    public float minSpeed = 5f;       
    public float maxSpeed = 30f;      
    private float targetSpeed = 10f;

    [Header("动态难度参数 (平滑高速公路)")]
    public float pathWidth = 12f;      
    public float turnAmplitude = 25f;  // 【当前】默认弯道幅度更大、更明显
    public float noiseStep = 0.015f;   

    [Header("难度视觉反馈 (颜色)")]
    public Color easyColor = new Color(0.2f, 0.9f, 0.4f);  
    public Color normalColor = new Color(0.2f, 0.6f, 1f);  
    public Color hardColor = new Color(1f, 0.2f, 0.2f);    
    private Color targetColor;

    [Header("路径基础设置")]
    public int segmentCount = 60;     
    public float segmentLength = 2f;  

    private LineRenderer lineRenderer;
    private List<Vector3> pathPoints = new List<Vector3>();
    
    // 生成新路点的连续游标
    private float pathCursorZ = 0f;   

    private float targetWidth;
    private float targetAmplitude;
    private float targetNoiseStep;

    void Start()
    {
        lineRenderer = GetComponent<LineRenderer>();
        lineRenderer.positionCount = segmentCount;
        lineRenderer.alignment = LineAlignment.TransformZ;

        targetWidth = pathWidth;
        targetAmplitude = turnAmplitude;
        targetNoiseStep = noiseStep;
        targetColor = normalColor;

        if (lineRenderer.material.HasProperty("_Color"))
            lineRenderer.material.color = targetColor;

        float currentZ = 0f;
        for (int i = 0; i < segmentCount; i++)
        {
            float noiseX = (Mathf.PerlinNoise(pathCursorZ, 0) - 0.5f) * turnAmplitude;
            pathPoints.Add(new Vector3(noiseX, 0, currentZ));
            currentZ += segmentLength;
            pathCursorZ += noiseStep;
        }
    }

    void Update()
    {
        // 平滑过渡数值
        pathWidth = Mathf.Lerp(pathWidth, targetWidth, Time.deltaTime * 1.5f); 
        turnAmplitude = Mathf.Lerp(turnAmplitude, targetAmplitude, Time.deltaTime * 0.8f);
        noiseStep = Mathf.Lerp(noiseStep, targetNoiseStep, Time.deltaTime * 0.8f);
        currentSpeed = Mathf.Lerp(currentSpeed, targetSpeed, Time.deltaTime * 2f);

        if (lineRenderer.material.HasProperty("_Color"))
            lineRenderer.material.color = Color.Lerp(lineRenderer.material.color, targetColor, Time.deltaTime * 1.5f);

        lineRenderer.startWidth = pathWidth;
        lineRenderer.endWidth = pathWidth;

        // 移动路点
        for (int i = 0; i < pathPoints.Count; i++)
        {
            Vector3 p = pathPoints[i];
            p.z -= currentSpeed * Time.deltaTime; 
            pathPoints[i] = p;
        }

        // 当最近的点跑到了身后，移除它，并在最前方生成一个新点
        while (pathPoints.Count > 0 && pathPoints[0].z < -10f)
        {
            pathPoints.RemoveAt(0);
            Vector3 lastPoint = pathPoints[pathPoints.Count - 1];

            // 只对“即将生成的新路面”应用弯道扭曲，脚下的路绝对不动！
            float noiseX = (Mathf.PerlinNoise(pathCursorZ, 0) - 0.5f) * turnAmplitude;
            pathPoints.Add(new Vector3(noiseX, 0, lastPoint.z + segmentLength));
            
            pathCursorZ += noiseStep;
        }

        lineRenderer.SetPositions(pathPoints.ToArray());
    }

    public void SetTargetSpeed(float speedRatio) 
    {
        if (speedRatio > 0) targetSpeed = Mathf.Lerp(10f, maxSpeed, speedRatio);
        else if (speedRatio < 0) targetSpeed = Mathf.Lerp(10f, minSpeed, -speedRatio);
        else targetSpeed = 10f; 
    }

    // 接收重心转移幅度来进行难度调整
    public void UpdateDifficulty(float movementAmplitude)
    {
        // 降低灵敏度：玩家必须晃动非常剧烈才会降低难度
        if (movementAmplitude > 1.2f) 
        {
            targetWidth = 16f;          
            targetAmplitude = 8f;       
            targetNoiseStep = 0.01f;    
            targetColor = easyColor;    
            Debug.Log("难度下降：玩家运动量达标，路面变宽平缓！");
        }
        // 降低灵敏度：玩家必须站得像木头一样死板才会触发困难模式
        else if (movementAmplitude < 0.1f) 
        {
            targetWidth = 8f;           
            targetAmplitude = 35f;      // 困难模式的弯道极其夸张明显！
            targetNoiseStep = 0.02f;    
            targetColor = hardColor;    
            Debug.Log("难度上升：玩家太闲了，极限大弯道开启！");
        }
        else // 良好状态
        {
            targetWidth = 12f;          
            targetAmplitude = 25f;      // 正常模式也保持明显的弯道
            targetNoiseStep = 0.015f;   
            targetColor = normalColor;  
        }
    }

    // 只用于判断是否掉落的安全查找法
    public float GetPathCenterX(float zPosition)
    {
        if (pathPoints.Count < 2) return 0f;
        for (int i = 0; i < pathPoints.Count - 1; i++)
        {
            Vector3 p1 = pathPoints[i];
            Vector3 p2 = pathPoints[i + 1];
            if (zPosition >= p1.z && zPosition <= p2.z)
            {
                float t = (zPosition - p1.z) / (p2.z - p1.z);
                return Mathf.Lerp(p1.x, p2.x, t);
            }
        }
        return pathPoints[0].x; 
    }
}