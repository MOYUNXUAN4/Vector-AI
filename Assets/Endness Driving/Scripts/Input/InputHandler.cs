using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

public class InputHandler : MonoBehaviour
{
    [SerializeField]
    CarHandler carHandler;

    private void Awake()
    {
        if (!CompareTag("Player"))
        {
            Destroy(this);
            return;
        }
    }

    void Update()
    {
        Vector2 input = Vector2.zero;

        input.x = Input.GetAxis("Horizontal");
        float rawV = Input.GetAxisRaw("Vertical");
        input.y = rawV > 0f ? 1f : (rawV < 0f ? 0.18f : 0.45f);

        carHandler.SetInput(input);

        if (Input.GetKeyDown(KeyCode.R))
        {
            //Restore time scale
            Time.timeScale = 1.0f;

            SceneManager.LoadScene(SceneManager.GetActiveScene().name);
        }
    }
}