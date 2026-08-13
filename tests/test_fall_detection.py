"""Tests for Phase 31 fall-detection heuristics (camera/fall_detector.py).

The detector is pure logic (no OpenCV/MediaPipe) so it can be tested with
fake landmark sequences: a standing frame, then a simulated drop-and-lying
burst -> "triggered", plus a no-crash hold after the lie is gone.
"""

from camera.fall_detector import FallDetector


def _landmark(x, y, v=1.0):
    return (x, y, v)


def _pose(*points):
    """Build a 33-landmark frame; index 11/12 = shoulders, 23/24 = hips."""
    lm = [_landmark(0.5, 0.8)] * 33
    for idx, point in points:
        lm[idx] = point
    return lm


def _standing_frame(torso_y=0.5):
    """A plausible upright pose: shoulders up, hips at torso_y."""
    return _pose(
        (0, _landmark(0.5, 0.2)),          # nose
        (11, _landmark(0.45, 0.3)),        # left shoulder
        (12, _landmark(0.55, 0.3)),        # right shoulder
        (23, _landmark(0.47, torso_y)),    # left hip
        (24, _landmark(0.53, torso_y)),    # right hip
    )


def _lying_frame(torso_y=0.85):
    """Torso near the floor and horizontal (shoulders/hips same y, split x)."""
    return _pose(
        (0, _landmark(0.5, 0.2)),
        (11, _landmark(0.38, torso_y)),   # shoulders -> one side
        (12, _landmark(0.42, torso_y)),
        (23, _landmark(0.58, torso_y + 0.01)),  # hips -> other side
        (24, _landmark(0.62, torso_y + 0.01)),
    )


def test_starts_in_tracking_then_learns_standing():
    det = FallDetector()
    state = det.add_frame(_standing_frame())
    assert state.label == "tracking"
    # After enough upright frames a baseline forms and the frame is ok.
    for _ in range(20):
        det.add_frame(_standing_frame())
    state = det.add_frame(_standing_frame())
    assert state.label in ("standing", "triggered")


def test_fall_trigger_after_lying_burst():
    det = FallDetector(track_frames=4)
    # Learn a standing baseline.
    for _ in range(20):
        det.add_frame(_standing_frame(torso_y=0.5))
    assert det._baseline is not None

    # Drop + lie for more than track_frames -> triggered.
    for _ in range(6):
        state = det.add_frame(_lying_frame(torso_y=0.85))
    assert state.label == "triggered"
    assert state.confidence >= 0.9
    assert state.torso_drop > 0


def test_no_false_trigger_for_stray_frame():
    det = FallDetector(track_frames=4)
    for _ in range(20):
        det.add_frame(_standing_frame())
    # One briefly-lowered frame must not fire.
    det.add_frame(_lying_frame(torso_y=0.8))
    state = det.add_frame(_standing_frame())
    assert state.label == "standing"


def test_no_trigger_without_lying():
    det = FallDetector(track_frames=4)
    for _ in range(20):
        det.add_frame(_standing_frame(torso_y=0.5))
    # A drop without a horizontal torso stays standing.
    dropped = _standing_frame(torso_y=0.9)
    for _ in range(6):
        state = det.add_frame(dropped)
    assert state.label != "triggered"


def test_no_person_decays_lying_streak():
    det = FallDetector(track_frames=4)
    for _ in range(20):
        det.add_frame(_standing_frame())
    # Person leaves mid-lie; no alarm may fire from a gap.
    for _ in range(8):
        state = det.add_frame(_lying_frame())
    assert state.label == "triggered"
    det.reset()
    for _ in range(20):
        det.add_frame(_standing_frame())
    assert det.add_frame(None).label == "tracking"


def test_reset_clears_baseline():
    det = FallDetector()
    for _ in range(20):
        det.add_frame(_standing_frame())
    assert det._baseline is not None
    det.reset()
    assert det._baseline is None


def test_module_importable_without_third_party():
    # fall_detector.py (pure logic) must be importable without opencv/mediapipe.
    import inspect

    import camera.fall_detector as fd

    src = inspect.getsource(fd)
    assert "import cv2" not in src and "mediapipe" not in src