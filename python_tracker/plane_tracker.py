from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import cv2
from tqdm import tqdm

AIRPLANE_CLASS_ID = 4
AIRPLANE_LABEL = "airplane"
DEFAULT_MODEL_PATH = "yolov8n.pt"
DEFAULT_TRACKER = "bytetrack.yaml"
DEFAULT_CACHE_DIR = Path(".plane_tracker_cache")


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
    return parser.parse_args()


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


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

        overlay_text = f"ID: {detection['track_id']} conf: {detection['confidence']:.2f}"
        text_origin = (x1, max(20, y1 - 10))
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
    return {
        "track_id": detection["track_id"],
        "label": detection["label"],
        "bbox": [round(float(value), 2) for value in detection["bbox"]],
        "confidence": round(float(detection["confidence"]), 4),
        "interpolated": interpolated,
    }


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
