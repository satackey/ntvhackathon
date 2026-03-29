using System;
using UnityEngine;
using UnityEngine.Playables;

namespace Sequence
{
    /// <summary>
    /// Runtime data for a single clip on the SetWorldPosition track.
    /// </summary>
    [Serializable]
    public class SetWorldPositionBehaviour : PlayableBehaviour
    {
        public Vector3 worldPosition;
    }
}

