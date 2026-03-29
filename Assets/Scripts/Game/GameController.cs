using Cysharp.Threading.Tasks;
using DefaultNamespace;
using TMPro;
using UnityEngine;
using UnityEngine.Playables;
using UnityEngine.InputSystem;

namespace Game
{
    public class GameController : MonoBehaviour
    {
        [SerializeField] private PlayableDirector _faceRightPlayableDirector;
        [SerializeField] private PlayableDirector _beforeInventoryPlayableDirector;
        [SerializeField] private PlayableDirector _resetPlayableDirector;
        [SerializeField] private Transform _planeRoot;
        [SerializeField] private Transform _beforeInventoryStartMarker;
        [SerializeField] private InventoryView _inventoryView;
        [SerializeField] private PlanePrefabRegistry _planePrefabRegistry;
        [SerializeField] private PlayerInventory _playerInventory;
        [SerializeField] private Transform _planeParent;
        [SerializeField] private Video3HitDetector _hitDetector;
        [SerializeField] private TMP_Text _planeDeets;

        [Header("Spawn Markers")]
        [SerializeField] private Transform[] _spawnMarkers;
        [SerializeField] private Camera _camera;

        private Animator _planeAnimator;
        private bool _isPlaying;
        
        // Stores planeRoot's original parent so we can restore it after each play.
        private Transform _originalPlaneRootParent;
        // Runtime-created transform that sits between the original parent and _planeRoot.
        private Transform _spawnOffset;

        private void Awake()
        {
            _planeAnimator = _planeRoot != null ? _planeRoot.GetComponent<Animator>() : null;
            _originalPlaneRootParent = _planeRoot != null ? _planeRoot.parent : null;
        }

        /// <summary>
        /// Call from a Timeline Signal to remove the spawn offset.
        /// Reparents _planeRoot back to its original parent, keeping its current world pose.
        /// </summary>
        public void ResetSpawnOffset()
        {
            _planeRoot.SetParent(_originalPlaneRootParent, true);
            Debug.Log($"[GameController] Spawn offset reset – planeRoot world pos: {_planeRoot.position}");
        }

        [Button]
        public void PlayFaceRight()
        {
            _faceRightPlayableDirector.Reset();
            _faceRightPlayableDirector.PlayAsync().Forget();
        }

        [Button]
        public void PlayBeforeInventory()
        {
            _beforeInventoryPlayableDirector.Reset();
            _beforeInventoryPlayableDirector.PlayAsync().Forget();
        }

        [Button]
        public void Play()
        {
            var screenPos = Mouse.current != null ? Mouse.current.position.ReadValue() : Vector2.zero;
            PlayAsync(screenPos).Forget();
        }

        public async UniTask PlayAsync(Vector2 screenClickPos)
        {
            if (_isPlaying)
            {
                return;
            }

            _isPlaying = true;
            var ct = this.GetCancellationTokenOnDestroy();

            // Find the closest spawn marker to the click position
            var closestMarker = FindClosestMarker(screenClickPos);

            // Read plane data from the marker's SpawnMarkerData component
            var markerData = closestMarker != null ? closestMarker.GetComponent<SpawnMarkerData>() : null;
            if (markerData == null)
            {
                Debug.LogError("[GameController] Closest marker has no SpawnMarkerData component.");
                _isPlaying = false;
                return;
            }

            var planeId = markerData.PlaneId;

            // Update the plane deets text
            if (_planeDeets != null)
            {
                _planeDeets.text = markerData.PlaneDeets;
            }

            // Spawn the plane prefab under _planeParent
            var planePrefab = _planePrefabRegistry.GetPrefab(planeId);
            if (planePrefab == null)
            {
                Debug.LogError($"[GameController] No plane prefab found for id \"{planeId}\".");
                _isPlaying = false;
                return;
            }
            var spawnedPlane = Instantiate(planePrefab, _planeParent);

            try
            {
                // Ensure the cell for this plane exists before opening (count 0 until fly-in)
                var cell = _inventoryView.GetOrCreateCell(planeId, 0);
                SetLayerRecursively(_planeRoot.gameObject, LayerMask.NameToLayer("Default"));

                _faceRightPlayableDirector.Reset();
                _beforeInventoryPlayableDirector.Reset();

                // Timeline's Reset()+Evaluate() writes _planeRoot back to its
                // default pose. We insert an offset parent so the whole animated
                // hierarchy is moved to the marker location.
                if (closestMarker != null)
                {
                    var defaultLocalPos = _planeRoot.localPosition;
                    var defaultLocalRot = _planeRoot.localRotation;

                    if (_spawnOffset == null)
                    {
                        _spawnOffset = new GameObject("_SpawnOffset").transform;
                    }

                    _spawnOffset.SetParent(_originalPlaneRootParent, false);
                    _spawnOffset.rotation = closestMarker.rotation * Quaternion.Inverse(defaultLocalRot);
                    _spawnOffset.position = closestMarker.position - _spawnOffset.rotation * defaultLocalPos;

                    _planeRoot.SetParent(_spawnOffset, false);
                    _planeRoot.localPosition = defaultLocalPos;
                    _planeRoot.localRotation = defaultLocalRot;

                    Debug.Log($"[GameController] Spawn offset applied – planeRoot world pos: {_planeRoot.position}");
                }

                if (_planeAnimator != null)
                {
                    _planeAnimator.enabled = true;
                }

                await _faceRightPlayableDirector.PlayAsync(ct);

                if (_planeAnimator != null)
                {
                    _planeAnimator.enabled = false;
                }

                _beforeInventoryStartMarker.position = _planeRoot.position;
                _beforeInventoryStartMarker.rotation = _planeRoot.rotation;
                _faceRightPlayableDirector.gameObject.SetActive(false);

                await WaitForClickAsync(ct);

                _inventoryView.Open();
                await _beforeInventoryPlayableDirector.PlayAsync(ct);

                _beforeInventoryPlayableDirector.gameObject.SetActive(false);

                await WaitForClickAsync(ct);

                SetLayerRecursively(_planeRoot.gameObject, LayerMask.NameToLayer("UI"));

                // Unparent the spawned plane and animate it into the inventory view cell
                spawnedPlane.transform.SetParent(null);
                await cell.AddItemAsync(spawnedPlane.transform, ct);

                // Add the plane to the player's inventory and update the cell count
                _playerInventory.Add(planeId);
                cell.UpdateCount(_playerInventory.GetCount(planeId));
                await UniTask.Delay(300, cancellationToken: ct); // Wait a moment before closing the inventory view
                _inventoryView.Close();

                await _resetPlayableDirector.PlayAsync(ct);
                _resetPlayableDirector.gameObject.SetActive(false);
            }
            // finally
            // {
            //     if (_planeAnimator != null)
            //     {
            //         _planeAnimator.enabled = false;
            //     }

            //     _isPlaying = false;
            // }

            finally
            {
                if (_planeAnimator != null)
                {
                    _planeAnimator.enabled = false;
                }

                // Restore planeRoot to its original parent
                if (_planeRoot != null && _originalPlaneRootParent != null)
                {
                    _planeRoot.SetParent(_originalPlaneRootParent, false);
                }

                _isPlaying = false;
            }


        }


        /// <summary>
        /// Finds the spawn marker whose screen-space position is closest to the given screen position.
        /// </summary>
        private Transform FindClosestMarker(Vector2 screenPos)
        {
            if (_spawnMarkers == null || _spawnMarkers.Length == 0)
            {
                return null;
            }

            var cam = _camera != null ? _camera : Camera.main;
            if (cam == null)
            {
                Debug.LogWarning("[GameController] No camera found to project marker positions.");
                return null;
            }

            Transform closest = null;
            float closestDist = float.MaxValue;

            foreach (var marker in _spawnMarkers)
            {
                if (marker == null) continue;

                Vector2 markerScreen = cam.WorldToScreenPoint(marker.position);
                float dist = Vector2.Distance(screenPos, markerScreen);
                if (dist < closestDist)
                {
                    closestDist = dist;
                    closest = marker;
                }
            }

            return closest;
        }

        private static void SetLayerRecursively(GameObject obj, int layer)
        {
            obj.layer = layer;
            foreach (Transform child in obj.transform)
            {
                SetLayerRecursively(child.gameObject, layer);
            }
        }

        private static UniTask WaitForClickAsync(System.Threading.CancellationToken ct)
        {
            return UniTask.WaitUntil(IsClickPressedThisFrame, cancellationToken: ct);
        }

        private static bool IsClickPressedThisFrame()
        {
#if ENABLE_INPUT_SYSTEM
            if (Mouse.current?.leftButton.wasPressedThisFrame == true)
            {
                return true;
            }

            if (Touchscreen.current != null)
            {
                foreach (var touch in Touchscreen.current.touches)
                {
                    if (touch.press.wasPressedThisFrame)
                    {
                        return true;
                    }
                }
            }
#endif

#if ENABLE_LEGACY_INPUT_MANAGER
            if (Input.GetMouseButtonDown(0))
            {
                return true;
            }

            for (var i = 0; i < Input.touchCount; i++)
            {
                if (Input.GetTouch(i).phase == TouchPhase.Began)
                {
                    return true;
                }
            }
#endif

            return false;
        }
    }
}

