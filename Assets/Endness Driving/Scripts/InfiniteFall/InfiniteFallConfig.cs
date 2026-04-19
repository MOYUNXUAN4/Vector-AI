using UnityEngine;

[CreateAssetMenu(fileName = "InfiniteFallConfig", menuName = "InfiniteFall/Config")]
public class InfiniteFallConfig : ScriptableObject
{
    [Header("Platform")]
    public float platformRadius = 3.8f;
    public float holeRadius = 0.85f;
    public float holeEdgePadding = 0.4f;
    public float layerThickness = 0.4f;
    public float layerGap = 12f;
    public int initialLayerCount = 6;
    public float platformSpreadRadius = 3.2f;

    [Header("Ball Physics")]
    public float ballRadius = 0.25f;
    public float ballSurfaceLift = 0.06f;
    public float gravityScale = 2f;
    public float linearDamping = 0.2f;
    public float angularDamping = 0.05f;
    public float tiltAssistForce = 22f;
    public float maxHorizontalSpeed = 8f;

    [Header("Control")]
    public float maxTiltRadians = 0.4f;
    public float tiltLerp = 0.1f;
    public float tiltInputScale = 0.002f;

    [Header("Camera")]
    public Vector3 cameraOffset = new Vector3(0f, 15f, -14f);
    public float cameraSmooth = 6f;
    public float cameraFallLookAhead = 6f;
    public float gameOverDropDistance = 20f;

    [Header("Score")]
    public int scorePerLayer = 500;
}
