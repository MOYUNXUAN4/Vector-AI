using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class RandomizeObject : MonoBehaviour
{
    [SerializeField]
    Vector3 localRotationMin = Vector3.zero;
    [SerializeField]
    Vector3 localRotationMax = Vector3.zero;

    [SerializeField]
    float localscaleMultiplierMin = 0.8f;
    [SerializeField]
    float localscaleMultiplierMax = 1.5f;

    Vector3 localScaleOriginal = Vector3.one;

    private void Start()
    {
        localScaleOriginal = transform.localScale;
    }

    void OnEnable()
    {
        transform.localRotation = Quaternion.Euler(Random.Range(localRotationMin.x, localRotationMax.x), Random.Range(localRotationMin.y, localRotationMax.y), Random.Range(localRotationMin.z, localRotationMax.z));

        transform.localScale = localScaleOriginal * Random.Range(localscaleMultiplierMin, localscaleMultiplierMax);
    }

}
