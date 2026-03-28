using System.Collections.Generic;
using UnityEngine;

namespace Game
{
    public class InventoryView : MonoBehaviour
    {
        [SerializeField] private Animator _animator;
        [SerializeField] private PlayerInventory _playerInventory;
        [SerializeField] private PlanePrefabRegistry _planePrefabRegistry;
        [SerializeField] private InventoryViewCell _cellPrefab;
        [SerializeField] private Transform _cellContainer;
        [SerializeField] private Camera _uiCamera;
        [SerializeField] private Camera _worldCamera;
        
        private readonly Dictionary<PlaneId, InventoryViewCell> _cells = new Dictionary<PlaneId, InventoryViewCell>();
        private readonly Dictionary<PlaneId, List<GameObject>> _spawnedPlanes = new Dictionary<PlaneId, List<GameObject>>();

        int OpenHash => Animator.StringToHash("Open");
        int CloseHash => Animator.StringToHash("Close");

        private void Awake()
        {
            Refresh();
            gameObject.SetActive(false);
        }

        private void OnEnable()
        {
            if (_playerInventory != null)
                _playerInventory.OnCountChanged += OnInventoryCountChanged;

            SetAllSpawnedPlanesActive(true);
        }

        private void OnDisable()
        {
            if (_playerInventory != null)
                _playerInventory.OnCountChanged -= OnInventoryCountChanged;

            SetAllSpawnedPlanesActive(false);
        }

        [Button]
        public void Open()
        {
            gameObject.SetActive(true);
            Refresh();
            _animator.SetTrigger(OpenHash);
        }
        
        [Button]
        public void Close()
        {
            _animator.SetTrigger(CloseHash);
        }

        /// <summary>
        /// Returns the cell for the given plane id.
        /// If none exists yet, creates one with the specified initial count
        /// (defaults to the current inventory count).
        /// </summary>
        public InventoryViewCell GetOrCreateCell(PlaneId planeId, int? initialCount = null)
        {
            if (_cells.TryGetValue(planeId, out var existing))
                return existing;

            var count = initialCount ?? _playerInventory.GetCount(planeId);
            return CreateCell(planeId, count);
        }

        /// <summary>
        /// Rebuild all cells from the current player inventory data.
        /// Cells that were pre-created (e.g. with count 0 for a pending fly-in)
        /// are kept even if they aren't in the inventory yet.
        /// </summary>
        private void Refresh()
        {
            var inventory = _playerInventory.GetAll();

            // Update existing cells – sync counts from inventory
            foreach (var kvp in _cells)
            {
                if (inventory.TryGetValue(kvp.Key, out var count))
                    kvp.Value.UpdateCount(count);
            }

            // Add cells for inventory entries that don't have a cell yet
            foreach (var kvp in inventory)
            {
                if (kvp.Value <= 0) continue;

                if (!_cells.ContainsKey(kvp.Key))
                {
                    CreateCell(kvp.Key, kvp.Value);
                }
            }
        }

        private InventoryViewCell CreateCell(PlaneId planeId, int count)
        {
            var cell = Instantiate(_cellPrefab, _cellContainer);
            cell.Init(_uiCamera, _worldCamera);
            cell.Setup(planeId, count);

            // Spawn 3D plane models for each item in the count
            var prefab = _planePrefabRegistry.GetPrefab(planeId);
            if (prefab != null)
            {
                var planes = new List<GameObject>(count);
                for (int i = 0; i < count; i++)
                {
                    var planeInstance = Instantiate(prefab);
                    SetLayerRecursively(planeInstance, LayerMask.NameToLayer("UI"));
                    planes.Add(planeInstance);
                    cell.AddItem(planeInstance.transform);
                }
                _spawnedPlanes[planeId] = planes;
            }

            _cells[planeId] = cell;
            return cell;
        }

        private void DestroyCell(PlaneId planeId)
        {
            if (_cells.TryGetValue(planeId, out var cell))
            {
                cell.ClearItems();
                Destroy(cell.gameObject);
                _cells.Remove(planeId);
            }

            if (_spawnedPlanes.TryGetValue(planeId, out var planes))
            {
                foreach (var plane in planes)
                    Destroy(plane);
                _spawnedPlanes.Remove(planeId);
            }
        }

        private void OnInventoryCountChanged(PlaneId planeId, int newCount)
        {
            if (newCount <= 0)
            {
                DestroyCell(planeId);
                return;
            }

            if (_cells.TryGetValue(planeId, out var cell))
            {
                cell.UpdateCount(newCount);
            }
            // Don't auto-create cells here; they are created on Open/Refresh or via GetOrCreateCell
        }

        private void SetAllSpawnedPlanesActive(bool active)
        {
            foreach (var planes in _spawnedPlanes.Values)
            {
                foreach (var plane in planes)
                {
                    if (plane != null)
                        plane.SetActive(active);
                }
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
    }
}