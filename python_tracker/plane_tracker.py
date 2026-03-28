from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import cv2
from tqdm import tqdm

AIRPLANE_CLASS_ID = 4
AIRPLANE_LABEL = "airplane"
DEFAULT_MODEL_PATH = "yolov8n.pt"
DEFAULT_TRACKER = "bytetrack.yaml"
DEFAULT_CACHE_DIR = Path(".plane_tracker_cache")
DEFAULT_CAMERA_HORIZONTAL_FOV = 60.0
DEFAULT_FR24_SAMPLE_SECONDS = 15.0
DEFAULT_FR24_SEARCH_RADIUS_KM = 25.0
DEFAULT_FR24_MATCH_MAX_ERROR_RATIO = 0.2
EARTH_RADIUS_KM = 6371.0088


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Track airplanes in a local MP4 file and export both Unity-ready JSON "
            "and a debug MP4 with overlays."
        )
    )
    parser.add_argument("--input", type=Path, required=True, help="Input MP4 file path.")
    parser.add_argument(
        "--output-json",
        type=Path,
        required=True,
        help="Output JSON path for Unity playback.",
    )
    parser.add_argument(
        "--output-video",
        type=Path,
        required=True,
        help="Output MP4 path for the annotated debug video.",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.25,
        help="Confidence threshold for detections. Default: 0.25.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Inference device, for example 'cpu', '0', or 'mps'.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_PATH,
        help="YOLO model path or model name. Default: yolov8n.pt.",
    )
    parser.add_argument(
        "--tracker",
        default=DEFAULT_TRACKER,
        help="Ultralytics tracker config. Default: bytetrack.yaml.",
    )
    parser.add_argument(
        "--start-time",
        type=float,
        default=0.0,
        help="Optional clip start time in seconds. Default: 0.0.",
    )
    parser.add_argument(
        "--end-time",
        type=float,
        default=None,
        help="Optional clip end time in seconds. If omitted, process until the end.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help="Directory for cached tracking results.",
    )
    parser.add_argument(
        "--force-recompute",
        action="store_true",
        help="Ignore existing cache and recompute tracking results.",
    )
    parser.add_argument(
        "--inference-stride",
        type=int,
        default=1,
        help="Run detection/tracking every N frames and interpolate between keyframes. Default: 1.",
    )
    parser.add_argument(
        "--fr24-recording-start",
        type=str,
        default=None,
        help="Recording start datetime, for example '2026-03-28 12:53:05'.",
    )
    parser.add_argument(
        "--fr24-timezone",
        type=str,
        default="Asia/Tokyo",
        help="Timezone for --fr24-recording-start. Default: Asia/Tokyo.",
    )
    parser.add_argument(
        "--camera-lat",
        type=float,
        default=None,
        help="Camera latitude for FR24 enrichment.",
    )
    parser.add_argument(
        "--camera-lon",
        type=float,
        default=None,
        help="Camera longitude for FR24 enrichment.",
    )
    parser.add_argument(
        "--camera-bearing",
        type=float,
        default=None,
        help="Camera bearing in degrees, where north=0 and east=90.",
    )
    parser.add_argument(
        "--camera-horizontal-fov",
        type=float,
        default=DEFAULT_CAMERA_HORIZONTAL_FOV,
        help=(
            "Estimated camera horizontal FOV in degrees. "
            f"Default: {DEFAULT_CAMERA_HORIZONTAL_FOV}."
        ),
    )
    parser.add_argument(
        "--fr24-sample-seconds",
        type=float,
        default=DEFAULT_FR24_SAMPLE_SECONDS,
        help=(
            "How often to sample FR24 snapshots for matching. "
            f"Default: {DEFAULT_FR24_SAMPLE_SECONDS}."
        ),
    )
    parser.add_argument(
        "--fr24-search-radius-km",
        type=float,
        default=DEFAULT_FR24_SEARCH_RADIUS_KM,
        help=(
            "Search radius around the camera in kilometers. "
            f"Default: {DEFAULT_FR24_SEARCH_RADIUS_KM}."
        ),
    )
    parser.add_argument(
        "--fr24-match-max-error-ratio",
        type=float,
        default=DEFAULT_FR24_MATCH_MAX_ERROR_RATIO,
        help=(
            "Maximum horizontal matching error as a fraction of frame width. "
            f"Default: {DEFAULT_FR24_MATCH_MAX_ERROR_RATIO}."
        ),
    )
    parser.add_argument(
        "--fr24-token",
        type=str,
        default=None,
        help="Optional FR24 API token. If omitted, environment variables or .env are used.",
    )
    return parser.parse_args()


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def source_env_file(env_path: Path = Path(".env")) -> dict[str, str]:
    if not env_path.exists():
        return {}

    loaded_values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]
        os.environ[key] = value
        loaded_values[key] = value
    return loaded_values


def open_video_capture(input_path: Path) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open input video: {input_path}")
    return capture


def build_metadata(input_path: Path, capture: cv2.VideoCapture) -> dict[str, Any]:
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    return {
        "video_name": input_path.name,
        "width": width,
        "height": height,
        "fps": fps,
        "total_frames": total_frames,
    }


def create_video_writer(output_path: Path, width: int, height: int, fps: float) -> cv2.VideoWriter:
    ensure_parent_dir(output_path)
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps if fps > 0 else 30.0,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"Could not create output video: {output_path}")
    return writer


def sanitize_cache_token(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value)


def compute_file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        while chunk := file_obj.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def build_cache_paths(
    cache_dir: Path,
    input_path: Path,
    model: str,
    tracker: str,
    conf: float,
    inference_stride: int,
) -> tuple[str, Path]:
    video_sha = compute_file_sha256(input_path)
    model_token = sanitize_cache_token(Path(model).name)
    tracker_token = sanitize_cache_token(Path(tracker).name)
    conf_token = f"{conf:.3f}".replace(".", "_")
    cache_key = (
        f"{video_sha[:16]}_{model_token}_{tracker_token}_airplane_conf-{conf_token}_stride-{inference_stride}"
    )
    return cache_key, cache_dir / f"{cache_key}.json"


def format_timecode(time_seconds: float) -> str:
    total_ms = round(time_seconds * 1000)
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    seconds = (total_ms % 60_000) // 1000
    milliseconds = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def build_frame_payload(
    frame_index: int,
    fps: float,
    detections: list[dict[str, Any]],
) -> dict[str, Any]:
    safe_fps = fps if fps > 0 else 30.0
    time_seconds = frame_index / safe_fps
    time_ms = round(time_seconds * 1000)
    return {
        "frame_index": frame_index,
        "time_seconds": round(time_seconds, 3),
        "time_ms": time_ms,
        "timecode": format_timecode(time_ms / 1000),
        "detections": detections,
    }


def resolve_frame_range(
    fps: float,
    total_frames: int,
    start_time: float,
    end_time: float | None,
) -> tuple[int, int]:
    safe_fps = fps if fps > 0 else 30.0
    if start_time < 0:
        raise ValueError("--start-time must be greater than or equal to 0.")
    start_frame = int(round(start_time * safe_fps))
    if end_time is None:
        end_frame = total_frames
    else:
        if end_time < start_time:
            raise ValueError("--end-time must be greater than or equal to --start-time.")
        end_frame = int(round(end_time * safe_fps))

    start_frame = min(max(start_frame, 0), total_frames)
    end_frame = min(max(end_frame, start_frame), total_frames)
    return start_frame, end_frame


def build_output_metadata(
    source_metadata: dict[str, Any],
    start_frame: int,
    end_frame: int,
    inference_stride: int,
) -> dict[str, Any]:
    fps = source_metadata["fps"]
    return {
        "video_name": source_metadata["video_name"],
        "width": source_metadata["width"],
        "height": source_metadata["height"],
        "fps": source_metadata["fps"],
        "source_total_frames": source_metadata["total_frames"],
        "total_frames": end_frame - start_frame,
        "clip_start_frame": start_frame,
        "clip_end_frame": end_frame,
        "clip_start_seconds": round(start_frame / fps, 3) if fps > 0 else 0.0,
        "clip_end_seconds": round(end_frame / fps, 3) if fps > 0 else 0.0,
        "inference_stride": inference_stride,
        "contains_interpolated_detections": inference_stride > 1,
        "flight_radar_enrichment": {
            "enabled": False,
        },
    }


def extract_detections(result: Any) -> list[dict[str, Any]]:
    boxes = getattr(result, "boxes", None)
    if boxes is None or getattr(boxes, "xyxy", None) is None:
        return []

    xyxy = boxes.xyxy.cpu().tolist()
    if not xyxy:
        return []

    confs = boxes.conf.cpu().tolist() if boxes.conf is not None else [0.0] * len(xyxy)
    if boxes.cls is None:
        class_ids = [AIRPLANE_CLASS_ID] * len(xyxy)
    else:
        class_ids = boxes.cls.int().cpu().tolist()

    if boxes.id is None:
        track_ids = [None] * len(xyxy)
    else:
        track_ids = boxes.id.int().cpu().tolist()

    detections: list[dict[str, Any]] = []
    for bbox, confidence, class_id, track_id in zip(
        xyxy, confs, class_ids, track_ids, strict=True
    ):
        if class_id != AIRPLANE_CLASS_ID or track_id is None:
            continue

        detections.append(
            {
                "track_id": int(track_id),
                "label": AIRPLANE_LABEL,
                "bbox": [round(float(value), 2) for value in bbox],
                "confidence": round(float(confidence), 4),
                "interpolated": False,
            }
        )

    detections.sort(key=lambda item: item["track_id"])
    return detections


def annotate_frame(frame: Any, detections: list[dict[str, Any]]) -> Any:
    for detection in detections:
        x1, y1, x2, y2 = [int(round(value)) for value in detection["bbox"]]
        color = (0, 255, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        overlay_lines = [f"ID: {detection['track_id']} conf: {detection['confidence']:.2f}"]
        flight_info = detection.get("flight_info")
        if isinstance(flight_info, dict) and flight_info.get("matched"):
            flight_label_parts = []
            for key in ("flight_number", "aircraft_type", "registration"):
                value = flight_info.get(key)
                if value:
                    flight_label_parts.append(str(value))
            if flight_label_parts:
                overlay_lines.append(" ".join(flight_label_parts))

        for line_index, overlay_text in enumerate(overlay_lines):
            text_origin = (x1, max(20, y1 - 10 - (len(overlay_lines) - line_index - 1) * 24))
            cv2.putText(
                frame,
                overlay_text,
                text_origin,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
                cv2.LINE_AA,
            )
    return frame


def write_json(output_path: Path, payload: dict[str, Any]) -> None:
    ensure_parent_dir(output_path)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def clone_detection(detection: dict[str, Any], *, interpolated: bool) -> dict[str, Any]:
    cloned_detection = {
        "track_id": detection["track_id"],
        "label": detection["label"],
        "bbox": [round(float(value), 2) for value in detection["bbox"]],
        "confidence": round(float(detection["confidence"]), 4),
        "interpolated": interpolated,
    }
    if detection.get("flight_info") is not None:
        cloned_detection["flight_info"] = json.loads(json.dumps(detection["flight_info"]))
    return cloned_detection


def interpolate_detection(
    start_detection: dict[str, Any],
    end_detection: dict[str, Any],
    ratio: float,
) -> dict[str, Any]:
    start_bbox = start_detection["bbox"]
    end_bbox = end_detection["bbox"]
    bbox = [
        round(start_value + (end_value - start_value) * ratio, 2)
        for start_value, end_value in zip(start_bbox, end_bbox, strict=True)
    ]
    confidence = round(
        start_detection["confidence"]
        + (end_detection["confidence"] - start_detection["confidence"]) * ratio,
        4,
    )
    return {
        "track_id": start_detection["track_id"],
        "label": start_detection["label"],
        "bbox": bbox,
        "confidence": confidence,
        "interpolated": True,
    }


def parse_recording_start_datetime(value: str, timezone_name: str) -> datetime:
    normalized = value.strip().replace("T", " ")
    parsed = datetime.fromisoformat(normalized)
    timezone = ZoneInfo(timezone_name)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def resolve_fr24_token(explicit_token: str | None, env_path: Path = Path(".env")) -> str | None:
    if explicit_token:
        return explicit_token
    source_env_file(env_path)
    for env_key in ("FR24_API_TOKEN", "FLIGHTRADAR24_API_KEY"):
        env_value = os.environ.get(env_key)
        if env_value:
            return env_value
    return None


def normalize_bearing(angle_degrees: float) -> float:
    return angle_degrees % 360.0


def angular_difference(left: float, right: float) -> float:
    return ((left - right + 180.0) % 360.0) - 180.0


def haversine_distance_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(haversine))


def bearing_between_points(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lon_rad = math.radians(lon2 - lon1)
    x = math.sin(delta_lon_rad) * math.cos(lat2_rad)
    y = (
        math.cos(lat1_rad) * math.sin(lat2_rad)
        - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lon_rad)
    )
    return normalize_bearing(math.degrees(math.atan2(x, y)))


def build_search_bounds(
    latitude: float,
    longitude: float,
    radius_km: float,
) -> str:
    lat_delta = radius_km / 111.32
    lon_divisor = max(0.1, math.cos(math.radians(latitude)))
    lon_delta = radius_km / (111.32 * lon_divisor)
    north = min(90.0, latitude + lat_delta)
    south = max(-90.0, latitude - lat_delta)
    west = max(-180.0, longitude - lon_delta)
    east = min(180.0, longitude + lon_delta)
    return f"{north:.6f},{south:.6f},{west:.6f},{east:.6f}"


def frame_detection_center_x(detection: dict[str, Any]) -> float:
    x1, _, x2, _ = detection["bbox"]
    return (float(x1) + float(x2)) / 2.0


def build_fr24_headers(api_token: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Accept-Version": "v1",
        "Authorization": f"Bearer {api_token}",
        "User-Agent": "FR24 API Python SDK/manual-integration",
    }


def log_fr24_event(message: str) -> None:
    tqdm.write(f"[fr24] {message}")


def build_fr24_cache_path(cache_dir: Path, timestamp: datetime, bounds: str, limit: int) -> Path:
    cache_key_payload = json.dumps(
        {
            "endpoint": "historic-flight-positions-full",
            "timestamp": int(timestamp.timestamp()),
            "bounds": bounds,
            "limit": limit,
        },
        sort_keys=True,
    )
    cache_key = hashlib.sha256(cache_key_payload.encode("utf-8")).hexdigest()
    return cache_dir / "fr24" / f"{cache_key}.json"


def build_fr24_track_cache_path(
    cache_dir: Path,
    *,
    video_name: str,
    clip_start_frame: int,
    clip_end_frame: int,
    track_id: int,
    camera_bearing: float,
    camera_horizontal_fov: float,
    search_radius_km: float,
    max_error_ratio: float,
) -> Path:
    cache_key_payload = json.dumps(
        {
            "strategy": "track_midpoint_sampling",
            "video_name": video_name,
            "clip_start_frame": clip_start_frame,
            "clip_end_frame": clip_end_frame,
            "track_id": track_id,
            "camera_bearing": round(camera_bearing, 4),
            "camera_horizontal_fov": round(camera_horizontal_fov, 4),
            "search_radius_km": round(search_radius_km, 4),
            "max_error_ratio": round(max_error_ratio, 6),
        },
        sort_keys=True,
    )
    cache_key = hashlib.sha256(cache_key_payload.encode("utf-8")).hexdigest()
    return cache_dir / "fr24_tracks" / f"{cache_key}.json"


def parse_retry_after_seconds(header_value: str | None) -> float | None:
    if not header_value:
        return None
    stripped = header_value.strip()
    if not stripped:
        return None
    try:
        return max(0.0, float(stripped))
    except ValueError:
        pass
    try:
        retry_datetime = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError):
        return None
    if retry_datetime.tzinfo is None:
        retry_datetime = retry_datetime.replace(tzinfo=ZoneInfo("UTC"))
    return max(0.0, (retry_datetime - datetime.now(retry_datetime.tzinfo)).total_seconds())


def fetch_fr24_json_with_retry(
    request: urllib.request.Request,
    *,
    max_retries: int = 4,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    attempt = 0
    request_url = getattr(request, "full_url", "<unknown>")
    while True:
        try:
            log_fr24_event(f"request {request_url}")
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                log_fr24_event(f"response received {request_url}")
                return json.load(response)
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            if exc.code != 429 or attempt >= max_retries:
                raise RuntimeError(
                    f"FR24 API returned HTTP {exc.code}: {error_body[:240]}"
                ) from exc

            retry_after_seconds = parse_retry_after_seconds(exc.headers.get("Retry-After"))
            if retry_after_seconds is None:
                retry_after_seconds = float(2**attempt)
            log_fr24_event(
                f"429 received {request_url} retry_after={retry_after_seconds:.1f}s"
            )
            time.sleep(retry_after_seconds)
            attempt += 1
        except urllib.error.URLError as exc:
            raise RuntimeError(f"FR24 API request failed: {exc.reason}") from exc


def fetch_fr24_historic_positions(
    api_token: str,
    timestamp: datetime,
    bounds: str,
    cache_dir: Path,
    cache_stats: dict[str, int],
    limit: int = 200,
) -> list[dict[str, Any]]:
    cache_path = build_fr24_cache_path(cache_dir, timestamp, bounds, limit)
    if cache_path.exists():
        cache_payload = load_json(cache_path)
        cache_stats["hits"] += 1
        log_fr24_event(
            "cached "
            f"historic/flight-positions/full timestamp={int(timestamp.timestamp())} limit={limit}"
        )
        data = cache_payload.get("data")
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    query = urllib.parse.urlencode(
        {
            "timestamp": str(int(timestamp.timestamp())),
            "bounds": bounds,
            "limit": str(limit),
        }
    )
    request = urllib.request.Request(
        f"https://fr24api.flightradar24.com/api/historic/flight-positions/full?{query}",
        headers=build_fr24_headers(api_token),
    )
    payload = fetch_fr24_json_with_retry(request)

    cache_stats["misses"] += 1
    write_json(
        cache_path,
        {
            "timestamp": timestamp.isoformat(),
            "bounds": bounds,
            "limit": limit,
            "data": payload.get("data", []),
        },
    )
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def project_flights_to_frame(
    flights: list[dict[str, Any]],
    *,
    camera_lat: float,
    camera_lon: float,
    camera_bearing: float,
    camera_horizontal_fov: float,
    frame_width: int,
    search_radius_km: float,
) -> list[dict[str, Any]]:
    projected_flights: list[dict[str, Any]] = []
    half_fov = camera_horizontal_fov / 2.0
    for flight in flights:
        flight_lat = flight.get("lat")
        flight_lon = flight.get("lon")
        if not isinstance(flight_lat, (float, int)) or not isinstance(flight_lon, (float, int)):
            continue

        distance_km = haversine_distance_km(camera_lat, camera_lon, flight_lat, flight_lon)
        if distance_km > search_radius_km:
            continue

        bearing = bearing_between_points(camera_lat, camera_lon, flight_lat, flight_lon)
        offset = angular_difference(bearing, camera_bearing)
        if abs(offset) > half_fov:
            continue

        projected_x = round(((offset + half_fov) / camera_horizontal_fov) * frame_width, 2)
        enriched_flight = dict(flight)
        enriched_flight["distance_from_camera_km"] = round(distance_km, 3)
        enriched_flight["bearing_from_camera_degrees"] = round(bearing, 2)
        enriched_flight["bearing_offset_degrees"] = round(offset, 2)
        enriched_flight["projected_center_x"] = projected_x
        projected_flights.append(enriched_flight)

    projected_flights.sort(key=lambda item: float(item["projected_center_x"]))
    return projected_flights


def match_detections_to_projected_flights(
    detections: list[dict[str, Any]],
    projected_flights: list[dict[str, Any]],
    frame_width: int,
    max_error_ratio: float,
) -> list[tuple[dict[str, Any], dict[str, Any], float]]:
    max_error_pixels = frame_width * max_error_ratio
    pairs: list[tuple[float, int, int]] = []
    for detection_index, detection in enumerate(detections):
        detection_center_x = frame_detection_center_x(detection)
        for flight_index, flight in enumerate(projected_flights):
            error_pixels = abs(detection_center_x - float(flight["projected_center_x"]))
            if error_pixels <= max_error_pixels:
                pairs.append((error_pixels, detection_index, flight_index))

    matches: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    used_detection_indices: set[int] = set()
    used_flight_indices: set[int] = set()
    for error_pixels, detection_index, flight_index in sorted(pairs):
        if detection_index in used_detection_indices or flight_index in used_flight_indices:
            continue
        used_detection_indices.add(detection_index)
        used_flight_indices.add(flight_index)
        matches.append((detections[detection_index], projected_flights[flight_index], error_pixels))
    return matches


def build_flight_info(
    flight: dict[str, Any],
    *,
    average_error_pixels: float,
    sample_count: int,
    sampled_query_count: int,
    source_timestamp: str,
    frame_width: int,
    max_error_ratio: float,
    matched_at_track_progress: float,
) -> dict[str, Any]:
    observed_ratio = sample_count / sampled_query_count if sampled_query_count > 0 else 0.0
    error_ratio = min(1.0, average_error_pixels / (frame_width * max_error_ratio))
    confidence = round(max(0.0, min(1.0, 0.6 * observed_ratio + 0.4 * (1.0 - error_ratio))), 3)
    return {
        "matched": True,
        "match_confidence": confidence,
        "sample_count": sample_count,
        "query_timestamp": source_timestamp,
        "matched_at_track_progress": round(matched_at_track_progress, 3),
        "fr24_id": flight.get("fr24_id"),
        "flight_number": flight.get("flight"),
        "callsign": flight.get("callsign"),
        "aircraft_type": flight.get("type"),
        "registration": flight.get("reg"),
        "airline_icao": flight.get("operating_as") or flight.get("painted_as"),
        "origin_iata": flight.get("orig_iata"),
        "origin_icao": flight.get("orig_icao"),
        "destination_iata": flight.get("dest_iata"),
        "destination_icao": flight.get("dest_icao"),
        "source_timestamp": source_timestamp,
        "source_latitude": (
            round(float(flight["lat"]), 6) if flight.get("lat") is not None else None
        ),
        "source_longitude": round(float(flight["lon"]), 6)
        if flight.get("lon") is not None
        else None,
        "source_track_degrees": flight.get("track"),
        "source_altitude_feet": flight.get("alt"),
        "distance_from_camera_km": flight.get("distance_from_camera_km"),
        "bearing_from_camera_degrees": flight.get("bearing_from_camera_degrees"),
    }


def summarize_track_frames(frames: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    track_frames: dict[int, list[int]] = {}
    for relative_index, frame_payload in enumerate(frames):
        for detection in frame_payload["detections"]:
            track_id = int(detection["track_id"])
            track_frames.setdefault(track_id, []).append(relative_index)

    summary: dict[int, dict[str, Any]] = {}
    if not frames:
        return summary

    last_relative_index = len(frames) - 1
    for track_id, relative_indices in track_frames.items():
        first_index = min(relative_indices)
        last_index = max(relative_indices)
        summary[track_id] = {
            "track_id": track_id,
            "first_relative_index": first_index,
            "last_relative_index": last_index,
            "frame_count": len(relative_indices),
            "is_persistent": first_index == 0 and last_index == last_relative_index,
        }
    return summary


def build_track_query_progress_points() -> list[float]:
    return [0.35, 0.45, 0.50, 0.55, 0.65]


def compute_track_query_indices(track_summary: dict[str, Any]) -> list[tuple[int, float]]:
    first_index = int(track_summary["first_relative_index"])
    last_index = int(track_summary["last_relative_index"])
    if last_index <= first_index:
        return [(first_index, 0.5)]

    span = last_index - first_index
    candidates: list[tuple[int, float]] = []
    seen_indices: set[int] = set()
    for progress in build_track_query_progress_points():
        relative_index = first_index + int(round(span * progress))
        relative_index = min(max(relative_index, first_index), last_index)
        if relative_index in seen_indices:
            continue
        seen_indices.add(relative_index)
        candidates.append((relative_index, progress))
    return candidates


def pick_track_detection(frame_payload: dict[str, Any], track_id: int) -> dict[str, Any] | None:
    for detection in frame_payload["detections"]:
        if int(detection["track_id"]) == track_id:
            return detection
    return None


def evaluate_track_match_candidate(
    detection: dict[str, Any],
    projected_flights: list[dict[str, Any]],
    frame_width: int,
    max_error_ratio: float,
) -> tuple[dict[str, Any], float] | None:
    matches = match_detections_to_projected_flights(
        [detection],
        projected_flights,
        frame_width,
        max_error_ratio,
    )
    if not matches:
        return None
    _, flight, error_pixels = matches[0]
    return flight, error_pixels


def load_track_cache(path: Path, cache_stats: dict[str, int]) -> dict[str, Any] | None:
    if not path.exists():
        return None
    cache_stats["hits"] += 1
    return load_json(path)


def store_track_cache(path: Path, payload: dict[str, Any], cache_stats: dict[str, int]) -> None:
    cache_stats["misses"] += 1
    write_json(path, payload)


def enrich_frames_with_fr24(
    frames: list[dict[str, Any]],
    metadata: dict[str, Any],
    *,
    cache_dir: Path,
    recording_start: datetime,
    camera_lat: float,
    camera_lon: float,
    camera_bearing: float,
    camera_horizontal_fov: float,
    fr24_search_radius_km: float,
    fr24_match_max_error_ratio: float,
    api_token: str,
) -> dict[str, Any]:
    bounds = build_search_bounds(camera_lat, camera_lon, fr24_search_radius_km)
    cache_stats = {"hits": 0, "misses": 0}
    track_stats = {
        "tracks_seen": 0,
        "tracks_skipped_persistent": 0,
        "tracks_queried": 0,
        "tracks_matched": 0,
        "tracks_no_match": 0,
        "tracks_error": 0,
    }
    track_summaries = summarize_track_frames(frames)
    track_stats["tracks_seen"] = len(track_summaries)
    resolved_track_info: dict[int, dict[str, Any]] = {}
    queryable_tracks = [
        (track_id, track_summary)
        for track_id, track_summary in sorted(track_summaries.items())
        if not track_summary["is_persistent"]
    ]
    track_stats["tracks_skipped_persistent"] = len(track_summaries) - len(queryable_tracks)

    for track_id, track_summary in tqdm(
        queryable_tracks,
        total=len(queryable_tracks),
        unit="track",
        desc="Resolving FR24",
    ):

        track_cache_path = build_fr24_track_cache_path(
            cache_dir,
            video_name=metadata["video_name"],
            clip_start_frame=frames[0]["frame_index"] if frames else 0,
            clip_end_frame=frames[-1]["frame_index"] if frames else 0,
            track_id=track_id,
            camera_bearing=camera_bearing,
            camera_horizontal_fov=camera_horizontal_fov,
            search_radius_km=fr24_search_radius_km,
            max_error_ratio=fr24_match_max_error_ratio,
        )
        cached_track_result = load_track_cache(track_cache_path, cache_stats)
        if cached_track_result is not None:
            cached_status = cached_track_result.get("status")
            if cached_status == "matched" and isinstance(
                cached_track_result.get("flight_info"), dict
            ):
                resolved_track_info[track_id] = cached_track_result["flight_info"]
                track_stats["tracks_matched"] += 1
            elif cached_status == "no_match":
                track_stats["tracks_no_match"] += 1
            elif cached_status == "error":
                track_stats["tracks_error"] += 1
            continue

        track_stats["tracks_queried"] += 1
        attempts: list[dict[str, Any]] = []
        candidate_scores: dict[str, dict[str, Any]] = {}
        track_error: str | None = None

        for relative_index, progress in compute_track_query_indices(track_summary):
            frame_payload = frames[relative_index]
            detection = pick_track_detection(frame_payload, track_id)
            if detection is None:
                continue

            absolute_timestamp = recording_start + timedelta(
                seconds=float(frame_payload["time_seconds"])
            )
            try:
                flights = fetch_fr24_historic_positions(
                    api_token,
                    absolute_timestamp,
                    bounds,
                    cache_dir,
                    cache_stats,
                )
            except RuntimeError as exc:
                track_error = str(exc)
                break

            projected_flights = project_flights_to_frame(
                flights,
                camera_lat=camera_lat,
                camera_lon=camera_lon,
                camera_bearing=camera_bearing,
                camera_horizontal_fov=camera_horizontal_fov,
                frame_width=metadata["width"],
                search_radius_km=fr24_search_radius_km,
            )
            attempt_payload = {
                "frame_index": frame_payload["frame_index"],
                "query_timestamp": absolute_timestamp.isoformat(),
                "track_progress": round(progress, 3),
                "projected_flights": len(projected_flights),
            }
            candidate = evaluate_track_match_candidate(
                detection,
                projected_flights,
                metadata["width"],
                fr24_match_max_error_ratio,
            )
            if candidate is None:
                attempts.append(attempt_payload)
                continue

            flight, error_pixels = candidate
            fr24_id = str(flight.get("fr24_id"))
            attempt_payload["matched_fr24_id"] = fr24_id
            attempt_payload["error_pixels"] = round(error_pixels, 3)
            attempts.append(attempt_payload)
            if fr24_id not in candidate_scores:
                candidate_scores[fr24_id] = {
                    "count": 0,
                    "total_error_pixels": 0.0,
                    "flight": flight,
                    "source_timestamp": absolute_timestamp.isoformat(),
                    "matched_at_track_progress": progress,
                }
            candidate_entry = candidate_scores[fr24_id]
            candidate_entry["count"] += 1
            candidate_entry["total_error_pixels"] += error_pixels
            candidate_entry["flight"] = flight
            candidate_entry["source_timestamp"] = absolute_timestamp.isoformat()
            candidate_entry["matched_at_track_progress"] = progress

            if candidate_entry["count"] >= 2:
                break

        if track_error is not None:
            track_stats["tracks_error"] += 1
            store_track_cache(
                track_cache_path,
                {
                    "status": "error",
                    "track_id": track_id,
                    "attempts": attempts,
                    "error": track_error,
                },
                cache_stats,
            )
            continue

        if not candidate_scores:
            track_stats["tracks_no_match"] += 1
            store_track_cache(
                track_cache_path,
                {
                    "status": "no_match",
                    "track_id": track_id,
                    "attempts": attempts,
                },
                cache_stats,
            )
            continue

        ranked_candidates = sorted(
            candidate_scores.values(),
            key=lambda item: (-item["count"], item["total_error_pixels"]),
        )
        if len(ranked_candidates) > 1 and (
            ranked_candidates[0]["count"] == ranked_candidates[1]["count"]
        ):
            track_stats["tracks_no_match"] += 1
            store_track_cache(
                track_cache_path,
                {
                    "status": "no_match",
                    "reason": "ambiguous",
                    "track_id": track_id,
                    "attempts": attempts,
                },
                cache_stats,
            )
            continue

        best_match = ranked_candidates[0]
        average_error = best_match["total_error_pixels"] / best_match["count"]
        flight_info = build_flight_info(
            best_match["flight"],
            average_error_pixels=average_error,
            sample_count=best_match["count"],
            sampled_query_count=max(1, len(attempts)),
            source_timestamp=best_match["source_timestamp"],
            frame_width=metadata["width"],
            max_error_ratio=fr24_match_max_error_ratio,
            matched_at_track_progress=float(best_match["matched_at_track_progress"]),
        )
        resolved_track_info[track_id] = flight_info
        track_stats["tracks_matched"] += 1
        store_track_cache(
            track_cache_path,
            {
                "status": "matched",
                "track_id": track_id,
                "attempts": attempts,
                "flight_info": flight_info,
            },
            cache_stats,
        )

    for frame_payload in frames:
        for detection in frame_payload["detections"]:
            flight_info = resolved_track_info.get(int(detection["track_id"]))
            if flight_info:
                detection["flight_info"] = flight_info

    return {
        "enabled": True,
        "provider": "flightradar24",
        "strategy": "track_midpoint_sampling",
        "status": "matched" if resolved_track_info else "no_matches",
        "recording_started_at": recording_start.isoformat(),
        "timezone": (
            recording_start.tzinfo.key
            if hasattr(recording_start.tzinfo, "key")
            else str(recording_start.tzinfo)
        ),
        "camera_latitude": camera_lat,
        "camera_longitude": camera_lon,
        "camera_bearing_degrees": round(normalize_bearing(camera_bearing), 2),
        "camera_horizontal_fov_degrees": round(camera_horizontal_fov, 2),
        "search_radius_km": round(fr24_search_radius_km, 2),
        "search_bounds": bounds,
        "track_stats": track_stats,
        "tracks_seen": track_stats["tracks_seen"],
        "tracks_skipped_persistent": track_stats["tracks_skipped_persistent"],
        "tracks_queried": track_stats["tracks_queried"],
        "tracks_matched": track_stats["tracks_matched"],
        "tracks_no_match": track_stats["tracks_no_match"],
        "tracks_error": track_stats["tracks_error"],
        "cache_hits": cache_stats["hits"],
        "cache_misses": cache_stats["misses"],
    }


def build_output_frames(
    keyframes: list[dict[str, Any]],
    fps: float,
    start_frame: int,
    end_frame: int,
) -> list[dict[str, Any]]:
    frame_payloads: dict[int, dict[str, Any]] = {
        frame_index: build_frame_payload(frame_index, fps, [])
        for frame_index in range(start_frame, end_frame)
    }

    for keyframe in keyframes:
        frame_index = keyframe["frame_index"]
        if start_frame <= frame_index < end_frame:
            frame_payloads[frame_index]["detections"] = [
                clone_detection(detection, interpolated=False)
                for detection in keyframe["detections"]
            ]

    for current_keyframe, next_keyframe in zip(keyframes, keyframes[1:], strict=False):
        current_index = current_keyframe["frame_index"]
        next_index = next_keyframe["frame_index"]
        gap = next_index - current_index
        if gap <= 1:
            continue

        current_by_id = {
            detection["track_id"]: detection for detection in current_keyframe["detections"]
        }
        next_by_id = {
            detection["track_id"]: detection for detection in next_keyframe["detections"]
        }
        shared_ids = sorted(set(current_by_id) & set(next_by_id))
        for frame_index in range(max(start_frame, current_index + 1), min(end_frame, next_index)):
            ratio = (frame_index - current_index) / gap
            frame_detections = frame_payloads[frame_index]["detections"]
            for track_id in shared_ids:
                frame_detections.append(
                    interpolate_detection(
                        current_by_id[track_id],
                        next_by_id[track_id],
                        ratio,
                    )
                )

    for frame_payload in frame_payloads.values():
        frame_payload["detections"].sort(key=lambda item: item["track_id"])

    return [frame_payloads[frame_index] for frame_index in range(start_frame, end_frame)]


def compute_tracking_cache(
    input_path: Path,
    model_path: str,
    tracker: str,
    conf: float,
    device: str | None,
    cache_path: Path,
    inference_stride: int,
) -> dict[str, Any]:
    from ultralytics import YOLO

    capture = open_video_capture(input_path)
    metadata = build_metadata(input_path, capture)
    model = YOLO(model_path)
    keyframes: list[dict[str, Any]] = []
    processed_frames = 0
    progress_total = metadata["total_frames"] or None

    try:
        with tqdm(total=progress_total, unit="frame", desc="Tracking airplanes") as progress:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break

                is_last_frame = processed_frames == metadata["total_frames"] - 1
                if processed_frames % inference_stride == 0 or is_last_frame:
                    results = model.track(
                        frame,
                        persist=True,
                        classes=[AIRPLANE_CLASS_ID],
                        conf=conf,
                        device=device,
                        tracker=tracker,
                        verbose=False,
                    )
                    detections = extract_detections(results[0])
                    keyframes.append(
                        build_frame_payload(processed_frames, metadata["fps"], detections)
                    )

                processed_frames += 1
                progress.update(1)
    finally:
        capture.release()

    metadata["total_frames"] = processed_frames
    payload = {
        "cache_metadata": {
            "cache_format_version": 2,
            "inference_stride": inference_stride,
        },
        "metadata": metadata,
        "keyframes": keyframes,
    }
    write_json(cache_path, payload)
    return payload


def get_tracking_cache(args: argparse.Namespace) -> tuple[str, Path, dict[str, Any]]:
    cache_key, cache_path = build_cache_paths(
        args.cache_dir,
        args.input,
        args.model,
        args.tracker,
        args.conf,
        args.inference_stride,
    )
    if cache_path.exists() and not args.force_recompute:
        return cache_key, cache_path, load_json(cache_path)

    ensure_parent_dir(cache_path)
    payload = compute_tracking_cache(
        args.input,
        args.model,
        args.tracker,
        args.conf,
        args.device,
        cache_path,
        args.inference_stride,
    )
    return cache_key, cache_path, payload


def render_clip_from_cache(
    input_path: Path,
    output_video: Path,
    metadata: dict[str, Any],
    frames: list[dict[str, Any]],
    start_frame: int,
) -> None:
    capture = open_video_capture(input_path)
    writer = create_video_writer(
        output_video,
        metadata["width"],
        metadata["height"],
        metadata["fps"],
    )

    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        for frame_payload in tqdm(
            frames,
            total=len(frames),
            unit="frame",
            desc="Rendering debug video",
        ):
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(
                    f"Could not read frame {frame_payload['frame_index']} from input video."
                )

            writer.write(annotate_frame(frame, frame_payload["detections"]))
    finally:
        capture.release()
        writer.release()


def run_tracking(args: argparse.Namespace) -> None:
    if not args.input.exists():
        raise FileNotFoundError(f"Input video not found: {args.input}")
    if args.input.suffix.lower() != ".mp4":
        raise ValueError("Only local .mp4 files are supported.")
    if args.inference_stride < 1:
        raise ValueError("--inference-stride must be greater than or equal to 1.")
    _, _, cache_payload = get_tracking_cache(args)
    source_metadata = cache_payload["metadata"]
    start_frame, end_frame = resolve_frame_range(
        source_metadata["fps"],
        source_metadata["total_frames"],
        args.start_time,
        args.end_time,
    )
    clip_frames = build_output_frames(
        cache_payload["keyframes"],
        source_metadata["fps"],
        start_frame,
        end_frame,
    )
    output_payload = {
        "metadata": build_output_metadata(
            source_metadata,
            start_frame,
            end_frame,
            args.inference_stride,
        ),
        "frames": clip_frames,
    }

    if args.fr24_recording_start is not None:
        required_values = {
            "--camera-lat": args.camera_lat,
            "--camera-lon": args.camera_lon,
            "--camera-bearing": args.camera_bearing,
        }
        missing_values = [name for name, value in required_values.items() if value is None]
        if missing_values:
            missing = ", ".join(missing_values)
            raise ValueError(f"FR24 enrichment requires {missing}.")

        api_token = resolve_fr24_token(args.fr24_token)
        if not api_token:
            raise ValueError(
                "FR24 enrichment requires --fr24-token or FR24_API_TOKEN/FLIGHTRADAR24_API_KEY."
            )
        recording_start = parse_recording_start_datetime(
            args.fr24_recording_start,
            args.fr24_timezone,
        )
        try:
            output_payload["metadata"]["flight_radar_enrichment"] = enrich_frames_with_fr24(
                clip_frames,
                source_metadata,
                cache_dir=args.cache_dir,
                recording_start=recording_start + timedelta(seconds=args.start_time),
                camera_lat=float(args.camera_lat),
                camera_lon=float(args.camera_lon),
                camera_bearing=float(args.camera_bearing),
                camera_horizontal_fov=float(args.camera_horizontal_fov),
                fr24_search_radius_km=float(args.fr24_search_radius_km),
                fr24_match_max_error_ratio=float(args.fr24_match_max_error_ratio),
                api_token=api_token,
            )
        except RuntimeError as exc:
            output_payload["metadata"]["flight_radar_enrichment"] = {
                "enabled": True,
                "provider": "flightradar24",
                "strategy": "track_midpoint_sampling",
                "status": "error",
                "recording_started_at": recording_start.isoformat(),
                "timezone": args.fr24_timezone,
                "camera_latitude": args.camera_lat,
                "camera_longitude": args.camera_lon,
                "camera_bearing_degrees": args.camera_bearing,
                "camera_horizontal_fov_degrees": args.camera_horizontal_fov,
                "search_radius_km": args.fr24_search_radius_km,
                "tracks_seen": 0,
                "tracks_skipped_persistent": 0,
                "tracks_queried": 0,
                "tracks_matched": 0,
                "tracks_no_match": 0,
                "tracks_error": 1,
                "cache_hits": 0,
                "cache_misses": 0,
                "error": str(exc),
            }

    render_clip_from_cache(
        args.input,
        args.output_video,
        source_metadata,
        clip_frames,
        start_frame,
    )
    write_json(args.output_json, output_payload)


def main() -> int:
    args = parse_args()
    run_tracking(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
