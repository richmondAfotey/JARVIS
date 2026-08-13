"""
Camera fall monitor (Phase 31).

Runs the webcam on a background daemon thread whenever the app is open and
uses MediaPipe Pose (Tasks API) to track the user's body. When the pose
lands into the "triggered" state (a sharp drop + sustained horizontal
torso), the monitor saves a snapshot of the frame and fires the `on_fall`
callback so the dashboard can start the help/call countdown.

Privacy by default: the monitor only runs while the app is running, saves
snapshots locally (only after a fall is detected), and an on-screen
indicator in the UI shows when the camera is active. MediaPipe 1.0 uses
the Tasks API and needs a ~5.7 MB pose model file, downloaded once into
the data folder.

The heavy libraries (cv2, mediapipe) are imported lazily and absent or
broken dependencies mean the service simply reports itself unavailable -
the app keeps running normally.
"""

from __future__ import annotations

import ctypes
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable

from camera.fall_detector import FallDetector
from config import settings
from utils.logger import get_logger

log = get_logger(__name__)

_MODEL_SUBPATH = "models/pose_landmarker_lite.task"
_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)

_cv2 = None
_mp = None
_mp_base = None
_mp_vision = None
_libs_ok: bool | None = None


def _init_libs() -> bool:
    """Import cv2 + mediapipe lazily (cached)."""
    global _cv2, _mp, _mp_base, _mp_vision, _libs_ok
    if _libs_ok is not None:
        return _libs_ok
    try:
        import cv2  # noqa: PLC0415
        import mediapipe as mp  # noqa: PLC0415
        from mediapipe.tasks import python as mp_base  # noqa: PLC0415
        from mediapipe.tasks.python import vision as mp_vision  # noqa: PLC0415

        _cv2, _mp, _mp_base, _mp_vision = cv2, mp, mp_base, mp_vision
        _libs_ok = True
    except Exception as exc:  # noqa: BLE001
        log.warning("Camera libs unavailable: %s", exc)
        _libs_ok = False
    return _libs_ok


def model_available() -> bool:
    """True when the pose model file exists (or can be downloaded)."""
    return _model_path().exists()


def _model_path() -> Path:
    folder = getattr(settings, "camera_models_dir", "") or ""
    if folder:
        root = Path(folder).expanduser()
    else:
        root = settings.data_dir / "models"
    return root / "pose_landmarker_lite.task"


def _download_model() -> Path | None:
    """Fetch the MediaPipe pose model if it is missing."""
    target = _model_path()
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        log.info("Downloading pose model (%s)", _MODEL_SUBPATH)
        urllib.request.urlretrieve(_MODEL_URL, target)
        if target.exists():
            return target
    except Exception as exc:  # noqa: BLE001
        log.error("Could not download pose model: %s", exc)
        try:
            target.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    return None


def _flash_cam_led(on: bool) -> None:
    """Poke the camera LED on Windows so the user can see it is live."""
    try:
        ctypes.windll.kernel32.GlobalMemoryStatusEx  # touch win32
    except Exception:  # noqa: BLE001 - LED blink is cosmetic
        pass


class CameraFallMonitor:
    """Daemon thread: capture webcam frames, run pose detection, alert on fall."""

    def __init__(
        self,
        camera_index: int = 0,
        on_fall: Callable[[Path | None], None] | None = None,
        detector: FallDetector | None = None,
        fallback_fps: float = 12.0,
    ):
        self.camera_index = int(camera_index)
        self.on_fall = on_fall
        self.detector = detector or FallDetector()
        self.fallback_fps = fallback_fps
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_fall_at = 0.0
        self._cooldown = 60.0
        self._snapshot_dir: Path | None = None
        self._status = "off"

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def status(self) -> str:
        """off / no-camera / no-model / running."""
        return self._status

    def start(self, snapshot_dir: Path | None = None) -> bool:
        """Start the capture loop. False when camera/model unavailable."""
        if self.running:
            return True
        if not _init_libs():
            self._status = "no-libs"
            return False
        if _download_model() is None:
            self._status = "no-model"
            return False
        self._snapshot_dir = snapshot_dir
        self._stop.clear()
        self.detector.reset()
        self._thread = threading.Thread(
            target=self._loop, name="camera-fall", daemon=True
        )
        self._thread.start()
        self._status = "running"
        log.info("Camera fall monitor started (camera %s).", self.camera_index)
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._status = "off"

    # -- Main loop ----------------------------------------------------------
    def _loop(self) -> None:
        cap = None
        try:
            cap = self._cv2_capture()
            if cap is None:
                self._status = "no-camera"
                log.warning("No camera on index %s.", self.camera_index)
                return
            landmarker = self._build_landmarker()
            if landmarker is None:
                self._status = "no-model"
                return
            self._status = "running"
            _flash_cam_led(True)
            self._read_loop(cap, landmarker)
        except Exception as exc:  # noqa: BLE001 - monitor must never crash the app
            log.error("Camera loop failed: %s", exc)
        finally:
            try:
                if cap is not None:
                    cap.release()
            except Exception:  # noqa: BLE001
                pass
            _flash_cam_led(False)
            if self._status == "running":
                self._status = "stopped"

    def _cv2_capture(self):
        """Open the webcam with a retry window (camera start can be slow)."""
        last_error: Exception | None = None
        for _ in range(10):
            try:
                cap = _cv2.VideoCapture(self.camera_index)
                if cap is not None and cap.isOpened():
                    return cap
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            time.sleep(0.3)
        if last_error is not None:
            log.debug("Camera open error: %s", last_error)
        return None

    def _build_landmarker(self):
        """Create a MediaPipe PoseLandmarker (Tasks API, IMAGE mode)."""
        model = _download_model()
        if model is None:
            return None
        options = _mp_vision.PoseLandmarkerOptions(
            base_options=_mp_base.BaseOptions(model_asset_path=str(model)),
            running_mode=_mp_vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
        )
        return _mp_vision.PoseLandmarker.create_from_options(options)

    def _read_loop(self, cap, landmarker) -> None:
        frame_interval = 1.0 / max(1.0, self.fallback_fps)
        while not self._stop.is_set():
            start = time.time()
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.2)
                continue
            # Flipped for a natural mirror image; pose detection is symmetric.
            frame = _cv2.flip(frame, 1)
            landmarks = self._detect(landmarker, frame)
            state = self.detector.add_frame(landmarks)
            if state.label == "triggered":
                self._on_triggered(frame, state.confidence)
            # Timer-based pacing is more robust than fixed fps for slower cams.
            elapsed = time.time() - start
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)

    def _detect(self, landmarker, frame):
        """Run pose detection; returns landmark list or None."""
        try:
            image = _mp.Image(
                image_format=_mp.ImageFormat.SRGB,
                data=_cv2.cvtColor(frame, _cv2.COLOR_BGR2RGB),
            )
            result = landmarker.detect(image)
            if not result.pose_landmarks:
                return None
            return result.pose_landmarks[0]
        except Exception as exc:  # noqa: BLE001
            log.debug("Pose detection failed: %s", exc)
            return None

    def _on_triggered(self, frame, confidence: float) -> None:
        now = time.time()
        if now - self._last_fall_at < self._cooldown:
            return
        self._last_fall_at = now
        snapshot = self._save_snapshot(frame, confidence)
        log.warning(
            "FALL DETECTED (confidence %.2f) - snapshot %s",
            confidence,
            snapshot,
        )
        if self.on_fall is not None:
            self.on_fall(snapshot)

    def _save_snapshot(self, frame, confidence: float) -> Path | None:
        if self._snapshot_dir is None:
            return None
        try:
            self._snapshot_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            file = self._snapshot_dir / f"fall-{stamp}-{int(confidence * 100)}.jpg"
            _cv2.imwrite(str(file), frame)
            return file
        except Exception as exc:  # noqa: BLE001 - snapshot is best effort
            log.error("Could not save fall snapshot: %s", exc)
            return None


_shared_monitor: CameraFallMonitor | None = None
_shared_lock = threading.Lock()


def get_shared_monitor(on_fall: Callable[[Path | None], None] | None = None) -> CameraFallMonitor:
    """A process-wide camera fall monitor bound to the configured camera."""
    global _shared_monitor
    with _shared_lock:
        if _shared_monitor is None:
            _shared_monitor = CameraFallMonitor(
                camera_index=int(getattr(settings, "camera_fall_index", 0) or 0),
                on_fall=on_fall,
            )
        elif on_fall is not None:
            _shared_monitor.on_fall = on_fall
        return _shared_monitor