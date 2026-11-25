"""Round 4 fixes of the talk server, client and hooks (bulldozer bd1125)."""
import threading
import time

import pytest

import speech
from helpers import AUTH, CALL, run, running_app, talk


async def settle(call):
    import asyncio
    for _ in range(100):
        if all(e.get("speech") in (None, "ready", "failed") for e in call.entries):
            return
        await asyncio.sleep(0.02)


# -- r2-client-3: the call page never waits for the key command ---------------------------------

def test_the_call_page_returns_at_once_while_the_key_command_runs(tmp_path, monkeypatch):
    runs = []

    def slow_command():
        runs.append(1)
        time.sleep(1.5)
        return ""

    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            monkeypatch.setattr(speech, "_engine", None)  # a process that has not chosen its engine yet
            monkeypatch.delenv("TALK_SPEECH", raising=False)
            monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
            monkeypatch.setattr(speech, "_key", None)
            monkeypatch.setattr(speech, "_key_missed_at", float("-inf"))
            monkeypatch.setattr(speech, "command_key", slow_command)
            first = threading.Thread(target=speech.engine)
            first.start()
            time.sleep(0.2)  # the key command is running now
            second = threading.Thread(target=speech.engine)
            second.start()
            began = time.monotonic()
            page = await client.get(f"/c/{CALL}")
            took = time.monotonic() - began
            html = await page.text()
            first.join(5), second.join(5)
            return took, html

    took, html = run(go())
    assert took < 0.5
    assert '"engine": "choosing"' in html and '"voices": []' in html
    assert len(runs) == 1  # two callers, one key command


# -- r2-client-4, r2-server-4, r2-robust-2, r3-robust-2 -------------------------------------------

def test_reply_then_reply_end_still_ends_the_call(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("hi", typed=True)
            await call.turns.next(timeout=1)
            first = await (await client.post("/api/reply", json={"id": "t1", "text": "Here it is."}, headers=AUTH)).json()
            wrap = await (await client.post("/api/reply", json={"id": "t1", "text": "Bye for now.", "end": True},
                                            headers=AUTH)).json()
            await settle(call)
            return first, wrap, call.ended, [e["text"] for e in call.entries if e["who"] == "claude"]

    first, wrap, ended, said = run(go())
    assert first == {"ok": True, "board_problems": []}
    assert wrap["ok"] is True and "ignored" not in wrap
    assert ended == "wrapped up by Claude"
    assert said == ["Here it is.", "Bye for now."]


def test_a_reply_of_only_a_board_is_refused_and_the_turn_stays_open(tmp_path):
    table = "[[show table | Costs]]\n| a | b |\n|---|---|\n| x | 1 |\n| y | 2 |\n[[/show]]"

    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("hi", typed=True)
            await call.turns.next(timeout=1)
            bad = await client.post("/api/reply", json={"id": "t1", "text": table}, headers=AUTH)
            body = await bad.json()
            claude = [e for e in call.entries if e["who"] == "claude"]
            still_open = "t1" in call.turns.open_ids
            good = await (await client.post("/api/reply", json={"id": "t1", "text": "The costs are here. " + table},
                                            headers=AUTH)).json()
            await settle(call)
            return bad.status, body, claude, still_open, good, [e.get("answer") for e in call.entries if e["who"] == "board"]

    status, body, claude, still_open, good, answers = run(go())
    assert status == 400 and claude == [] and still_open is True
    assert "a board needs a sentence" in body["error"]
    assert any("a board needs a sentence" in p for p in body["board_problems"])
    assert good["ok"] is True
    assert answers[-1] == 1  # the answer number the refused reply never consumed


def test_a_surrogate_in_a_reply_is_cleaned_at_the_door(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("hi", typed=True)
            await call.turns.next(timeout=1)
            resp = await client.post("/api/reply", data='{"id": "t1", "text": "Bad \\ud800 text."}',
                                     headers={**AUTH, "Content-Type": "application/json"})
            await settle(call)
            return resp.status, [e["text"] for e in call.entries if e["who"] == "claude"], fake.spoken

    status, said, spoken = run(go())
    assert status == 200 and said == ["Bad � text."] and spoken == ["Bad � text."]


def test_a_surrogate_in_a_typed_line_is_cleaned_and_a_failed_record_adds_nothing(tmp_path, monkeypatch):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            resp = await client.post("/api/say", data='{"text": "hello \\ud800"}',
                                     headers={**AUTH, "Content-Type": "application/json"})
            entry = (await resp.json())["entry"]

            def boom(label, text):
                raise OSError("disk full")

            monkeypatch.setattr(call, "record", boom)
            before = len(call.entries)
            with pytest.raises(OSError):
                call.add("note", "x")
            return entry, before, len(call.entries)

    entry, before, after = run(go())
    assert entry["text"] == "hello �"
    assert after == before  # nothing half-added


def test_a_typed_line_must_be_a_string(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            out = []
            for body in ({"text": None}, {"text": 123}, {"text": ["a"]}, {}, {"text": "   "}):
                resp = await client.post("/api/say", json=body, headers=AUTH)
                out.append((resp.status, (await resp.json())["error"]))
            return out

    assert run(go()) == [(400, "text must be a string"), (400, "text must be a string"),
                         (400, "text must be a string"), (400, "nothing to send"), (400, "nothing to send")]


# -- r2-client-5 ---------------------------------------------------------------------------------

def test_the_answer_on_stdin_is_read_as_utf8_whatever_the_locale(monkeypatch):
    import io

    import talk_client

    raw = "Καλημέρα κόσμε".encode() + b" \xff"
    # a process under LC_ALL=POSIX: stdin is ASCII with surrogateescape
    monkeypatch.setattr(talk_client.sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="ascii",
                                                                    errors="surrogateescape"))
    assert talk_client.read_stdin() == "Καλημέρα κόσμε �"


# -- r2-server-6 ---------------------------------------------------------------------------------

def test_speech_is_tried_once_more_for_a_transient_error_and_not_for_others(monkeypatch):
    calls = []

    class Engine:
        outcome = "HTTP 503 busy"

        @staticmethod
        def speak(text, voice, wav=False):
            calls.append(text)
            if len(calls) == 1 or Engine.outcome.startswith("bad key"):
                raise speech.SpeechError(Engine.outcome)
            return "made"

    monkeypatch.setattr(speech, "engine", lambda: Engine)
    monkeypatch.setattr(speech, "RETRY_S", 0)
    assert speech.speak("hi", "v") == "made" and calls == ["hi", "hi"]
    for says in ("HTTP 429 slow down", "Azure text to speech failed: 500", "cannot reach VoiceStudio at x"):
        assert speech.transient(speech.SpeechError(says)) is True
    calls.clear()
    Engine.outcome = "bad key"
    with pytest.raises(speech.SpeechError, match="bad key"):
        speech.speak("hi", "v")
    assert calls == ["hi"]  # a final error is not tried again


def test_speak_again_reads_a_failed_answer_and_refuses_the_rest(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("hi", typed=True)
            await call.turns.next(timeout=1)
            fake.fail = "HTTP 400 no"
            await client.post("/api/reply", json={"id": "t1", "text": "Here it is."}, headers=AUTH)
            await settle(call)
            failed = (call.entries[-1]["speech"], call.entries[-1]["speech_error"])
            entry_id = call.entries[-1]["id"]
            fake.fail = None
            resp = await client.post("/api/speak", json={"entry": entry_id}, headers=AUTH)
            body = await resp.json()
            await settle(call)
            again = await client.post("/api/speak", json={"entry": entry_id}, headers=AUTH)
            odd = await client.post("/api/speak", json={"entry": 0}, headers=AUTH)
            nope = await client.post("/api/speak", json={"entry": "x"}, headers=AUTH)
            return (failed, body, call.entries[-1]["speech"], call.entries[-1]["audio"], again.status, odd.status,
                    nope.status, fake.spoken)

    failed, body, speech_now, audio, again, odd, nope, spoken = run(go())
    assert failed == ("failed", "HTTP 400 no")
    assert body == {"ok": True, "speech": "pending"} and speech_now == "ready" and audio == "audio/0001.wav"
    assert (again, odd, nope) == (409, 404, 404)
    assert spoken == ["Here it is."]
