using UnityEngine;

public class InfiniteFallCameraFollow : MonoBehaviour
{
    private Camera _camera;
    private Transform _target;
    private InfiniteFallConfig _config;
    private float _visualY;

    public float VisualY => _visualY;

    public void Initialize(Camera cam, Transform target, InfiniteFallConfig config)
    {
        _camera = cam;
        _target = target;
        _config = config;
        _visualY = target.position.y;
    }

    public void Tick(float dt, bool isFalling)
    {
        if (_camera == null || _target == null) return;

        float targetY = _target.position.y;
        if (isFalling) targetY += _config.cameraFallLookAhead;
        _visualY = Mathf.Lerp(_visualY, targetY, 1f - Mathf.Exp(-_config.cameraSmooth * dt));

        Vector3 lookTarget = new Vector3(_target.position.x, _visualY, _target.position.z);
        _camera.transform.position = lookTarget + _config.cameraOffset;
        _camera.transform.LookAt(lookTarget + Vector3.up * 0.7f);
    }
}
