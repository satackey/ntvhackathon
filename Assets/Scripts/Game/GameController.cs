using Cysharp.Threading.Tasks;
using DefaultNamespace;
using UnityEngine;
using UnityEngine.Playables;

namespace Game
{
    public class GameController : MonoBehaviour
    {
        [SerializeField] private PlayableDirector _faceRightPlayableDirector;
        
        [Button]
        public void PlayFaceRight()
        {
            _faceRightPlayableDirector.Reset();
            _faceRightPlayableDirector.PlayAsync().Forget();
        }
    }
}