const state = {
  snapshot: null,
  viewer: null,
  cameraEntity: null,
  dragMode: null,
  dragStart: null,
  keyState: { shift: false, alt: false },
  pendingUpdate: null,
  updateTimer: null,
  hasBootstrappedView: false,
};

const els = {
  frameImage: document.querySelector("#frame-image"),
  overlayCanvas: document.querySelector("#overlay-canvas"),
  frameSlider: document.querySelector("#frame-slider"),
  prevFrame: document.querySelector("#prev-frame"),
  nextFrame: document.querySelector("#next-frame"),
  trackSelect: document.querySelector("#track-select"),
  assignMatch: document.querySelector("#assign-match"),
  fetchView: document.querySelector("#fetch-view"),
  fetchTrack: document.querySelector("#fetch-track"),
  saveCamera: document.querySelector("#save-camera"),
  saveMatches: document.querySelector("#save-matches"),
  exportJson: document.querySelector("#export-json"),
  referenceTime: document.querySelector("#reference-time"),
  timeOffset: document.querySelector("#time-offset"),
  overlayOpacity: document.querySelector("#overlay-opacity"),
  matchNotes: document.querySelector("#match-notes"),
  selectedTrackSummary: document.querySelector("#selected-track-summary"),
  cameraSummary: document.querySelector("#camera-summary"),
  authSummary: document.querySelector("#auth-summary"),
  statusLine: document.querySelector("#status-line"),
  trackTable: document.querySelector("#track-table"),
  candidateTable: document.querySelector("#candidate-table"),
  statesTable: document.querySelector("#states-table"),
  cacheTable: document.querySelector("#cache-table"),
};

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return Number(value).toFixed(digits);
}

async function api(method, url, payload) {
  const response = await fetch(url, {
    method,
    headers: payload ? { "Content-Type": "application/json" } : {},
    body: payload ? JSON.stringify(payload) : undefined,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || response.statusText);
  }
  return response.json();
}

function showStatus(message) {
  els.statusLine.textContent = message;
}

function setFrameImage(frameIndex) {
  const url = `/api/frame-image?frame_index=${frameIndex}&ts=${Date.now()}`;
  els.frameImage.src = url;
}

function drawOverlay() {
  const snapshot = state.snapshot;
  if (!snapshot) return;
  const image = els.frameImage;
  if (!image.naturalWidth || !image.naturalHeight) return;

  const canvas = els.overlayCanvas;
  const rect = image.getBoundingClientRect();
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  canvas.style.width = `${rect.width}px`;
  canvas.style.height = `${rect.height}px`;

  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.globalAlpha = Number(snapshot.ui_state.overlay_opacity || 0.7);

  for (const detection of snapshot.frame_payload.detections) {
    if (snapshot.ui_state.only_selected_track && detection.track_id !== snapshot.ui_state.selected_track_id) {
      continue;
    }
    const [x1, y1, x2, y2] = detection.bbox;
    ctx.strokeStyle = detection.track_id === snapshot.ui_state.selected_track_id ? "#ff6b6b" : "#00e676";
    ctx.lineWidth = 3;
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    ctx.fillStyle = "rgba(18, 33, 42, 0.72)";
    ctx.fillRect(x1, Math.max(0, y1 - 20), 80, 18);
    ctx.fillStyle = "white";
    ctx.font = "14px sans-serif";
    ctx.fillText(`track ${detection.track_id}`, x1 + 6, Math.max(14, y1 - 6));
  }

  const selectedCandidate = snapshot.selected_candidate;
  for (const candidate of snapshot.candidates) {
    ctx.beginPath();
    ctx.fillStyle =
      selectedCandidate && selectedCandidate.icao24 === candidate.icao24 ? "#ffd54f" : "#00bcd4";
    ctx.arc(candidate.screen_x, candidate.screen_y, Number(snapshot.ui_state.marker_size || 10), 0, Math.PI * 2);
    ctx.fill();
    if (snapshot.ui_state.show_labels) {
      const label = `${candidate.callsign || "-"} / ${candidate.icao24}`;
      ctx.font = "14px sans-serif";
      const labelWidth = ctx.measureText(label).width;
      ctx.fillStyle = "rgba(18, 33, 42, 0.72)";
      ctx.fillRect(candidate.screen_x + 10, candidate.screen_y - 22, labelWidth + 12, 18);
      ctx.fillStyle = "white";
      ctx.fillText(label, candidate.screen_x + 16, candidate.screen_y - 8);
    }
  }
}

function tableHtml(headers, rows, selectedKey) {
  const head = `<thead><tr>${headers.map((item) => `<th>${item}</th>`).join("")}</tr></thead>`;
  const bodyRows = rows
    .map(({ key, cells }) => {
      const klass = selectedKey !== undefined && key === selectedKey ? ' class="selected"' : "";
      return `<tr data-key="${key ?? ""}"${klass}>${cells.map((cell) => `<td>${cell ?? ""}</td>`).join("")}</tr>`;
    })
    .join("");
  return `${head}<tbody>${bodyRows}</tbody>`;
}

function renderTables(snapshot) {
  els.trackTable.innerHTML = tableHtml(
    ["frame", "time", "bbox", "conf"],
    snapshot.selected_track_frames.map((row) => ({
      key: row.frame_index,
      cells: [
        row.frame_index,
        formatNumber(row.time_seconds, 2),
        row.bbox.map((value) => formatNumber(value, 1)).join(", "),
        formatNumber(row.confidence, 3),
      ],
    })),
  );
  document.querySelectorAll("#track-table tbody tr").forEach((row) => {
    row.addEventListener("click", async () => {
      const frameIndex = Number(row.dataset.key);
      const nextIndex = state.snapshot.frame_indices.indexOf(frameIndex);
      if (nextIndex >= 0) {
        await pushState({ frame_index: nextIndex });
      }
    });
  });

  els.candidateTable.innerHTML = tableHtml(
    ["icao24", "callsign", "dist(px)", "alt", "time"],
    snapshot.candidates.map((row) => ({
      key: row.icao24,
      cells: [
        row.icao24,
        row.callsign || "-",
        formatNumber(row.distance_px, 1),
        formatNumber(row.geo_altitude, 0),
        row.time,
      ],
    })),
    snapshot.selected_candidate?.icao24,
  );

  els.statesTable.innerHTML = tableHtml(
    ["icao24", "callsign", "lat", "lon", "heading"],
    snapshot.current_states.map((row) => ({
      key: row.icao24,
      cells: [
        row.icao24,
        row.callsign || "-",
        formatNumber(row.lat, 5),
        formatNumber(row.lon, 5),
        formatNumber(row.heading, 0),
      ],
    })),
  );

  els.cacheTable.innerHTML = tableHtml(
    ["type", "begin", "end", "records", "bbox"],
    snapshot.cache_overview.map((row, index) => ({
      key: index,
      cells: [
        row.query_type,
        row.begin_unix,
        row.end_unix,
        row.record_count,
        Array.isArray(row.bbox) ? row.bbox.join(", ") : "-",
      ],
    })),
  );

  document.querySelectorAll("#candidate-table tbody tr").forEach((row) => {
    row.addEventListener("click", async () => {
      await pushState({ selected_candidate_icao: row.dataset.key });
    });
  });
}

function renderSummary(snapshot) {
  const camera = snapshot.camera_config;
  els.cameraSummary.innerHTML = `
    <div><strong>lat/lon:</strong> ${formatNumber(camera.lat, 6)}, ${formatNumber(camera.lon, 6)}</div>
    <div><strong>heading/tilt/roll:</strong> ${formatNumber(camera.azimuth_deg, 1)} / ${formatNumber(camera.tilt_deg, 1)} / ${formatNumber(camera.roll_deg, 1)}</div>
    <div><strong>fov:</strong> ${formatNumber(camera.hfov_deg, 1)} x ${formatNumber(camera.vfov_deg, 1)}</div>
    <div><strong>estimated UTC:</strong> ${snapshot.estimated_unix ? new Date(snapshot.estimated_unix * 1000).toISOString() : "unset"}</div>
    <div><strong>bbox:</strong> ${snapshot.current_bbox.map((value) => formatNumber(value, 4)).join(", ")}</div>
  `;
  els.authSummary.innerHTML = snapshot.auth.configured
    ? `<div><strong>OpenSky auth:</strong> ${snapshot.auth.mode}</div>`
    : `<div><strong>OpenSky auth:</strong> not configured</div>`;
  els.selectedTrackSummary.innerHTML = `
    <div><strong>track:</strong> ${snapshot.ui_state.selected_track_id ?? "-"}</div>
    <div><strong>detection:</strong> ${snapshot.selected_detection ? snapshot.selected_detection.bbox.map((v) => formatNumber(v, 1)).join(", ") : "-"}</div>
    <div><strong>manual match:</strong> ${snapshot.manual_match ? `${snapshot.manual_match.icao24} / ${snapshot.manual_match.callsign || "-"}` : "none"}</div>
    <div><strong>candidate sets:</strong> ${snapshot.candidate_index_count}</div>
  `;
}

function renderControls(snapshot) {
  els.frameSlider.max = String(Math.max(0, snapshot.frame_count - 1));
  els.frameSlider.value = String(snapshot.ui_state.frame_index);
  els.trackSelect.innerHTML = snapshot.tracks
    .map((trackId) => `<option value="${trackId}">track ${trackId}</option>`)
    .join("");
  els.trackSelect.value = String(snapshot.ui_state.selected_track_id ?? "");
  els.referenceTime.value = snapshot.camera_config.reference_time_utc || "";
  els.timeOffset.value = snapshot.camera_config.time_offset_sec;
  els.overlayOpacity.value = snapshot.ui_state.overlay_opacity;
  els.matchNotes.value = snapshot.ui_state.notes || "";
}

function updateCesium(snapshot) {
  const viewer = state.viewer;
  viewer.entities.removeAll();

  const camera = snapshot.camera_config;
  const cameraPosition = Cesium.Cartesian3.fromDegrees(camera.lon, camera.lat, camera.elevation_m);
  state.cameraEntity = viewer.entities.add({
    id: "camera-marker",
    position: cameraPosition,
    point: {
      pixelSize: 14,
      color: Cesium.Color.fromCssColorString("#ff6b6b"),
      outlineColor: Cesium.Color.WHITE,
      outlineWidth: 2,
    },
    label: {
      text: "Camera",
      font: "14px sans-serif",
      pixelOffset: new Cesium.Cartesian2(0, -24),
      fillColor: Cesium.Color.WHITE,
      showBackground: true,
      backgroundColor: Cesium.Color.fromCssColorString("rgba(18,33,42,0.72)"),
    },
  });

  const bbox = snapshot.current_bbox;
  viewer.entities.add({
    rectangle: {
      coordinates: Cesium.Rectangle.fromDegrees(bbox[1], bbox[0], bbox[3], bbox[2]),
      material: Cesium.Color.fromCssColorString("#0a87a8").withAlpha(0.1),
      outline: true,
      outlineColor: Cesium.Color.fromCssColorString("#0a87a8"),
    },
  });

  snapshot.current_states.forEach((row) => {
    viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(row.lon, row.lat, row.geo_altitude || row.baro_altitude || 0),
      point: {
        pixelSize: snapshot.selected_candidate && snapshot.selected_candidate.icao24 === row.icao24 ? 12 : 8,
        color:
          snapshot.selected_candidate && snapshot.selected_candidate.icao24 === row.icao24
            ? Cesium.Color.YELLOW
            : Cesium.Color.CYAN,
      },
      label: snapshot.ui_state.show_labels
        ? {
            text: `${row.callsign || "-"} / ${row.icao24}`,
            font: "12px sans-serif",
            pixelOffset: new Cesium.Cartesian2(0, -18),
            showBackground: true,
            backgroundColor: Cesium.Color.fromCssColorString("rgba(18,33,42,0.72)"),
          }
        : undefined,
    });
  });

  if (snapshot.selected_track_records.length > 1) {
    viewer.entities.add({
      polyline: {
        positions: snapshot.selected_track_records.map((row) =>
          Cesium.Cartesian3.fromDegrees(row.lon, row.lat, row.geo_altitude || row.baro_altitude || 0),
        ),
        width: 3,
        material: Cesium.Color.ORANGE,
      },
    });
  }
}

function renderSnapshot(snapshot) {
  state.snapshot = snapshot;
  setFrameImage(snapshot.frame_payload.frame_index);
  renderControls(snapshot);
  renderSummary(snapshot);
  renderTables(snapshot);
  updateCesium(snapshot);
  showStatus(`frame=${snapshot.frame_payload.frame_index} candidates=${snapshot.candidates.length}`);
}

async function pushState(payload) {
  const snapshot = await api("POST", "/api/state", payload);
  renderSnapshot(snapshot);
}

function scheduleDragUpdate(payload) {
  state.pendingUpdate = payload;
  if (state.updateTimer) return;
  state.updateTimer = setTimeout(async () => {
    const pending = state.pendingUpdate;
    state.pendingUpdate = null;
    state.updateTimer = null;
    try {
      await pushState(pending);
    } catch (error) {
      showStatus(error.message);
    }
  }, 80);
}

function installCesiumInteraction() {
  const viewer = state.viewer;
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Shift") state.keyState.shift = true;
    if (event.key === "Alt") state.keyState.alt = true;
  });
  document.addEventListener("keyup", (event) => {
    if (event.key === "Shift") state.keyState.shift = false;
    if (event.key === "Alt") state.keyState.alt = false;
  });

  handler.setInputAction((click) => {
    const picked = viewer.scene.pick(click.position);
    if (picked && picked.id === state.cameraEntity) {
      state.dragMode = "move-marker";
      viewer.scene.screenSpaceCameraController.enableRotate = false;
      return;
    }
    if (state.keyState.alt && state.keyState.shift) {
      state.dragMode = "roll-fov";
      state.dragStart = {
        position: click.position,
        camera: { ...state.snapshot.camera_config },
      };
      viewer.scene.screenSpaceCameraController.enableRotate = false;
      return;
    }
    if (state.keyState.alt) {
      state.dragMode = "orientation";
      state.dragStart = {
        position: click.position,
        camera: { ...state.snapshot.camera_config },
      };
      viewer.scene.screenSpaceCameraController.enableRotate = false;
    }
  }, Cesium.ScreenSpaceEventType.LEFT_DOWN);

  handler.setInputAction((movement) => {
    if (!state.dragMode) return;

    if (state.dragMode === "move-marker") {
      const cartesian = viewer.camera.pickEllipsoid(
        movement.endPosition,
        viewer.scene.globe.ellipsoid,
      );
      if (!cartesian) return;
      const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
      let lat = Cesium.Math.toDegrees(cartographic.latitude);
      let lon = Cesium.Math.toDegrees(cartographic.longitude);
      if (state.keyState.shift) {
        const current = state.snapshot.camera_config;
        lat = current.lat + (lat - current.lat) * 0.15;
        lon = current.lon + (lon - current.lon) * 0.15;
      }
      scheduleDragUpdate({ camera_config: { lat, lon } });
      return;
    }

    const dx = movement.endPosition.x - state.dragStart.position.x;
    const dy = movement.endPosition.y - state.dragStart.position.y;
    const camera = state.dragStart.camera;

    if (state.dragMode === "orientation") {
      scheduleDragUpdate({
        camera_config: {
          azimuth_deg: camera.azimuth_deg + dx * 0.2,
          tilt_deg: Math.max(-89, Math.min(89, camera.tilt_deg - dy * 0.1)),
        },
      });
      return;
    }

    const fovDelta = -dy * 0.05;
    scheduleDragUpdate({
      camera_config: {
        roll_deg: camera.roll_deg + dx * 0.2,
        hfov_deg: Math.max(5, Math.min(170, camera.hfov_deg + fovDelta)),
        vfov_deg: Math.max(5, Math.min(170, camera.vfov_deg + fovDelta)),
      },
    });
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

  handler.setInputAction(() => {
    state.dragMode = null;
    state.dragStart = null;
    viewer.scene.screenSpaceCameraController.enableRotate = true;
  }, Cesium.ScreenSpaceEventType.LEFT_UP);
}

function bindEvents() {
  els.prevFrame.addEventListener("click", () =>
    pushState({ frame_index: Math.max(0, state.snapshot.ui_state.frame_index - 1) }),
  );
  els.nextFrame.addEventListener("click", () =>
    pushState({
      frame_index: Math.min(state.snapshot.frame_count - 1, state.snapshot.ui_state.frame_index + 1),
    }),
  );
  els.frameSlider.addEventListener("input", () => pushState({ frame_index: Number(els.frameSlider.value) }));
  els.trackSelect.addEventListener("change", () => pushState({ selected_track_id: Number(els.trackSelect.value) }));
  els.referenceTime.addEventListener("change", () =>
    pushState({ camera_config: { reference_time_utc: els.referenceTime.value } }),
  );
  els.timeOffset.addEventListener("change", () =>
    pushState({ camera_config: { time_offset_sec: Number(els.timeOffset.value) } }),
  );
  els.overlayOpacity.addEventListener("input", () =>
    pushState({ ui_state: { overlay_opacity: Number(els.overlayOpacity.value) } }),
  );
  els.matchNotes.addEventListener("change", () =>
    pushState({ ui_state: { notes: els.matchNotes.value } }),
  );
  els.assignMatch.addEventListener("click", async () => {
    const snapshot = await api("POST", "/api/manual-match");
    renderSnapshot(snapshot);
  });
  els.fetchView.addEventListener("click", async () => {
    const snapshot = await api("POST", "/api/fetch/current-view");
    renderSnapshot(snapshot);
  });
  els.fetchTrack.addEventListener("click", async () => {
    const snapshot = await api("POST", "/api/fetch/track");
    renderSnapshot(snapshot);
  });
  els.saveCamera.addEventListener("click", async () => {
    const result = await api("POST", "/api/save/camera-config");
    showStatus(`saved ${result.path}`);
  });
  els.saveMatches.addEventListener("click", async () => {
    const result = await api("POST", "/api/save/manual-matches");
    showStatus(`saved ${result.path}`);
  });
  els.exportJson.addEventListener("click", async () => {
    const result = await api("POST", "/api/export");
    showStatus(`exported ${result.path}`);
  });
  els.frameImage.addEventListener("load", drawOverlay);
  window.addEventListener("resize", drawOverlay);
}

async function boot() {
  state.viewer = new Cesium.Viewer("cesium-container", {
    terrainProvider: new Cesium.EllipsoidTerrainProvider(),
    imageryProvider: new Cesium.OpenStreetMapImageryProvider({
      url: "https://tile.openstreetmap.org/",
    }),
    baseLayerPicker: false,
    timeline: false,
    animation: false,
    geocoder: false,
    homeButton: false,
    navigationHelpButton: false,
    sceneModePicker: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
  });
  state.viewer.scene.globe.enableLighting = true;
  state.viewer.scene.screenSpaceCameraController.inertiaSpin = 0;
  state.viewer.scene.screenSpaceCameraController.inertiaTranslate = 0;
  state.viewer.scene.screenSpaceCameraController.inertiaZoom = 0;
  state.viewer.scene.screenSpaceCameraController.maximumTiltAngle = Cesium.Math.PI_OVER_TWO;
  bindEvents();
  installCesiumInteraction();
  const snapshot = await api("GET", "/api/bootstrap");
  renderSnapshot(snapshot);
  if (!state.hasBootstrappedView) {
    const camera = snapshot.camera_config;
    state.viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(
        camera.lon,
        camera.lat,
        Math.max(1200, Number(camera.elevation_m || 0) + 1200),
      ),
      orientation: {
        heading: Cesium.Math.toRadians(Number(camera.azimuth_deg || 90)),
        pitch: Cesium.Math.toRadians(-45),
        roll: 0,
      },
      duration: 0,
    });
    state.hasBootstrappedView = true;
  }
}

boot().catch((error) => {
  showStatus(error.message);
  console.error(error);
});
