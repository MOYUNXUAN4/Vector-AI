using UnityEngine;

public class EndlessVisualTheme : MonoBehaviour
{
    [Header("Global Theme")]
    [SerializeField] private Color ambientSky = new Color(0.88f, 0.97f, 0.93f, 1f);
    [SerializeField] private Color ambientEquator = new Color(0.66f, 0.82f, 0.76f, 1f);
    [SerializeField] private Color ambientGround = new Color(0.34f, 0.55f, 0.50f, 1f);
    [SerializeField] private Color fogColor = new Color(0.78f, 0.91f, 0.86f, 1f);
    [SerializeField] private float fogDensity = 0.013f;

    [Header("Gradient Palette")]
    [SerializeField] private Color platformGradientTop = new Color(0.94f, 0.99f, 0.97f, 1f);
    [SerializeField] private Color platformGradientBottom = new Color(0.20f, 0.48f, 0.40f, 1f);
    [SerializeField] private Color accentColor = new Color(0.24f, 0.56f, 0.48f, 1f);
    [SerializeField] private Color ballColor = new Color(0.19f, 0.46f, 0.56f, 1f);
    [SerializeField] private float gradientTopY = 8f;
    [SerializeField] private float gradientBottomY = -36f;
    [SerializeField] private float smoothness = 0.62f;
    [SerializeField] private float metallic = 0.05f;

    [Header("Subtle Motion")]
    [SerializeField] private bool enableLightPulse = true;
    [SerializeField] private float pulseSpeed = 0.65f;
    [SerializeField] private float pulseAmount = 0.2f;

    private Light keyLight;
    private Light fillLight;
    private Camera mainCam;

    private void Awake()
    {
        ApplyRenderSettings();
        SetupLights();
        SetupCamera();
        RecolorScene();
    }

    private void Update()
    {
        if (!enableLightPulse || keyLight == null) return;
        float pulse = 1f + Mathf.Sin(Time.time * pulseSpeed) * pulseAmount;
        keyLight.intensity = 0.95f * pulse;
    }

    private void ApplyRenderSettings()
    {
        RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Trilight;
        RenderSettings.ambientSkyColor = ambientSky;
        RenderSettings.ambientEquatorColor = ambientEquator;
        RenderSettings.ambientGroundColor = ambientGround;
        RenderSettings.fog = true;
        RenderSettings.fogMode = FogMode.ExponentialSquared;
        RenderSettings.fogColor = fogColor;
        RenderSettings.fogDensity = fogDensity;
    }

    private void SetupLights()
    {
        Light[] lights = FindObjectsOfType<Light>(true);
        for (int i = 0; i < lights.Length; i++)
        {
            if (lights[i].type == LightType.Directional)
            {
                if (keyLight == null) keyLight = lights[i];
                else if (fillLight == null) fillLight = lights[i];
            }
        }

        if (keyLight == null)
        {
            GameObject key = new GameObject("Theme_KeyLight");
            keyLight = key.AddComponent<Light>();
            keyLight.type = LightType.Directional;
            keyLight.transform.rotation = Quaternion.Euler(42f, -32f, 0f);
        }
        keyLight.color = new Color(0.90f, 0.95f, 0.98f);
        keyLight.intensity = 0.95f;
        keyLight.shadows = LightShadows.Soft;

        if (fillLight == null)
        {
            GameObject fill = new GameObject("Theme_FillLight");
            fillLight = fill.AddComponent<Light>();
            fillLight.type = LightType.Directional;
            fillLight.transform.rotation = Quaternion.Euler(18f, 140f, 0f);
        }
        fillLight.color = new Color(0.52f, 0.74f, 0.66f);
        fillLight.intensity = 0.38f;
        fillLight.shadows = LightShadows.None;
    }

    private void SetupCamera()
    {
        mainCam = Camera.main;
        if (mainCam == null) return;
        mainCam.clearFlags = CameraClearFlags.SolidColor;
        mainCam.backgroundColor = new Color(0.84f, 0.95f, 0.90f, 1f);
        mainCam.allowHDR = true;
    }

    private void RecolorScene()
    {
        Renderer[] renderers = FindObjectsOfType<Renderer>(true);
        for (int i = 0; i < renderers.Length; i++)
        {
            Renderer r = renderers[i];
            if (r == null || r.sharedMaterial == null) continue;

            string n = r.gameObject.name.ToLowerInvariant();
            bool isBall = n.Contains("ball");
            bool isPlatform = n.Contains("platform") || n.Contains("ring");
            if (!isBall && !isPlatform) continue;

            MaterialPropertyBlock mpb = new MaterialPropertyBlock();
            r.GetPropertyBlock(mpb);

            Color c;
            if (isBall)
            {
                c = ballColor;
            }
            else
            {
                float t = Mathf.InverseLerp(gradientBottomY, gradientTopY, r.bounds.center.y);
                c = Color.Lerp(platformGradientBottom, platformGradientTop, t);
                if (n.Contains("hole") || n.Contains("inner"))
                {
                    c = Color.Lerp(c, accentColor, 0.4f);
                }
            }

            mpb.SetColor("_BaseColor", c);
            mpb.SetColor("_Color", c);
            mpb.SetFloat("_Smoothness", smoothness);
            mpb.SetFloat("_Metallic", metallic);
            r.SetPropertyBlock(mpb);
        }
    }
}
