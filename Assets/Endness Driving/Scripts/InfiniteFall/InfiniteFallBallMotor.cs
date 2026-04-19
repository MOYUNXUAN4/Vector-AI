using UnityEngine;

public class InfiniteFallBallMotor : MonoBehaviour
{
    private Rigidbody _rb;
    private InfiniteFallConfig _config;
    private float _tiltX;
    private float _tiltZ;
    private float _worldRadius;

    public Vector3 Position => _rb != null ? _rb.position : transform.position;
    public Vector3 Velocity => _rb != null ? _rb.linearVelocity : Vector3.zero;
    public Quaternion CurrentTilt => Quaternion.Euler(_tiltX * Mathf.Rad2Deg, 0f, _tiltZ * Mathf.Rad2Deg);
    public float WorldRadius => _worldRadius > 0f ? _worldRadius : (_config != null ? _config.ballRadius : 0.25f);

    public void Initialize(InfiniteFallConfig config)
    {
        _config = config;
        _rb = GetComponent<Rigidbody>();
        if (_rb == null) _rb = gameObject.AddComponent<Rigidbody>();
        _rb.isKinematic = false;
        _rb.useGravity = true;
        _rb.mass = 1f;
        _rb.linearDamping = _config.linearDamping;
        _rb.angularDamping = _config.angularDamping;
        _rb.interpolation = RigidbodyInterpolation.Interpolate;
        _rb.collisionDetectionMode = CollisionDetectionMode.ContinuousDynamic;
        _rb.constraints = RigidbodyConstraints.FreezeRotation;

        SphereCollider sphere = GetComponent<SphereCollider>();
        if (sphere == null) sphere = gameObject.AddComponent<SphereCollider>();
        sphere.isTrigger = false;
        if (sphere.radius <= 0.0001f) sphere.radius = _config.ballRadius;
        _worldRadius = sphere.radius * Mathf.Max(transform.lossyScale.x, transform.lossyScale.y, transform.lossyScale.z);
        Renderer rd = GetComponentInChildren<Renderer>();
        if (rd != null)
            _worldRadius = Mathf.Max(_worldRadius, rd.bounds.extents.y);
    }

    public void Respawn(Vector3 worldPosition)
    {
        if (_rb == null) return;
        _rb.position = worldPosition;
        _rb.linearVelocity = Vector3.zero;
        _rb.angularVelocity = Vector3.zero;
        _tiltX = 0f;
        _tiltZ = 0f;
    }

    public void TickInput(float dt)
    {
        bool pressed = Input.GetMouseButton(0);
        if (pressed)
        {
            float inputX = (Input.mousePosition.x - Screen.width * 0.5f) * _config.tiltInputScale;
            float inputY = (Input.mousePosition.y - Screen.height * 0.5f) * _config.tiltInputScale;
            _tiltX = Mathf.Lerp(_tiltX, Mathf.Clamp(-inputY * 1.5f, -_config.maxTiltRadians, _config.maxTiltRadians), _config.tiltLerp);
            _tiltZ = Mathf.Lerp(_tiltZ, Mathf.Clamp(inputX * 1.5f, -_config.maxTiltRadians, _config.maxTiltRadians), _config.tiltLerp);
        }
        else
        {
            _tiltX = Mathf.Lerp(_tiltX, 0f, _config.tiltLerp);
            _tiltZ = Mathf.Lerp(_tiltZ, 0f, _config.tiltLerp);
        }

        Vector3 assist = new Vector3(Mathf.Sin(_tiltZ), 0f, -Mathf.Sin(_tiltX)) * _config.tiltAssistForce;
        _rb.AddForce(assist, ForceMode.Acceleration);

        Vector3 v = _rb.linearVelocity;
        Vector3 hv = new Vector3(v.x, 0f, v.z);
        if (hv.magnitude > _config.maxHorizontalSpeed)
        {
            hv = hv.normalized * _config.maxHorizontalSpeed;
            _rb.linearVelocity = new Vector3(hv.x, v.y, hv.z);
        }
    }

    public void SetState(Vector3 position, Vector3 velocity)
    {
        if (_rb == null) return;
        _rb.position = position;
        _rb.linearVelocity = velocity;
    }
}
