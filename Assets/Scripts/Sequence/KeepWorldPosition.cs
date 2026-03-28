using UnityEngine;

namespace Sequence
{
    /// <summary>
    /// Keeps this transform at a fixed world position even if its parent moves, rotates, or scales.
    /// </summary>
    [ExecuteAlways]
    [DefaultExecutionOrder(10000)]
    public class KeepWorldPosition : MonoBehaviour
    {
        [SerializeField] private bool _capturePositionOnEnable = true;
        [SerializeField] private Vector3 _lockedWorldPosition;
        [SerializeField] private Quaternion _lockedWorldRotation = Quaternion.identity;

        private void Reset()
        {
            CaptureCurrentTransform();
        }

        private void OnEnable()
        {
            if (_capturePositionOnEnable)
            {
                CaptureCurrentTransform();
            }

            ApplyLockedTransform();
        }

        private void LateUpdate()
        {
            ApplyLockedTransform();
        }

        [ContextMenu("Capture Current Transform")]
        public void CaptureCurrentTransform()
        {
            CaptureCurrentPosition();
            CaptureCurrentRotation();
        }

        public void CaptureCurrentPosition()
        {
            _lockedWorldPosition = transform.position;
        }

        public void CaptureCurrentRotation()
        {
            _lockedWorldRotation = transform.rotation;
        }

        public void SetLockedWorldPosition(Vector3 worldPosition)
        {
            _lockedWorldPosition = worldPosition;
            ApplyLockedTransform();
        }

        public void SetLockedWorldRotation(Quaternion worldRotation)
        {
            _lockedWorldRotation = worldRotation;
            ApplyLockedTransform();
        }

        private void ApplyLockedTransform()
        {
            if (transform.position != _lockedWorldPosition)
            {
                transform.position = _lockedWorldPosition;
            }

            if (transform.rotation != _lockedWorldRotation)
            {
                transform.rotation = _lockedWorldRotation;
            }
        }
    }
}

