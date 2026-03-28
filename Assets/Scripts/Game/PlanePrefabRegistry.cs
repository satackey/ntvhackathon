using System;
using System.Collections.Generic;
using UnityEngine;

namespace Game
{
    public enum PlaneId
    {
        Boeing787,
        AirbusA320,
        AirbusA380,
        Boeing747,
        Boeing777,
    }

    /// <summary>
    /// Keeps a PlaneId → plane-prefab map.
    /// Attach this to a GameObject in the scene so other scripts (e.g. GameController)
    /// can look up a plane prefab by its PlaneId.
    /// </summary>
    public class PlanePrefabRegistry : MonoBehaviour
    {
        [Serializable]
        public struct PlanePrefabEntry
        {
            public PlaneId id;
            public GameObject prefab;
        }

        [SerializeField] private List<PlanePrefabEntry> _entries = new List<PlanePrefabEntry>();

        private Dictionary<PlaneId, GameObject> _map;

        private void Awake()
        {
            BuildMap();
        }

        private void BuildMap()
        {
            _map = new Dictionary<PlaneId, GameObject>(_entries.Count);
            foreach (var entry in _entries)
            {
                if (!_map.TryAdd(entry.id, entry.prefab))
                {
                    Debug.LogWarning($"[PlanePrefabRegistry] Duplicate id \"{entry.id}\" – only the first entry is kept.", this);
                }
            }
        }

        /// <summary>
        /// Returns the plane prefab registered under <paramref name="planeId"/>,
        /// or <c>null</c> if no such id exists.
        /// </summary>
        public GameObject GetPrefab(PlaneId planeId)
        {
            if (_map == null) BuildMap();

            if (_map!.TryGetValue(planeId, out var prefab))
                return prefab;

            Debug.LogWarning($"[PlanePrefabRegistry] No prefab found for id \"{planeId}\".", this);
            return null;
        }

        /// <summary>
        /// Returns true when a prefab is registered for the given id.
        /// </summary>
        public bool HasPrefab(PlaneId planeId)
        {
            if (_map == null) BuildMap();
            return _map!.ContainsKey(planeId);
        }
    }
}



