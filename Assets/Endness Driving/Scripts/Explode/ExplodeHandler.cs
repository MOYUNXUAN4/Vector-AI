using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class ExplodeHandler : MonoBehaviour
{
    [SerializeField]
    GameObject orignalObject;

    [SerializeField]
    GameObject model;

    Rigidbody[] rigidbodies;

    private void Awake()
    {
        rigidbodies = model.GetComponentsInChildren<Rigidbody>(true);
    }

    // Start is called before the first frame update
    void Start()
    {
       //Explode(Vector3.forward);
    }

    public void Explode(Vector3 externalForce)
    {
        orignalObject.SetActive(false);

        foreach (Rigidbody rb in rigidbodies)
        {
            rb.transform.parent = null;

            rb.GetComponent<MeshCollider>().enabled = true;

            rb.gameObject.SetActive(true);
            rb.isKinematic = false;
            rb.interpolation = RigidbodyInterpolation.Interpolate;
            rb.AddForce(Vector3.up * 200 +  externalForce, ForceMode.Force);
            rb.AddTorque(Random.insideUnitSphere * 0.5f, ForceMode.Impulse);

            //Change the tag so other objects can explode after being hit by a carpart
            rb.gameObject.tag = "CarPart";
        }
    }


}
