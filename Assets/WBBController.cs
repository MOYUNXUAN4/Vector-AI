using UnityEngine;
using System.Collections.Generic;

[RequireComponent(typeof(Rigidbody))] 
public class WBBController : MonoBehaviour
{
    [Header("算法参数 (参考论文3.8.1)")]
    public int filterSize = 5; 
    public float deadzone = 0.1f; 

    [Header("物理弹簧手感 (完美兼容重力下落)")]
    public float maxReach = 9.5f; // ⚠️ 导师建议：你的 Death Radius 是 10，所以 Reach 设为 9.5，防止误触死亡
    public float springForce = 10f; // 弹簧力度（建议 10-15）

    private Queue<Vector3> inputHistory = new Queue<Vector3>();
    private Rigidbody rb;

    void Start()
    {
        rb = GetComponent<Rigidbody>(); 
        
        // 确保物理引擎的设定是正确的，防止摩擦力干扰弹簧手感
        rb.linearDamping = 0f; 
    }

    void FixedUpdate() 
    {
        // 1. 获取原始输入
        float rawX = Input.GetAxisRaw("Horizontal"); 
        float rawY = Input.GetAxisRaw("Vertical");
        Vector3 rawInput = new Vector3(rawX, 0, rawY);

        // 2. 移动平均滤波
        inputHistory.Enqueue(rawInput);
        if (inputHistory.Count > filterSize)
        {
            inputHistory.Dequeue();
        }

        Vector3 smoothedInput = Vector3.zero;
        foreach (Vector3 input in inputHistory)
        {
            smoothedInput += input;
        }
        smoothedInput /= inputHistory.Count;

        // 3. 应用死区
        if (smoothedInput.magnitude < deadzone)
        {
            smoothedInput = Vector3.zero;
        }

        // --- 【终极重力兼容方案：修改速度】 ---
        
        // A. 计算你的身体想让小球去到的目标 X 和 Z 坐标
        float targetX = smoothedInput.x * maxReach;
        float targetZ = smoothedInput.z * maxReach;

        // B. 计算弹簧拉力：目标位置离小球当前位置越远，拉拽的速度就越快
        float velocityX = (targetX - rb.position.x) * springForce;
        float velocityZ = (targetZ - rb.position.z) * springForce;

        // C. 将速度赋给刚体！注意：rb.velocity.y 保持原样，让重力自由发挥作用！
        rb.linearVelocity = new Vector3(velocityX, rb.linearVelocity.y, velocityZ);
    }

}
