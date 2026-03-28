using System;
using System.Collections.Generic;

[Serializable]
public class PlaneTrackingMetadata
{
    public string video_name;
    public int width;
    public int height;
    public float fps;
    public int total_frames;
}

[Serializable]
public class PlaneDetection
{
    public int track_id;
    public string label;
    public float[] bbox;
    public float confidence;
}

[Serializable]
public class PlaneTrackingFrame
{
    public int frame_index;
    public float time_seconds;
    public int time_ms;
    public string timecode;
    public List<PlaneDetection> detections;
}

[Serializable]
public class PlaneTrackingJson
{
    public PlaneTrackingMetadata metadata;
    public List<PlaneTrackingFrame> frames;
}
