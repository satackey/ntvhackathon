from __future__ import annotations

from types import SimpleNamespace

from plane_tracker import (
    AIRPLANE_CLASS_ID,
    AIRPLANE_LABEL,
    build_frame_payload,
    build_output_frames,
    build_output_metadata,
    clone_detection,
    extract_detections,
    format_timecode,
    interpolate_detection,
    resolve_frame_range,
)


class FakeTensor:
    def __init__(self, values):
        self.values = values

    def cpu(self):
        return self

    def int(self):
        if isinstance(self.values, list):
            return FakeTensor([int(value) for value in self.values])
        return FakeTensor(int(self.values))

    def tolist(self):
        return self.values


def test_extract_detections_returns_tracked_airplanes_only() -> None:
    boxes = SimpleNamespace(
        xyxy=FakeTensor([[10.123, 20.456, 30.789, 40.987], [1, 2, 3, 4]]),
        conf=FakeTensor([0.92345, 0.5]),
        cls=FakeTensor([AIRPLANE_CLASS_ID, 0]),
        id=FakeTensor([7, 99]),
    )
    result = SimpleNamespace(boxes=boxes)

    detections = extract_detections(result)

    assert detections == [
        {
            "track_id": 7,
            "label": AIRPLANE_LABEL,
            "bbox": [10.12, 20.46, 30.79, 40.99],
            "confidence": 0.9234,
            "interpolated": False,
        }
    ]


def test_extract_detections_skips_untracked_boxes() -> None:
    boxes = SimpleNamespace(
        xyxy=FakeTensor([[10, 20, 30, 40]]),
        conf=FakeTensor([0.9]),
        cls=FakeTensor([AIRPLANE_CLASS_ID]),
        id=None,
    )
    result = SimpleNamespace(boxes=boxes)

    assert extract_detections(result) == []


def test_format_timecode_uses_hours_minutes_seconds_and_milliseconds() -> None:
    assert format_timecode(4.004) == "00:00:04.004"
    assert format_timecode(65.432) == "00:01:05.432"


def test_build_frame_payload_adds_time_fields() -> None:
    payload = build_frame_payload(120, 29.97, [])

    assert payload == {
        "frame_index": 120,
        "time_seconds": 4.004,
        "time_ms": 4004,
        "timecode": "00:00:04.004",
        "detections": [],
    }


def test_resolve_frame_range_uses_seconds_and_clamps_to_bounds() -> None:
    assert resolve_frame_range(30.0, 900, 1.0, 3.5) == (30, 105)
    assert resolve_frame_range(30.0, 900, 29.0, 40.0) == (870, 900)


def test_build_output_metadata_adds_clip_information() -> None:
    metadata = build_output_metadata(
        {
            "video_name": "plane.mp4",
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "total_frames": 900,
        },
        30,
        105,
        3,
    )

    assert metadata["total_frames"] == 75
    assert metadata["source_total_frames"] == 900
    assert metadata["clip_start_frame"] == 30
    assert metadata["clip_end_frame"] == 105
    assert metadata["clip_start_seconds"] == 1.0
    assert metadata["clip_end_seconds"] == 3.5
    assert metadata["inference_stride"] == 3
    assert metadata["contains_interpolated_detections"] is True


def test_interpolate_detection_marks_output_as_interpolated() -> None:
    detection = interpolate_detection(
        {
            "track_id": 1,
            "label": AIRPLANE_LABEL,
            "bbox": [0.0, 0.0, 10.0, 10.0],
            "confidence": 0.2,
            "interpolated": False,
        },
        {
            "track_id": 1,
            "label": AIRPLANE_LABEL,
            "bbox": [10.0, 10.0, 20.0, 20.0],
            "confidence": 0.6,
            "interpolated": False,
        },
        0.5,
    )

    assert detection == {
        "track_id": 1,
        "label": AIRPLANE_LABEL,
        "bbox": [5.0, 5.0, 15.0, 15.0],
        "confidence": 0.4,
        "interpolated": True,
    }


def test_build_output_frames_interpolates_between_keyframes() -> None:
    keyframes = [
        build_frame_payload(
            0,
            30.0,
            [
                {
                    "track_id": 1,
                    "label": AIRPLANE_LABEL,
                    "bbox": [0.0, 0.0, 10.0, 10.0],
                    "confidence": 0.2,
                    "interpolated": False,
                }
            ],
        ),
        build_frame_payload(
            2,
            30.0,
            [
                {
                    "track_id": 1,
                    "label": AIRPLANE_LABEL,
                    "bbox": [10.0, 10.0, 20.0, 20.0],
                    "confidence": 0.6,
                    "interpolated": False,
                }
            ],
        ),
    ]

    frames = build_output_frames(keyframes, 30.0, 0, 3)

    assert frames[0]["detections"] == [
        clone_detection(keyframes[0]["detections"][0], interpolated=False)
    ]
    assert frames[1]["detections"] == [
        {
            "track_id": 1,
            "label": AIRPLANE_LABEL,
            "bbox": [5.0, 5.0, 15.0, 15.0],
            "confidence": 0.4,
            "interpolated": True,
        }
    ]
    assert frames[2]["detections"] == [
        clone_detection(keyframes[1]["detections"][0], interpolated=False)
    ]
