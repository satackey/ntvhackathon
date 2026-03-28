using System.Collections.Generic;
using System.Threading;
using Cysharp.Threading.Tasks;
using TMPro;
using UnityEngine;

namespace Game
{
    /// <summary>
    /// UI cell that positions one or more 3D items in world space so they appear
    /// centered within this cell, even though the UI camera and 3D camera are different.
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

        [Tooltip("Initial rotation applied to items when placed in this cell.")]
        [SerializeField] private Vector3 _itemRotation = Vector3.zero;

        [Header("Animation")]
        [Tooltip("Duration in seconds for the SetItemAsync lerp animation.")]
        [SerializeField] private float _animationDuration = 0.5f;

        [Tooltip("Animation curve controlling the lerp. Values beyond 0-1 allow overshoot.")]
        [SerializeField] private AnimationCurve _animationCurve = new AnimationCurve(
            new Keyframe(0f, 0f, 0f, 2f),
            new Keyframe(1f, 1f, 0f, 0f)
        );

        private RectTransform _rectTransform;
        private readonly List<Transform> _items = new List<Transform>();
        
        [SerializeField] private TMP_Text _itemCountText;
        private bool _isAnimating;

        /// <summary>The plane id this cell is showing.</summary>
        public PlaneId PlaneId { get; private set; }

        /// <summary>How many items this cell currently holds.</summary>
        public int ItemCount => _items.Count;

        /// <summary>
        /// Initialize the cell for a specific plane id and count.
        /// </summary>
        public void Setup(PlaneId planeId, int count)
        {
            PlaneId = planeId;
            UpdateCount(count);
        }

        /// <summary>
        /// Inject camera references. Call this right after Instantiate
        /// when the cameras aren't baked into the prefab.
        /// </summary>
        public void Init(Camera uiCamera, Camera worldCamera = null)
        {
            _uiCamera = uiCamera;
            _worldCamera = worldCamera != null ? worldCamera : uiCamera;
        }

        /// <summary>
        /// Update the displayed count text.
        /// </summary>
        public void UpdateCount(int count)
        {
            if (_itemCountText != null)
                _itemCountText.text = count.ToString();
        }

        private void Awake()
        {
            _rectTransform = GetComponent<RectTransform>();
            if (_worldCamera == null)
                _worldCamera = _uiCamera;
        }

        /// <summary>
        /// Add a 3D item to this cell. The item will be repositioned every
        /// frame so that it stays visually centered on the cell.
        /// All items remain active.
        /// </summary>
        public void AddItem(Transform item)
        {

            _items.Add(item);
            item.gameObject.SetActive(true);
            item.rotation = Quaternion.Euler(_itemRotation);
            UpdateItemPosition(item);
        }

        /// <summary>
        /// Convenience overload – replaces all items with a single one.
        /// </summary>
        public void SetItem(Transform item)
        {
            ClearItems();
            AddItem(item);
        }

        /// <summary>
        /// Add a 3D item to this cell with an animated lerp from its current
        /// position to the cell target.
        /// </summary>
        public async UniTask AddItemAsync(Transform item, CancellationToken ct = default)
        {

            _items.Add(item);
            item.gameObject.SetActive(true);

            Vector3 startPosition = item.position;
            Quaternion startRotation = item.rotation;
            Quaternion targetRotation = Quaternion.Euler(_itemRotation);
            Vector3 startScale = item.localScale;
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
                item.position = Vector3.LerpUnclamped(startPosition, targetPosition, curveValue);
                item.rotation = Quaternion.LerpUnclamped(startRotation, targetRotation, curveValue);
                item.localScale = Vector3.LerpUnclamped(startScale, targetScale, curveValue);

                await UniTask.Yield(PlayerLoopTiming.PostLateUpdate, ct);
            }

            _isAnimating = false;
            UpdateItemPosition(item);
        }

        /// <summary>
        /// Convenience overload – replaces all items with a single one, animated.
        /// </summary>
        public async UniTask SetItemAsync(Transform item, CancellationToken ct = default)
        {
            ClearItems();
            await AddItemAsync(item, ct);
        }

        /// <summary>
        /// Remove a specific item from this cell (hides it).
        /// </summary>
        public void RemoveItem(Transform item)
        {
            if (item == null) return;

            item.gameObject.SetActive(false);
            _items.Remove(item);
        }

        /// <summary>
        /// Remove all items from this cell (hides them).
        /// </summary>
        public void ClearItems()
        {
            foreach (var item in _items)
            {
                if (item != null)
                    item.gameObject.SetActive(false);
            }
            _items.Clear();
        }

        /// <summary>
        /// Legacy alias for <see cref="ClearItems"/>.
        /// </summary>
        public void ClearItem() => ClearItems();

        private void LateUpdate()
        {
            if (_items.Count > 0 && !_isAnimating)
            {
                foreach (var item in _items)
                {
                    if (item != null)
                        UpdateItemPosition(item);
                }
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

        private void UpdateItemPosition(Transform item)
        {
            item.position = GetCellWorldPosition();
            item.rotation = Quaternion.Euler(_itemRotation);
            item.localScale = Vector3.one * _itemScale;
        }
    }
}