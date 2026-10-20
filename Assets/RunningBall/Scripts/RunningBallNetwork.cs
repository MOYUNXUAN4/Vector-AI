using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Collections.Generic;

public class RunningBallNetwork : MonoBehaviour
{
    [Header("网络配置 (专属 5007/5008 端口)")]
    public string pythonIP = "127.0.0.1";
    public int sendPort = 5007;   
    public int listenPort = 5008; 
    public float sendRate = 50f; 
    
    [Header("绑定脚本")]
    public runningballPlayerContral playerControl;
    public PathGenerator pathGen;

    private UdpClient udpSender;
    private UdpClient udpReceiver;
    private Thread receiveThread;
    private float nextSendTime = 0f;

    private readonly object dataLock = new object();
    private Queue<string> packetQueue = new Queue<string>();

    public int currentAIDifficulty = 1;
    public float currentRMSE = 0f;

    [System.Serializable]
    public class TelemetryData
    {
        public float time;
        public float copX;
        public float targetX;
        public float pathWidth;
        public int passedCount; 
    }

    [System.Serializable]
    public class AICommandPacket
    {
        public string type;
        public int difficulty; 
        public float rmse; 
        public string content; 
    }

    void Start()
    {
        udpSender = new UdpClient();
        try 
        {
            IPEndPoint localEndPoint = new IPEndPoint(IPAddress.Parse("127.0.0.1"), listenPort);
            udpReceiver = new UdpClient(localEndPoint);
            receiveThread = new Thread(new ThreadStart(ReceiveDataLoop));
            receiveThread.IsBackground = true;
            receiveThread.Start();
            
            // ==========================================
            // 💡 【核心新增】：向 Python 报到，激活专属记忆
            // ==========================================
            string playerName = PlayerPrefs.GetString("CurrentPlayer", "Guest");
            string startMsg = $"{{\"command\": \"start_session\", \"nickname\": \"{playerName}\"}}";
            byte[] bytes = Encoding.UTF8.GetBytes(startMsg);
            udpSender.Send(bytes, bytes.Length, pythonIP, sendPort);

            Debug.Log($"<color=green>[Running Ball AI Channel] Connected to backend on port 5007. Player: {playerName}</color>");
        }
        catch (System.Exception e) { Debug.LogError($"Network startup failed: {e.Message}"); }
    }

    void Update()
    {
        if (playerControl != null && pathGen != null && Time.time >= nextSendTime)
        {
            SendData();
            nextSendTime = Time.time + (1f / sendRate);
        }

        lock (dataLock)
        {
            while (packetQueue.Count > 0)
            {
                string jsonToParse = packetQueue.Dequeue();
                try
                {
                    AICommandPacket aiPacket = JsonUtility.FromJson<AICommandPacket>(jsonToParse);
                    
                    if (aiPacket.type == "ai_report")
                    {
                        if (runningbollUiManager.Instance != null)
                        {
                            runningbollUiManager.Instance.ReceiveAIResponse(aiPacket.content);
                        }
                    }
                    else if (aiPacket.type == "realtime" || string.IsNullOrEmpty(aiPacket.type))
                    {
                        currentAIDifficulty = aiPacket.difficulty;
                        currentRMSE = aiPacket.rmse; 
                        if (pathGen != null) pathGen.ApplyAIDifficulty(currentAIDifficulty);
                    }
                }
                catch { }
            }
        }
    }

    void SendData()
    {
        try
        {
            TelemetryData data = new TelemetryData
            {
                time = Time.time,
                copX = playerControl.GetPlayerX(), 
                targetX = playerControl.GetTargetX(),
                pathWidth = pathGen.pathWidth,
                passedCount = playerControl.GetDistance() 
            };

            string jsonString = JsonUtility.ToJson(data);
            byte[] bytes = Encoding.UTF8.GetBytes(jsonString);
            udpSender.Send(bytes, bytes.Length, pythonIP, sendPort);
        }
        catch { }
    }

    private void ReceiveDataLoop()
    {
        IPEndPoint remoteEndPoint = new IPEndPoint(IPAddress.Any, 0);
        while (true)
        {
            try
            {
                byte[] data = udpReceiver.Receive(ref remoteEndPoint);
                string rawJson = Encoding.UTF8.GetString(data);
                lock (dataLock) { packetQueue.Enqueue(rawJson); }
            }
            catch { }
        }
    }

    private void OnDestroy()
    {
        if (receiveThread != null && receiveThread.IsAlive) receiveThread.Abort();
        if (udpReceiver != null) udpReceiver.Close();
        if (udpSender != null) udpSender.Close();
    }
}