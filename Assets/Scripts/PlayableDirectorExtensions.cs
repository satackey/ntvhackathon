using System;
using System.Threading;
using UnityEngine.Playables;
using Cysharp.Threading.Tasks;

namespace DefaultNamespace
{
    public static class PlayableDirectorExtensions
    {
        public static void Reset(this PlayableDirector director)
        {
            if (director == null)
            {
                return;
            }

            director.Stop();
            director.time = 0d;
            director.Evaluate();
        }

        public static async UniTask PlayAsync(this PlayableDirector director, CancellationToken ct = default)
        {
            director.gameObject.SetActive(true);    
            director.Play();

            while (director != null)
            {
                ct.ThrowIfCancellationRequested();

                if (HasCompleted(director))
                {
                    break;
                }

                await UniTask.Yield(PlayerLoopTiming.Update, ct);
            }
        }

        public static async UniTask PlayAsync(this PlayableDirector director, PlayableAsset asset, CancellationToken ct = default)
        {
            director.playableAsset = asset;
            director.Play();

            while (director != null)
            {
                ct.ThrowIfCancellationRequested();

                if (HasCompleted(director))
                {
                    break;
                }

                await UniTask.Yield(PlayerLoopTiming.Update, ct);
            }
        }

        static bool HasCompleted(PlayableDirector director)
        {
            if (director == null)
            {
                return true;
            }

            if (director.state != PlayState.Playing)
            {
                return true;
            }

            if (director.extrapolationMode == DirectorWrapMode.Loop)
            {
                return false;
            }

            var duration = director.duration;
            if (double.IsNaN(duration) || double.IsInfinity(duration) || duration <= 0d)
            {
                return false;
            }

            return director.time >= Math.Max(0d, duration - 0.001d);
        }
    }
}