using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

[System.Serializable]
public struct SceneMenuButtonBinding
{
    public Button button;
    public string targetSceneName;
}

/// <summary>
/// Attach to Canvas and assign one or more buttons with target scenes.
/// </summary>
public class SceneMenuWireup : MonoBehaviour
{
    [SerializeField] SceneMenuButtonBinding[] buttonBindings;

    void Awake()
    {
        if (buttonBindings == null)
            return;

        for (int i = 0; i < buttonBindings.Length; i++)
        {
            var binding = buttonBindings[i];
            if (binding.button == null || string.IsNullOrWhiteSpace(binding.targetSceneName))
                continue;

            string targetSceneName = binding.targetSceneName;
            binding.button.onClick.RemoveAllListeners();
            binding.button.onClick.AddListener(() =>
                SceneManager.LoadScene(targetSceneName, LoadSceneMode.Single));
        }
    }
}
