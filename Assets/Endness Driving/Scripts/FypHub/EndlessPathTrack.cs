using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Spawns flat path tiles with random 90° turns; recycles old tiles for an endless track.
/// </summary>
public class EndlessPathTrack : MonoBehaviour
{
    [SerializeField] float tileSize = 2f;
    [SerializeField] float pathThickness = 0.2f;
    [SerializeField] int minStraightTiles = 3;
    [SerializeField] int maxStraightTiles = 8;
    [SerializeField] int maxStoredTiles = 120;
    [SerializeField] float extendAheadDistance = 14f;

    Transform _player;
    Vector3 _gridEnd;
    Vector3 _dir;
    readonly Queue<GameObject> _spawnOrder = new Queue<GameObject>();
    readonly Stack<GameObject> _pool = new Stack<GameObject>();
    Material _pathMat;
    PhysicsMaterial _pathPhys;

    public void Initialize(Transform player)
    {
        _player = player;
        _gridEnd = Vector3.zero;
        _dir = Vector3.forward;

        _pathMat = CreatePathMaterial();
        _pathPhys = new PhysicsMaterial("PathTrackPhys")
        {
            dynamicFriction = 0.8f,
            staticFriction = 0.85f,
            bounciness = 0f,
            frictionCombine = PhysicsMaterialCombine.Maximum,
            bounceCombine = PhysicsMaterialCombine.Minimum
        };
        SpawnTileAt(Vector3.zero);

        for (int i = 0; i < 10; i++)
            ExtendSegment();
    }

    void Update()
    {
        if (_player == null)
            return;
        while (Vector3.Distance(Flat(_player.position), Flat(_gridEnd)) < extendAheadDistance)
            ExtendSegment();
    }

    static Vector3 Flat(Vector3 v) => new Vector3(v.x, 0f, v.z);

    void ExtendSegment()
    {
        int n = Random.Range(minStraightTiles, maxStraightTiles + 1);
        for (int i = 0; i < n; i++)
        {
            _gridEnd += _dir * tileSize;
            SpawnTileAt(_gridEnd);
        }

        _dir = Random.value < 0.5f
            ? new Vector3(_dir.z, 0f, -_dir.x)
            : new Vector3(-_dir.z, 0f, _dir.x);
    }

    void SpawnTileAt(Vector3 xzCenter)
    {
        var tile = GetTile();
        tile.SetActive(true);
        tile.transform.SetParent(transform, false);
        var y = pathThickness * 0.5f;
        tile.transform.position = new Vector3(xzCenter.x, y, xzCenter.z);
        tile.transform.localScale = new Vector3(tileSize, pathThickness, tileSize);
        var r = tile.GetComponent<Renderer>();
        if (r != null)
            r.sharedMaterial = _pathMat;
        var bc = tile.GetComponent<BoxCollider>();
        if (bc != null)
            bc.material = _pathPhys;

        _spawnOrder.Enqueue(tile);

        while (_spawnOrder.Count > maxStoredTiles)
            ReturnToPool(_spawnOrder.Dequeue());
    }

    GameObject GetTile()
    {
        if (_pool.Count > 0)
            return _pool.Pop();

        var cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
        cube.name = "PathTile";
        cube.layer = LayerMask.NameToLayer("Default");
        return cube;
    }

    void ReturnToPool(GameObject go)
    {
        go.SetActive(false);
        go.transform.SetParent(transform, false);
        _pool.Push(go);
    }

    static Material CreatePathMaterial()
    {
        Shader shader = Shader.Find("Universal Render Pipeline/Lit");
        if (shader == null)
            shader = Shader.Find("Standard");
        if (shader == null)
            shader = Shader.Find("Diffuse");

        var c = new Color(0.35f, 0.42f, 0.5f);
        var m = new Material(shader);
        if (m.HasProperty("_BaseColor"))
            m.SetColor("_BaseColor", c);
        else
            m.color = c;
        return m;
    }
}
