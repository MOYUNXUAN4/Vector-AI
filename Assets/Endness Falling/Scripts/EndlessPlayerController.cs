using UnityEngine;
using UnityEngine.SceneManagement;
using System.Collections;

[RequireComponent(typeof(Rigidbody))]
public class EndlessPlayerController : MonoBehaviour
{
    [Header("Movement Settings")]
    public float moveSpeed = 20f; 
    public float maxSpeed = 15f;  
    
    private Rigidbody rb;
    private Transform cam;
    private LevelManager levelManager;
    
    private bool isDead = false;
    private bool hasWon = false; 

    void Start()
    {
        // 确保开局时时间流速是正常的
        Time.timeScale = 1f;

        rb = GetComponent<Rigidbody>();
        if (Camera.main != null) cam = Camera.main.transform;
        rb.interpolation = RigidbodyInterpolation.Interpolate;
        
        levelManager = FindObjectOfType<LevelManager>();
    }

    void FixedUpdate()
    {
        if (isDead || hasWon) return;

        float h = 0f; float v = 0f;
        if (Input.GetKey(KeyCode.W)) v += 1f;
        if (Input.GetKey(KeyCode.S)) v -= 1f;
        if (Input.GetKey(KeyCode.D)) h += 1f;
        if (Input.GetKey(KeyCode.A)) h -= 1f;

        Vector3 inputDir = new Vector3(h, 0, v);

        if (inputDir.sqrMagnitude > 0.01f) 
        {
            Vector3 moveForce = inputDir.normalized * moveSpeed;
            rb.AddForce(moveForce);
        }

        Vector3 vel = rb.linearVelocity;
        Vector3 horizontalVel = new Vector3(vel.x, 0, vel.z);
        if (horizontalVel.magnitude > maxSpeed)
        {
            horizontalVel = horizontalVel.normalized * maxSpeed;
            rb.linearVelocity = new Vector3(horizontalVel.x, vel.y, horizontalVel.z);
        }
    }

    void Update()
    {
        if (!isDead && !hasWon && levelManager != null)
        {
            Vector2 playerXZ = new Vector2(transform.position.x, transform.position.z);
            float exactDeathRadius = levelManager.GetCurrentDeathRadius();
            
            if (playerXZ.magnitude > exactDeathRadius)
            {
                TriggerDeath("Fell off edge! Current distance: " + playerXZ.magnitude);
            }

            // 实时更新 HUD
            if (UIManager.Instance != null)
            {
                UIManager.Instance.UpdateHUD(
                    levelManager.GetCurrentLayer(), 
                    levelManager.currentLevel, 
                    levelManager.GetRemainingInPart()
                );
            }
        }
    }

    void TriggerDeath(string logMessage)
    {
        if (isDead) return; 
        isDead = true; 
        Debug.LogWarning(logMessage); 
        
        if (cam != null)
        {
            CameraController camScript = cam.GetComponent<CameraController>();
            if (camScript != null) camScript.target = null;
        }

        // Keep physics running so the ball can free-fall naturally.
        rb.useGravity = true;

        StartCoroutine(GameOverSequence());
    }

    IEnumerator GameOverSequence()
    {
        // Wait 1 second before showing the session-ended panel.
        yield return new WaitForSeconds(1f);

        if (UIManager.Instance != null && levelManager != null)
        {
            Time.timeScale = 0f;
            UIManager.Instance.ShowGameOver(levelManager.GetPassedCount(), levelManager.currentLevel);
        }
    }

    public void TriggerWin()
    {
        if (hasWon) return;
        hasWon = true;
        rb.linearVelocity = Vector3.zero;
        Time.timeScale = 0f;
        if (UIManager.Instance != null && levelManager != null)
        {
            int displayDifficulty = Mathf.Clamp(levelManager.currentLevel, 1, 5);
            UIManager.Instance.ShowGameOver(levelManager.GetPassedCount(), displayDifficulty, true);
        }
        Debug.Log("Rehab Completed!");
    }
}