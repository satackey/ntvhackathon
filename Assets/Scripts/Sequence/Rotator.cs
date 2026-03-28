using UnityEngine;

namespace Sequence
{
    [ExecuteAlways]
    public class Rotator : MonoBehaviour
    {
        [SerializeField] private Vector3 _degreesPerSecond = new Vector3(0f, 0f, 0f);
        [SerializeField] private Space _space = Space.Self;

        private void Update()
        {
            transform.Rotate(_degreesPerSecond * Time.deltaTime, _space);
        }
    }
}