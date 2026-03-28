from __future__ import annotations

import json
from email.message import Message
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError

from plane_tracker import (
    AIRPLANE_CLASS_ID,
    AIRPLANE_LABEL,
    angular_difference,
    bearing_between_points,
    build_fr24_cache_path,
    build_fr24_track_cache_path,
    build_frame_payload,
    build_output_frames,
    build_output_metadata,
    clone_detection,
    compute_track_query_indices,
    extract_detections,
    fetch_fr24_historic_positions,
    fetch_fr24_json_with_retry,
    format_timecode,
    interpolate_detection,
    match_detections_to_projected_flights,
    project_flights_to_frame,
    resolve_frame_range,
    source_env_file,
    summarize_track_frames,
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


def test_angular_difference_wraps_across_zero() -> None:
    assert angular_difference(5.0, 355.0) == 10.0
    assert angular_difference(355.0, 5.0) == -10.0


def test_bearing_between_points_points_east_for_same_latitude() -> None:
    bearing = bearing_between_points(35.0, 139.0, 35.0, 140.0)

    assert 85.0 < bearing < 95.0


def test_project_flights_to_frame_filters_by_camera_fov() -> None:
    flights = [
        {"fr24_id": "east", "lat": 35.5536, "lon": 139.90, "flight": "ANA1"},
        {"fr24_id": "west", "lat": 35.5536, "lon": 139.60, "flight": "ANA2"},
    ]

    projected = project_flights_to_frame(
        flights,
        camera_lat=35.5536,
        camera_lon=139.7871,
        camera_bearing=90.0,
        camera_horizontal_fov=60.0,
        frame_width=1920,
        search_radius_km=25.0,
    )

    assert [flight["fr24_id"] for flight in projected] == ["east"]
    assert 0.0 <= projected[0]["projected_center_x"] <= 1920.0


def test_match_detections_to_projected_flights_uses_nearest_x() -> None:
    detections = [
        {"track_id": 1, "bbox": [90.0, 0.0, 110.0, 10.0]},
        {"track_id": 2, "bbox": [890.0, 0.0, 910.0, 10.0]},
    ]
    projected_flights = [
        {"fr24_id": "left", "projected_center_x": 100.0},
        {"fr24_id": "right", "projected_center_x": 900.0},
    ]

    matches = match_detections_to_projected_flights(
        detections,
        projected_flights,
        frame_width=1000,
        max_error_ratio=0.2,
    )

    assert [(detection["track_id"], flight["fr24_id"]) for detection, flight, _ in matches] == [
        (1, "left"),
        (2, "right"),
    ]


def test_source_env_file_loads_flightradar_key(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("FLIGHTRADAR24_API_KEY=test-token|part2\nOTHER=value\n", encoding="utf-8")
    monkeypatch.delenv("FLIGHTRADAR24_API_KEY", raising=False)

    loaded = source_env_file(env_path)

    assert loaded["FLIGHTRADAR24_API_KEY"] == "test-token|part2"


def test_fetch_fr24_historic_positions_uses_disk_cache(tmp_path, monkeypatch) -> None:
    timestamp = SimpleNamespace(
        timestamp=lambda: 1_234_567_890,
        isoformat=lambda: "2026-03-28T12:53:05+09:00",
    )
    cache_path = build_fr24_cache_path(tmp_path, timestamp, "1,2,3,4", 200)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"data": [{"fr24_id": "cached"}]}), encoding="utf-8")
    cache_stats = {"hits": 0, "misses": 0}

    def fail_urlopen(_request, timeout: int = 30):  # pragma: no cover
        raise AssertionError("urlopen should not be called on cache hit")

    monkeypatch.setattr("plane_tracker.urllib.request.urlopen", fail_urlopen)

    flights = fetch_fr24_historic_positions(
        "token",
        timestamp,
        "1,2,3,4",
        tmp_path,
        cache_stats,
    )

    assert flights == [{"fr24_id": "cached"}]
    assert cache_stats == {"hits": 1, "misses": 0}


def test_summarize_track_frames_marks_persistent_tracks() -> None:
    frames = [
        build_frame_payload(
            10,
            30.0,
            [
                {
                    "track_id": 1,
                    "bbox": [0, 0, 1, 1],
                    "label": "airplane",
                    "confidence": 1.0,
                    "interpolated": False,
                }
            ],
        ),
        build_frame_payload(
            11,
            30.0,
            [
                {
                    "track_id": 1,
                    "bbox": [0, 0, 1, 1],
                    "label": "airplane",
                    "confidence": 1.0,
                    "interpolated": False,
                }
            ],
        ),
        build_frame_payload(
            12,
            30.0,
            [
                {
                    "track_id": 1,
                    "bbox": [0, 0, 1, 1],
                    "label": "airplane",
                    "confidence": 1.0,
                    "interpolated": False,
                },
                {
                    "track_id": 2,
                    "bbox": [0, 0, 1, 1],
                    "label": "airplane",
                    "confidence": 1.0,
                    "interpolated": False,
                },
            ],
        ),
    ]

    summary = summarize_track_frames(frames)

    assert summary[1]["is_persistent"] is True
    assert summary[2]["is_persistent"] is False


def test_compute_track_query_indices_uses_midpoint_progresses() -> None:
    query_indices = compute_track_query_indices(
        {"first_relative_index": 10, "last_relative_index": 20}
    )

    assert query_indices == [(14, 0.35), (15, 0.5), (16, 0.55)]


def test_build_fr24_track_cache_path_is_stable(tmp_path) -> None:
    path_a = build_fr24_track_cache_path(
        tmp_path,
        video_name="clip.mp4",
        clip_start_frame=0,
        clip_end_frame=100,
        track_id=7,
        camera_bearing=90.0,
        camera_horizontal_fov=60.0,
        search_radius_km=25.0,
        max_error_ratio=0.2,
    )
    path_b = build_fr24_track_cache_path(
        tmp_path,
        video_name="clip.mp4",
        clip_start_frame=0,
        clip_end_frame=100,
        track_id=7,
        camera_bearing=90.0,
        camera_horizontal_fov=60.0,
        search_radius_km=25.0,
        max_error_ratio=0.2,
    )

    assert path_a == path_b


def test_fetch_fr24_json_with_retry_retries_after_429(monkeypatch) -> None:
    headers = Message()
    headers["Retry-After"] = "0"
    calls = {"count": 0}
    sleeps: list[float] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    def fake_urlopen(_request, timeout=30):
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPError(
                "http://example.com",
                429,
                "Too Many Requests",
                headers,
                BytesIO(b'{"message":"retry"}'),
            )
        response = FakeResponse()
        response.read = lambda: b'{"data":[1]}'
        return response

    monkeypatch.setattr("plane_tracker.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("plane_tracker.time.sleep", lambda seconds: sleeps.append(seconds))

    payload = fetch_fr24_json_with_retry(SimpleNamespace())

    assert payload == {"data": [1]}
    assert calls["count"] == 2
    assert sleeps == [0.0]
