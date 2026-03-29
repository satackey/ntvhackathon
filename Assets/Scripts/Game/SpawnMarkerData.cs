using UnityEngine;

namespace Game
{
    /// <summary>
    /// Attach to each spawn marker to define which plane it spawns
    /// and the description text shown in the UI.
    /// </summary>
    public class SpawnMarkerData : MonoBehaviour
    {
        [SerializeField] private PlaneId _planeId;
        [TextArea(2, 5)]
        [SerializeField] private string _planeDeets;

        public PlaneId PlaneId => _planeId;
        public string PlaneDeets => _planeDeets;
    }
}

