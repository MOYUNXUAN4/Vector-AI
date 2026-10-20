using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

/// <summary>
/// 开车躲避游戏专属 UDP 通信枢纽
/// 负责发送摇晃度（映射为 RMSE），并接收 Q-Learning 下发的难度。
/// </summary>
public class UDPCarNetworkManager : MonoBehaviour
{
    [Header("🔌 UDP 网络设置")]
    public string pythonIP = "127.0.0.1";
    public int sendPort = 5007;     // 发送给 Python 的端口
    public int receivePort = 5008;  // 接收 Python 数据的端口

    [Header("⚙️ 性能与发送设置")]
    public float sendRate = 50f; 
    private float nextSendTime = 0f;
    private float sessionStartTime = 0f;

    [Header("🔗 核心引用")]
    public string playerName = "Player_Car"; 
    [Tooltip("拖入挂载了 AICarSpawner 的物体")]
    public AICarSpawner carSpawner; 

    public int CurrentDifficulty => carSpawner != null ? carSpawner.currentDifficultyLevel : 1;
    public float CurrentRMSE => currentRMSE;

    // 网络底层变量
    private UdpClient udpSender;
    private UdpClient udpReceiver;
    private Thread receiveThread;
    private bool isRunning = true;

    // 主线程队列：用于接收子线程传来的难度
    private int pendingDifficulty = -1;
    private bool hasNewDifficulty = false;
    private object lockObj = new object();
    private int lastLoggedReceivedDifficulty = -1;
    private int lastAppliedDifficulty = -1;
    private float currentRMSE = 0f;
    private string pendingAIReportContent = null;
    private bool hasNewAIReportContent = false;
    private UIHandler uiHandler;

    void Start()
    {
        // 1. 初始化发送端
        udpSender = new UdpClient();
        sessionStartTime = Time.time;
        playerName = ResolvePlayerName();

        // 2. 自动寻找引用防呆设计
        if (carSpawner == null)
        {
            carSpawner = FindObjectOfType<AICarSpawner>();
            if (carSpawner == null) Debug.LogError("【严重错误】场景里找不到 AICarSpawner，请检查！");
        }

        uiHandler = FindObjectOfType<UIHandler>();

        // 3. 发送启动信号给 Python
        SendStartSessionCommand();

        // 4. 启动接收子线程
        StartReceiverThread();

        Debug.Log($"<color=cyan>🚗 车载 AI UDP 枢纽启动 | TX:{sendPort} RX:{receivePort}</color>");
    }

    void Update()
    {
        // ==========================================
        // 发送逻辑 (按照 50Hz 频率发送)
        // ==========================================
        if (carSpawner != null && Time.time >= nextSendTime)
        {
            SendDataToPython();
            nextSendTime = Time.time + (1f / sendRate);
        }

        // ==========================================
        // 接收逻辑 (在 Unity 主线程应用修改)
        // ==========================================
        if (hasNewDifficulty)
        {
            int newDiff = 1;
            lock (lockObj)
            {
                newDiff = pendingDifficulty;
                hasNewDifficulty = false;
            }

            if (carSpawner != null)
            {
                carSpawner.SetDifficultyFromBackend(newDiff);

                if (newDiff != lastAppliedDifficulty)
                {
                    lastAppliedDifficulty = newDiff;
                    Debug.Log($"<color=green>🚗 [UDP] Applied backend difficulty Level {newDiff}</color>");
                }
            }
        }

        if (hasNewAIReportContent)
        {
            string content = null;
            lock (lockObj)
            {
                content = pendingAIReportContent;
                pendingAIReportContent = null;
                hasNewAIReportContent = false;
            }

            if (!string.IsNullOrEmpty(content))
            {
                if (uiHandler == null)
                    uiHandler = FindObjectOfType<UIHandler>();

                if (uiHandler != null)
                    uiHandler.ReceiveAIResponse(content);
            }
        }
    }

    // ==========================================
    // 发送数据打包逻辑
    // ==========================================
    public void RequestReport(int passedCount)
    {
        SendJsonToPython($"{{\"command\":\"generate_report\",\"passedCount\":{passedCount}}}");
    }

    public void SendChatMessage(string message)
    {
        string escaped = message.Replace("\\", "\\\\").Replace("\"", "\\\"");
        SendJsonToPython($"{{\"command\":\"chat\",\"message\":\"{escaped}\"}}");
    }

    void SendJsonToPython(string json)
    {
        try
        {
            byte[] bytes = Encoding.UTF8.GetBytes(json);
            udpSender.Send(bytes, bytes.Length, pythonIP, sendPort);
        }
        catch (System.Exception e) { Debug.LogWarning("发送指令失败: " + e.Message); }
    }

    void SendStartSessionCommand()
    {
        string json = $"{{\"command\": \"start_session\", \"nickname\": \"{playerName}\"}}";
        byte[] bytes = Encoding.UTF8.GetBytes(json);
        udpSender.Send(bytes, bytes.Length, pythonIP, sendPort);
    }

    string ResolvePlayerName()
    {
        string cachedName = PlayerPrefs.GetString("CurrentPlayer", string.Empty).Trim();
        if (!string.IsNullOrEmpty(cachedName))
            return cachedName;

        return string.IsNullOrWhiteSpace(playerName) ? "Guest" : playerName.Trim();
    }

    void SendDataToPython()
    {
        try
        {
            // 【核心魔法转换】
            // 1. 将 0~100 的 Jitter 缩小 20 倍，伪装成 X 坐标偏移量
            float fakeCopX = carSpawner.playerCopJitter / 20f;
            
            // 2. 将存活秒数乘以 10，伪装成经过的距离
            // 这样每活 5 秒，刚好经过 50 单位距离，触发 Python 的周期评估！
            int calculatedDistance = Mathf.FloorToInt((Time.time - sessionStartTime) * 10f);

            // 构造符合 Python Q-Learning 要求的物理数据包
            CarTelemetryData data = new CarTelemetryData
            {
                time = Time.time,
                copX = fakeCopX,   // Jitter 伪装
                targetX = 0.0f,    // 目标永远为 0
                pathWidth = 10.0f, // 保持恒定容差
                passedCount = calculatedDistance // 存活时间伪装
            };

            string jsonString = JsonUtility.ToJson(data);
            byte[] bytes = Encoding.UTF8.GetBytes(jsonString);
            udpSender.Send(bytes, bytes.Length, pythonIP, sendPort);
        }
        catch (System.Exception e) { Debug.LogWarning("发送数据失败: " + e.Message); }
    }

    // ==========================================
    // 接收后台 Q-Learning 数据的子线程
    // ==========================================
    void StartReceiverThread()
    {
        receiveThread = new Thread(new ThreadStart(ReceiveData));
        receiveThread.IsBackground = true;
        receiveThread.Start();
    }

    void ReceiveData()
    {
        udpReceiver = new UdpClient(receivePort);
        IPEndPoint anyIP = new IPEndPoint(IPAddress.Any, receivePort);

        while (isRunning)
        {
            try
            {
                byte[] data = udpReceiver.Receive(ref anyIP);
                string text = Encoding.UTF8.GetString(data);
                
                // 解析 Python 发来的 Json
                PythonResponse response = JsonUtility.FromJson<PythonResponse>(text);

                if (response != null && response.type == "ai_report")
                {
                    lock (lockObj)
                    {
                        pendingAIReportContent = response.content;
                        hasNewAIReportContent = true;
                    }
                }
                else if (response != null && (response.type == "realtime" || string.IsNullOrEmpty(response.type)))
                {
                    lock (lockObj)
                    {
                        pendingDifficulty = response.difficulty;
                        hasNewDifficulty = true;
                        currentRMSE = response.rmse;
                    }

                    if (response.difficulty != lastLoggedReceivedDifficulty)
                    {
                        lastLoggedReceivedDifficulty = response.difficulty;
                        Debug.Log($"<color=cyan>🚗 [UDP] Received difficulty packet Level {response.difficulty} | RMSE {response.rmse:F2}</color>");
                    }
                }
            }
            catch (SocketException) { /* 忽略正常的关闭异常 */ }
            catch (ThreadAbortException) { /* 忽略线程被关闭时的异常 */ }
            catch (System.ObjectDisposedException) { /* 忽略 socket 关闭时的异常 */ }
            catch (System.Exception err) { Debug.LogError("接收异常: " + err.ToString()); }
        }
    }

    private void OnApplicationQuit()
    {
        ShutdownReceiver();
    }

    private void OnDestroy()
    {
        ShutdownReceiver();
    }

    void ShutdownReceiver()
    {
        if (!isRunning) return;

        isRunning = false;

        if (udpReceiver != null)
        {
            udpReceiver.Close();
            udpReceiver = null;
        }

        if (udpSender != null)
        {
            udpSender.Close();
            udpSender = null;
        }

        if (receiveThread != null)
        {
            if (receiveThread.IsAlive)
                receiveThread.Join(100);

            receiveThread = null;
        }
    }
}

// ==========================================
// 数据结构定义
// ==========================================
[System.Serializable]
public class CarTelemetryData
{
    public float time;
    public float copX;
    public float targetX; 
    public float pathWidth; 
    public int passedCount; 
}

[System.Serializable]
public class PythonResponse
{
    public string type;
    public int difficulty;
    public float rmse;
    public string content;
}
