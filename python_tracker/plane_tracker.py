from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
from tqdm import tqdm

AIRPLANE_CLASS_ID = 4
AIRPLANE_LABEL = "airplane"
DEFAULT_MODEL_PATH = "yolov8n.pt"
DEFAULT_TRACKER = "bytetrack.yaml"


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


def run_tracking(args: argparse.Namespace) -> None:
    from ultralytics import YOLO

    if not args.input.exists():
        raise FileNotFoundError(f"Input video not found: {args.input}")
    if args.input.suffix.lower() != ".mp4":
        raise ValueError("Only local .mp4 files are supported.")

    capture = open_video_capture(args.input)
    metadata = build_metadata(args.input, capture)
    writer = create_video_writer(
        args.output_video,
        metadata["width"],
        metadata["height"],
        metadata["fps"],
    )
    model = YOLO(args.model)

    frames: list[dict[str, Any]] = []
    processed_frames = 0
    progress_total = metadata["total_frames"] or None

    try:
        with tqdm(total=progress_total, unit="frame", desc="Tracking airplanes") as progress:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break

                results = model.track(
                    frame,
                    persist=True,
                    classes=[AIRPLANE_CLASS_ID],
                    conf=args.conf,
                    device=args.device,
                    tracker=args.tracker,
                    verbose=False,
                )
                detections = extract_detections(results[0])
                frames.append({"frame_index": processed_frames, "detections": detections})
                writer.write(annotate_frame(frame.copy(), detections))

                processed_frames += 1
                progress.update(1)
    finally:
        capture.release()
        writer.release()

    metadata["total_frames"] = processed_frames
    payload = {"metadata": metadata, "frames": frames}
    write_json(args.output_json, payload)


def main() -> int:
    args = parse_args()
    run_tracking(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
