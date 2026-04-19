using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using System; // 修复：加上了缺失的分号

public class CarHandler : MonoBehaviour
{
    [SerializeField]
    Rigidbody rb;

    [SerializeField]
    Transform gameModel;

    [SerializeField]
    MeshRenderer carMeshRender;

    [SerializeField]
    ExplodeHandler explodeHandler;

    [Header("SFX")]
    [SerializeField]
    AudioSource carEngineAS;

    [SerializeField]
    AnimationCurve carPitchAnimationCurve;

    [SerializeField]
    AudioSource carSkidAS;

    [SerializeField]
    AudioSource carCrashAS;

    //Max values
    float maxSteerVelocity = 2;
    float maxForwardVelocity = 30;
    float carMaxSpeedPercentage = 0;

    //Multipliers
    float accelerationMultiplier = 3;
    float breaksMultiplier = 15;
    float steeringMultiplier = 5;

    //Input
    Vector2 input = Vector2.zero;

    //Emissive property
    int _EmissionColor = Shader.PropertyToID("_EmissionColor");
    Color emissiveColor = Color.white;
    float emissiveColorMultiplier = 0f;

    //Exploded state
    bool isExploded = false;
    bool isPlayer = true;

    float carStartPositionZ;
    float distanceTravelled = 0;
    
    public float DistanceTravelled => distanceTravelled;

    public event Action<CarHandler> OnPlayerCrashed;

    // Start is called before the first frame update
    void Start()
    {
        isPlayer = CompareTag("Player");

        if (isPlayer && carEngineAS != null)
            carEngineAS.Play();
        
        carStartPositionZ = transform.position.z;
    }

    // Update is called once per frame
    void Update()
    {
        if (isExploded)
        {
            FadeOutCarAudio();
            return;
        }

        // --- 核心修改：如果是玩家，自动读取键盘/手柄输入 ---
        if (isPlayer)
        {
            float h = Input.GetAxis("Horizontal"); // A/D 或 左右方向键
            float v = Input.GetAxis("Vertical");   // W/S 或 上下方向键
            SetInput(new Vector2(h, v));
        }

        //Rotate car model when "turning"
        if (gameModel != null)
        {
            gameModel.transform.rotation = Quaternion.Euler(0, rb.linearVelocity.x * 5, 0);
        }

        if (carMeshRender != null)
        {
            float desiredCarEmissiveColorMultiplier = 0f;

            if (input.y < 0)
                desiredCarEmissiveColorMultiplier = 4.0f;

            emissiveColorMultiplier = Mathf.Lerp(emissiveColorMultiplier, desiredCarEmissiveColorMultiplier, Time.deltaTime * 4);

            carMeshRender.material.SetColor(_EmissionColor, emissiveColor * emissiveColorMultiplier);
        }

        UpdateCarAudio();

        //Update distance travelled (修改：使用绝对值，防止向反方向开时里程变负数)
        distanceTravelled = Mathf.Abs(transform.position.z - carStartPositionZ);
    }

    private void FixedUpdate()
    {
        //Is exploded
        if (isExploded)
        {
            //Apply drag
            rb.linearDamping = rb.linearVelocity.z * 0.1f;
            rb.linearDamping = Mathf.Clamp(rb.linearDamping, 1.5f, 10);

            //Move towards after a the car has exploded
            rb.MovePosition(Vector3.Lerp(transform.position, new Vector3(0, 0, transform.position.z), Time.deltaTime * 0.5f));

            return;
        }

        //Apply Acceleration
        if (input.y > 0)
            Accelerate();
        else
            rb.linearDamping = 0.2f;

        //Apply Brakes
        if (input.y < 0)
            Brake();

        Steer();

        //Force the car not to go backwards
        if (rb.linearVelocity.z <= 0)
            rb.linearVelocity = Vector3.zero;
    }

    void Accelerate()
    {
        rb.linearDamping = 0;

        //Stay within the speed limit
        if (rb.linearVelocity.z >= maxForwardVelocity)
            return;

        rb.AddForce(transform.forward * accelerationMultiplier * input.y, ForceMode.Acceleration); // 修改：加入 ForceMode.Acceleration 让推力不受质量影响
    }

    void Brake()
    {
        //Don't brake unless we are going forward
        if (rb.linearVelocity.z <= 0)
            return;

        rb.AddForce(transform.forward * breaksMultiplier * input.y, ForceMode.Acceleration);
    }

    void Steer()
    {
        if (Mathf.Abs(input.x) > 0)
        {
            //Move the car sideways
            float speedBaseSteerLimit = rb.linearVelocity.z / 5.0f;
            speedBaseSteerLimit = Mathf.Clamp01(speedBaseSteerLimit);

            rb.AddForce(transform.right * steeringMultiplier * input.x * speedBaseSteerLimit, ForceMode.Acceleration);

            //Normalize the X Velocity
            float normalizedX = rb.linearVelocity.x / maxSteerVelocity;

            //Ensure that we don't allow it to get bigger than 1 in magnitued. 
            normalizedX = Mathf.Clamp(normalizedX, -1.0f, 1.0f);

            //Make sure we stay within the turn speed limit
            rb.linearVelocity = new Vector3(normalizedX * maxSteerVelocity, 0, rb.linearVelocity.z);
        }
        else 
        {
            //Auto center car
            rb.linearVelocity = Vector3.Lerp(rb.linearVelocity, new Vector3(0, 0, rb.linearVelocity.z), Time.fixedDeltaTime * 3);
        }
    }

    void UpdateCarAudio()
    {
        if (!isPlayer || carEngineAS == null || carSkidAS == null)
            return;

        carMaxSpeedPercentage = rb.linearVelocity.z / maxForwardVelocity;

        carEngineAS.pitch = carPitchAnimationCurve.Evaluate(carMaxSpeedPercentage);

        if (input.y < 0 && carMaxSpeedPercentage > 0.2f)
        {
            if (!carSkidAS.isPlaying)
                carSkidAS.Play();

            carSkidAS.volume = Mathf.Lerp(carSkidAS.volume, 1.0f, Time.deltaTime * 10);
        }
        else
        {
            carSkidAS.volume = Mathf.Lerp(carSkidAS.volume, 0, Time.deltaTime * 30);
        }
    }

    void FadeOutCarAudio()
    {
        if (!isPlayer || carEngineAS == null || carSkidAS == null)
            return;

        carEngineAS.volume = Mathf.Lerp(carEngineAS.volume, 0, Time.deltaTime * 10);
        carSkidAS.volume = Mathf.Lerp(carSkidAS.volume, 0, Time.deltaTime * 10);
    }

    public void SetInput(Vector2 inputVector)
    {
        inputVector.Normalize();
        input = inputVector;
    }

    public void SetMaxSpeed(float newMaxSpeed)
    {
        maxForwardVelocity = newMaxSpeed;
    }

    IEnumerator SlowDownTimeCO()
    {
        while (Time.timeScale > 0.2f)
        {
            Time.timeScale -= Time.unscaledDeltaTime * 2; // 修复：使用 unscaledDeltaTime 防止卡死
            yield return null;
        }

        yield return new WaitForSecondsRealtime(0.5f); // 修复：使用 Realtime 

        while (Time.timeScale <= 1.0f)
        {
            Time.timeScale += Time.unscaledDeltaTime;
            yield return null;
        }

        Time.timeScale = 1.0f;
    }

    //Events
    private void OnCollisionEnter(Collision collision)
    {
        if (isExploded) return; // 修复：防止重复触发爆炸

        //AI cars will only explode when they hit the player or a car part
        if (!isPlayer)
        {
            if (collision.transform.root.CompareTag("Untagged") || collision.transform.root.CompareTag("CarAI"))
                return;
        }

        Vector3 velocity = rb.linearVelocity;
        
        if (explodeHandler != null)
            explodeHandler.Explode(velocity * 45);

        isExploded = true;

        if (carCrashAS != null)
        {
            carCrashAS.volume = Mathf.Clamp(carMaxSpeedPercentage, 0.25f, 1.0f);
            carCrashAS.pitch = Mathf.Clamp(carMaxSpeedPercentage, 0.3f, 1.0f);
            carCrashAS.Play();
        }

        // 触发撞车事件给 UIHandler
        OnPlayerCrashed?.Invoke(this);

        StartCoroutine(SlowDownTimeCO());
    }
}