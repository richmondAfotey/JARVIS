"""Tests for Phase 30: background services and conversational summaries."""

import threading
import time

import pytest

from ai.conversation import Conversation
from ai.summaries import ConversationSummarizer, _local_digest, summarize_turns


# -- Conversation summation -------------------------------------------------

def test_local_digest_builds_without_provider():
    turns = [{"role": "user", "content": "please remember my birthday"}, {"role": "assistant", "content": "done"}]
    digest = _local_digest(turns)
    assert "birthday" in digest


def test_summarize_turns_offline_fallback():
    from ai.providers.local_echo import LocalEchoProvider

    turns = [{"role": "user", "content": "remind me to buy milk"}]
    out = summarize_turns(LocalEchoProvider(), turns)
    assert out


def test_summarizer_noop_below_threshold():
    summ = ConversationSummarizer(threshold=10, keep_recent=4)
    history = [{"role": "user", "content": f"m{i}"} for i in range(5)]
    out = summ.apply(history)
    assert len(out) == 5
    assert not summ._pending


def test_summarizer_compresses_above_threshold():
    summ = ConversationSummarizer(threshold=6, keep_recent=4)
    history = [{"role": "user", "content": f"m{i}"} for i in range(10)]
    out = summ.apply(history)
    assert summ._pending
    assert out[0]["role"] == "system"
    assert "summary of earlier turns" in out[0]["content"]
    # Recent turns are kept verbatim.
    assert any(m["content"] == "m9" for m in out)


def test_summarizer_reattaches_when_below_threshold():
    summ = ConversationSummarizer(threshold=6, keep_recent=4)
    history = [{"role": "user", "content": f"m{i}"} for i in range(10)]
    summ.apply(history)
    # Now only a couple of new turns arrive; the earlier summary is kept.
    small = [{"role": "user", "content": "m10"}, {"role": "assistant", "content": "a10"}]
    out = summ.apply(small)
    assert any(m["role"] == "system" and "summary" in m["content"] for m in out)
    assert any(m["content"] == "m10" for m in out)


def test_conversation_integration_no_pileup():
    c = Conversation(system_prompt="SYS")
    summ = ConversationSummarizer(threshold=6, keep_recent=4)
    c._summarizer = summ.apply
    for i in range(40):
        c.add_user(f"m{i}")
        c.add_assistant(f"a{i}")
    prompts = [m for m in c.messages if m["content"] == "SYS"]
    summaries = [m for m in c.messages if m["role"] == "system" and "summary" in m["content"]]
    assert len(prompts) == 1
    assert len(summaries) == 1
    assert len(c.messages) < 20


# -- Folder watcher ---------------------------------------------------------

def test_folder_watcher_detects_changes(tmp_path):
    from system.folder_watcher import FolderWatcher

    folder = tmp_path / "watch"
    folder.mkdir()
    changes = []
    watcher = FolderWatcher(folder=str(folder), on_change=changes.append, poll_seconds=0.1)
    assert watcher.start() is True

    try:
        (folder / "new.txt").write_text("hello")
        time.sleep(0.4)
        assert any("new.txt" in str(p) for p in changes)
    finally:
        watcher.stop()


def test_folder_watcher_shows_no_folder():
    from system.folder_watcher import FolderWatcher

    watcher = FolderWatcher(folder=None)
    assert watcher.start() is False


# -- Focus recap ------------------------------------------------------------

def test_focus_recap_disabled_on_unknown_idle():
    from system.focus_recap import FocusRecapService

    service = FocusRecapService(idle_minutes=0, on_idle=lambda: None)
    assert service.start() is False


# -- Push-to-talk -----------------------------------------------------------

def test_ptt_trigger_fires():
    from voice.ptt import PushToTalk

    calls = []

    class FakeKeyboard:
        def add_hotkey(self, hotkey, cb, **kw):
            cb()

        def remove_hotkey(self, hotkey):
            pass

    import voice.ptt as ptt

    monkeypatch = None
    # Patch the module globals directly (keyboard lib is absent in CI).
    old_kb, old_avail = ptt._kb, ptt._hotkey_available
    ptt._kb = FakeKeyboard()
    ptt._hotkey_available = True
    try:
        ptt_service = PushToTalk(hotkey="ctrl+space", on_trigger=lambda: calls.append(1))
        assert ptt_service.start() is True
        assert calls == [1]
        ptt_service.stop()
    finally:
        ptt._kb, ptt._hotkey_available = old_kb, old_avail
    assert not ptt_service.armed


def test_ptt_unavailable_without_lib():
    from voice.ptt import PushToTalk, _kb, _hotkey_available

    import voice.ptt as ptt

    old_kb, old_avail = ptt._kb, ptt._hotkey_available
    ptt._kb = None
    ptt._hotkey_available = False
    try:
        ptt_service = PushToTalk(hotkey="ctrl+space")
        assert ptt_service.available is False
        assert ptt_service.start() is False
    finally:
        ptt._kb, ptt._hotkey_available = old_kb, old_avail
    assert not ptt_service.armed


# -- Mood-adapted TTS voice -------------------------------------------------

def test_tts_mood_rate_shifts():
    from voice.text_to_speech import TTSService

    service = TTSService(rate=180, mood_emphasis=True)
    assert service._mood_rate("happy") == 205
    assert service._mood_rate("sad") == 155
    assert service._mood_rate(None) == 180
    service_mood_off = TTSService(rate=180, mood_emphasis=False)
    assert service_mood_off._mood_rate("happy") == 180


def test_tts_speak_passes_emotion():
    from voice.text_to_speech import TTSService

    rates = []

    class FakeEngine:
        def setProperty(self, k, v):
            if k == "rate":
                rates.append(v)

        def getProperty(self, k):
            return []

        def say(self, t):
            pass

        def runAndWait(self):
            pass

    service = TTSService(enabled=True, rate=180, mood_emphasis=True)
    service._engine = FakeEngine()
    service.voice_name = ""
    assert service.speak("hello", emotion="happy") is True
    # The mood rate (205) is applied before speech, then reset back to 180.
    assert 205 in rates
    assert rates[-1] == 180