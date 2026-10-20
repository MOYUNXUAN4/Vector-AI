using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class AIHandler : MonoBehaviour
{
    [SerializeField]
    CarHandler carHandler;

    //Collision detection
    [SerializeField]
    LayerMask otherCarsLayerMask;

    [SerializeField]
    MeshCollider meshCollider;

    [Header("SFX")]
    [SerializeField]
    AudioSource honkHornAS;

    RaycastHit[] raycastHits = new RaycastHit[1];
    bool isCarAhead = false;
    float carAheadDistance = 0;

    // 【修改1】用来记录出生时的车道 X 坐标
    float lockedLaneX = 0f;

    //Timing
    WaitForSeconds wait = new WaitForSeconds(0.2f);

    private void Awake()
    {
        if (CompareTag("Player"))
        {
            Destroy(this);
            return;
        }
    }

    void Start()
    {
        StartCoroutine(UpdateLessOftenCO());
    }

    void Update()
    {
        float accelerationInput = 1.0f;
        float steerInput = 0.0f;

        // 防追尾逻辑（保留）
        if (isCarAhead)
        {
            accelerationInput = -1;

            if (carAheadDistance < 10 && !honkHornAS.isPlaying)
            {
                honkHornAS.pitch = Random.Range(0.5f, 1.1f);
                honkHornAS.Play();
            }
        }

        // 【修改2】不再读取全局的 Utils.CarLanes，而是锁定自己出生时的 X 坐标
        float difference = lockedLaneX - transform.position.x;

        if (Mathf.Abs(difference) > 0.05f)
            steerInput = 1.0f * difference;

        steerInput = Mathf.Clamp(steerInput, -1.0f, 1.0f);

        carHandler.SetInput(new Vector2(steerInput, accelerationInput));
    }

    IEnumerator UpdateLessOftenCO()
    {
        while (true)
        {
            isCarAhead = CheckIfOtherCarsIsAhead();
            yield return wait;
        }
    }

    bool CheckIfOtherCarsIsAhead()
    {
        meshCollider.enabled = false;

        int numberOfHits = Physics.BoxCastNonAlloc(transform.position, Vector3.one * 0.25f, transform.forward, raycastHits, Quaternion.identity, 2, otherCarsLayerMask);

        meshCollider.enabled = true;

        if (numberOfHits > 0)
        {
            carAheadDistance = (transform.position - raycastHits[0].point).magnitude;
            return true;
        }

        return false;
    }

    //Events
    private void OnEnable()
    {
        // 赋予随机速度 (2到4)，如果嫌慢可以改大一点
        carHandler.SetMaxSpeed(Random.Range(2, 4));

        // 【修改3】当车子被 Spawner 生成出来时，直接把当前位置当作自己的目标车道！
        // 这样 Spawner 把它放在四车道的哪条线，它就死死咬住那条线直走，绝不乱拐！
        lockedLaneX = transform.position.x;
    }
}