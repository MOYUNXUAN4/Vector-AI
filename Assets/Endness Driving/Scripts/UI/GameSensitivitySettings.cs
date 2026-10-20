using UnityEngine;

public static class GameSensitivitySettings
{
    const string FallingKey = "Sensitivity.Falling";
    const string PathKey = "Sensitivity.Path";
    const string DriverKey = "Sensitivity.Driver";

    public const float FallingDefault = 0.5f;
    public const float FallingMin = 0.1f;
    public const float FallingMax = 3f;

    public const float PathDefault = 10f;
    public const float PathMin = 4f;
    public const float PathMax = 20f;

    public const float DriverDefault = 5f;
    public const float DriverMin = 1f;
    public const float DriverMax = 10f;

    public static float GetFalling()
    {
        return Mathf.Clamp(PlayerPrefs.GetFloat(FallingKey, FallingDefault), FallingMin, FallingMax);
    }

    public static float GetPath()
    {
        return Mathf.Clamp(PlayerPrefs.GetFloat(PathKey, PathDefault), PathMin, PathMax);
    }

    public static float GetDriver()
    {
        return Mathf.Clamp(PlayerPrefs.GetFloat(DriverKey, DriverDefault), DriverMin, DriverMax);
    }

    public static void SetFalling(float value)
    {
        PlayerPrefs.SetFloat(FallingKey, Mathf.Clamp(value, FallingMin, FallingMax));
    }

    public static void SetPath(float value)
    {
        PlayerPrefs.SetFloat(PathKey, Mathf.Clamp(value, PathMin, PathMax));
    }

    public static void SetDriver(float value)
    {
        PlayerPrefs.SetFloat(DriverKey, Mathf.Clamp(value, DriverMin, DriverMax));
    }

    public static void Save()
    {
        PlayerPrefs.Save();
    }
}
