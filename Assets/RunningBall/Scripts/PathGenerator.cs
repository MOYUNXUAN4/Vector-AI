using System.Collections.Generic;
using UnityEngine;

[RequireComponent(typeof(LineRenderer))]
public class PathGenerator : MonoBehaviour
{
    [Header("实时速度控制")]
    public float currentSpeed = 15f;
    public float minSpeed = 11f;
    public float maxSpeed = 34f;
    private float targetSpeed = 15f;

    [Header("动态难度参数 (平滑过渡)")]
    public float pathWidth = 12f;
    public float turnAmplitude = 25f;
    public float noiseStep = 0.015f;

    [Header("难度视觉反馈 (颜色)")]
    public Color easyColor = new Color(0.12f, 0.28f, 0.16f);
    public Color normalColor = new Color(0.12f, 0.20f, 0.30f);
    public Color hardColor = new Color(0.32f, 0.12f, 0.12f);
    private Color targetColor;

    [Header("路径基础设置")]
    public int segmentCount = 60;
    public float segmentLength = 2f;

    private LineRenderer lineRenderer;
    private Material roadMaterial;
    private Mesh roadMesh;
    private MeshFilter roadMeshFilter;
    private MeshRenderer roadMeshRenderer;
    private readonly List<Vector3> pathPoints = new List<Vector3>();
    private readonly List<Vector3> meshVertices = new List<Vector3>(256);
    private readonly List<int> meshTriangles = new List<int>(512);
    private readonly List<Vector2> meshUvs = new List<Vector2>(256);
    private float pathDistanceCursor = 0f;

    private float targetWidth;
    private float targetAmplitude;
    private float targetNoiseStep;
    private int currentDifficultyLevel = 1;
    private const float Level1InitialStraightDistance = 160f;
    private const float Level1CurveRampDistance = 120f;

    void Start()
    {
        lineRenderer = GetComponent<LineRenderer>();
        lineRenderer.enabled = false;

        targetWidth = pathWidth;
        targetAmplitude = turnAmplitude;
        targetNoiseStep = noiseStep;
        targetColor = normalColor;

        EnsureRoadMeshRenderer();
        ApplyRoadColor(targetColor);

        float currentZ = 0f;
        pathDistanceCursor = 0f;
        float previousPathX = 0f;
        for (int i = 0; i < segmentCount; i++)
        {
            float pathX = EvaluateSmoothedPathX(previousPathX, pathDistanceCursor);
            pathPoints.Add(new Vector3(pathX, 0f, currentZ));
            previousPathX = pathX;
            currentZ += segmentLength;
            pathDistanceCursor += segmentLength;
        }

        UpdateRoadMesh();
    }

    void Update()
    {
        pathWidth = Mathf.Lerp(pathWidth, targetWidth, Time.deltaTime * 1.5f);
        turnAmplitude = Mathf.Lerp(turnAmplitude, targetAmplitude, Time.deltaTime * 0.8f);
        noiseStep = Mathf.Lerp(noiseStep, targetNoiseStep, Time.deltaTime * 0.8f);
        currentSpeed = Mathf.Lerp(currentSpeed, targetSpeed, Time.deltaTime * 2f);
        ApplyRoadColor(Color.Lerp(GetRoadColor(), targetColor, Time.deltaTime * 1.5f));

        for (int i = 0; i < pathPoints.Count; i++)
        {
            Vector3 p = pathPoints[i];
            p.z -= currentSpeed * Time.deltaTime;
            pathPoints[i] = p;
        }

        while (pathPoints.Count > 0 && pathPoints[0].z < -10f)
        {
            pathPoints.RemoveAt(0);
            Vector3 lastPoint = pathPoints[pathPoints.Count - 1];

            float pathX = EvaluateSmoothedPathX(lastPoint.x, pathDistanceCursor);
            pathPoints.Add(new Vector3(pathX, 0f, lastPoint.z + segmentLength));
            pathDistanceCursor += segmentLength;
        }

        UpdateRoadMesh();
    }

    void EnsureRoadMeshRenderer()
    {
        GameObject go = GameObject.Find("_PathGeneratorRoadMesh");
        if (go == null) go = new GameObject("_PathGeneratorRoadMesh");

        go.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
        go.transform.localScale = Vector3.one;

        roadMeshFilter = go.GetComponent<MeshFilter>();
        if (roadMeshFilter == null) roadMeshFilter = go.AddComponent<MeshFilter>();

        roadMeshRenderer = go.GetComponent<MeshRenderer>();
        if (roadMeshRenderer == null) roadMeshRenderer = go.AddComponent<MeshRenderer>();
        roadMeshRenderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        roadMeshRenderer.receiveShadows = false;

        roadMesh = roadMeshFilter.sharedMesh;
        if (roadMesh == null)
        {
            roadMesh = new Mesh { name = "PathGeneratorRoadMesh" };
            roadMesh.MarkDynamic();
            roadMeshFilter.sharedMesh = roadMesh;
        }

        Material sourceMaterial = lineRenderer != null ? lineRenderer.sharedMaterial : null;
        if (sourceMaterial != null)
        {
            roadMaterial = new Material(sourceMaterial);
        }
        else
        {
            Shader shader = Shader.Find("Universal Render Pipeline/Unlit");
            if (shader == null) shader = Shader.Find("Universal Render Pipeline/Particles/Unlit");
            if (shader == null) shader = Shader.Find("Particles/Standard Unlit");
            if (shader == null) shader = Shader.Find("Unlit/Color");
            roadMaterial = new Material(shader);
        }

        roadMeshRenderer.sharedMaterial = roadMaterial;
    }

    void UpdateRoadMesh()
    {
        if (roadMesh == null || pathPoints.Count < 2) return;

        meshVertices.Clear();
        meshTriangles.Clear();
        meshUvs.Clear();

        float surfaceY = transform.position.y;
        int pointCount = pathPoints.Count;
        float halfWidth = pathWidth * 0.5f;

        for (int i = 0; i < pointCount; i++)
        {
            Vector3 current = pathPoints[i];
            Vector3 forward;

            if (i == 0)
                forward = pathPoints[i + 1] - current;
            else if (i == pointCount - 1)
                forward = current - pathPoints[i - 1];
            else
                forward = pathPoints[i + 1] - pathPoints[i - 1];

            forward.y = 0f;
            if (forward.sqrMagnitude <= 0.0001f)
                forward = Vector3.forward;
            else
                forward.Normalize();

            Vector3 right = Vector3.Cross(Vector3.up, forward) * halfWidth;
            meshVertices.Add(new Vector3(current.x - right.x, surfaceY, current.z - right.z));
            meshVertices.Add(new Vector3(current.x + right.x, surfaceY, current.z + right.z));

            float v = i / (float)(pointCount - 1);
            meshUvs.Add(new Vector2(0f, v));
            meshUvs.Add(new Vector2(1f, v));
        }

        for (int i = 0; i < pointCount - 1; i++)
        {
            int baseIndex = i * 2;
            meshTriangles.Add(baseIndex + 0);
            meshTriangles.Add(baseIndex + 2);
            meshTriangles.Add(baseIndex + 1);
            meshTriangles.Add(baseIndex + 1);
            meshTriangles.Add(baseIndex + 2);
            meshTriangles.Add(baseIndex + 3);
        }

        roadMesh.Clear();
        roadMesh.SetVertices(meshVertices);
        roadMesh.SetTriangles(meshTriangles, 0);
        roadMesh.SetUVs(0, meshUvs);
        roadMesh.RecalculateNormals();
        roadMesh.RecalculateBounds();
    }

    void ApplyRoadColor(Color color)
    {
        if (roadMaterial == null) return;

        roadMaterial.color = color;
        if (roadMaterial.HasProperty("_BaseColor")) roadMaterial.SetColor("_BaseColor", color);
        if (roadMaterial.HasProperty("_Color")) roadMaterial.SetColor("_Color", color);
    }

    Color GetRoadColor()
    {
        if (roadMaterial == null) return targetColor;
        if (roadMaterial.HasProperty("_BaseColor")) return roadMaterial.GetColor("_BaseColor");
        if (roadMaterial.HasProperty("_Color")) return roadMaterial.GetColor("_Color");
        return roadMaterial.color;
    }

    float EvaluatePathX(float distance)
    {
        if (currentDifficultyLevel == 1)
            return 0f;

        float longCurve = Mathf.Sin(distance * noiseStep) * turnAmplitude;
        float detailNoise = (Mathf.PerlinNoise(distance * noiseStep * 0.30f, 0f) - 0.5f) * turnAmplitude * 0.04f;
        return longCurve + detailNoise;
    }

    float EvaluateSmoothedPathX(float previousX, float distance)
    {
        float targetX = EvaluatePathX(distance);
        return Mathf.Lerp(previousX, targetX, 0.18f);
    }

    public void SetTargetSpeed(float speedRatio)
    {
        if (speedRatio > 0f) targetSpeed = Mathf.Lerp(15f, maxSpeed, speedRatio);
        else if (speedRatio < 0f) targetSpeed = Mathf.Lerp(15f, minSpeed, -speedRatio);
        else targetSpeed = 15f;
    }

    public void ApplyAIDifficulty(int level)
    {
        level = Mathf.Clamp(level, 1, 5);
        currentDifficultyLevel = level;

        switch (level)
        {
            case 1:
                targetWidth = 16f;
                targetAmplitude = 10f;
                targetNoiseStep = 0.0045f;
                targetColor = easyColor;
                break;
            case 2:
                targetWidth = 14f;
                targetAmplitude = 11f;
                targetNoiseStep = 0.0055f;
                targetColor = easyColor;
                break;
            case 3:
                targetWidth = 12f;
                targetAmplitude = 14f;
                targetNoiseStep = 0.0068f;
                targetColor = normalColor;
                break;
            case 4:
                targetWidth = 10f;
                targetAmplitude = 24f;
                targetNoiseStep = 0.0092f;
                targetColor = hardColor;
                break;
            default:
                targetWidth = 8f;
                targetAmplitude = 34f;
                targetNoiseStep = 0.0110f;
                targetColor = hardColor;
                break;
        }
    }

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
