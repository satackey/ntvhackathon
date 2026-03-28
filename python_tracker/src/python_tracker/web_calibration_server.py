from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from python_tracker.calibration import (
    DEFAULT_TIME_WINDOW_SEC,
    aggregate_tracks,
    build_candidate_index,
    build_with_flight_info_payload,
    cached_track_records_for_aircraft,
    candidate_aircraft_for_detection,
    compute_search_bbox,
    encode_frame_as_jpeg,
    fetch_states_all,
    fetch_track,
    find_missing_intervals,
    frame_to_estimated_unix,
    load_camera_config,
    load_json,
    load_manual_matches,
    load_opensky_cache,
    manual_matches_by_track,
    merge_opensky_query,
    normalize_camera_config,
    normalize_reference_time_utc,
    project_state_records,
    resolve_opensky_access_token_from_config,
    resolve_opensky_auth_config,
    state_records_for_frame,
    upsert_manual_match,
    write_json,
)

STATIC_DIR = Path(__file__).with_name("web_assets")


class CalibrationSession:
    def __init__(self, args: Any) -> None:
        self.args = args
        self.video_path = Path(args.video)
        self.tracking_json_path = Path(args.tracking_json)
        self.opensky_cache_path = Path(args.opensky_cache)
        self.camera_config_path = (
            Path(args.camera_config)
            if args.camera_config
            else self.tracking_json_path.with_name("camera_config.json")
        )
        self.manual_matches_path = (
            Path(args.manual_matches)
            if args.manual_matches
            else self.tracking_json_path.with_name("manual_matches.json")
        )
        self.export_path = self.tracking_json_path.with_name(
            f"{self.tracking_json_path.stem}.with_flight_info.json"
        )
        self.tracking_payload = load_json(self.tracking_json_path)
        self.tracks = aggregate_tracks(self.tracking_payload.get("frames", []))
        self.camera_config = normalize_camera_config(
            load_camera_config(self.camera_config_path, self.video_path),
            video_path=self.video_path,
        )
        self.manual_matches_payload = load_manual_matches(self.manual_matches_path)
        self.opensky_cache_payload = load_opensky_cache(self.opensky_cache_path)
        self.auth_config = resolve_opensky_auth_config(args)
        self.lock = threading.Lock()
        self.ui_state: dict[str, Any] = {
            "frame_index": 0,
            "selected_track_id": next(iter(self.tracks), None),
            "selected_candidate_icao": None,
            "time_window_sec": DEFAULT_TIME_WINDOW_SEC,
            "show_labels": True,
            "only_selected_track": False,
            "bbox_opacity": 0.45,
            "marker_size": 10,
            "overlay_opacity": 0.7,
            "notes": "",
        }

    def auth_summary(self) -> dict[str, Any]:
        if self.auth_config is None:
            return {"configured": False, "mode": None}
        summary = {"configured": True, "mode": self.auth_config.mode}
        if self.auth_config.mode == "credentials_json":
            summary["credentials_json"] = str(self.auth_config.credentials_json)
        return summary

    def _selected_detection(self, frame_payload: dict[str, Any]) -> dict[str, Any] | None:
        selected_track_id = self.ui_state["selected_track_id"]
        return next(
            (
                detection
                for detection in frame_payload.get("detections", [])
                if detection["track_id"] == selected_track_id
            ),
            None,
        )

    def _frame_payload(self) -> dict[str, Any]:
        return self.tracking_payload["frames"][self.ui_state["frame_index"]]

    def _current_bbox(self) -> list[float]:
        return compute_search_bbox(self.camera_config["lat"], self.camera_config["lon"])

    def _current_states(self, frame_payload: dict[str, Any]) -> list[dict[str, Any]]:
        frame_unix = frame_to_estimated_unix(frame_payload, self.camera_config)
        return state_records_for_frame(
            self.opensky_cache_payload,
            frame_unix=frame_unix,
            bbox=self._current_bbox(),
        )

    def _projected_states(self, current_states: list[dict[str, Any]]) -> list[dict[str, Any]]:
        metadata = self.tracking_payload["metadata"]
        return project_state_records(
            current_states,
            camera_config=self.camera_config,
            frame_width=int(metadata["width"]),
            frame_height=int(metadata["height"]),
        )

    def _cache_overview(self) -> list[dict[str, Any]]:
        return [
            {
                "query_type": query["query_type"],
                "begin_unix": query["begin_unix"],
                "end_unix": query["end_unix"],
                "bbox": query.get("bbox"),
                "record_count": len(query.get("records", [])),
                "fetched_at": query.get("fetched_at"),
            }
            for query in self.opensky_cache_payload.get("queries", [])
        ]

    def snapshot(self) -> dict[str, Any]:
        frame_payload = self._frame_payload()
        current_states = self._current_states(frame_payload)
        projected_states = self._projected_states(current_states)
        selected_detection = self._selected_detection(frame_payload)
        candidates = candidate_aircraft_for_detection(selected_detection, projected_states)
        selected_candidate_icao = self.ui_state["selected_candidate_icao"]
        if candidates and selected_candidate_icao not in {item["icao24"] for item in candidates}:
            selected_candidate_icao = candidates[0]["icao24"]
            self.ui_state["selected_candidate_icao"] = selected_candidate_icao
        selected_candidate = next(
            (item for item in candidates if item["icao24"] == selected_candidate_icao),
            None,
        )
        selected_track_records = cached_track_records_for_aircraft(
            self.opensky_cache_payload,
            icao24=selected_candidate_icao,
        )
        estimated_unix = frame_to_estimated_unix(frame_payload, self.camera_config)
        track_id = self.ui_state["selected_track_id"]
        return {
            "tracking_metadata": self.tracking_payload["metadata"],
            "frame_count": len(self.tracking_payload["frames"]),
            "frame_indices": [
                frame["frame_index"] for frame in self.tracking_payload.get("frames", [])
            ],
            "frame_payload": frame_payload,
            "frame_image_url": f"/api/frame-image?frame_index={frame_payload['frame_index']}",
            "camera_config": self.camera_config,
            "ui_state": self.ui_state,
            "auth": self.auth_summary(),
            "tracks": list(self.tracks.keys()),
            "selected_track_frames": self.tracks.get(track_id, {}).get("frames", []),
            "selected_detection": selected_detection,
            "manual_match": manual_matches_by_track(self.manual_matches_payload).get(track_id),
            "current_bbox": self._current_bbox(),
            "estimated_unix": estimated_unix,
            "current_states": current_states,
            "projected_states": projected_states,
            "candidates": candidates,
            "selected_candidate": selected_candidate,
            "selected_track_records": selected_track_records,
            "cache_overview": self._cache_overview(),
            "candidate_index_count": len(
                build_candidate_index(
                    self.tracking_payload,
                    self.camera_config,
                    self.opensky_cache_payload,
                )
            ),
        }

    def update_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if "frame_index" in payload:
                frame_count = len(self.tracking_payload["frames"])
                self.ui_state["frame_index"] = max(
                    0,
                    min(int(payload["frame_index"]), frame_count - 1),
                )
            if "selected_track_id" in payload and payload["selected_track_id"] is not None:
                track_id = int(payload["selected_track_id"])
                if track_id in self.tracks:
                    self.ui_state["selected_track_id"] = track_id
            if "selected_candidate_icao" in payload:
                self.ui_state["selected_candidate_icao"] = payload["selected_candidate_icao"]
            if "ui_state" in payload:
                for key in (
                    "time_window_sec",
                    "show_labels",
                    "only_selected_track",
                    "bbox_opacity",
                    "marker_size",
                    "overlay_opacity",
                    "notes",
                ):
                    if key in payload["ui_state"]:
                        self.ui_state[key] = payload["ui_state"][key]
            if "camera_config" in payload:
                new_camera = dict(self.camera_config)
                new_camera.update(payload["camera_config"])
                if "reference_time_utc" in payload["camera_config"]:
                    new_camera["reference_time_utc"] = normalize_reference_time_utc(
                        payload["camera_config"]["reference_time_utc"]
                    )
                self.camera_config = normalize_camera_config(new_camera, video_path=self.video_path)
            return self.snapshot()

    def fetch_current_view(self) -> dict[str, Any]:
        with self.lock:
            frame_payload = self._frame_payload()
            estimated_unix = frame_to_estimated_unix(frame_payload, self.camera_config)
            if estimated_unix is None:
                raise RuntimeError("Reference UTC is required before fetching OpenSky data.")
            token = resolve_opensky_access_token_from_config(self.auth_config)
            begin_unix = int(estimated_unix - self.ui_state["time_window_sec"])
            end_unix = int(estimated_unix + self.ui_state["time_window_sec"])
            bbox = self._current_bbox()
            missing_intervals = find_missing_intervals(
                self.opensky_cache_payload,
                query_type="states_all",
                begin_unix=begin_unix,
                end_unix=end_unix,
                bbox=bbox,
            )
            if missing_intervals:
                now_unix = int(datetime.now(UTC).timestamp())
                if end_unix < now_unix - 3600:
                    raise RuntimeError(
                        "OpenSky /states/all cannot fetch data more than 1 hour in the past. "
                        "Use cached data for this clip, or fetch/import historical data through a "
                        "different source before reopening the app."
                    )
            for missing_begin, missing_end in missing_intervals:
                query = fetch_states_all(
                    token=token,
                    begin_unix=missing_begin,
                    end_unix=missing_end,
                    bbox=bbox,
                )
                merge_opensky_query(self.opensky_cache_payload, query)
            write_json(self.opensky_cache_path, self.opensky_cache_payload)
            snapshot = self.snapshot()
            snapshot["fetch_result"] = {"missing_intervals": missing_intervals}
            return snapshot

    def fetch_selected_track(self) -> dict[str, Any]:
        with self.lock:
            frame_payload = self._frame_payload()
            estimated_unix = frame_to_estimated_unix(frame_payload, self.camera_config)
            if estimated_unix is None:
                raise RuntimeError("Reference UTC is required before fetching OpenSky track data.")
            icao24 = self.ui_state["selected_candidate_icao"]
            if not icao24:
                raise RuntimeError("Select an aircraft candidate first.")
            token = resolve_opensky_access_token_from_config(self.auth_config)
            query = fetch_track(token=token, icao24=icao24, time_unix=estimated_unix)
            merge_opensky_query(self.opensky_cache_payload, query)
            write_json(self.opensky_cache_path, self.opensky_cache_payload)
            return self.snapshot()

    def assign_manual_match(self) -> dict[str, Any]:
        with self.lock:
            icao24 = self.ui_state["selected_candidate_icao"]
            if not icao24:
                raise RuntimeError("Select an aircraft candidate first.")
            candidate = self.snapshot()["selected_candidate"]
            self.manual_matches_payload = upsert_manual_match(
                self.manual_matches_payload,
                track_id=int(self.ui_state["selected_track_id"]),
                icao24=icao24,
                callsign=candidate.get("callsign") if candidate else None,
                notes=self.ui_state.get("notes"),
            )
            return self.snapshot()

    def save_camera_config(self) -> str:
        with self.lock:
            write_json(self.camera_config_path, self.camera_config)
            return str(self.camera_config_path)

    def save_manual_matches(self) -> str:
        with self.lock:
            write_json(self.manual_matches_path, self.manual_matches_payload)
            return str(self.manual_matches_path)

    def export_with_flight_info(self) -> str:
        with self.lock:
            payload = build_with_flight_info_payload(
                self.tracking_payload,
                camera_config=self.camera_config,
                manual_matches_payload=self.manual_matches_payload,
                opensky_cache_path=self.opensky_cache_path,
                cache_payload=self.opensky_cache_payload,
            )
            write_json(self.export_path, payload)
            return str(self.export_path)


def create_app(args: Any) -> FastAPI:
    session = CalibrationSession(args)
    app = FastAPI(title="Cesium OpenSky Calibration")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/bootstrap")
    def bootstrap() -> dict[str, Any]:
        return session.snapshot()

    @app.get("/api/frame-image")
    def frame_image(frame_index: int) -> Response:
        try:
            data = encode_frame_as_jpeg(session.video_path, frame_index)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(content=data, media_type="image/jpeg")

    @app.post("/api/state")
    def update_state(payload: dict[str, Any]) -> dict[str, Any]:
        return session.update_state(payload)

    @app.post("/api/fetch/current-view")
    def fetch_current_view() -> dict[str, Any]:
        try:
            return session.fetch_current_view()
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/fetch/track")
    def fetch_selected_track() -> dict[str, Any]:
        try:
            return session.fetch_selected_track()
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/manual-match")
    def assign_manual_match() -> dict[str, Any]:
        try:
            return session.assign_manual_match()
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/save/camera-config")
    def save_camera_config() -> dict[str, Any]:
        return {"path": session.save_camera_config()}

    @app.post("/api/save/manual-matches")
    def save_manual_matches() -> dict[str, Any]:
        return {"path": session.save_manual_matches()}

    @app.post("/api/export")
    def export_with_flight_info() -> dict[str, Any]:
        return {"path": session.export_with_flight_info()}

    return app
