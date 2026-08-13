"""
Tone-of-voice emotion detection (Phase 29).

Infers the *mood of a spoken utterance* (happy / sad / angry / neutral)
from the **way it sounds** - prosody - not from what the words mean:

    * loudness and how much it varies   (energy / dynamics)
    * how fast the speech is            (envelope peaks per second)
    * how high or low the voice is      (fundamental frequency, F0)
    * how bright / harsh it sounds      (spectral brightness + zero crossings)

This is a lightweight, heuristic, fully local signal analyser: it only
needs ``numpy`` (already a dependency) and never phones home or needs an
API key. It is deliberately honest about its limits:

    * It is not a trained neural model, so on unclear input it says
      ``neutral`` instead of inventing a mood.
    * It can confuse similar-sounding emotions (e.g. two angry people).
    * It never guesses from silence or very short audio.
    * The emotion is only a *hint* the assistant may use; the assistant
      still treats the user's actual words as the source of truth.

The pipeline:

    1. Convert the PCM samples to a float array.
    2. Split it into short frames and measure, per frame: energy (RMS),
       pitch (autocorrelation F0), zero-crossing rate and spectral
       brightness.
    3. Collapse the frames into utterance-level features.
    4. Map arousal (calm -> excited) and valence (negative -> positive)
       onto one of the four emotions using documented thresholds.

Tests use deterministic synthetic tones (sine waves with AM / harmonics /
noise) so the behaviour is reproducible without a microphone.
"""

from __future__ import annotations

from dataclasses import dataclass

from utils.logger import get_logger

log = get_logger(__name__)

SAMPLE_RATE = 16000

EMOTIONS = ("happy", "sad", "angry", "neutral")

# Prosody analysis windows.
FRAME_SECONDS = 0.032
HOP_SECONDS = 0.016

# Pitch search range (Hz).
F0_MIN = 80
F0_MAX = 400

# Frames below this RMS are treated as silence for voicing/pitch.
VOICE_RMS = 0.004

# Arousal blend used only for the reported arousal axis (not the label).
# Roughness (harshness) comes from the zero-crossing rate.

# How far (in the normalized feature space) a decision must be from a
# boundary before we report it instead of "neutral".
CONFIDENCE_MIN = 0.30

np = None  # lazy import (Phase 20: keep module import cheap)


def _numpy() -> bool:
    """Ensure numpy is imported; return True when it is available."""
    global np
    if np is None:
        try:
            import numpy  # noqa: PLC0415
            np = numpy
        except Exception:  # noqa: BLE001
            return False
    return True


@dataclass(frozen=True)
class EmotionResult:
    """The tone-of-voice estimate for one utterance.

    Attributes:
        emotion: one of ``happy`` / ``sad`` / ``angry`` / ``neutral``.
        confidence: 0..1 - how far the features were from a boundary.
        arousal: -1..1 estimate of how energetic the speech was.
        valence: -1..1 estimate of how positive (vs negative) it sounded.
    """

    emotion: str = "neutral"
    confidence: float = 0.0
    arousal: float = 0.0
    valence: float = 0.0


# Static valence mapping used when the label is known.
_VALENCE = {"happy": 0.8, "angry": -0.55, "sad": -0.8, "neutral": 0.0}


def _clamp01(value: float) -> float:
    return 0.0 if value <= 0.0 else 1.0 if value >= 1.0 else value


def _scale(value: float, low: float, high: float) -> float:
    """Linearly map ``value`` into 0..1 between ``low`` and ``high``."""
    if high == low:
        return 0.0
    return _clamp01((value - low) / (high - low))


class EmotionDetector:
    """Estimate the emotional tone of recorded speech from its sound."""

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._frame = int(sample_rate * FRAME_SECONDS)
        self._hop = int(sample_rate * HOP_SECONDS)
        self._min_samples = self._frame

    # -- Public API ----------------------------------------------------------
    @property
    def libraries_available(self) -> bool:
        return _numpy()

    def detect_from_pcm(self, samples, sample_rate: int | None = None) -> EmotionResult:
        """Analyse raw 16-bit PCM bytes (or a float array) and return a mood.

        ``samples`` may be ``bytes``/``bytearray`` of int16 PCM, or any
        array-like of floats already scaled to roughly -1..1.
        """
        if not _numpy():
            return EmotionResult()
        rate = sample_rate or self.sample_rate
        x = self._to_float(samples)
        if x is None or x.size < self._min_samples:
            return EmotionResult()  # too short / unusable -> neutral
        features = self._analyze(x, rate)
        return self._classify(features)

    def detect_from_audiodata(self, audio) -> EmotionResult | None:
        """Analyse a ``speech_recognition.AudioData`` object (or None)."""
        if audio is None:
            return None
        try:
            frame_data = audio.get_wav_data(convert_rate=16000, convert_width=2)
        except Exception:  # noqa: BLE001
            return None
        if not frame_data:
            return None
        return self.detect_from_pcm(frame_data, sample_rate=16000)

    # -- Feature extraction --------------------------------------------------
    def _to_float(self, samples) -> np.ndarray | None:
        if isinstance(samples, (bytes, bytearray)):
            if len(samples) % 2 != 0:
                return None
            raw = np.frombuffer(samples, dtype=np.int16)
            if raw.size == 0:
                return None
            return raw.astype(np.float32) / 32768.0
        try:
            arr = np.asarray(samples)
        except Exception:  # noqa: BLE001
            return None
        if arr.ndim > 1:
            arr = arr[:, 0] if arr.shape[1] == 1 else arr.mean(axis=1)
        arr = arr.flatten()
        # Integer samples (e.g. int16 PCM) need normalizing to ~-1..1;
        # float samples are assumed to already be in that range.
        if np.issubdtype(arr.dtype, np.integer):
            arr = arr.astype(np.float32) / 32768.0
        else:
            arr = arr.astype(np.float32)
        return arr

    def _frames(self, x: np.ndarray) -> np.ndarray:
        """Return a (n_frames, frame_len) view of the signal."""
        n_frames = 1 + (len(x) - self._frame) // self._hop
        if n_frames < 1:
            n_frames = 1
        idx = self._hop * np.arange(n_frames)[:, None] + np.arange(self._frame)[None, :]
        return x[idx]

    def _frame_f0(self, frame: np.ndarray) -> float | None:
        """Fundamental frequency of one frame via autocorrelation (YIN-lite).

        Returns None when the frame is not periodic enough (silence or
        noise), so pitch statistics only come from voiced speech.
        """
        x = frame - frame.mean()
        r0 = float(np.dot(x, x))
        if r0 < 1e-9:
            return None
        n = len(x)
        ac = np.correlate(x, x, mode="full")[n - 1 : n - 1 + n // 2]
        lo = max(1, self.sample_rate // F0_MAX)
        hi = min(max(3, self.sample_rate // F0_MIN), ac.size - 1)
        if hi <= lo:
            return None
        seg = ac[lo:hi]
        peak = float(seg.max())
        if peak / r0 < 0.10:  # not periodic -> treat as unvoiced
            return None
        return self.sample_rate / (int(np.argmax(seg)) + lo)

    def _analyze(self, x: np.ndarray, rate: int) -> dict:
        frames = self._frames(x)
        n = frames.shape[0]

        rms = np.sqrt(np.mean(frames * frames, axis=1))
        voiced = rms > VOICE_RMS

        # Zero-crossing rate per frame.
        signs = np.sign(frames)
        zcr = np.mean(signs[:, 1:] != signs[:, :-1], axis=1)

        # Spectral brightness: fraction of energy above the cutoff.
        cutoff_bin = max(1, int(900.0 / rate * self._frame))
        win = np.hanning(self._frame)
        spec = np.abs(np.fft.rfft(frames * win, axis=1))
        total = spec.sum(axis=1) + 1e-9
        bright = spec[:, cutoff_bin:].sum(axis=1) / total

        # F0 over voiced frames.
        f0s = []
        for i in range(n):
            if voiced[i]:
                f0 = self._frame_f0(frames[i])
                if f0 is not None:
                    f0s.append(f0)

        # Per-frame dB energy.
        db = 20.0 * np.log10(rms + 1e-9)
        energy_db = float(db.mean()) if n else -60.0
        energy_var_db = float(db.std()) if n else 0.0

        # Speaking tempo proxy: how much the loudness fluctuates relative
        # to its average. Rhythmic, animated speech oscillates a lot;
        # monotone speech stays flat. (A robust alternative to counting
        # envelope peaks, which is noisy for steady tones.)
        mod_mean = float(np.mean(rms)) if n else 0.0
        modulation = float(np.std(rms)) / max(mod_mean, 1e-6)

        f0_mean = float(np.mean(f0s)) if f0s else None
        f0_cv = (
            float(np.std(f0s) / max(np.mean(f0s), 1e-9)) if len(f0s) > 1 else 0.0
        )

        # Energy-weighted aggregates for the brightness / roughness cues.
        weights = rms / (float(rms.sum()) + 1e-9)
        if float(weights.sum()) > 0.0:
            brightness = float(np.average(bright, weights=weights))
            zcr_mean = float(np.average(zcr, weights=weights))
        else:
            brightness = 0.0
            zcr_mean = 0.0

        return {
            "energy_db": energy_db,
            "energy_var_db": energy_var_db,
            "modulation": modulation,
            "f0_mean": f0_mean,
            "f0_cv": f0_cv,
            "brightness": brightness,
            "zcr": zcr_mean,
        }

    # -- Classification ------------------------------------------------------
    def _classify(self, f: dict) -> EmotionResult:
        f0 = f["f0_mean"]

        # Normalized prosody features (all 0..1).
        energy_level = _scale(f["energy_db"], -55.0, -12.0)
        energy_var = _scale(f["energy_var_db"], 0.0, 7.0)
        rate = _scale(f["modulation"], 0.02, 0.45)
        rough = _scale(f["zcr"], 0.04, 0.45)
        bright = _clamp01(f["brightness"] * 2.0)
        pitch_hi = _scale(f0, 120.0, 330.0) if f0 else 0.0
        pitch_lo = _scale(f0, 220.0, 90.0) if f0 else 0.0
        quiet = _scale(-f["energy_db"], 10.0, 25.0)

        # Every emotion needs real speech energy, not just silence.
        speech = energy_level

        # Happy: bright, high-pitched, animated speech.
        happy = speech * (
            0.30 * pitch_hi
            + 0.25 * energy_var
            + 0.20 * rate
            + 0.15 * energy_level
            + 0.10 * bright
        )

        # Angry: loud, harsh (rough), bright but not high-pitched.
        angry = speech * (
            0.40 * rough
            + 0.25 * energy_level
            + 0.15 * bright
            + 0.10 * (1.0 - pitch_hi)
            + 0.10 * energy_var
        )

        # Sad: quiet AND low-pitched (both are required - a calm voice
        # that is merely flat or quiet should stay neutral, not sad).
        sad_gate = 1.0 if (pitch_lo >= 0.5 and quiet >= 0.5) else 0.0
        sad = sad_gate * (
            0.35 * pitch_lo
            + 0.30 * quiet
            + 0.20 * (1.0 - energy_var)
            + 0.15 * (1.0 - rate)
        )

        scores = {"happy": happy, "angry": angry, "sad": sad}
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best, best_score = ordered[0]
        second = ordered[1][1]

        if best_score < 0.10:
            # Not confident there is speech at all.
            return EmotionResult("neutral", confidence=0.0, arousal=0.0)

        # Confidence = how clearly the best emotion beat the runner-up.
        confidence = _scale(best_score - second, 0.02, 0.22)
        if confidence < CONFIDENCE_MIN:
            return EmotionResult(
                "neutral", confidence=round(confidence, 3), arousal=0.0
            )

        arousal = (
            0.30 * energy_level
            + 0.20 * energy_var
            + 0.25 * rate
            + 0.15 * rough
            + 0.10 * pitch_hi
        )
        return EmotionResult(
            emotion=best,
            confidence=round(_clamp01(confidence), 3),
            arousal=round(_clamp01(arousal) * 2.0 - 1.0, 3),
            valence=_VALENCE[best],
        )
