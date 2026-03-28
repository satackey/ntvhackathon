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
    public int source_total_frames;
    public int clip_start_frame;
    public int clip_end_frame;
    public float clip_start_seconds;
    public float clip_end_seconds;
    public int inference_stride;
    public bool contains_interpolated_detections;
}

[Serializable]
public class PlaneDetection
{
    public int track_id;
    public string label;
    public float[] bbox;
    public float confidence;
    public bool interpolated;
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
