using UnityEngine;

/// <summary>
/// 平台数据容器：挂载在平台预制体的根节点上。
/// 用于向外部（如 LevelManager 和 UDPManager）提供该平台的关键位置信息。
/// </summary>
public class PlatformData : MonoBehaviour
{
    [Header("目标追踪点")]
    [Tooltip("请将代表洞口中心的空物体 (HoleCenter) 拖拽到这里")]
    public Transform holeCenter;

    [Header("Telemetry Geometry")]
    [Tooltip("Hole inner-edge radius in this platform's local scale. Telemetry only.")]
    [Min(0f)] public float holeRadius = 1.5536f;

    // 导师提示：未来如果你需要在这个平台上加其他特定数据（比如这层的特定得分、特定的障碍物），
    // 都可以统一放在这个数据容器类里，保持代码的整洁和高内聚。
}