using UnityEngine;
using UnityEngine.Playables;
using UnityEngine.Timeline;

namespace Sequence
{
    /// <summary>
    /// A Timeline track that sets the world position of the bound Transform.
    /// Add clips to specify target world positions; overlapping clips blend smoothly.
    /// </summary>
    [TrackColor(0.2f, 0.6f, 1.0f)]
    [TrackBindingType(typeof(Transform))]
    [TrackClipType(typeof(SetWorldPositionClip))]
    public class SetWorldPositionTrack : TrackAsset
    {
        public override Playable CreateTrackMixer(PlayableGraph graph, GameObject go, int inputCount)
        {
            return ScriptPlayable<SetWorldPositionMixerBehaviour>.Create(graph, inputCount);
        }
    }
}

