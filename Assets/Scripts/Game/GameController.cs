using Cysharp.Threading.Tasks;
using DefaultNamespace;
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
        [SerializeField] private PlaneId _planeId;
        [SerializeField] private Transform _planeParent;
            
        private Animator _planeAnimator;
        private bool _isPlaying;

        private void Awake()
        {
            _planeAnimator = _planeRoot != null ? _planeRoot.GetComponent<Animator>() : null;
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
            PlayAsync().Forget();
        }
        
        public async UniTask PlayAsync()
        {
            if (_isPlaying)
            {
                return;
            }

            _isPlaying = true;
            var ct = this.GetCancellationTokenOnDestroy();

            // Spawn the plane prefab under _planeParent
            var planePrefab = _planePrefabRegistry.GetPrefab(_planeId);
            if (planePrefab == null)
            {
                Debug.LogError($"[GameController] No plane prefab found for id \"{_planeId}\".");
                _isPlaying = false;
                return;
            }
            var spawnedPlane = Instantiate(planePrefab, _planeParent);

            try
            {
                // Ensure the cell for this plane exists before opening (count 0 until fly-in)
                var cell = _inventoryView.GetOrCreateCell(_planeId, 0);
                SetLayerRecursively(_planeRoot.gameObject, LayerMask.NameToLayer("Default"));

                _faceRightPlayableDirector.Reset();
                _beforeInventoryPlayableDirector.Reset();

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
                _playerInventory.Add(_planeId);
                cell.UpdateCount(_playerInventory.GetCount(_planeId));
                await UniTask.Delay(300, cancellationToken: ct); // Wait a moment before closing the inventory view
                _inventoryView.Close();
                
                await _resetPlayableDirector.PlayAsync(ct);
                _resetPlayableDirector.gameObject.SetActive(false);
            }
            finally
            {
                if (_planeAnimator != null)
                {
                    _planeAnimator.enabled = false;
                }

                _isPlaying = false;
            }
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