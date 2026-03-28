using System;
using UnityEngine;

namespace Game
{
    public class InventoryView : MonoBehaviour
    {
        [SerializeField] private Animator _animator;
        
        int OpenHash => Animator.StringToHash("Open");
        int CloseHash => Animator.StringToHash("Close");

        private void Awake()
        {
            gameObject.SetActive(false);
        }

        [Button]
        public void Open()
        {
            gameObject.SetActive(true);
            _animator.SetTrigger(OpenHash);
        }
        
        [Button]
        public void Close()
        {
            _animator.SetTrigger(CloseHash);
        }
    }
}