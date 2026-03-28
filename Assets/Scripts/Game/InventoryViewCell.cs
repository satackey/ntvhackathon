using System.Threading;
using Cysharp.Threading.Tasks;
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

        [Tooltip("World-space offset applied to the item after positioning.")]
        [SerializeField] private Vector3 _itemOffset = Vector3.zero;

        [Header("Animation")]
        [Tooltip("Duration in seconds for the SetItemAsync lerp animation.")]
        [SerializeField] private float _animationDuration = 0.5f;

        [Tooltip("Animation curve controlling the lerp. Values beyond 0-1 allow overshoot.")]
        [SerializeField] private AnimationCurve _animationCurve = new AnimationCurve(
            new Keyframe(0f, 0f, 0f, 2f),
            new Keyframe(1f, 1f, 0f, 0f)
        );

        private RectTransform _rectTransform;
        [SerializeField] private Transform _currentItem;
        private bool _isAnimating;

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
                UpdateItemPosition();
            }
        }

        /// <summary>
        /// Assign a 3D item to this cell with an animated lerp from its current
        /// position to the cell target. Uses <see cref="_animationCurve"/> and
        /// <see cref="_animationDuration"/>. The curve may overshoot (values &gt; 1).
        /// </summary>
        public async UniTask SetItemAsync(Transform item, CancellationToken ct = default)
        {
            if (_currentItem != null)
            {
                _currentItem.gameObject.SetActive(false);
            }

            _currentItem = item;

            if (_currentItem == null)
                return;

            _currentItem.gameObject.SetActive(true);

            Vector3 startPosition = _currentItem.position;
            Vector3 startScale = _currentItem.localScale;
            Vector3 targetScale = Vector3.one * _itemScale;

            _isAnimating = true;
            float elapsed = 0f;

            while (elapsed < _animationDuration)
            {
                ct.ThrowIfCancellationRequested();

                elapsed += Time.deltaTime;
                float t = Mathf.Clamp01(elapsed / _animationDuration);
                float curveValue = _animationCurve.Evaluate(t);

                Vector3 targetPosition = GetCellWorldPosition();
                _currentItem.position = Vector3.LerpUnclamped(startPosition, targetPosition, curveValue);
                _currentItem.localScale = Vector3.LerpUnclamped(startScale, targetScale, curveValue);

                await UniTask.Yield(PlayerLoopTiming.PostLateUpdate, ct);
            }

            _isAnimating = false;
            UpdateItemPosition();
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
            if (_currentItem != null && !_isAnimating)
            {
                UpdateItemPosition();
            }
        }

        /// <summary>
        /// Computes the world-space target position for the cell center.
        /// </summary>
        private Vector3 GetCellWorldPosition()
        {
            Vector3 screenPoint = RectTransformUtility.WorldToScreenPoint(_uiCamera, _rectTransform.position);
            Ray ray = _worldCamera.ScreenPointToRay(screenPoint);
            return ray.GetPoint(_itemDistance) + _itemOffset;
        }

        /// <summary>
        /// Converts the center of this UI cell from screen space (via the UI camera)
        /// into a world-space position in front of the 3D camera, so the item
        /// looks like it's sitting inside the cell.
        /// </summary>
        private void UpdateItemPosition()
        {
            _currentItem.position = GetCellWorldPosition();

            // // Optionally face the camera so the item always looks nice.
            // _currentItem.rotation = Quaternion.LookRotation(
            //     _currentItem.position - _worldCamera.transform.position,
            //     _worldCamera.transform.up
            // );
            
            _currentItem.localScale = Vector3.one * _itemScale;
        }
    }
}