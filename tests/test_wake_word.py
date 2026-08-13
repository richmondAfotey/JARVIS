"""Tests for the wake-word listener (uses fakes - no microphone)."""

import numpy as np
import pytest

from voice.speech_to_text import STTError
from voice.wake_word import WakeWordListener


class FakeSTT:
    def __init__(self, results):
        self.results = list(results)  # popped in order
        self.calls = 0

    def recognize(self, audio):
        self.calls += 1
        if not self.results:
            raise STTError("no more results")
        return self.results.pop(0)


def loud_block() -> np.ndarray:
    return np.full((4000, 1), 0.3, dtype=np.float32)


def quiet_block() -> np.ndarray:
    return np.zeros((4000, 1), dtype=np.float32)


def make_clock():
    """Return (time_fn, advance_fn) for a controllable fake clock."""
    state = {"t": 1000.0}

    def _time():
        return state["t"]

    def _advance(seconds):
        state["t"] += seconds

    return _time, _advance


def make_listener(stt, monkeypatch=None, **kwargs):
    fired = []
    wake_phrase = kwargs.pop("wake_phrase", "hey jarvis")
    silence_after = kwargs.pop("silence_after", 0.8)
    listener = WakeWordListener(
        wake_phrase=wake_phrase,
        stt=stt,
        on_wake=lambda: fired.append("woke"),
        silence_after=silence_after,
        **kwargs,
    )
    if monkeypatch is not None:
        time_fn, _advance = make_clock()
        listener._advance = _advance
        monkeypatch.setattr("voice.wake_word.time.time", time_fn)
    return listener, fired


# -- matching ----------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hey Jarvis!", True),
        ("hey jarvis open the weather app", True),
        ("jarvis what time is it", True),
        ("JARVIS", True),
        ("hello there", False),
        ("", False),
        ("open chrome please", False),
    ],
)
def test_matches(text, expected):
    listener, _ = make_listener(FakeSTT([]))
    assert listener._matches(text) is expected


def test_matches_custom_phrase():
    listener, _ = make_listener(FakeSTT([]), wake_phrase="ok computer")
    assert listener._matches("ok computer open the door")
    assert listener._matches("hello there") is False


# -- utterance handling ------------------------------------------------------

def test_wake_fires_on_phrase(monkeypatch):
    stt = FakeSTT(["hey jarvis"])
    listener, fired = make_listener(stt, monkeypatch)
    listener._feed(loud_block())          # speech starts
    listener._feed(quiet_block())         # first silence -> timestamp set
    listener._advance(1.0)                # silence lasts long enough
    listener._feed(quiet_block())         # utterance ends -> wake
    assert fired == ["woke"]


def test_wake_ignores_non_matching_speech(monkeypatch):
    stt = FakeSTT(["good morning"])
    listener, fired = make_listener(stt, monkeypatch)
    listener._feed(loud_block())
    listener._feed(quiet_block())
    listener._advance(1.0)
    listener._feed(quiet_block())
    assert fired == []


def test_wake_cooldown_prevents_repeat(monkeypatch):
    stt = FakeSTT(["hey jarvis", "hey jarvis"])
    listener, fired = make_listener(stt, monkeypatch, cooldown=10.0)
    listener._feed(loud_block())
    listener._feed(quiet_block())
    listener._advance(1.0)
    listener._feed(quiet_block())  # first wake

    listener._feed(loud_block())
    listener._feed(quiet_block())
    listener._advance(1.0)
    listener._feed(quiet_block())  # within cooldown -> ignored
    assert len(fired) == 1


def test_wake_no_crash_when_stt_fails(monkeypatch):
    stt = FakeSTT([])  # raises STTError
    listener, fired = make_listener(stt, monkeypatch)
    listener._feed(loud_block())
    listener._feed(quiet_block())
    listener._advance(1.0)
    listener._feed(quiet_block())
    assert fired == []


def test_wake_pause_drops_audio():
    stt = FakeSTT(["hey jarvis"])
    listener, fired = make_listener(stt)
    listener.pause()
    listener._feed(loud_block())  # ignored while paused
    listener._feed(quiet_block())
    assert fired == []
    assert stt.calls == 0


def test_wake_resume_resets_state(monkeypatch):
    stt = FakeSTT(["hey jarvis"])
    listener, fired = make_listener(stt, monkeypatch)
    listener._feed(loud_block())  # start speaking
    listener.pause()              # pause mid-utterance (state reset)
    listener.resume()             # state reset again
    listener._feed(loud_block())  # fresh utterance
    listener._feed(quiet_block())
    listener._advance(1.0)
    listener._feed(quiet_block())
    assert fired == ["woke"]


def test_max_utterance_ends_long_speech(monkeypatch):
    stt = FakeSTT(["hey jarvis"])
    listener, fired = make_listener(
        stt, monkeypatch, max_utterance=0.5, silence_after=99.0
    )
    listener._feed(loud_block())  # speech starts
    listener._advance(1.0)        # > max_utterance
    listener._feed(loud_block())  # still speaking -> duration exceeded
    assert fired == ["woke"]


def test_loop_fires_with_synthetic_audio(monkeypatch):
    """End-to-end: the background loop feeds blocks and wakes the callback."""
    stt = FakeSTT(["hey jarvis"])
    listener, fired = make_listener(stt, monkeypatch, silence_after=0.0)

    # Override the audio source so no microphone is needed.
    blocks = [loud_block(), quiet_block()]

    def fake_blocks():
        yield from blocks

    listener._audio_blocks = fake_blocks
    listener._loop()
    assert fired == ["woke"]
