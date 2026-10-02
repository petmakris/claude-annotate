import math
import struct

import ear

RATE = ear.SAMPLE_RATE


def tone(seconds: float, amplitude: int = 6000, hz: int = 220) -> bytes:
    n = int(seconds * RATE)
    return struct.pack(f"<{n}h", *(int(amplitude * math.sin(2 * math.pi * hz * i / RATE)) for i in range(n)))


def silence(seconds: float) -> bytes:
    return b"\0\0" * int(seconds * RATE)


# -- spot_name ---------------------------------------------------------------


def test_the_name_is_spotted_as_a_whole_word_in_any_case():
    assert ear.spot_name("Nova, what do you think?", ["Nova"])
    assert ear.spot_name("so what does NOVA say", ["Nova"])
    assert ear.spot_name("ask nova", ["Nova"])


def test_punctuation_around_the_name_does_not_hide_it():
    for text in ("(Nova) any idea?", "Nova? Anyone?", "okay... Nova.", "\"Nova\", please", "what's Nova's view"):
        assert ear.spot_name(text, ["Nova"]), text


def test_a_similar_name_or_a_longer_word_is_not_the_name():
    assert not ear.spot_name("Nora, what do you think?", ["Nova"])
    assert not ear.spot_name("Novak sent the numbers", ["Nova"])
    assert not ear.spot_name("the casanova pattern", ["Nova"])
    assert not ear.spot_name("", ["Nova"])


def test_sound_alikes_count_as_the_name():
    names = ["Nova", "Noa", "Nover"]
    assert ear.spot_name("noa, lower the retry limit", names)
    assert ear.spot_name("Nover what's next", names)
    assert not ear.spot_name("Noah is late", names)


def test_a_two_word_name_matches_across_any_spacing():
    assert ear.spot_name("hey  nova can you", ["Hey Nova"])
    assert not ear.spot_name("hey there nova", ["Hey Nova"])


# -- wakes -------------------------------------------------------------------


def seg(text, start=0.0, end=1.0, **extra):
    return {"text": text, "start": start, "end": end, **extra}


def test_speech_wakes_on_two_words_and_not_on_a_cough():
    assert not ear.wakes(seg("hm"), "speech", ["Nova"])
    assert not ear.wakes(seg(""), "speech", ["Nova"])
    assert ear.wakes(seg("okay so"), "speech", ["Nova"])


def test_name_wakes_only_on_the_name():
    assert not ear.wakes(seg("let us lower the retry limit"), "name", ["Nova"])
    assert ear.wakes(seg("Nova, lower it?"), "name", ["Nova"])


def test_before_the_model_is_ready_speech_wakes_on_energy_alone_and_a_name_never_does():
    long_burst = seg("", 0.0, 1.0, energy_only=True)
    short_burst = seg("", 0.0, 0.3, energy_only=True)
    assert ear.wakes(long_burst, "speech", ["Nova"])
    assert not ear.wakes(short_burst, "speech", ["Nova"])
    assert not ear.wakes(long_burst, "name", ["Nova"])


# -- Segmenter ---------------------------------------------------------------


def test_two_bursts_separated_by_silence_are_two_utterances():
    s = ear.Segmenter()
    out = s.feed(silence(0.5) + tone(1.0) + silence(1.0) + tone(0.5) + silence(1.0))
    assert len(out) == 2
    assert abs(out[0].start - 0.5) < 0.03
    assert abs(out[1].start - 2.5) < 0.03
    # Each utterance keeps the hangover it waited through.
    assert abs(out[0].end - (1.5 + ear.HANGOVER_S)) < 0.03


def test_a_short_pause_inside_speech_does_not_split_it():
    s = ear.Segmenter()
    out = s.feed(tone(1.0) + silence(0.4) + tone(1.0) + silence(1.0))
    assert len(out) == 1
    assert abs(out[0].end - out[0].start - (2.4 + ear.HANGOVER_S)) < 0.03


def test_a_monologue_is_cut_at_fifteen_seconds():
    s = ear.Segmenter()
    out = s.feed(tone(20.0))
    assert len(out) == 1
    assert abs(out[0].end - out[0].start - ear.MAX_UTTERANCE_S) < 0.03
    rest = s.flush()
    assert len(rest) == 1 and abs(rest[0].start - ear.MAX_UTTERANCE_S) < 0.03


def test_a_click_is_not_an_utterance():
    s = ear.Segmenter()
    assert s.feed(silence(0.5) + tone(0.06) + silence(1.0)) == []


def test_a_quiet_room_is_not_speech():
    s = ear.Segmenter()
    assert s.feed(tone(3.0, amplitude=200)) == [] and s.flush() == []


def test_frames_split_mid_sample_are_reassembled():
    s = ear.Segmenter()
    pcm = silence(0.2) + tone(1.0) + silence(1.0)
    out = []
    for i in range(0, len(pcm), 333):  # odd sizes: frames end half-way through a sample
        out += s.feed(pcm[i:i + 333])
    whole = ear.Segmenter().feed(pcm)
    assert [(u.start, u.end, u.pcm) for u in out] == [(u.start, u.end, u.pcm) for u in whole]
    assert len(out) == 1
