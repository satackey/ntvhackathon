using UnityEngine;
using UnityEngine.Playables;

namespace Sequence
{
    /// <summary>
    /// Mixer that blends SetWorldPosition clips and applies the result to the bound Transform.
    /// When clips overlap, their world positions are blended by weight.
    /// When NO clip is active, the Transform is left untouched (animation tracks keep working).
    /// </summary>
    public class SetWorldPositionMixerBehaviour : PlayableBehaviour
    {
        public void ProcessFrame(Playable playable, FrameData info, object playerData)
        {
            var transform = playerData as Transform;
            if (transform == null)
                return;

            int inputCount = playable.GetInputCount();
            Vector3 blendedPosition = Vector3.zero;
            float totalWeight = 0f;

            for (int i = 0; i < inputCount; i++)
            {
                float weight = playable.GetInputWeight(i);
                if (weight <= 0f)
                    continue;

                var inputPlayable = (ScriptPlayable<SetWorldPositionBehaviour>)playable.GetInput(i);
                var behaviour = inputPlayable.GetBehaviour();

                blendedPosition += behaviour.worldPosition * weight;
                totalWeight += weight;
            }

            // Only override position when at least one clip is active.
            // This avoids fighting with Animation tracks when no clip is playing.
            if (totalWeight <= 0f)
                return;

            // When totalWeight < 1 (e.g. ease-in/out), blend between the current
            // position (which may come from an Animation track) and the clip target.
            if (totalWeight >= 1f)
            {
                transform.position = blendedPosition;
            }
            else
            {
                // Normalize the blended position and lerp from current (animation) position
                transform.position = Vector3.Lerp(transform.position, blendedPosition / totalWeight, totalWeight);
            }
        }
    }
}

