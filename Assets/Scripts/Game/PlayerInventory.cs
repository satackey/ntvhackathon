using System;
using System.Collections.Generic;
using UnityEngine;

namespace Game
{
    /// <summary>
    /// Keeps the player's inventory data: which planes they own and how many of each.
    /// </summary>
    public class PlayerInventory : MonoBehaviour
    {
        [Serializable]
        public struct InventoryEntry
        {
            public PlaneId id;
            public int count;
        }

        [SerializeField] private List<InventoryEntry> _entries = new List<InventoryEntry>();

        private Dictionary<PlaneId, int> _map;

        public event Action<PlaneId, int> OnCountChanged;

        private void Awake()
        {
            BuildMap();
        }

        private void BuildMap()
        {
            _map = new Dictionary<PlaneId, int>();
            foreach (var entry in _entries)
            {
                if (_map.ContainsKey(entry.id))
                    _map[entry.id] += entry.count;
                else
                    _map[entry.id] = entry.count;
            }
        }

        /// <summary>
        /// Add <paramref name="amount"/> of the given plane to the inventory.
        /// </summary>
        public void Add(PlaneId planeId, int amount = 1)
        {
            if (_map == null) BuildMap();

            if (_map!.ContainsKey(planeId))
                _map[planeId] += amount;
            else
                _map[planeId] = amount;

            SyncEntries();
            OnCountChanged?.Invoke(planeId, _map[planeId]);
        }

        /// <summary>
        /// Remove <paramref name="amount"/> of the given plane from the inventory.
        /// Returns false if the player doesn't have enough.
        /// </summary>
        public bool Remove(PlaneId planeId, int amount = 1)
        {
            if (_map == null) BuildMap();

            if (!_map!.TryGetValue(planeId, out var current) || current < amount)
                return false;

            _map[planeId] = current - amount;
            if (_map[planeId] <= 0)
                _map.Remove(planeId);

            SyncEntries();
            OnCountChanged?.Invoke(planeId, GetCount(planeId));
            return true;
        }

        /// <summary>
        /// Returns how many of the given plane the player owns.
        /// </summary>
        public int GetCount(PlaneId planeId)
        {
            if (_map == null) BuildMap();
            return _map!.TryGetValue(planeId, out var count) ? count : 0;
        }

        /// <summary>
        /// Returns true if the player owns at least one of the given plane.
        /// </summary>
        public bool Has(PlaneId planeId)
        {
            return GetCount(planeId) > 0;
        }

        /// <summary>
        /// Returns a read-only snapshot of the full inventory.
        /// </summary>
        public IReadOnlyDictionary<PlaneId, int> GetAll()
        {
            if (_map == null) BuildMap();
            return _map!;
        }

        /// <summary>
        /// Sync the dictionary back to the serialized list so Inspector stays up to date.
        /// </summary>
        private void SyncEntries()
        {
            _entries.Clear();
            foreach (var kvp in _map)
            {
                _entries.Add(new InventoryEntry { id = kvp.Key, count = kvp.Value });
            }
        }
    }
}

