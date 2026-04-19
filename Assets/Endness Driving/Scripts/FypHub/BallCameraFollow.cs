using UnityEngine;

public class BallCameraFollow : MonoBehaviour
{
    Transform _target;

    [SerializeField] Vector3 offset = new Vector3(0f, 11f, -12f);
    [SerializeField] float smooth = 6f;

    public void Bind(Transform target)
    {
        _target = target;
    }

    void LateUpdate()
    {
        if (_target == null)
            return;

        var wanted = _target.position + offset;
        transform.position = Vector3.Lerp(transform.position, wanted, 1f - Mathf.Exp(-smooth * Time.deltaTime));
        transform.LookAt(_target.position + Vector3.up * 0.35f, Vector3.up);
    }
}
