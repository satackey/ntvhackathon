using System;
using System.ComponentModel;
using UnityEngine;
using UnityEngine.Playables;
using UnityEngine.Timeline;

namespace Sequence
{
    /// <summary>
    /// A Timeline clip that sets the world position of the bound Transform.
    /// </summary>
    [Serializable]
    [DisplayName("Set World Position")]
    public class SetWorldPositionClip : PlayableAsset, ITimelineClipAsset, IPropertyPreview
    {
        [Tooltip("The world position to set on the bound Transform.")]
        public Vector3 worldPosition;

        public ClipCaps clipCaps => ClipCaps.Blending;

        public override Playable CreatePlayable(PlayableGraph graph, GameObject owner)
        {
            var playable = ScriptPlayable<SetWorldPositionBehaviour>.Create(graph);
            var behaviour = playable.GetBehaviour();
            behaviour.worldPosition = worldPosition;
            return playable;
        }

        public void GatherProperties(PlayableDirector director, IPropertyCollector driver)
        {
            driver.AddFromName<Transform>("m_LocalPosition.x");
            driver.AddFromName<Transform>("m_LocalPosition.y");
            driver.AddFromName<Transform>("m_LocalPosition.z");
        }
    }
}

