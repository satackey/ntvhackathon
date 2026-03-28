using UnityEngine;
using UnityEngine.UI;
using System;
using System.Collections;
using TMPro;


public class ClockText : MonoBehaviour
{
    public TMP_Text clockText;

    void Start()
    {
        StartCoroutine(UpdateClock());
    }

    IEnumerator UpdateClock()
    {
        while (true)
        {
            DateTime now = DateTime.Now;
            clockText.text = now.ToString("HH:mm:ss");

            yield return new WaitForSeconds(1f);
        }
    }
}