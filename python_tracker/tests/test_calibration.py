from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from python_tracker.calibration import (
    aggregate_tracks,
    build_default_camera_config,
    cached_track_records_for_aircraft,
    merge_opensky_query,
    project_world_to_screen,
    resolve_opensky_auth_config,
)


def load_schema(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_project_world_to_screen_centers_target_straight_ahead() -> None:
    camera = build_default_camera_config(Path("plane.mp4"))
    camera.update(
        {
            "lat": 0.0,
            "lon": 0.0,
            "elevation_m": 0.0,
            "azimuth_deg": 0.0,
            "tilt_deg": 0.0,
            "roll_deg": 0.0,
            "hfov_deg": 90.0,
            "vfov_deg": 90.0,
        }
    )

    projection = project_world_to_screen(
        target_lat=0.0009,
        target_lon=0.0,
        target_altitude_m=0.0,
        camera_config=camera,
        frame_width=1000,
        frame_height=1000,
    )

    assert projection.visible is True
    assert projection.screen_x == 500.0
    assert abs(projection.screen_y - 500.0) < 1.0


def test_default_camera_config_starts_east_facing() -> None:
    camera = build_default_camera_config(Path("plane.mp4"))

    assert camera["azimuth_deg"] == 90.0


def test_project_world_to_screen_changes_when_camera_position_changes() -> None:
    camera = build_default_camera_config(Path("plane.mp4"))
    camera.update(
        {
            "lat": 35.55362508260334,
            "lon": 139.7871835937992,
            "elevation_m": 0.0,
            "azimuth_deg": 90.0,
            "tilt_deg": 0.0,
            "roll_deg": 0.0,
            "hfov_deg": 90.0,
            "vfov_deg": 90.0,
        }
    )

    target = {
        "target_lat": 35.55362508260334,
        "target_lon": 139.7921835937992,
        "target_altitude_m": 0.0,
        "frame_width": 1920,
        "frame_height": 1080,
    }
    first = project_world_to_screen(camera_config=camera, **target)
    camera["lon"] = 139.7881835937992
    second = project_world_to_screen(camera_config=camera, **target)

    assert first.visible is True
    assert second.visible is True
    assert abs(second.screen_x - first.screen_x) > 1e-6


def test_merge_opensky_query_deduplicates_records_by_icao24_and_time() -> None:
    cache = {"cache_format_version": 1, "queries": []}
    first = {
        "query_type": "states_all",
        "begin_unix": 100,
        "end_unix": 160,
        "bbox": [1.0, 2.0, 3.0, 4.0],
        "fetched_at": "2026-03-28T00:00:00Z",
        "records": [
            {"icao24": "abc123", "time": 110, "lat": 1.0, "lon": 2.0},
            {"icao24": "def456", "time": 120, "lat": 1.0, "lon": 2.0},
        ],
    }
    second = {
        "query_type": "states_all",
        "begin_unix": 100,
        "end_unix": 160,
        "bbox": [1.0, 2.0, 3.0, 4.0],
        "fetched_at": "2026-03-28T00:01:00Z",
        "records": [
            {"icao24": "abc123", "time": 110, "lat": 9.0, "lon": 9.0},
            {"icao24": "ghi789", "time": 130, "lat": 1.0, "lon": 2.0},
        ],
    }

    merge_opensky_query(cache, first)
    merge_opensky_query(cache, second)

    records = cache["queries"][0]["records"]
    assert len(records) == 3
    assert next(record for record in records if record["icao24"] == "abc123")["lat"] == 9.0


def test_cached_track_records_for_aircraft_filters_by_icao24() -> None:
    cache = {
        "queries": [
            {
                "query_type": "tracks",
                "records": [
                    {"icao24": "abc123", "time": 100},
                    {"icao24": "def456", "time": 101},
                    {"icao24": "abc123", "time": 99},
                ],
            }
        ]
    }

    records = cached_track_records_for_aircraft(cache, icao24="abc123")

    assert [record["time"] for record in records] == [99, 100]


def test_aggregate_tracks_groups_detections_by_track_id() -> None:
    frames = [
        {
            "frame_index": 0,
            "time_seconds": 0.0,
            "detections": [
                {"track_id": 1, "bbox": [0, 0, 10, 10], "confidence": 0.9, "interpolated": False},
                {"track_id": 2, "bbox": [10, 10, 20, 20], "confidence": 0.8, "interpolated": False},
            ],
        },
        {
            "frame_index": 1,
            "time_seconds": 0.1,
            "detections": [
                {"track_id": 1, "bbox": [1, 1, 11, 11], "confidence": 0.85, "interpolated": True}
            ],
        },
    ]

    tracks = aggregate_tracks(frames)

    assert list(tracks) == [1, 2]
    assert tracks[1]["count"] == 2
    assert tracks[1]["first_frame_index"] == 0
    assert tracks[1]["last_frame_index"] == 1
    assert tracks[2]["count"] == 1


def test_resolve_opensky_auth_config_prefers_access_token_then_credentials_json() -> None:
    args = SimpleNamespace(
        opensky_access_token="token",
        opensky_credentials_json=Path("cred.json"),
        opensky_client_id="id",
        opensky_client_secret="secret",
    )

    config = resolve_opensky_auth_config(args)

    assert config is not None
    assert config.mode == "access_token"
    assert config.access_token == "token"


def test_resolve_opensky_auth_config_uses_client_credentials_when_present() -> None:
    args = SimpleNamespace(
        opensky_access_token=None,
        opensky_credentials_json=None,
        opensky_client_id="id",
        opensky_client_secret="secret",
    )

    config = resolve_opensky_auth_config(args)

    assert config is not None
    assert config.mode == "client_credentials"
    assert config.client_id == "id"
    assert config.client_secret == "secret"


def test_schemas_accept_expected_payloads() -> None:
    camera_schema = load_schema("schemas/camera_config.schema.json")
    manual_schema = load_schema("schemas/manual_matches.schema.json")
    with_flight_info_schema = load_schema("schemas/with_flight_info.schema.json")

    Draft202012Validator.check_schema(camera_schema)
    Draft202012Validator.check_schema(manual_schema)
    Draft202012Validator.check_schema(with_flight_info_schema)

    Draft202012Validator(camera_schema).validate(
        {
            "camera_name": "camera-a",
            "video_name": "plane.mp4",
            "initial_guess": {"lat": 35.55362508260334, "lon": 139.7871835937992},
            "reference_time_utc": "2026-03-28T10:00:00Z",
            "lat": 35.55362508260334,
            "lon": 139.7871835937992,
            "elevation_m": 10.0,
            "azimuth_deg": 1.0,
            "tilt_deg": 2.0,
            "roll_deg": 3.0,
            "hfov_deg": 60.0,
            "vfov_deg": 35.0,
            "time_offset_sec": 0.0,
        }
    )
    Draft202012Validator(manual_schema).validate(
        {
            "matches": [
                {
                    "track_id": 1,
                    "icao24": "abc123",
                    "callsign": "JAL123",
                    "notes": "manual",
                }
            ]
        }
    )
    Draft202012Validator(with_flight_info_schema).validate(
        {
            "metadata": {
                "video_name": "plane.mp4",
                "width": 1920,
                "height": 1080,
                "fps": 30.0,
                "total_frames": 2,
                "flight_info_enrichment": {
                    "manual_match_count": 1,
                    "exported_at": "2026-03-28T10:00:00Z",
                },
                "camera": {
                    "lat": 35.55362508260334,
                    "lon": 139.7871835937992,
                },
                "time_offset_sec": 0.0,
                "opensky_cache_source": "opensky_cache.json",
            },
            "frames": [
                {
                    "frame_index": 0,
                    "time_seconds": 0.0,
                    "time_ms": 0,
                    "timecode": "00:00:00.000",
                    "detections": [
                        {
                            "track_id": 1,
                            "label": "airplane",
                            "bbox": [0.0, 0.0, 10.0, 10.0],
                            "confidence": 0.9,
                            "interpolated": False,
                            "flight_info_ref": {
                                "icao24": "abc123",
                                "callsign": "JAL123",
                            },
                        }
                    ],
                }
            ],
            "tracks": [
                {
                    "track_id": 1,
                    "matched": True,
                    "icao24": "abc123",
                    "callsign": "JAL123",
                    "candidate_count": 2,
                }
            ],
        }
    )
