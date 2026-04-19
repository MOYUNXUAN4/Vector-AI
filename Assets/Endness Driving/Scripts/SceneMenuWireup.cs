using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

/// <summary>
/// Attach to Canvas. Assign the Button and scene name in the Inspector (or scene YAML).
/// Avoids putting custom scripts on the Button (fewer missing-script issues).
/// </summary>
public class SceneMenuWireup : MonoBehaviour
{
    [SerializeField] Button loadSceneButton;
    [SerializeField] string targetSceneName;

    void Awake()
    {
        if (loadSceneButton == null || string.IsNullOrEmpty(targetSceneName))
            return;
        loadSceneButton.onClick.RemoveAllListeners();
        loadSceneButton.onClick.AddListener(() =>
            SceneManager.LoadScene(targetSceneName, LoadSceneMode.Single));
    }
}
