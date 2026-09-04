"""Bounded translation units assembled from immutable English ASR finals.

This is a conservative boundary heuristic, not an English parser or an ASR
correction step. One worker must own the assembler and call ``flush_due`` on
idle ticks, and ``flush`` on confirmed silence/stop. It never sleeps, calls a
model, changes an input event, or changes the translation prompt.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping


TRANSLATION_UNIT_POLICIES = ("legacy", "bounded_semantic_v1")
WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?", re.IGNORECASE)
# "her", "his", and "each" also stand alone ("I saw her", "This is his").
DETERMINERS = frozenset("a an the my your our their its every".split())
LINKERS = frozenset("and or but because if unless although whether".split())
PREPOSITIONS = frozenset("of to with from into onto about without".split())
AUXILIARIES = frozenset(
    "can could will would shall should must may might cannot "
    "can't couldn't won't wouldn't shouldn't mustn't don't doesn't didn't "
    "hasn't haven't hadn't isn't aren't wasn't weren't".split()
)
FREQUENCY_ADVERBS = frozenset("rarely seldom often always never usually sometimes".split())
COPULAS = frozenset("am is are was were be been being have has had".split())
RESTART_WORDS = frozenset(
    "i you he she it we they i'm you're he's she's it's we're they're "
    "because if unless although however but so".split()
)


def is_contentless_fragment(text: str) -> bool:
    """Identify a lone closed-class token unsuitable for isolated translation.

    This lexical admission guard is not speech/music classification. Callers
    must retain the immutable ASR final and log any skipped translation. Do not
    generalize this to all short replies: "Amen", "No", and "Why" carry meaning.
    """
    words = re.findall(r"\w+(?:'\w+)*", text.replace("’", "'").lower())
    return len(words) == 1 and words[0] in DETERMINERS | LINKERS | PREPOSITIONS


def incomplete_tail_reason(text: str) -> str | None:
    """Recognize narrow unfinished endings even when ASR added a full stop.

    Complete short responses and verb-final adverbs ("We meet rarely") are
    deliberately left alone. Conditional clauses are only held when short and
    no comma, semicolon, or explicit ``then`` supplies a clause boundary.
    False negatives are preferable to delaying every unpunctuated ASR final.
    """
    normalized = text.replace("’", "'")
    clauses = [part.strip() for part in re.split(r"[.!?]+", normalized) if part.strip()]
    tail = clauses[-1] if clauses else normalized
    words = [word.lower() for word in WORD_RE.findall(tail)]
    if len(words) < 2:
        return None
    last = words[-1]
    if last in DETERMINERS:
        return "trailing_determiner"
    if last in LINKERS:
        return "trailing_linker"
    if last in PREPOSITIONS and not (
        normalized.rstrip().endswith("?")
        and words[0] in {"what", "where", "who", "which", "how", "when"}
    ):
        return "trailing_preposition"
    # "I don't", "Who can?", and similar standalone responses can be complete.
    if len(words) >= 3 and (last in AUXILIARIES or last == "not"):
        return "trailing_auxiliary"
    if (
        last in FREQUENCY_ADVERBS
        and len(words) >= 3
        and words[-2] in COPULAS | AUXILIARIES
    ):
        return "auxiliary_frequency_adverb"
    if (
        words[0] in {"if", "unless", "although"}
        and 3 <= len(words) <= 9
        and not any(mark in tail for mark in (",", ";", ":"))
        and "then" not in words
        and not any(word in {"i", "you", "he", "she", "it", "we", "they"} for word in words[3:])
    ):
        return "short_dependent_clause"
    return None


@dataclass(frozen=True)
class SourceFinal:
    segment_id: str
    source_text_en: str
    audio_start_ms: int
    audio_end_ms: int
    final_at: float
    event_sequence: int | None = None
    event_at: str | None = None


@dataclass(frozen=True)
class TranslationUnit:
    source_finals: tuple[SourceFinal, ...]
    source_text_en: str
    policy: str
    first_accepted_at: float
    ready_at: float
    release_reason: str
    hold_reason: str | None
    unresolved_tail: bool

    @property
    def segment_id(self) -> str:
        # Existing presenters use the newest immutable ASR segment ID.
        return self.source_finals[-1].segment_id

    @property
    def source_segment_ids(self) -> tuple[str, ...]:
        return tuple(final.segment_id for final in self.source_finals)

    @property
    def audio_start_ms(self) -> int:
        return self.source_finals[0].audio_start_ms

    @property
    def audio_end_ms(self) -> int:
        return self.source_finals[-1].audio_end_ms

    @property
    def first_final_at(self) -> float:
        return self.source_finals[0].final_at

    @property
    def last_final_at(self) -> float:
        return self.source_finals[-1].final_at

    def event_metadata(self) -> dict[str, Any]:
        return {
            "translationUnitId": "unit-" + "--".join(self.source_segment_ids),
            "translationUnitPolicy": self.policy,
            "sourceSegmentIds": list(self.source_segment_ids),
            "sourceFinals": [
                {
                    "segmentId": final.segment_id,
                    "sourceTextEn": final.source_text_en,
                    "audioStartMs": final.audio_start_ms,
                    "audioEndMs": final.audio_end_ms,
                    "sequence": final.event_sequence,
                    "at": final.event_at,
                }
                for final in self.source_finals
            ],
            "translationUnitHoldMs": round((self.ready_at - self.first_accepted_at) * 1000),
            "translationUnitQueueWaitMs": round((self.first_accepted_at - self.first_final_at) * 1000),
            "translationUnitSourceFinalToReadyMs": round((self.ready_at - self.first_final_at) * 1000),
            "translationUnitHoldReason": self.hold_reason,
            "translationUnitReleaseReason": self.release_reason,
            "translationUnitUnresolvedTail": self.unresolved_tail,
            "translationUnitJoinPolicy": (
                "held_boundary_punctuation_only" if len(self.source_finals) > 1 else "unchanged"
            ),
        }


class TranslationUnitAssembler:
    def __init__(
        self,
        policy: str = "legacy",
        max_wait_ms: int = 3200,
        max_segments: int = 2,
        max_audio_duration_ms: int = 6500,
        max_audio_gap_ms: int = 800,
    ) -> None:
        if policy not in TRANSLATION_UNIT_POLICIES:
            raise ValueError(f"unsupported translation unit policy: {policy}")
        if max_wait_ms <= 0 or max_segments < 1 or max_audio_duration_ms <= 0 or max_audio_gap_ms < 0:
            raise ValueError("translation unit limits must be positive (audio gap may be zero)")
        self.policy = policy
        self.max_wait_ms = max_wait_ms
        self.max_segments = max_segments
        self.max_audio_duration_ms = max_audio_duration_ms
        self.max_audio_gap_ms = max_audio_gap_ms
        self._pending: list[SourceFinal] = []
        self._text = ""
        self._hold_reason: str | None = None
        self._first_accepted_at: float | None = None
        self._last_now: float | None = None
        self._last_audio_end_ms = -1

    @property
    def pending(self) -> bool:
        return bool(self._pending)

    @property
    def deadline_at(self) -> float | None:
        return self._pending[0].final_at + self.max_wait_ms / 1000 if self._pending else None

    def _check_time(self, now: float) -> None:
        if not math.isfinite(now) or (self._last_now is not None and now < self._last_now):
            raise ValueError("now must be a finite monotonic timestamp in seconds")
        self._last_now = now

    def add(
        self, final: Mapping[str, Any], now: float, *, final_at: float | None = None,
    ) -> list[TranslationUnit]:
        """Accept a final; preserve its original monotonic time across a queue.

        ``final_at`` defaults to ``now`` for immediate ASR-side integration.
        A translation worker should supply the original ASR final timestamp so
        queue delays never restart this unit's maximum waiting allowance.
        """
        if final.get("type") != "asr.final":
            raise ValueError("only immutable asr.final events may enter translation units")
        text = final.get("sourceTextEn")
        segment_id = final.get("segmentId")
        start, end = final.get("audioStartMs"), final.get("audioEndMs")
        if not isinstance(text, str) or not text.strip() or not isinstance(segment_id, str) or not segment_id:
            raise ValueError("ASR final requires a segment ID and nonempty source text")
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise ValueError("ASR final requires a positive ordered audio interval")
        if start < self._last_audio_end_ms:
            raise ValueError("ASR finals must have ordered nonoverlapping audio intervals")
        final_at = now if final_at is None else final_at
        if not math.isfinite(final_at) or final_at > now:
            raise ValueError("final_at must be finite and no later than now")
        self._check_time(now)
        self._last_audio_end_ms = end
        source = SourceFinal(segment_id, text, start, end, final_at, final.get("sequence"), final.get("at"))
        units = self.flush_due(now)
        if self._pending:
            gap = start - self._pending[-1].audio_end_ms
            duration = end - self._pending[0].audio_start_ms
            if gap > self.max_audio_gap_ms:
                units.extend(self.flush(now, "audio_gap"))
            elif duration > self.max_audio_duration_ms:
                units.extend(self.flush(now, "audio_duration_limit"))
            elif not self._can_continue(text):
                units.extend(self.flush(now, "incompatible_continuation"))
        if self._pending:
            self._text = self._text.rstrip().rstrip(".,;:!?…") + " " + text.strip()
            self._pending.append(source)
        else:
            self._pending = [source]
            self._text = text
            self._hold_reason = incomplete_tail_reason(text)
            self._first_accepted_at = now
        if self.policy == "legacy":
            return units + self.flush(now, "legacy_immediate")
        if self.deadline_at is not None and now >= self.deadline_at:
            return units + self.flush(now, "max_wait")
        reason = incomplete_tail_reason(self._text)
        if len(self._pending) >= self.max_segments:
            return units + self.flush(now, "segment_limit")
        if end - self._pending[0].audio_start_ms >= self.max_audio_duration_ms:
            return units + self.flush(now, "audio_duration_limit")
        if reason is None:
            return units + self.flush(now, "no_open_tail")
        return units

    def _can_continue(self, text: str) -> bool:
        reason = incomplete_tail_reason(self._text)
        if reason not in {"trailing_determiner", "trailing_auxiliary", "auxiliary_frequency_adverb"}:
            return True
        words = WORD_RE.findall(text.replace("’", "'").lower())
        # A fresh subject or causal clause cannot supply a missing noun/verb.
        # Preserve both finals instead of creating "your Because"/"doesn't It's".
        if not words or words[0] in RESTART_WORDS:
            return False
        if words[0].split("'")[0] in {"i", "you", "he", "she", "it", "we", "they"}:
            return False
        if len(words) > 1 and words[0] in {"this", "that", "these", "those"} and words[1] in COPULAS | AUXILIARIES:
            return False
        return True

    def flush_due(self, now: float) -> list[TranslationUnit]:
        self._check_time(now)
        if self.deadline_at is not None and now >= self.deadline_at:
            return self.flush(now, "max_wait")
        return []

    def flush(self, now: float, reason: str = "stop") -> list[TranslationUnit]:
        self._check_time(now)
        if not self._pending:
            return []
        assert self._first_accepted_at is not None
        unit = TranslationUnit(
            tuple(self._pending), self._text, self.policy, self._first_accepted_at, now, reason,
            self._hold_reason, incomplete_tail_reason(self._text) is not None,
        )
        self._pending = []
        self._text = ""
        self._hold_reason = None
        self._first_accepted_at = None
        return [unit]
