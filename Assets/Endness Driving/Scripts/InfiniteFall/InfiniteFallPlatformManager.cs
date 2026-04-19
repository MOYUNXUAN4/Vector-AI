using System.Collections.Generic;
using UnityEngine;

public class InfiniteFallPlatformManager : MonoBehaviour
{
    private readonly List<PlatformData> _platforms = new List<PlatformData>();
    private InfiniteFallConfig _config;
    private Transform _platformPrefab;
    private Transform _spawnRoot;
    private int _pendingScore;

    private struct PlatformData
    {
        public float y;
        public Vector2 center;
        public Vector2 holeCenter;
        public Transform root;
    }

    public void Initialize(InfiniteFallConfig config, Transform platformPrefab, Transform spawnRoot)
    {
        _config = config;
        _platformPrefab = platformPrefab;
        _spawnRoot = spawnRoot;
    }

    public void ResetPlatforms()
    {
        for (int i = 0; i < _platforms.Count; i++)
        {
            if (_platforms[i].root != null) Destroy(_platforms[i].root.gameObject);
        }
        _platforms.Clear();
        _pendingScore = 0;

        int count = Mathf.Max(3, _config.initialLayerCount);
        for (int i = 0; i < count; i++)
            _platforms.Add(CreatePlatform(-i * _config.layerGap));
    }

    public void Tick(float ballY)
    {
        if (_platforms.Count == 0) return;
        PlatformData last = _platforms[_platforms.Count - 1];
        if (ballY < last.y + _config.layerGap * 3f)
        {
            _platforms.Add(CreatePlatform(last.y - _config.layerGap));
            _pendingScore += _config.scorePerLayer;
        }

        PlatformData first = _platforms[0];
        if (first.y > ballY + _config.layerGap * 3f)
        {
            if (first.root != null) Destroy(first.root.gameObject);
            _platforms.RemoveAt(0);
        }
    }

    public int ConsumePendingScore()
    {
        int v = _pendingScore;
        _pendingScore = 0;
        return v;
    }

    public int GetDepth(float ballY)
    {
        return Mathf.Max(0, Mathf.RoundToInt(Mathf.Abs(ballY) / _config.layerGap));
    }

    public bool IsInsideSupport(Vector3 ballPos)
    {
        return IsInsideSupport(ballPos, _config.ballRadius);
    }

    public bool IsInsideSupport(Vector3 ballPos, float ballRadius)
    {
        Vector2 xz = new Vector2(ballPos.x, ballPos.z);
        float yBand = _config.layerGap * 0.65f;

        for (int i = 0; i < _platforms.Count; i++)
        {
            float surfaceY = _platforms[i].y + _config.layerThickness * 0.5f + ballRadius + _config.ballSurfaceLift;
            if (Mathf.Abs(ballPos.y - surfaceY) > yBand) continue;
            if (Vector2.Distance(xz, _platforms[i].center) <= _config.platformRadius + 0.1f)
                return true;
        }

        return false;
    }

    public bool ResolveBallPenetration(ref Vector3 ballPos, ref Vector3 ballVel)
    {
        return ResolveBallPenetration(ref ballPos, ref ballVel, _config.ballRadius);
    }

    public bool ResolveBallPenetration(ref Vector3 ballPos, ref Vector3 ballVel, float ballRadius)
    {
        Vector2 xz = new Vector2(ballPos.x, ballPos.z);
        bool corrected = false;

        for (int i = 0; i < _platforms.Count; i++)
        {
            PlatformData p = _platforms[i];
            Vector2 local = xz - p.center;
            float distCenter = local.magnitude;
            float distHole = Vector2.Distance(local, p.holeCenter);

            if (distCenter >= _config.platformRadius) continue;
            if (distHole < _config.holeRadius * 0.85f) continue;

            float surfaceY = p.y + _config.layerThickness * 0.5f + ballRadius + _config.ballSurfaceLift;
            if (ballPos.y < surfaceY && ballPos.y > surfaceY - 2.5f)
            {
                ballPos.y = surfaceY;
                if (ballVel.y < 0f) ballVel.y = 0f;
                corrected = true;
            }
        }

        return corrected;
    }

    public void ApplyTilt(Quaternion tiltRotation)
    {
        for (int i = 0; i < _platforms.Count; i++)
        {
            if (_platforms[i].root != null) _platforms[i].root.rotation = tiltRotation;
        }
    }

    private PlatformData CreatePlatform(float yPos)
    {
        GameObject root = new GameObject($"Platform_{yPos:0.00}");
        root.transform.SetParent(_spawnRoot, false);

        Vector2 center = Random.insideUnitCircle * _config.platformSpreadRadius;
        Vector2 holeCenter;
        if (Mathf.Approximately(yPos, 0f))
        {
            holeCenter = new Vector2(-1.6f, 0f);
        }
        else
        {
            float angle = Random.Range(0f, Mathf.PI * 2f);
            float minR = Mathf.Max(0.35f, _config.holeRadius + 0.1f);
            float maxR = Mathf.Max(minR, _config.platformRadius - _config.holeRadius - _config.holeEdgePadding);
            float r = Random.Range(minR, maxR);
            holeCenter = new Vector2(Mathf.Cos(angle) * r, Mathf.Sin(angle) * r);
        }

        root.transform.position = new Vector3(center.x, yPos, center.y);

        Transform model = Instantiate(_platformPrefab, root.transform);
        model.name = "PlatformModel";
        model.localPosition = Vector3.zero;
        model.localRotation = Quaternion.identity;
        model.localScale = Vector3.one;
        model.gameObject.SetActive(true);

        Transform holePivot = FindNamedChild(model, "HolePivot");
        if (holePivot == null) holePivot = FindNamedChild(model, "HoleRoot");
        if (holePivot != null)
            holePivot.localPosition = new Vector3(holeCenter.x, holePivot.localPosition.y, holeCenter.y);

        Collider[] cols = model.GetComponentsInChildren<Collider>(true);
        if (cols.Length == 0)
        {
            MeshFilter mf = model.GetComponentInChildren<MeshFilter>(true);
            if (mf != null && mf.sharedMesh != null)
            {
                MeshCollider mc = mf.gameObject.AddComponent<MeshCollider>();
                mc.sharedMesh = mf.sharedMesh;
                mc.convex = false;
            }
        }

        return new PlatformData { y = yPos, center = center, holeCenter = holeCenter, root = root.transform };
    }

    private static Transform FindNamedChild(Transform root, string childName)
    {
        Transform[] all = root.GetComponentsInChildren<Transform>(true);
        for (int i = 0; i < all.Length; i++)
        {
            if (all[i].name == childName) return all[i];
        }
        return null;
    }
}
