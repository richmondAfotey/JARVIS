"""
Fall detection logic (Phase 31) - pure heuristic, no OpenCV/MediaPipe.

This module decides, from a sequence of body-pose landmarks, whether the
user has fallen. It is kept free of any third-party import so it can be
unit-tested anywhere; the camera capture and landmarker live in
`camera/monitor.py`.

How a "fall" is recognised (MediaPipe Pose gives 33 normalized landmarks,
each an (x, y, visibility) tuple with y increasing downward):
    * We track the torso centre (mid-shoulders to mid-hips).
    * First we learn a *standing* baseline height over a short window.
    * A fall is flagged when, in a burst of consecutive frames, the torso
      centre drops far below the standing baseline AND the torso becomes
      nearly horizontal (the person is lying), then stays down. A rapid
      downward drop plus a sustained lying pose is the classic signature.

Output: `FallDetector.add_frame(landmarks)` returns the state after each
frame ("standing", "tracking", "lying", "triggered") plus a confidence.
The "triggered" state is held for a few frames only; the caller is
expected to start the help countdown from it.
"""

from __future__ import annotations

from dataclasses import dataclass

# MediaPipe Pose landmark indices (33 total).
_NOSE = 0
_LEFT_SHOULDER = 11
_RIGHT_SHOULDER = 12
_LEFT_HIP = 23
_RIGHT_HIP = 24

#: Normalised distance thresholds (frame is 0..1 on both axes).
_DROP_FRACTION = 0.14        # torso centre must fall this much of the frame height
_STANDING_ANGLE = 25.0       # deg from vertical below which we accept "standing"
_LYING_ANGLE = 55.0          # deg from vertical above which we accept "lying"
_TRACK_FRAMES = 12           # frames needed to learn a standing baseline
_TRIGGER_HOLD_FRAMES = 8     # how many frames a trigger stays active


@dataclass
class FallFrameState:
    label: str  # standing / tracking / lying / triggered
    confidence: float  # 0..1
    torso_drop: float = 0.0  # normalised drop below the standing baseline


def _visible(landmark) -> bool:
    """MediaPipe lists visibility in index 2; tolerate sparse formats."""
    try:
        return bool(landmark[2] >= 0.3)
    except (IndexError, TypeError):
        return bool(landmark[2]) if len(landmark) > 2 else True


def _centre(landmarks, points: list[int]) -> tuple[float, float] | None:
    pts = [landmarks[i] for i in points]
    pts = [p for p in pts if _visible(p)]
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _torso_vector(landmarks) -> tuple[float, float] | None:
    """Vector from mid-shoulder to mid-hip, in normalised coords."""
    shoulders = _centre(landmarks, [_LEFT_SHOULDER, _RIGHT_SHOULDER])
    hips = _centre(landmarks, [_LEFT_HIP, _RIGHT_HIP])
    if shoulders is None or hips is None:
        return None
    return hips[0] - shoulders[0], hips[1] - shoulders[1]


def _angle_from_vertical(landmarks) -> float | None:
    """Angle (degrees) of the torso from the vertical (downwards = 0)."""
    vector = _torso_vector(landmarks)
    if vector is None:
        return None
    dx, dy = vector
    import math

    length = math.hypot(dx, dy)
    if length < 1e-6:
        return None
    # Vertical axis points downward (0,+1). Dot product gives cos(angle).
    cos_angle = max(-1.0, min(1.0, dy / length))
    return math.degrees(math.acos(cos_angle))


class FallDetector:
    """Streaming fall detector over pose-landmark sequences."""

    def __init__(
        self,
        track_frames: int = _TRACK_FRAMES,
        drop_fraction: float = _DROP_FRACTION,
        lying_angle: float = _LYING_ANGLE,
        standing_angle: float = _STANDING_ANGLE,
    ) -> None:
        self.track_frames = track_frames
        self.drop_fraction = drop_fraction
        self.lying_angle = lying_angle
        self.standing_angle = standing_angle
        self._baseline: float | None = None  # standing torso-centre y
        self._warmup_count = 0
        self._warmup_total = 0.0
        self._warmup_samples = 0
        self._lying_frames = 0
        self._trigger_hold = 0

    def reset(self) -> None:
        self._baseline = None
        self._warmup_count = 0
        self._warmup_total = 0.0
        self._warmup_samples = 0
        self._lying_frames = 0
        self._trigger_hold = 0

    def add_frame(self, landmarks) -> FallFrameState:
        """Feed one pose frame's landmarks (list of 33 (x, y, vis) tuples).

        Pass None when no person is detected.
        """
        if not landmarks:
            return self._no_person()
        torso = _centre(landmarks, [_LEFT_HIP, _RIGHT_HIP])
        if torso is None:
            return self._no_person()
        torso_y = torso[1]
        angle = _angle_from_vertical(landmarks)

        # Warm up: collect upright torso readings until we have a baseline.
        if self._baseline is None:
            self._warmup_count += 1
            upright = angle is not None and abs(angle) <= self.standing_angle
            if upright and torso_y < 0.9:
                self._warmup_total += torso_y
                self._warmup_samples += 1
            if self._warmup_count >= self.track_frames and self._warmup_samples > 0:
                self._baseline = self._warmup_total / self._warmup_samples
            return FallFrameState("tracking", 0.25, 0.0)

        # Live: drop below the standing baseline + horizontal torso = fall.
        drop = max(0.0, torso_y - self._baseline)
        lying = angle is not None and abs(angle) >= self.lying_angle and drop >= self.drop_fraction

        if lying:
            self._lying_frames += 1
        else:
            # Let a few stray frames decay instead of instant-cancelling.
            self._lying_frames = max(0, self._lying_frames - 1)

        if self._lying_frames >= self.track_frames:
            self._trigger_hold = _TRIGGER_HOLD_FRAMES
            return FallFrameState("triggered", 0.92, drop)
        if self._lying_frames > 0:
            return FallFrameState("lying", 0.55, drop)
        return FallFrameState("standing", 0.35, drop)

    def _no_person(self) -> FallFrameState:
        # Person out of frame: decay the lying streak so a gap does not
        # fire a false alarm.
        self._lying_frames = 0
        if self._trigger_hold > 0:
            self._trigger_hold -= 1
        return FallFrameState("tracking", 0.0, 0.0)