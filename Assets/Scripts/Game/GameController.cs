using Cysharp.Threading.Tasks;
using DefaultNamespace;
using UnityEngine;
using UnityEngine.Playables;

namespace Game
{
    public class GameController : MonoBehaviour
    {
        [SerializeField] private PlayableDirector _faceRightPlayableDirector;
        [SerializeField] private PlayableDirector _beforeInventoryPlayableDirector;
        [SerializeField] private Transform _planeRoot;
        [SerializeField] private Transform _beforeInventoryStartMarker;
        
        [Button]
        public void PlayFaceRight()
        {
            _faceRightPlayableDirector.Reset();
            _faceRightPlayableDirector.PlayAsync().Forget();
        }
        
        [Button]
        public void PlayBeforeInventory()
        {
            _beforeInventoryPlayableDirector.Reset();
            _beforeInventoryPlayableDirector.PlayAsync().Forget();
        }
        
        [Button]
        public void Play()
        {
            PlayAsync().Forget();
        }
        
        public async UniTask PlayAsync()
        {
            _faceRightPlayableDirector.Reset();
            _beforeInventoryPlayableDirector.Reset();
            _planeRoot.GetComponent<Animator>().enabled = true;
            await _faceRightPlayableDirector.PlayAsync();
            _planeRoot.GetComponent<Animator>().enabled = false;
            _beforeInventoryStartMarker.position = _planeRoot.position;
            _beforeInventoryStartMarker.rotation = _planeRoot.rotation;
            _faceRightPlayableDirector.gameObject.SetActive(false);
            await _beforeInventoryPlayableDirector.PlayAsync();
            _beforeInventoryPlayableDirector.gameObject.SetActive(false);
        }
    }
}