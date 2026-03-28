from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from python_tracker.calibration import (
    DEFAULT_TIME_WINDOW_SEC,
    LAT_BOUNDS,
    LON_BOUNDS,
    aggregate_tracks,
    build_candidate_index,
    build_with_flight_info_payload,
    candidate_aircraft_for_detection,
    clamp,
    compute_search_bbox,
    fetch_opensky_access_token,
    fetch_states_all,
    fetch_track,
    find_missing_intervals,
    frame_to_estimated_unix,
    load_camera_config,
    load_json,
    load_manual_matches,
    load_opensky_cache,
    load_opensky_client_credentials,
    manual_matches_by_track,
    merge_opensky_query,
    normalize_camera_config,
    normalize_reference_time_utc,
    parse_streamlit_cli_args,
    project_state_records,
    read_video_frame,
    state_records_for_frame,
    upsert_manual_match,
    write_json,
)


def default_output_paths(
    tracking_json_path: Path,
    camera_config_path: Path | None,
    manual_matches_path: Path | None,
) -> tuple[Path, Path, Path]:
    camera_path = camera_config_path or tracking_json_path.with_name("camera_config.json")
    matches_path = manual_matches_path or tracking_json_path.with_name("manual_matches.json")
    export_path = tracking_json_path.with_name(f"{tracking_json_path.stem}.with_flight_info.json")
    return camera_path, matches_path, export_path


def slider_step(base_step: float, precision_mode: str) -> float:
    multiplier = {
        "coarse": 10.0,
        "normal": 1.0,
        "fine": 0.2,
    }[precision_mode]
    return base_step * multiplier


def update_camera_config(camera_config: dict[str, Any]) -> None:
    st.session_state.camera_config = camera_config
    st.rerun()


def configure_auth_from_args(args: Any) -> None:
    st.session_state.auth_from_cli = False
    if getattr(args, "opensky_credentials_json", None):
        st.session_state.opensky_auth_mode = "credentials_json"
        st.session_state.opensky_credentials_path = str(args.opensky_credentials_json)
        st.session_state.auth_from_cli = True
    elif getattr(args, "opensky_client_id", None) and getattr(
        args, "opensky_client_secret", None
    ):
        st.session_state.opensky_auth_mode = "client_credentials"
        st.session_state.opensky_client_id = args.opensky_client_id
        st.session_state.opensky_client_secret = args.opensky_client_secret
        st.session_state.auth_from_cli = True
    elif getattr(args, "opensky_access_token", None):
        st.session_state.opensky_auth_mode = "access_token"
        st.session_state.api_token = args.opensky_access_token
        st.session_state.auth_from_cli = True


def resolve_opensky_access_token() -> str:
    auth_mode = st.session_state.opensky_auth_mode
    if auth_mode == "access_token":
        token = st.session_state.api_token.strip()
        if not token:
            raise RuntimeError("OpenSky access token を入力してください。")
        return token

    if auth_mode == "credentials_json":
        credentials_path = st.session_state.opensky_credentials_path.strip()
        if not credentials_path:
            raise RuntimeError("OpenSky credentials JSON path を入力してください。")
        client_id, client_secret = load_opensky_client_credentials(Path(credentials_path))
    else:
        client_id = st.session_state.opensky_client_id.strip()
        client_secret = st.session_state.opensky_client_secret.strip()
        if not client_id or not client_secret:
            raise RuntimeError("OpenSky clientId / clientSecret を入力してください。")

    token, _ = fetch_opensky_access_token(client_id, client_secret)
    return token


def session_defaults(
    *,
    tracking_payload: dict[str, Any],
    video_path: Path,
    camera_config_path: Path,
    manual_matches_path: Path,
    opensky_cache_path: Path,
) -> None:
    if "camera_config" not in st.session_state:
        st.session_state.camera_config = load_camera_config(camera_config_path, video_path)
    if "manual_matches_payload" not in st.session_state:
        st.session_state.manual_matches_payload = load_manual_matches(manual_matches_path)
    if "opensky_cache_payload" not in st.session_state:
        st.session_state.opensky_cache_payload = load_opensky_cache(opensky_cache_path)
    if "frame_index" not in st.session_state:
        st.session_state.frame_index = 0
    if "selected_track_id" not in st.session_state:
        tracks = aggregate_tracks(tracking_payload.get("frames", []))
        st.session_state.selected_track_id = next(iter(tracks), None)
    if "bbox_opacity" not in st.session_state:
        st.session_state.bbox_opacity = 0.6
    if "marker_size" not in st.session_state:
        st.session_state.marker_size = 12
    if "show_labels" not in st.session_state:
        st.session_state.show_labels = True
    if "only_selected_track" not in st.session_state:
        st.session_state.only_selected_track = False
    if "time_window_sec" not in st.session_state:
        st.session_state.time_window_sec = DEFAULT_TIME_WINDOW_SEC
    if "api_token" not in st.session_state:
        st.session_state.api_token = ""
    if "opensky_auth_mode" not in st.session_state:
        st.session_state.opensky_auth_mode = "credentials_json"
    if "opensky_credentials_path" not in st.session_state:
        st.session_state.opensky_credentials_path = ""
    if "opensky_client_id" not in st.session_state:
        st.session_state.opensky_client_id = ""
    if "opensky_client_secret" not in st.session_state:
        st.session_state.opensky_client_secret = ""
    if "manual_match_notes" not in st.session_state:
        st.session_state.manual_match_notes = ""
    if "drag_precision" not in st.session_state:
        st.session_state.drag_precision = "normal"
    if "auth_from_cli" not in st.session_state:
        st.session_state.auth_from_cli = False


def frame_payload_at(tracking_payload: dict[str, Any], frame_index: int) -> dict[str, Any]:
    frames = tracking_payload.get("frames", [])
    if not frames:
        return {
            "frame_index": 0,
            "time_seconds": 0.0,
            "time_ms": 0,
            "timecode": "00:00:00.000",
            "detections": [],
        }
    return frames[frame_index]


def candidate_label(candidate: dict[str, Any]) -> str:
    callsign = candidate.get("callsign") or "-"
    altitude = candidate.get("geo_altitude")
    altitude_label = "-" if altitude is None else f"{float(altitude):.0f}m"
    return f"{callsign} / {candidate['icao24']} / {altitude_label}"


def track_select_options(tracks: dict[int, dict[str, Any]]) -> list[int]:
    return list(tracks.keys())


def render_overlay_figure(
    rgb_frame: Any,
    frame_payload: dict[str, Any],
    *,
    selected_track_id: int | None,
    candidates: list[dict[str, Any]],
    bbox_opacity: float,
    marker_size: int,
    show_labels: bool,
    only_selected_track: bool,
) -> go.Figure:
    height, width = rgb_frame.shape[:2]
    fig = go.Figure()
    fig.add_trace(go.Image(z=rgb_frame))

    for detection in frame_payload.get("detections", []):
        if (
            only_selected_track
            and selected_track_id is not None
            and detection["track_id"] != selected_track_id
        ):
            continue
        color = (
            "rgba(255, 80, 80, 1.0)"
            if detection["track_id"] == selected_track_id
            else "rgba(0, 255, 0, 1.0)"
        )
        fill = color.replace("1.0", str(bbox_opacity))
        x1, y1, x2, y2 = detection["bbox"]
        fig.add_shape(
            type="rect",
            x0=x1,
            y0=y1,
            x1=x2,
            y1=y2,
            line={"color": color, "width": 2},
            fillcolor=fill,
        )
        center_x = (x1 + x2) / 2.0
        fig.add_annotation(
            x=center_x,
            y=max(0, y1 - 12),
            text=f"track {detection['track_id']}",
            showarrow=False,
            font={"size": 12, "color": "white"},
            bgcolor="rgba(0,0,0,0.6)",
        )

    visible_candidates = [candidate for candidate in candidates if candidate["visible"]]
    if visible_candidates:
        fig.add_trace(
            go.Scatter(
                x=[candidate["screen_x"] for candidate in visible_candidates],
                y=[candidate["screen_y"] for candidate in visible_candidates],
                mode="markers+text" if show_labels else "markers",
                marker={
                    "size": marker_size,
                    "color": [
                        "#ffcc00" if candidate.get("selected") else "#00bfff"
                        for candidate in visible_candidates
                    ],
                    "line": {"color": "#111111", "width": 1},
                },
                text=[candidate_label(candidate) for candidate in visible_candidates]
                if show_labels
                else None,
                textposition="top center",
                hovertemplate=(
                    "icao24=%{customdata[0]}<br>"
                    "callsign=%{customdata[1]}<br>"
                    "time=%{customdata[2]}<br>"
                    "alt=%{customdata[3]}<extra></extra>"
                ),
                customdata=[
                    [
                        candidate["icao24"],
                        candidate.get("callsign"),
                        candidate["time"],
                        candidate.get("geo_altitude"),
                    ]
                    for candidate in visible_candidates
                ],
            )
        )

    fig.update_layout(
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        width=width,
        height=height,
        xaxis={"visible": False, "range": [0, width]},
        yaxis={"visible": False, "range": [height, 0]},
    )
    return fig


def save_camera_config(camera_path: Path, video_path: Path) -> None:
    payload = normalize_camera_config(st.session_state.camera_config, video_path=video_path)
    write_json(camera_path, payload)
    st.session_state.camera_config = payload


def save_manual_matches(manual_matches_path: Path) -> None:
    write_json(manual_matches_path, st.session_state.manual_matches_payload)


def export_with_flight_info(
    *,
    export_path: Path,
    tracking_payload: dict[str, Any],
    opensky_cache_path: Path,
    video_path: Path,
) -> None:
    camera_config = normalize_camera_config(st.session_state.camera_config, video_path=video_path)
    payload = build_with_flight_info_payload(
        tracking_payload,
        camera_config=camera_config,
        manual_matches_payload=st.session_state.manual_matches_payload,
        opensky_cache_path=opensky_cache_path,
        cache_payload=st.session_state.opensky_cache_payload,
    )
    write_json(export_path, payload)


def main() -> None:
    args = parse_streamlit_cli_args(sys.argv[1:])
    camera_config_path, manual_matches_path, export_path = default_output_paths(
        args.tracking_json,
        args.camera_config,
        args.manual_matches,
    )

    st.set_page_config(layout="wide", page_title="OpenSky Calibration MVP")
    st.title("OpenSky Calibration MVP")

    tracking_payload = load_json(args.tracking_json)
    tracks = aggregate_tracks(tracking_payload.get("frames", []))
    session_defaults(
        tracking_payload=tracking_payload,
        video_path=args.video,
        camera_config_path=camera_config_path,
        manual_matches_path=manual_matches_path,
        opensky_cache_path=args.opensky_cache,
    )
    configure_auth_from_args(args)

    frame_count = len(tracking_payload.get("frames", []))
    if frame_count == 0:
        st.error("Tracking JSON にフレームがありません。")
        st.stop()

    st.session_state.frame_index = int(clamp(st.session_state.frame_index, 0, frame_count - 1))
    frame_payload = frame_payload_at(tracking_payload, st.session_state.frame_index)
    frame_detections = frame_payload.get("detections", [])
    frame_track_ids = [int(detection["track_id"]) for detection in frame_detections]
    if st.session_state.selected_track_id not in tracks:
        st.session_state.selected_track_id = next(iter(tracks), None)
    if (
        st.session_state.only_selected_track
        and st.session_state.selected_track_id not in frame_track_ids
    ):
        st.session_state.only_selected_track = False

    camera_config = normalize_camera_config(st.session_state.camera_config, video_path=args.video)
    st.session_state.camera_config = camera_config
    current_bbox = compute_search_bbox(camera_config["lat"], camera_config["lon"])
    estimated_unix = frame_to_estimated_unix(frame_payload, camera_config)
    current_states = state_records_for_frame(
        st.session_state.opensky_cache_payload,
        frame_unix=estimated_unix,
        bbox=current_bbox,
    )
    projected_states = project_state_records(
        current_states,
        camera_config=camera_config,
        frame_width=int(tracking_payload["metadata"]["width"]),
        frame_height=int(tracking_payload["metadata"]["height"]),
    )
    selected_detection = next(
        (d for d in frame_detections if d["track_id"] == st.session_state.selected_track_id),
        None,
    )
    candidates = candidate_aircraft_for_detection(selected_detection, projected_states)

    match_by_track = manual_matches_by_track(st.session_state.manual_matches_payload)
    selected_candidate_icao = st.session_state.get("selected_candidate_icao")
    if candidates and selected_candidate_icao not in {
        candidate["icao24"] for candidate in candidates
    }:
        st.session_state.selected_candidate_icao = candidates[0]["icao24"]
        selected_candidate_icao = candidates[0]["icao24"]
    for candidate in candidates:
        candidate["selected"] = candidate["icao24"] == selected_candidate_icao

    rgb_frame = read_video_frame(args.video, int(frame_payload["frame_index"]))

    left_col, middle_col, right_col = st.columns([1.7, 1.0, 1.1])

    with left_col:
        st.subheader("Frame Overlay")
        prev_col, next_col = st.columns(2)
        with prev_col:
            if st.button("Prev"):
                st.session_state.frame_index = max(0, st.session_state.frame_index - 1)
                st.rerun()
        with next_col:
            if st.button("Next"):
                st.session_state.frame_index = min(
                    frame_count - 1, st.session_state.frame_index + 1
                )
                st.rerun()
        frame_slider = st.slider(
            "Frame",
            min_value=0,
            max_value=frame_count - 1,
            value=st.session_state.frame_index,
        )
        if frame_slider != st.session_state.frame_index:
            st.session_state.frame_index = frame_slider
            st.rerun()
        time_values = [float(frame["time_seconds"]) for frame in tracking_payload["frames"]]
        selected_time = st.select_slider(
            "Time (sec)",
            options=time_values,
            value=float(frame_payload["time_seconds"]),
        )
        if selected_time != float(frame_payload["time_seconds"]):
            nearest_index = min(
                range(frame_count),
                key=lambda idx: abs(
                    float(tracking_payload["frames"][idx]["time_seconds"]) - selected_time
                ),
            )
            st.session_state.frame_index = nearest_index
            st.rerun()
        st.plotly_chart(
            render_overlay_figure(
                rgb_frame,
                frame_payload,
                selected_track_id=st.session_state.selected_track_id,
                candidates=candidates,
                bbox_opacity=float(st.session_state.bbox_opacity),
                marker_size=int(st.session_state.marker_size),
                show_labels=bool(st.session_state.show_labels),
                only_selected_track=bool(st.session_state.only_selected_track),
            ),
            use_container_width=True,
        )

    with middle_col:
        st.subheader("Track / Aircraft")
        selected_track_id = st.selectbox(
            "Track ID",
            options=track_select_options(tracks),
            index=track_select_options(tracks).index(st.session_state.selected_track_id)
            if st.session_state.selected_track_id in tracks
            else 0,
        )
        if selected_track_id != st.session_state.selected_track_id:
            st.session_state.selected_track_id = selected_track_id
            st.rerun()

        selected_track = tracks[selected_track_id]
        st.caption(
            f"frames={selected_track['count']} first={selected_track['first_frame_index']} "
            f"last={selected_track['last_frame_index']}"
        )
        st.dataframe(selected_track["frames"], use_container_width=True, height=240)

        candidate_df = [
            {
                "icao24": candidate["icao24"],
                "callsign": candidate.get("callsign"),
                "time": candidate["time"],
                "distance_px": candidate.get("distance_px"),
                "screen_x": candidate["screen_x"],
                "screen_y": candidate["screen_y"],
                "geo_altitude": candidate.get("geo_altitude"),
            }
            for candidate in candidates
        ]
        st.dataframe(candidate_df, use_container_width=True, height=220)
        if current_states:
            with st.expander("Current OpenSky states"):
                st.dataframe(current_states, use_container_width=True, height=240)
        selected_candidate = None
        if candidates:
            selected_label = st.selectbox(
                "Selected aircraft",
                options=[candidate_label(candidate) for candidate in candidates],
                index=[candidate["icao24"] for candidate in candidates].index(
                    selected_candidate_icao
                ),
            )
            selected_candidate = candidates[
                [candidate_label(candidate) for candidate in candidates].index(selected_label)
            ]
            st.session_state.selected_candidate_icao = selected_candidate["icao24"]
            st.session_state.manual_match_notes = st.text_input(
                "Match notes",
                value=st.session_state.manual_match_notes,
            )
            if st.button("Assign selected aircraft to track"):
                st.session_state.manual_matches_payload = upsert_manual_match(
                    st.session_state.manual_matches_payload,
                    track_id=selected_track_id,
                    icao24=selected_candidate["icao24"],
                    callsign=selected_candidate.get("callsign"),
                    notes=st.session_state.manual_match_notes,
                )
                st.success(
                    f"track {selected_track_id} -> {selected_candidate['icao24']} を更新しました。"
                )
        else:
            st.info("現在フレームに候補 aircraft はありません。")
        if selected_candidate is not None:
            with st.expander("Selected aircraft details"):
                st.json(selected_candidate)

        if (
            candidates
            and estimated_unix is not None
            and st.button("Fetch track for selected aircraft")
        ):
            try:
                token = resolve_opensky_access_token()
                selected_candidate = next(
                    candidate
                    for candidate in candidates
                    if candidate["icao24"] == st.session_state.selected_candidate_icao
                )
                query = fetch_track(
                    token=token,
                    icao24=selected_candidate["icao24"],
                    time_unix=estimated_unix,
                )
                merge_opensky_query(st.session_state.opensky_cache_payload, query)
                write_json(args.opensky_cache, st.session_state.opensky_cache_payload)
                st.success("tracks query をキャッシュに追記しました。")
            except RuntimeError as exc:
                st.warning(str(exc))

    with right_col:
        st.subheader("Controls")
        st.text_input("Video", value=str(args.video), disabled=True)
        st.text_input("Tracking JSON", value=str(args.tracking_json), disabled=True)
        st.text_input("OpenSky Cache", value=str(args.opensky_cache), disabled=True)
        if st.session_state.auth_from_cli:
            st.caption(f"OpenSky auth: CLI ({st.session_state.opensky_auth_mode})")
            if st.session_state.opensky_auth_mode == "credentials_json":
                st.text_input(
                    "OpenSky credentials JSON path",
                    value=st.session_state.opensky_credentials_path,
                    disabled=True,
                )
            elif st.session_state.opensky_auth_mode == "client_credentials":
                st.text_input(
                    "OpenSky clientId",
                    value=st.session_state.opensky_client_id,
                    disabled=True,
                )
                st.text_input(
                    "OpenSky clientSecret",
                    value="********",
                    disabled=True,
                )
            else:
                st.text_input(
                    "OpenSky access token",
                    value="********",
                    disabled=True,
                )
        else:
            st.session_state.opensky_auth_mode = st.segmented_control(
                "OpenSky auth",
                options=["credentials_json", "client_credentials", "access_token"],
                default=st.session_state.opensky_auth_mode,
            )
            if st.session_state.opensky_auth_mode == "credentials_json":
                st.session_state.opensky_credentials_path = st.text_input(
                    "OpenSky credentials JSON path",
                    value=st.session_state.opensky_credentials_path,
                    placeholder="/Users/.../credentials.json",
                )
            elif st.session_state.opensky_auth_mode == "client_credentials":
                st.session_state.opensky_client_id = st.text_input(
                    "OpenSky clientId",
                    value=st.session_state.opensky_client_id,
                )
                st.session_state.opensky_client_secret = st.text_input(
                    "OpenSky clientSecret",
                    type="password",
                    value=st.session_state.opensky_client_secret,
                )
            else:
                st.session_state.api_token = st.text_input(
                    "OpenSky access token",
                    type="password",
                    value=st.session_state.api_token,
                )
        reference_time = st.text_input(
            "Reference UTC (frame 0)",
            value=camera_config.get("reference_time_utc") or "",
            placeholder="2026-03-28T12:34:56Z",
        )
        if reference_time != (camera_config.get("reference_time_utc") or ""):
            camera_config["reference_time_utc"] = (
                normalize_reference_time_utc(reference_time) if reference_time else None
            )
            st.session_state.camera_config = camera_config
            st.rerun()

        estimated_utc_text = "unavailable"
        if estimated_unix is not None:
            estimated_utc_text = (
                datetime.fromtimestamp(estimated_unix, tz=UTC).isoformat().replace("+00:00", "Z")
            )
        st.caption(f"Estimated UTC: {estimated_utc_text}")
        st.caption(f"time_offset_sec={camera_config['time_offset_sec']:.2f}")
        st.caption(f"Current frame tracks: {frame_track_ids or '[]'}")
        st.caption(f"Candidates in frame: {len(candidates)}")
        st.caption("Default heading: east (azimuth_deg=90)")
        st.session_state.drag_precision = st.segmented_control(
            "Drag precision",
            options=["coarse", "normal", "fine"],
            default=st.session_state.drag_precision,
        )

        lat_col, lon_col = st.columns(2)
        with lat_col:
            lat_value = st.number_input(
                "lat",
                min_value=float(LAT_BOUNDS[0]),
                max_value=float(LAT_BOUNDS[1]),
                value=float(camera_config["lat"]),
                step=0.0001,
                format="%.8f",
            )
            if lat_value != camera_config["lat"]:
                camera_config["lat"] = lat_value
                update_camera_config(camera_config)
            lat_minus, lat_plus = st.columns(2)
            with lat_minus:
                if st.button("lat -"):
                    camera_config["lat"] = clamp(camera_config["lat"] - 0.0001, *LAT_BOUNDS)
                    update_camera_config(camera_config)
            with lat_plus:
                if st.button("lat +"):
                    camera_config["lat"] = clamp(camera_config["lat"] + 0.0001, *LAT_BOUNDS)
                    update_camera_config(camera_config)
        with lon_col:
            lon_value = st.number_input(
                "lon",
                min_value=float(LON_BOUNDS[0]),
                max_value=float(LON_BOUNDS[1]),
                value=float(camera_config["lon"]),
                step=0.0001,
                format="%.8f",
            )
            if lon_value != camera_config["lon"]:
                camera_config["lon"] = lon_value
                update_camera_config(camera_config)
            lon_minus, lon_plus = st.columns(2)
            with lon_minus:
                if st.button("lon -"):
                    camera_config["lon"] = clamp(camera_config["lon"] - 0.0001, *LON_BOUNDS)
                    update_camera_config(camera_config)
            with lon_plus:
                if st.button("lon +"):
                    camera_config["lon"] = clamp(camera_config["lon"] + 0.0001, *LON_BOUNDS)
                    update_camera_config(camera_config)

        st.caption("Mouse drag sliders")
        lat_slider = st.slider(
            "lat drag",
            min_value=float(LAT_BOUNDS[0]),
            max_value=float(LAT_BOUNDS[1]),
            value=float(camera_config["lat"]),
            step=slider_step(0.0001, st.session_state.drag_precision),
            format="%.8f",
        )
        if lat_slider != camera_config["lat"]:
            camera_config["lat"] = lat_slider
            update_camera_config(camera_config)

        lon_slider = st.slider(
            "lon drag",
            min_value=float(LON_BOUNDS[0]),
            max_value=float(LON_BOUNDS[1]),
            value=float(camera_config["lon"]),
            step=slider_step(0.0001, st.session_state.drag_precision),
            format="%.8f",
        )
        if lon_slider != camera_config["lon"]:
            camera_config["lon"] = lon_slider
            update_camera_config(camera_config)

        for key, min_value, max_value, step in (
            ("elevation_m", -100.0, 1000.0, 1.0),
            ("azimuth_deg", -180.0, 180.0, 0.5),
            ("tilt_deg", -89.0, 89.0, 0.5),
            ("roll_deg", -180.0, 180.0, 0.5),
            ("hfov_deg", 5.0, 170.0, 0.5),
            ("vfov_deg", 5.0, 170.0, 0.5),
            ("time_offset_sec", -3600.0, 3600.0, 0.5),
        ):
            value = st.number_input(
                key,
                min_value=min_value,
                max_value=max_value,
                value=float(camera_config[key]),
                step=step,
            )
            if value != camera_config[key]:
                camera_config[key] = value
                update_camera_config(camera_config)
            drag_value = st.slider(
                f"{key} drag",
                min_value=float(min_value),
                max_value=float(max_value),
                value=float(camera_config[key]),
                step=slider_step(step, st.session_state.drag_precision),
            )
            if drag_value != camera_config[key]:
                camera_config[key] = drag_value
                update_camera_config(camera_config)

        st.session_state.bbox_opacity = st.slider(
            "bbox opacity",
            min_value=0.0,
            max_value=1.0,
            value=float(st.session_state.bbox_opacity),
        )
        st.session_state.marker_size = st.slider(
            "OpenSky marker size",
            min_value=4,
            max_value=30,
            value=int(st.session_state.marker_size),
        )
        st.session_state.show_labels = st.toggle(
            "labels on",
            value=bool(st.session_state.show_labels),
        )
        st.session_state.only_selected_track = st.toggle(
            "only selected track",
            value=bool(st.session_state.only_selected_track),
        )
        st.session_state.time_window_sec = st.number_input(
            "time_window_sec",
            min_value=30,
            max_value=3600,
            value=int(st.session_state.time_window_sec),
            step=30,
        )

        if st.button("Fetch OpenSky for current view"):
            if estimated_unix is None:
                st.warning("Reference UTC を設定してから取得してください。")
            else:
                begin_unix = int(estimated_unix - st.session_state.time_window_sec)
                end_unix = int(estimated_unix + st.session_state.time_window_sec)
                try:
                    token = resolve_opensky_access_token()
                    missing_intervals = find_missing_intervals(
                        st.session_state.opensky_cache_payload,
                        query_type="states_all",
                        begin_unix=begin_unix,
                        end_unix=end_unix,
                        bbox=current_bbox,
                    )
                    if not missing_intervals:
                        st.info("現在 view の OpenSky states/all は既にキャッシュ済みです。")
                    for missing_begin, missing_end in missing_intervals:
                        query = fetch_states_all(
                            token=token,
                            begin_unix=missing_begin,
                            end_unix=missing_end,
                            bbox=current_bbox,
                        )
                        merge_opensky_query(st.session_state.opensky_cache_payload, query)
                    write_json(args.opensky_cache, st.session_state.opensky_cache_payload)
                    if missing_intervals:
                        st.success("OpenSky cache を更新しました。")
                    st.rerun()
                except RuntimeError as exc:
                    st.warning(str(exc))

        if st.button("Save camera_config"):
            save_camera_config(camera_config_path, args.video)
            st.success(str(camera_config_path))

        if st.button("Save manual_matches"):
            save_manual_matches(manual_matches_path)
            st.success(str(manual_matches_path))

        if st.button("Export with_flight_info"):
            export_with_flight_info(
                export_path=export_path,
                tracking_payload=tracking_payload,
                opensky_cache_path=args.opensky_cache,
                video_path=args.video,
            )
            st.success(str(export_path))

        match = match_by_track.get(int(st.session_state.selected_track_id))
        if match:
            st.caption(
                "Manual match: "
                f"track {match['track_id']} -> {match['icao24']} / "
                f"{match.get('callsign') or '-'}"
            )

        candidate_index = build_candidate_index(
            tracking_payload,
            camera_config,
            st.session_state.opensky_cache_payload,
        )
        st.caption(f"Resolved candidate sets: {len(candidate_index)} tracks")
        with st.expander("OpenSky cache overview"):
            st.dataframe(
                [
                    {
                        "query_type": query["query_type"],
                        "begin_unix": query["begin_unix"],
                        "end_unix": query["end_unix"],
                        "bbox": query.get("bbox"),
                        "record_count": len(query.get("records", [])),
                        "fetched_at": query.get("fetched_at"),
                    }
                    for query in st.session_state.opensky_cache_payload.get("queries", [])
                ],
                use_container_width=True,
                height=240,
            )


if __name__ == "__main__":
    main()
