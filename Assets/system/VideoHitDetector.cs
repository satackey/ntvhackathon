using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Video;
using UnityEngine.InputSystem; // Input System用

// --- データ構造 (ここにあるので他のファイルからは削除してください) ---
[Serializable]
public class VideoData
{
    public Metadata metadata;
    public List<FrameData> frames;
}

[Serializable]
public class Metadata
{
    public string video_name;
    public int width;
    public int height;
    public float fps;
    public int total_frames;
}

[Serializable]
public class FrameData
{
    public int frame_index;
    public List<Detection> detections;
}

[Serializable]
public class Detection
{
    public int track_id;
    public string label;
    public float[] bbox; // [x_min, y_min, x_max, y_max]
    public float confidence;
}

public class VideoHitDetector : MonoBehaviour
{
    public VideoPlayer videoPlayer;
    public TextAsset jsonFile;
    private VideoData videoData;

    void Start()
    {
        if (jsonFile != null)
        {
            videoData = JsonUtility.FromJson<VideoData>(jsonFile.text);
        }
    }

    void Update()
    {
        // クリックした瞬間を検知
        if (Mouse.current != null && Mouse.current.leftButton.wasPressedThisFrame)
        {
            CheckHit();
        }
    }

    void CheckHit()
    {
        if (videoData == null || videoPlayer == null) return;

        long currentFrame = videoPlayer.frame;
        var frameInfo = videoData.frames.Find(f => f.frame_index == (int)currentFrame);

        if (frameInfo == null || frameInfo.detections.Count == 0)
        {
            // ここもフレーム番号を入れることで、連続クリックしても埋もれません
            Debug.Log($"[{currentFrame}f] このフレームには当たり判定データがありません。");
            return;
        }

        Vector2 mousePos = Mouse.current.position.ReadValue();
        float videoX = mousePos.x * (videoData.metadata.width / (float)Screen.width);
        float videoY = (Screen.height - mousePos.y) * (videoData.metadata.height / (float)Screen.height);

        bool isAnyHit = false;

        foreach (var detection in frameInfo.detections)
        {
            float xMin = detection.bbox[0];
            float yMin = detection.bbox[1];
            float xMax = detection.bbox[2];
            float yMax = detection.bbox[3];

            if (videoX >= xMin && videoX <= xMax && videoY >= yMin && videoY <= yMax)
            {
                // 【修正ポイント】先頭に [フレーム番号] や [発生時刻] を追加して文字列をユニークにする
                Debug.Log($"[{currentFrame}f / {Time.time:F2}s] <color=green>【HIT!】</color> ID: {detection.track_id} ({detection.label})");
                isAnyHit = true;
            }
        }

        if (!isAnyHit)
        {
            // 【修正ポイント】MISSの時もフレーム番号を入れる
            Debug.Log($"[{currentFrame}f / {Time.time:F2}s] <color=red>【MISS】</color> どこにも当たっていません。");
        }
    }
}