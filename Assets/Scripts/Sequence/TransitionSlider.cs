using System;
using UnityEngine;
using UnityEngine.UI;

namespace Sequence
{
    public class TransitionSlider : MonoBehaviour
    {
        [SerializeField] private RawImage _liveCamImage;
        [SerializeField] private RawImage _planeImage;

        [SerializeField] private Color _liveCamColor1;
        [SerializeField] private Color _liveCamColor2;
        [SerializeField] private Color _planeColor1;
        [SerializeField] private Color _planeColor2;
        [SerializeField] [Range(0f, 1f)] private float _sliderValue;

#if UNITY_EDITOR
        private void OnValidate()
        {
            _liveCamImage.color = Color.Lerp(_liveCamColor1, _liveCamColor2, _sliderValue);
            _planeImage.color = Color.Lerp(_planeColor1, _planeColor2, _sliderValue);
        }
#endif
    }
}