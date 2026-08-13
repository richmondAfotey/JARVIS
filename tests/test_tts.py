"""Tests for the text-to-speech service (uses a fake engine - no hardware)."""

import threading
import time

import pytest

from voice.text_to_speech import TTSService


class FakeVoice:
    def __init__(self, name, id):
        self.name = name
        self.id = id


class FakeEngine:
    """Minimal stand-in for a pyttsx3 engine."""

    def __init__(self, voices=None):
        self.said = []
        self.rate = None
        self.voice = None
        self._voices = voices or [FakeVoice("Voice A", "a"), FakeVoice("Voice B", "b")]
        self.stopped = False

    def say(self, text):
        self.said.append(text)

    def runAndWait(self):
        pass

    def stop(self):
        self.stopped = True

    def getProperty(self, name):
        if name == "voices":
            return self._voices
        if name == "rate":
            return self.rate

    def setProperty(self, name, value):
        if name == "rate":
            self.rate = value
        elif name == "voice":
            self.voice = value


def make_service(engine=None, **kwargs):
    service = TTSService(**kwargs)

    def _create():
        if engine is None:
            raise RuntimeError("no engine available")
        return engine

    service._create_engine = _create
    return service


def test_speak_records_text():
    engine = FakeEngine()
    service = make_service(engine, enabled=True)
    assert service.speak("hello there") is True
    assert engine.said == ["hello there"]


def test_speak_when_disabled_does_nothing():
    engine = FakeEngine()
    service = make_service(engine, enabled=False)
    assert service.speak("hello") is False
    assert engine.said == []


def test_speak_empty_text_does_nothing():
    engine = FakeEngine()
    service = make_service(engine, enabled=True)
    assert service.speak("   ") is False
    assert engine.said == []


def test_speak_when_engine_unavailable_is_safe():
    service = make_service(None, enabled=True)  # engine creation raises
    assert service.available is False
    assert service.speak("anything") is False  # does not crash


class HangingEngine(FakeEngine):
    """An engine whose runAndWait() blocks until stop() unblocks it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._released = threading.Event()

    def runAndWait(self):
        self._released.wait(10)  # simulate a wedged engine

    def stop(self):
        self.stopped = True
        self._released.set()


def _work(service, text, out, slot):
    out[slot] = service.speak(text)


def test_followup_speak_survives_hung_first():
    """A wedged runAndWait from the first reply must not block the next."""
    engine = HangingEngine()
    service = make_service(engine, enabled=True)

    results = {}
    t1 = threading.Thread(target=_work, args=(service, "first", results, 1))
    t1.start()
    time.sleep(0.2)  # let the first speak take the lock and hang

    results[2] = service.speak("second")  # must not block forever
    assert results[2] is True
    assert "second" in engine.said
    t1.join(timeout=2)
    assert not t1.is_alive()


def test_speak_exception_recovers_next_call(monkeypatch):
    """An engine that blows up mid-speak is replaced on the next call."""

    class BlowsUp(FakeEngine):
        def runAndWait(self):
            raise RuntimeError("engine died")

    service = TTSService(enabled=True)
    created = []

    def _create():
        item = BlowsUp() if not created else FakeEngine()
        created.append(item)
        return item

    monkeypatch.setattr(service, "_create_engine", _create)
    assert service.speak("boom") is False
    assert service.speak("recover") is True
    assert created and created[1].said == ["recover"]


def test_list_voices():
    engine = FakeEngine()
    service = make_service(engine)
    assert service.list_voices() == ["Voice A", "Voice B"]


def test_set_voice_selects_by_name():
    engine = FakeEngine()
    service = make_service(engine)
    service.set_voice("Voice B")
    assert engine.voice == "b"


def test_set_voice_unknown_keeps_current():
    engine = FakeEngine()
    service = make_service(engine)
    service.set_voice("Voice A")
    service.set_voice("Nope")  # not found -> stays on Voice A
    assert engine.voice == "a"


def test_set_rate_clamps():
    service = TTSService()
    service.set_rate(10000)
    assert service.rate == 400
    service.set_rate(1)
    assert service.rate == 80


def test_set_enabled_stops_speech():
    engine = FakeEngine()
    service = make_service(engine, enabled=True)
    service.list_voices()  # ensure the engine is created
    service.set_enabled(False)
    assert service.enabled is False
    assert engine.stopped is True
