from __future__ import annotations

import argparse
import copy
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, parse, request

import cv2

DEFAULT_INITIAL_LAT = 35.55362508260334
DEFAULT_INITIAL_LON = 139.7871835937992
LAT_BOUNDS = (35.50362508260334, 35.60362508260334)
LON_BOUNDS = (139.7371835937992, 139.8371835937992)
DEFAULT_TIME_WINDOW_SEC = 300
DEFAULT_FETCH_STEP_SEC = 10
DEFAULT_TRACK_PROXIMITY_PX = 250.0
OPENSKY_BASE_URL = "https://opensky-network.org/api"
OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
)


@dataclass(slots=True)
class CameraProjection:
    x: float
    y: float
    z: float
    screen_x: float
    screen_y: float
    visible: bool


@dataclass(slots=True)
class OpenSkyAuthConfig:
    mode: str
    access_token: str | None = None
    credentials_json: Path | None = None
    client_id: str | None = None
    client_secret: str | None = None


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent_dir(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def clamp_camera_lat_lon(camera_config: dict[str, Any]) -> dict[str, Any]:
    camera_config["lat"] = clamp(float(camera_config["lat"]), *LAT_BOUNDS)
    camera_config["lon"] = clamp(float(camera_config["lon"]), *LON_BOUNDS)
    return camera_config


def build_default_camera_config(video_path: Path) -> dict[str, Any]:
    return {
        "camera_name": video_path.stem,
        "video_name": video_path.name,
        "initial_guess": {
            "lat": DEFAULT_INITIAL_LAT,
            "lon": DEFAULT_INITIAL_LON,
        },
        "reference_time_utc": None,
        "lat": DEFAULT_INITIAL_LAT,
        "lon": DEFAULT_INITIAL_LON,
        "elevation_m": 0.0,
        "azimuth_deg": 90.0,
        "tilt_deg": 0.0,
        "roll_deg": 0.0,
        "hfov_deg": 60.0,
        "vfov_deg": 35.0,
        "time_offset_sec": 0.0,
    }


def load_camera_config(path: Path, video_path: Path) -> dict[str, Any]:
    config = build_default_camera_config(video_path)
    if path.exists():
        config.update(load_json(path))
        config["initial_guess"] = {
            "lat": float(
                config.get("initial_guess", {}).get("lat", DEFAULT_INITIAL_LAT)  # type: ignore[union-attr]
            ),
            "lon": float(
                config.get("initial_guess", {}).get("lon", DEFAULT_INITIAL_LON)  # type: ignore[union-attr]
            ),
        }
    return clamp_camera_lat_lon(config)


def normalize_camera_config(
    camera_config: dict[str, Any],
    *,
    video_path: Path,
) -> dict[str, Any]:
    normalized = build_default_camera_config(video_path)
    normalized.update(camera_config)
    normalized["camera_name"] = str(normalized["camera_name"])
    normalized["video_name"] = str(normalized["video_name"])
    normalized["initial_guess"] = {
        "lat": float(normalized.get("initial_guess", {}).get("lat", DEFAULT_INITIAL_LAT)),
        "lon": float(normalized.get("initial_guess", {}).get("lon", DEFAULT_INITIAL_LON)),
    }
    normalized["reference_time_utc"] = normalize_reference_time_utc(
        normalized.get("reference_time_utc")
    )
    for key in (
        "lat",
        "lon",
        "elevation_m",
        "azimuth_deg",
        "tilt_deg",
        "roll_deg",
        "hfov_deg",
        "vfov_deg",
        "time_offset_sec",
    ):
        normalized[key] = float(normalized[key])
    return clamp_camera_lat_lon(normalized)


def default_manual_matches_payload() -> dict[str, Any]:
    return {"matches": []}


def load_manual_matches(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_manual_matches_payload()
    payload = load_json(path)
    matches = []
    for match in payload.get("matches", []):
        matches.append(
            {
                "track_id": int(match["track_id"]),
                "icao24": str(match["icao24"]).lower(),
                "callsign": clean_callsign(match.get("callsign")),
                "notes": match.get("notes"),
            }
        )
    return {"matches": matches}


def manual_matches_by_track(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(match["track_id"]): match for match in payload.get("matches", [])}


def upsert_manual_match(
    payload: dict[str, Any],
    *,
    track_id: int,
    icao24: str,
    callsign: str | None,
    notes: str | None,
) -> dict[str, Any]:
    matches = manual_matches_by_track(payload)
    matches[int(track_id)] = {
        "track_id": int(track_id),
        "icao24": icao24.lower(),
        "callsign": clean_callsign(callsign),
        "notes": notes or None,
    }
    ordered = [matches[key] for key in sorted(matches)]
    return {"matches": ordered}


def default_opensky_cache() -> dict[str, Any]:
    return {"cache_format_version": 1, "queries": []}


def load_opensky_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_opensky_cache()
    payload = load_json(path)
    payload.setdefault("cache_format_version", 1)
    payload.setdefault("queries", [])
    return payload


def normalize_bbox(
    bbox: list[float] | tuple[float, float, float, float] | None,
) -> list[float] | None:
    if bbox is None:
        return None
    return [round(float(value), 4) for value in bbox]


def compute_search_bbox(lat: float, lon: float, radius_km: float = 15.0) -> list[float]:
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.2))
    return (
        normalize_bbox([lat - lat_delta, lon - lon_delta, lat + lat_delta, lon + lon_delta]) or []
    )


def cache_query_key(query: dict[str, Any]) -> tuple[Any, ...]:
    begin_bucket = int(query["begin_unix"]) // 60
    end_bucket = int(query["end_unix"]) // 60
    return (
        str(query["query_type"]),
        begin_bucket,
        end_bucket,
        tuple(normalize_bbox(query.get("bbox")) or []),
    )


def dedupe_record_key(query_type: str, record: dict[str, Any]) -> tuple[Any, ...]:
    if query_type in {"states_all", "tracks"}:
        return (record.get("icao24"), int(record.get("time", 0)))
    return (
        record.get("icao24"),
        int(record.get("firstSeen", record.get("begin_unix", 0))),
        int(record.get("lastSeen", record.get("end_unix", 0))),
        record.get("callsign"),
    )


def merge_opensky_query(cache_payload: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    cache_payload.setdefault("queries", [])
    query = copy.deepcopy(query)
    query["bbox"] = normalize_bbox(query.get("bbox"))
    for existing in cache_payload["queries"]:
        if cache_query_key(existing) != cache_query_key(query):
            continue
        existing["begin_unix"] = min(int(existing["begin_unix"]), int(query["begin_unix"]))
        existing["end_unix"] = max(int(existing["end_unix"]), int(query["end_unix"]))
        by_key = {
            dedupe_record_key(str(existing["query_type"]), record): record
            for record in existing.get("records", [])
        }
        for record in query.get("records", []):
            by_key[dedupe_record_key(str(existing["query_type"]), record)] = record
        existing["records"] = sorted(
            by_key.values(),
            key=lambda item: (
                str(item.get("icao24", "")),
                int(item.get("time", item.get("firstSeen", 0))),
            ),
        )
        return cache_payload

    cache_payload["queries"].append(query)
    cache_payload["queries"].sort(
        key=lambda item: (
            str(item["query_type"]),
            int(item["begin_unix"]),
            int(item["end_unix"]),
        )
    )
    return cache_payload


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not intervals:
        return []
    sorted_intervals = sorted(intervals)
    merged = [sorted_intervals[0]]
    for start, end in sorted_intervals[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end:
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def find_missing_intervals(
    cache_payload: dict[str, Any],
    *,
    query_type: str,
    begin_unix: int,
    end_unix: int,
    bbox: list[float] | None,
) -> list[tuple[int, int]]:
    target_bbox = normalize_bbox(bbox)
    covered = []
    for query in cache_payload.get("queries", []):
        if query.get("query_type") != query_type:
            continue
        if normalize_bbox(query.get("bbox")) != target_bbox:
            continue
        start = max(begin_unix, int(query["begin_unix"]))
        end = min(end_unix, int(query["end_unix"]))
        if start < end:
            covered.append((start, end))

    missing = []
    cursor = begin_unix
    for start, end in merge_intervals(covered):
        if cursor < start:
            missing.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < end_unix:
        missing.append((cursor, end_unix))
    return missing


def clean_callsign(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def normalize_reference_time_utc(value: Any) -> str | None:
    if value in (None, ""):
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_reference_unix(value: str | None) -> int | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(dt.timestamp())


def frame_to_estimated_unix(
    frame_payload: dict[str, Any],
    camera_config: dict[str, Any],
) -> int | None:
    reference_unix = parse_reference_unix(camera_config.get("reference_time_utc"))
    if reference_unix is None:
        return None
    return int(
        round(
            reference_unix + float(frame_payload["time_seconds"]) + camera_config["time_offset_sec"]
        )
    )


def aggregate_tracks(frames: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    tracks: dict[int, dict[str, Any]] = {}
    for frame in frames:
        for detection in frame.get("detections", []):
            track_id = int(detection["track_id"])
            track = tracks.setdefault(
                track_id,
                {
                    "track_id": track_id,
                    "frames": [],
                    "count": 0,
                    "first_frame_index": frame["frame_index"],
                    "last_frame_index": frame["frame_index"],
                },
            )
            track["frames"].append(
                {
                    "frame_index": frame["frame_index"],
                    "time_seconds": frame["time_seconds"],
                    "bbox": detection["bbox"],
                    "confidence": detection["confidence"],
                    "interpolated": detection.get("interpolated", False),
                }
            )
            track["count"] += 1
            track["last_frame_index"] = frame["frame_index"]
    return dict(sorted(tracks.items()))


def bbox_center(bbox: list[float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def bbox_size(bbox: list[float]) -> tuple[float, float]:
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def normalize_state_vector(
    raw_state: list[Any] | dict[str, Any], snapshot_time: int
) -> dict[str, Any] | None:
    if isinstance(raw_state, dict):
        lat = raw_state.get("latitude", raw_state.get("lat"))
        lon = raw_state.get("longitude", raw_state.get("lon"))
        if lat is None or lon is None:
            return None
        return {
            "icao24": str(raw_state["icao24"]).lower(),
            "callsign": clean_callsign(raw_state.get("callsign")),
            "time": int(raw_state.get("time", snapshot_time)),
            "lat": float(lat),
            "lon": float(lon),
            "geo_altitude": raw_state.get("geo_altitude"),
            "baro_altitude": raw_state.get("baro_altitude"),
            "velocity": raw_state.get("velocity"),
            "heading": raw_state.get("true_track", raw_state.get("heading")),
            "vertical_rate": raw_state.get("vertical_rate"),
        }

    if len(raw_state) < 14:
        return None
    if raw_state[5] is None or raw_state[6] is None:
        return None
    return {
        "icao24": str(raw_state[0]).lower(),
        "callsign": clean_callsign(raw_state[1]),
        "time": int(snapshot_time),
        "lat": float(raw_state[6]),
        "lon": float(raw_state[5]),
        "geo_altitude": raw_state[13],
        "baro_altitude": raw_state[7],
        "velocity": raw_state[9],
        "heading": raw_state[10],
        "vertical_rate": raw_state[11],
    }


def normalize_track_waypoint(
    icao24: str,
    callsign: str | None,
    waypoint: dict[str, Any] | list[Any],
) -> dict[str, Any] | None:
    if isinstance(waypoint, dict):
        lat = waypoint.get("latitude", waypoint.get("lat"))
        lon = waypoint.get("longitude", waypoint.get("lon"))
        if lat is None or lon is None:
            return None
        return {
            "icao24": icao24,
            "callsign": callsign,
            "time": int(waypoint["time"]),
            "lat": float(lat),
            "lon": float(lon),
            "geo_altitude": waypoint.get("geo_altitude"),
            "baro_altitude": waypoint.get("baro_altitude"),
            "velocity": None,
            "heading": waypoint.get("true_track", waypoint.get("heading")),
            "vertical_rate": None,
        }
    if len(waypoint) < 6 or waypoint[1] is None or waypoint[2] is None:
        return None
    return {
        "icao24": icao24,
        "callsign": callsign,
        "time": int(waypoint[0]),
        "lat": float(waypoint[1]),
        "lon": float(waypoint[2]),
        "geo_altitude": waypoint[3],
        "baro_altitude": waypoint[3],
        "velocity": None,
        "heading": waypoint[4],
        "vertical_rate": None,
    }


def load_opensky_client_credentials(path: Path) -> tuple[str, str]:
    payload = load_json(path)
    return str(payload["clientId"]), str(payload["clientSecret"])


def resolve_opensky_auth_config(args: argparse.Namespace) -> OpenSkyAuthConfig | None:
    if getattr(args, "opensky_access_token", None):
        return OpenSkyAuthConfig(mode="access_token", access_token=args.opensky_access_token)
    if getattr(args, "opensky_credentials_json", None):
        return OpenSkyAuthConfig(
            mode="credentials_json",
            credentials_json=Path(args.opensky_credentials_json),
        )
    if getattr(args, "opensky_client_id", None) and getattr(args, "opensky_client_secret", None):
        return OpenSkyAuthConfig(
            mode="client_credentials",
            client_id=args.opensky_client_id,
            client_secret=args.opensky_client_secret,
        )
    return None


def fetch_opensky_access_token(client_id: str, client_secret: str) -> tuple[str, int]:
    body = parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    req = request.Request(OPENSKY_TOKEN_URL, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return str(payload["access_token"]), int(payload.get("expires_in", 1800))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenSky token error {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenSky token request failed: {exc.reason}") from exc


def request_opensky_json(endpoint: str, params: dict[str, Any], token: str) -> Any:
    query = parse.urlencode({key: value for key, value in params.items() if value is not None})
    url = f"{OPENSKY_BASE_URL}{endpoint}?{query}"
    headers = {"Authorization": f"Bearer {token.strip()}", "Accept": "application/json"}
    req = request.Request(url, headers=headers)
    try:
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenSky API error {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenSky request failed: {exc.reason}") from exc


def resolve_opensky_access_token_from_config(auth_config: OpenSkyAuthConfig | None) -> str:
    if auth_config is None:
        raise RuntimeError("OpenSky credentials are not configured.")
    if auth_config.mode == "access_token":
        assert auth_config.access_token is not None
        return auth_config.access_token
    if auth_config.mode == "credentials_json":
        assert auth_config.credentials_json is not None
        client_id, client_secret = load_opensky_client_credentials(auth_config.credentials_json)
        token, _ = fetch_opensky_access_token(client_id, client_secret)
        return token
    assert auth_config.client_id is not None
    assert auth_config.client_secret is not None
    token, _ = fetch_opensky_access_token(auth_config.client_id, auth_config.client_secret)
    return token


def fetch_states_all(
    *,
    token: str,
    begin_unix: int,
    end_unix: int,
    bbox: list[float],
    step_sec: int = DEFAULT_FETCH_STEP_SEC,
) -> dict[str, Any]:
    records: dict[tuple[Any, ...], dict[str, Any]] = {}
    lamin, lomin, lamax, lomax = bbox
    inclusive_end = max(begin_unix, end_unix)
    for timestamp in range(begin_unix, inclusive_end + 1, max(step_sec, 1)):
        response = request_opensky_json(
            "/states/all",
            {
                "time": timestamp,
                "lamin": lamin,
                "lomin": lomin,
                "lamax": lamax,
                "lomax": lomax,
            },
            token,
        )
        snapshot_time = int(response.get("time", timestamp))
        for raw_state in response.get("states", []) or []:
            normalized = normalize_state_vector(raw_state, snapshot_time)
            if normalized is None:
                continue
            records[dedupe_record_key("states_all", normalized)] = normalized

    return {
        "query_type": "states_all",
        "begin_unix": begin_unix,
        "end_unix": end_unix,
        "bbox": normalize_bbox(bbox),
        "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "records": sorted(records.values(), key=lambda item: (item["time"], item["icao24"])),
    }


def fetch_track(
    *,
    token: str,
    icao24: str,
    time_unix: int,
) -> dict[str, Any]:
    response = request_opensky_json(
        "/tracks/all",
        {"icao24": icao24.lower(), "time": time_unix},
        token,
    )
    callsign = clean_callsign(response.get("callsign"))
    records = []
    for waypoint in response.get("path", []) or []:
        normalized = normalize_track_waypoint(icao24.lower(), callsign, waypoint)
        if normalized is not None:
            records.append(normalized)
    return {
        "query_type": "tracks",
        "begin_unix": int(response.get("startTime", time_unix)),
        "end_unix": int(response.get("endTime", time_unix)),
        "bbox": None,
        "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "records": records,
    }


def get_cached_records(
    cache_payload: dict[str, Any],
    *,
    query_type: str,
    begin_unix: int,
    end_unix: int,
    bbox: list[float] | None,
) -> list[dict[str, Any]]:
    target_bbox = normalize_bbox(bbox)
    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for query in cache_payload.get("queries", []):
        if query.get("query_type") != query_type:
            continue
        if normalize_bbox(query.get("bbox")) != target_bbox:
            continue
        if int(query["end_unix"]) < begin_unix or int(query["begin_unix"]) > end_unix:
            continue
        for record in query.get("records", []):
            record_time = int(record.get("time", record.get("firstSeen", 0)))
            if begin_unix <= record_time <= end_unix:
                deduped[dedupe_record_key(query_type, record)] = record
    return sorted(
        deduped.values(), key=lambda item: (int(item.get("time", 0)), item.get("icao24", ""))
    )


def state_records_for_frame(
    cache_payload: dict[str, Any],
    *,
    frame_unix: int | None,
    bbox: list[float],
    tolerance_sec: int = 10,
) -> list[dict[str, Any]]:
    if frame_unix is None:
        return []
    records = get_cached_records(
        cache_payload,
        query_type="states_all",
        begin_unix=frame_unix - tolerance_sec,
        end_unix=frame_unix + tolerance_sec,
        bbox=bbox,
    )
    nearest_by_aircraft: dict[str, dict[str, Any]] = {}
    for record in records:
        icao24 = str(record["icao24"])
        if icao24 not in nearest_by_aircraft:
            nearest_by_aircraft[icao24] = record
            continue
        current_delta = abs(int(nearest_by_aircraft[icao24]["time"]) - frame_unix)
        new_delta = abs(int(record["time"]) - frame_unix)
        if new_delta < current_delta:
            nearest_by_aircraft[icao24] = record
    return sorted(nearest_by_aircraft.values(), key=lambda item: (item["time"], item["icao24"]))


def wgs84_to_ecef(lat_deg: float, lon_deg: float, altitude_m: float) -> tuple[float, float, float]:
    a = 6378137.0
    e_sq = 6.69437999014e-3
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)
    n = a / math.sqrt(1.0 - e_sq * sin_lat * sin_lat)
    x = (n + altitude_m) * cos_lat * cos_lon
    y = (n + altitude_m) * cos_lat * sin_lon
    z = (n * (1.0 - e_sq) + altitude_m) * sin_lat
    return x, y, z


def ecef_to_enu(
    x: float,
    y: float,
    z: float,
    ref_lat_deg: float,
    ref_lon_deg: float,
    ref_alt_m: float,
) -> tuple[float, float, float]:
    ref_x, ref_y, ref_z = wgs84_to_ecef(ref_lat_deg, ref_lon_deg, ref_alt_m)
    dx = x - ref_x
    dy = y - ref_y
    dz = z - ref_z
    lat = math.radians(ref_lat_deg)
    lon = math.radians(ref_lon_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)
    east = -sin_lon * dx + cos_lon * dy
    north = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    up = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
    return east, north, up


def normalize_vector(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in vector))
    if length == 0:
        return (0.0, 0.0, 0.0)
    return tuple(component / length for component in vector)  # type: ignore[return-value]


def cross(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def rotate_around_axis(
    vector: tuple[float, float, float],
    axis: tuple[float, float, float],
    angle_deg: float,
) -> tuple[float, float, float]:
    angle = math.radians(angle_deg)
    axis = normalize_vector(axis)
    cos_angle = math.cos(angle)
    sin_angle = math.sin(angle)
    cross_term = cross(axis, vector)
    dot_term = dot(axis, vector)
    return (
        vector[0] * cos_angle + cross_term[0] * sin_angle + axis[0] * dot_term * (1.0 - cos_angle),
        vector[1] * cos_angle + cross_term[1] * sin_angle + axis[1] * dot_term * (1.0 - cos_angle),
        vector[2] * cos_angle + cross_term[2] * sin_angle + axis[2] * dot_term * (1.0 - cos_angle),
    )


def camera_basis(camera_config: dict[str, Any]) -> tuple[tuple[float, float, float], ...]:
    azimuth = math.radians(camera_config["azimuth_deg"])
    tilt = math.radians(camera_config["tilt_deg"])
    forward = normalize_vector(
        (
            math.sin(azimuth) * math.cos(tilt),
            math.cos(azimuth) * math.cos(tilt),
            math.sin(tilt),
        )
    )
    world_up = (0.0, 0.0, 1.0)
    right = normalize_vector(cross(forward, world_up))
    if right == (0.0, 0.0, 0.0):
        right = (1.0, 0.0, 0.0)
    down = normalize_vector(cross(forward, right))
    roll_deg = float(camera_config["roll_deg"])
    if abs(roll_deg) > 1e-9:
        right = normalize_vector(rotate_around_axis(right, forward, roll_deg))
        down = normalize_vector(rotate_around_axis(down, forward, roll_deg))
    return right, down, forward


def project_world_to_screen(
    *,
    target_lat: float,
    target_lon: float,
    target_altitude_m: float,
    camera_config: dict[str, Any],
    frame_width: int,
    frame_height: int,
) -> CameraProjection:
    target_ecef = wgs84_to_ecef(target_lat, target_lon, target_altitude_m)
    enu = ecef_to_enu(
        target_ecef[0],
        target_ecef[1],
        target_ecef[2],
        float(camera_config["lat"]),
        float(camera_config["lon"]),
        float(camera_config["elevation_m"]),
    )
    right, down, forward = camera_basis(camera_config)
    cam_x = dot(enu, right)
    cam_y = dot(enu, down)
    cam_z = dot(enu, forward)
    if cam_z <= 0:
        return CameraProjection(cam_x, cam_y, cam_z, -1.0, -1.0, False)

    fx = frame_width / (2.0 * math.tan(math.radians(camera_config["hfov_deg"]) / 2.0))
    fy = frame_height / (2.0 * math.tan(math.radians(camera_config["vfov_deg"]) / 2.0))
    screen_x = frame_width / 2.0 + fx * (cam_x / cam_z)
    screen_y = frame_height / 2.0 + fy * (cam_y / cam_z)
    visible = 0.0 <= screen_x <= frame_width and 0.0 <= screen_y <= frame_height
    return CameraProjection(cam_x, cam_y, cam_z, screen_x, screen_y, visible)


def project_state_records(
    state_records: list[dict[str, Any]],
    *,
    camera_config: dict[str, Any],
    frame_width: int,
    frame_height: int,
) -> list[dict[str, Any]]:
    projected = []
    for record in state_records:
        altitude = record.get("geo_altitude")
        if altitude is None:
            altitude = record.get("baro_altitude")
        if altitude is None:
            altitude = 0.0
        projection = project_world_to_screen(
            target_lat=float(record["lat"]),
            target_lon=float(record["lon"]),
            target_altitude_m=float(altitude),
            camera_config=camera_config,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        projected.append(
            {
                **record,
                "screen_x": round(projection.screen_x, 2),
                "screen_y": round(projection.screen_y, 2),
                "cam_z": round(projection.z, 2),
                "visible": projection.visible,
            }
        )
    return projected


def candidate_aircraft_for_detection(
    detection: dict[str, Any] | None,
    projected_records: list[dict[str, Any]],
    *,
    max_candidates: int = 20,
) -> list[dict[str, Any]]:
    if detection is None:
        return [record for record in projected_records if record["visible"]][:max_candidates]
    center_x, center_y = bbox_center(detection["bbox"])
    ranked = []
    for record in projected_records:
        if not record["visible"]:
            continue
        distance_px = math.dist((center_x, center_y), (record["screen_x"], record["screen_y"]))
        ranked.append({**record, "distance_px": round(distance_px, 2)})
    ranked.sort(key=lambda item: item["distance_px"])
    return ranked[:max_candidates]


def build_candidate_index(
    tracking_payload: dict[str, Any],
    camera_config: dict[str, Any],
    cache_payload: dict[str, Any],
) -> dict[int, set[str]]:
    metadata = tracking_payload["metadata"]
    bbox = compute_search_bbox(camera_config["lat"], camera_config["lon"])
    index: dict[int, set[str]] = {}
    for frame in tracking_payload.get("frames", []):
        frame_unix = frame_to_estimated_unix(frame, camera_config)
        state_records = state_records_for_frame(cache_payload, frame_unix=frame_unix, bbox=bbox)
        projected = project_state_records(
            state_records,
            camera_config=camera_config,
            frame_width=int(metadata["width"]),
            frame_height=int(metadata["height"]),
        )
        for detection in frame.get("detections", []):
            candidates = candidate_aircraft_for_detection(detection, projected, max_candidates=5)
            for candidate in candidates:
                if (
                    candidate.get("distance_px", DEFAULT_TRACK_PROXIMITY_PX + 1.0)
                    > DEFAULT_TRACK_PROXIMITY_PX
                ):
                    continue
                index.setdefault(int(detection["track_id"]), set()).add(str(candidate["icao24"]))
    return index


def build_with_flight_info_payload(
    tracking_payload: dict[str, Any],
    *,
    camera_config: dict[str, Any],
    manual_matches_payload: dict[str, Any],
    opensky_cache_path: Path,
    cache_payload: dict[str, Any],
) -> dict[str, Any]:
    payload = copy.deepcopy(tracking_payload)
    matches_by_track = manual_matches_by_track(manual_matches_payload)
    candidate_index = build_candidate_index(payload, camera_config, cache_payload)
    payload.setdefault("metadata", {})
    payload["metadata"]["flight_info_enrichment"] = {
        "manual_match_count": len(matches_by_track),
        "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    payload["metadata"]["camera"] = {
        key: value for key, value in camera_config.items() if key != "initial_guess"
    }
    payload["metadata"]["time_offset_sec"] = camera_config["time_offset_sec"]
    payload["metadata"]["opensky_cache_source"] = str(opensky_cache_path)
    for frame in payload.get("frames", []):
        for detection in frame.get("detections", []):
            match = matches_by_track.get(int(detection["track_id"]))
            if match is None:
                detection["flight_info_ref"] = None
            else:
                detection["flight_info_ref"] = {
                    "icao24": match["icao24"],
                    "callsign": match.get("callsign"),
                }
    tracks = []
    for track_id, track in aggregate_tracks(payload.get("frames", [])).items():
        match = matches_by_track.get(track_id)
        tracks.append(
            {
                "track_id": track_id,
                "matched": match is not None,
                "icao24": match.get("icao24") if match else None,
                "callsign": match.get("callsign") if match else None,
                "candidate_count": len(candidate_index.get(track_id, set())),
            }
        )
    payload["tracks"] = tracks
    return payload


def cached_track_records_for_aircraft(
    cache_payload: dict[str, Any],
    *,
    icao24: str | None,
) -> list[dict[str, Any]]:
    if not icao24:
        return []
    records = []
    for query in cache_payload.get("queries", []):
        if query.get("query_type") != "tracks":
            continue
        for record in query.get("records", []):
            if str(record.get("icao24", "")).lower() == icao24.lower():
                records.append(record)
    records.sort(key=lambda item: (int(item.get("time", 0)), str(item.get("icao24", ""))))
    return records


def encode_frame_as_jpeg(video_path: Path, frame_index: int, quality: int = 90) -> bytes:
    rgb_frame = read_video_frame(video_path, frame_index)
    bgr_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)
    ok, encoded = cv2.imencode(".jpg", bgr_frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError(f"Could not encode frame {frame_index} from video: {video_path}")
    return encoded.tobytes()


def read_video_frame(video_path: Path, frame_index: int) -> Any:
    capture = cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            raise RuntimeError(f"Could not open video: {video_path}")
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"Could not read frame {frame_index} from video: {video_path}")
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    finally:
        capture.release()


def parse_streamlit_cli_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--tracking-json", type=Path, required=True)
    parser.add_argument("--opensky-cache", type=Path, required=True)
    parser.add_argument("--camera-config", type=Path)
    parser.add_argument("--manual-matches", type=Path)
    parser.add_argument("--opensky-credentials-json", type=Path)
    parser.add_argument("--opensky-client-id")
    parser.add_argument("--opensky-client-secret")
    parser.add_argument("--opensky-access-token")
    return parser.parse_args(argv)


def parse_web_cli_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Cesium-based OpenSky calibration web app."
    )
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--tracking-json", type=Path, required=True)
    parser.add_argument("--opensky-cache", type=Path, required=True)
    parser.add_argument("--camera-config", type=Path)
    parser.add_argument("--manual-matches", type=Path)
    parser.add_argument("--opensky-credentials-json", type=Path)
    parser.add_argument("--opensky-client-id")
    parser.add_argument("--opensky-client-secret")
    parser.add_argument("--opensky-access-token")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args(argv)
