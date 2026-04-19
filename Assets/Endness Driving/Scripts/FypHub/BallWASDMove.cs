using UnityEngine;

[RequireComponent(typeof(Rigidbody))]
public class BallWASDMove : MonoBehaviour
{
    [SerializeField] float moveForce = 28f;
    [SerializeField] float maxHorizontalSpeed = 14f;
    [SerializeField] float fallY = -6f;
    [SerializeField] Vector3 respawnPosition = new Vector3(0f, 0.45f, 0f);

    Rigidbody _rb;

    void Awake()
    {
        _rb = GetComponent<Rigidbody>();
    }

    void FixedUpdate()
    {
        float x = Input.GetAxisRaw("Horizontal");
        float z = Input.GetAxisRaw("Vertical");
        var dir = new Vector3(x, 0f, z);
        if (dir.sqrMagnitude > 1f)
            dir.Normalize();

        if (dir.sqrMagnitude > 0.01f)
            _rb.AddForce(dir * moveForce, ForceMode.Force);

        var v = _rb.linearVelocity;
        var hv = new Vector3(v.x, 0f, v.z);
        if (hv.magnitude > maxHorizontalSpeed)
        {
            hv = hv.normalized * maxHorizontalSpeed;
            _rb.linearVelocity = new Vector3(hv.x, v.y, hv.z);
        }

        if (transform.position.y < fallY)
        {
            _rb.linearVelocity = Vector3.zero;
            _rb.angularVelocity = Vector3.zero;
            transform.position = respawnPosition;
        }
    }
}
