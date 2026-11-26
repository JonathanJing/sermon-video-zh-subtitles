"""Synthetic Layer 1 inputs for the weekly-auto tests: no recording, no sermon text, no network."""
import json
from pathlib import Path
import wave

SENTENCES = [
    "Good evening, everyone, and welcome.",
    "We are continuing our series in chapter 21.",
    "The writer says the city had 12 gates.",
    "And I want you to notice who is at the center.",
    "It is not the walls.",
    "It means your ordinary work is not wasted.",
    "Let's pray.",
]


def make_raw(sentences=SENTENCES, start=1.0):
    """A whisper-1 verbose_json answer: one segment per sentence, 0.3 s words, 0.6 s between sentences."""
    words, segments, t = [], [], start
    for sentence in sentences:
        first = t
        for token in sentence.split():
            words.append({"word": token.strip(".,?!"), "start": round(t, 2), "end": round(t + 0.3, 2)})
            t += 0.4
        segments.append({"start": round(first, 2), "end": round(t - 0.1, 2), "text": " " + sentence})
        t += 0.5
    return {"duration": round(t + 1.0, 2), "text": " ".join(sentences), "segments": segments, "words": words}


def write_transcript(layer1: Path, sentences=SENTENCES, second_pass=None):
    """The files l1_transcribe.py leaves behind, with a second pass that differs in one sentence."""
    raw = make_raw(sentences)
    layer1.mkdir(parents=True, exist_ok=True)
    (layer1 / "raw-whisper.json").write_text(json.dumps(raw), encoding="utf-8")
    words = [{"text": w["word"], "start": w["start"], "end": w["end"]} for w in raw["words"]]
    (layer1 / "words.json").write_text(json.dumps(words), encoding="utf-8")
    text = second_pass or " ".join(sentences).replace("who is at the center", "who's at the center of it all")
    chunks = [{"chunk": 0, "start": 0.0, "end": raw["duration"], "whisperWords": len(words), "words": len(text.split()),
               "attempts": [{"attempt": 1, "words": len(text.split()), "seconds": 0.1}], "text": text}]
    (layer1 / "gpt-4o-chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
    (layer1 / "raw-gpt-4o-transcribe.txt").write_text(text + "\n", encoding="utf-8")
    (layer1 / "transcribe-usage.json").write_text(json.dumps({"models": {
        "whisper-1": {"audioSeconds": raw["duration"], "calls": 1}, "gpt-4o-transcribe": {"audioSeconds": raw["duration"], "calls": 1}}}))
    return raw


def write_wav(path: Path, seconds: float, rate: int = 16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(seconds * rate))
