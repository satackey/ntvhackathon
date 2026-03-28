using UnityEngine;

namespace Game
{
    /// <summary>
    /// UI cell that positions a 3D item in world space so it appears centered
    /// within this cell, even though the UI camera and 3D camera are different.
    /// </summary>
    [RequireComponent(typeof(RectTransform))]
    public class InventoryViewCell : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private Camera _uiCamera;
        [Tooltip("If left empty, defaults to the UI camera.")]
        [SerializeField] private Camera _worldCamera;

        [Header("Settings")]
        [Tooltip("Distance from the world camera at which the 3D item is placed.")]
        [SerializeField] private float _itemDistance = 5f;

        [Tooltip("Uniform scale applied to the 3D item when displayed in this cell.")]
        [SerializeField] private float _itemScale = 1f;

        private RectTransform _rectTransform;
        [SerializeField] private Transform _currentItem;

        private void Awake()
        {
            _rectTransform = GetComponent<RectTransform>();
            if (_worldCamera == null)
                _worldCamera = _uiCamera;
        }

        /// <summary>
        /// Assign a 3D item to this cell.  The item will be repositioned every
        /// frame so that it stays visually centered on the cell.
        /// </summary>
        public void SetItem(Transform item)
        {
            if (_currentItem != null)
            {
                _currentItem.gameObject.SetActive(false);
            }

            _currentItem = item;

            if (_currentItem != null)
            {
                _currentItem.gameObject.SetActive(true);
                _currentItem.localScale = Vector3.one * _itemScale;
                UpdateItemPosition();
            }
        }

        /// <summary>
        /// Remove the current item from this cell (hides it).
        /// </summary>
        public void ClearItem()
        {
            if (_currentItem != null)
            {
                _currentItem.gameObject.SetActive(false);
                _currentItem = null;
            }
        }

        private void LateUpdate()
        {
            if (_currentItem != null)
            {
                UpdateItemPosition();
            }
        }

        /// <summary>
        /// Converts the center of this UI cell from screen space (via the UI camera)
        /// into a world-space position in front of the 3D camera, so the item
        /// looks like it's sitting inside the cell.
        /// </summary>
        private void UpdateItemPosition()
        {
            // 1. Get the screen-space center of this RectTransform.
            Vector3 screenPoint = RectTransformUtility.WorldToScreenPoint(_uiCamera, _rectTransform.position);

            // 2. Cast a ray from the world camera through that screen point.
            Ray ray = _worldCamera.ScreenPointToRay(screenPoint);

            // 3. Place the 3D item at the desired distance along that ray.
            _currentItem.position = ray.GetPoint(_itemDistance);

            // Optionally face the camera so the item always looks nice.
            _currentItem.rotation = Quaternion.LookRotation(
                _currentItem.position - _worldCamera.transform.position,
                _worldCamera.transform.up
            );
        }
    }
}