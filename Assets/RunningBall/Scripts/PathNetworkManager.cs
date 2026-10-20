using UnityEngine;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

public class PathNetworkManager : MonoBehaviour
{
    [Header("网络配置 (专属独立端口)")]
    public string pythonIP = "127.0.0.1";
    public int sendPort = 5007;   // 发给 Python 的端口
    public int listenPort = 5008; // 监听 Python 的端口
    public float sendRate = 50f; 
    
    [Header("引用")]
    public PathFollowingGame pathGame;

    private UdpClient udpSender;
    private UdpClient udpReceiver;
    private Thread receiveThread;
    private float nextSendTime = 0f;

    private readonly object dataLock = new object();
    private string pendingJsonData = null;
    public int currentAIDifficulty = 1;

    [System.Serializable]
    public class PathTelemetryData
    {
        public float time;
        public float copX;
        public float targetX;
        public int passedCount; 
    }

    [System.Serializable]
    public class AICommandPacket
    {
        public string type;
        public int difficulty; 
        public float rmse; 
    }

    void Start()
    {
        if (pathGame == null) pathGame = FindObjectOfType<PathFollowingGame>();

        udpSender = new UdpClient();
        try 
        {
            IPEndPoint localEndPoint = new IPEndPoint(IPAddress.Parse("127.0.0.1"), listenPort);
            udpReceiver = new UdpClient(localEndPoint);
            receiveThread = new Thread(new ThreadStart(ReceiveDataLoop));
            receiveThread.IsBackground = true;
            receiveThread.Start();
            Debug.Log("<color=green>[Path Network] Dedicated bidirectional UDP channel (5007/5008) started.</color>");
        }
        catch (System.Exception e) { Debug.LogError($"Receiver startup failed: {e.Message}"); }
    }

    void Update()
    {
        // 1. 定时发送数据给 Python
        if (pathGame != null && Time.time >= nextSendTime)
        {
            SendData();
            nextSendTime = Time.time + (1f / sendRate);
        }

        // 2. 解析 Python 传回的 JSON 指令
        string jsonToParse = null;
        lock (dataLock)
        {
            if (!string.IsNullOrEmpty(pendingJsonData))
            {
                jsonToParse = pendingJsonData;
                pendingJsonData = null; 
            }
        }

        if (jsonToParse != null)
        {
            try
            {
                AICommandPacket aiPacket = JsonUtility.FromJson<AICommandPacket>(jsonToParse);
                if (aiPacket.type == "realtime" || string.IsNullOrEmpty(aiPacket.type))
                {
                    currentAIDifficulty = aiPacket.difficulty;
                    // 让游戏本体根据 AI 的指示平滑改变路况
                    if (pathGame != null)
                    {
                        pathGame.ApplyAIDifficulty(currentAIDifficulty);
                    }
                }
            }
            catch (System.Exception e) { Debug.LogWarning($"Packet parse failed: {e.Message}"); }
        }
    }

    void SendData()
    {
        try
        {
            float playerX = pathGame.GetPlayerX(); 
            float targetX = pathGame.GetTargetX();
            int distance = pathGame.GetDistance(); // 将跑过的距离当作层数发过去

            PathTelemetryData data = new PathTelemetryData
            {
                time = Time.time,
                copX = playerX, 
                targetX = targetX, 
                passedCount = distance 
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
                lock (dataLock) { pendingJsonData = rawJson; }
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