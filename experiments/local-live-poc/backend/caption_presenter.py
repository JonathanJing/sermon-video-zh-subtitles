from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable


CAPTION_PRESENTATION_POLICIES = {"legacy", "readable_chunks"}
READABLE_BOUNDARY_RE = re.compile(r"[，。！？；：…]$")


def chinese_character_count(value: str) -> int:
    return len(re.sub(r"\s", "", value or ""))


@dataclass
class SegmentPresentationState:
    first_partial_at: float | None = None
    last_visible_at: float | None = None
    last_visible_text: str = ""
    visible_update_count: int = 0


class CaptionPresenter:
    """Turns model events into stable, user-visible caption events.

    Raw ASR and translation events remain unchanged in the session log.  This
    class only emits an additional ``caption.display`` stream for viewers.
    """

    def __init__(
        self,
        policy: str = "readable_chunks",
        initial_wait_ms: int = 400,
        minimum_initial_chars: int = 6,
        minimum_update_interval_ms: int = 500,
        minimum_update_chars: int = 4,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if policy not in CAPTION_PRESENTATION_POLICIES:
            raise ValueError(f"unsupported caption presentation policy: {policy}")
        self.policy = policy
        self.initial_wait_ms = initial_wait_ms
        self.minimum_initial_chars = minimum_initial_chars
        self.minimum_update_interval_ms = minimum_update_interval_ms
        self.minimum_update_chars = minimum_update_chars
        self.clock = clock
        self.states: dict[str, SegmentPresentationState] = {}

    @property
    def raw_events_are_visible(self) -> bool:
        return self.policy == "legacy"

    def partial(self, event: dict[str, Any]) -> dict[str, Any] | None:
        if self.policy == "legacy":
            return None
        segment_id = str(event.get("segmentId") or "")
        target_text = str(event.get("targetTextZh") or "")
        if not segment_id or not target_text:
            return None
        now = self.clock()
        state = self.states.setdefault(segment_id, SegmentPresentationState())
        if state.first_partial_at is None:
            state.first_partial_at = now
        elapsed_ms = round((now - state.first_partial_at) * 1000)
        character_count = chinese_character_count(target_text)

        if state.last_visible_at is None:
            if elapsed_ms < self.initial_wait_ms or character_count < self.minimum_initial_chars:
                return None
            reason = "readable_initial_chunk"
        else:
            interval_ms = round((now - state.last_visible_at) * 1000)
            added_chars = max(0, character_count - chinese_character_count(state.last_visible_text))
            if interval_ms < self.minimum_update_interval_ms or added_chars < self.minimum_update_chars:
                return None
            reason = "readable_increment"

        return self._display_event(event, state, now, "partial", reason)

    def final(self, event: dict[str, Any]) -> dict[str, Any] | None:
        if self.policy == "legacy":
            return None
        segment_id = str(event.get("segmentId") or "")
        if not segment_id:
            return None
        now = self.clock()
        state = self.states.setdefault(segment_id, SegmentPresentationState())
        display = self._display_event(event, state, now, "final", "translation_final")
        self.states.pop(segment_id, None)
        return display

    def terminal(
        self,
        event: dict[str, Any],
        target_text: str,
        phase: str = "error",
    ) -> dict[str, Any] | None:
        """Display a stable fallback when translation cannot complete."""
        if self.policy == "legacy":
            return None
        segment_id = str(event.get("segmentId") or "")
        if not segment_id:
            return None
        now = self.clock()
        state = self.states.setdefault(segment_id, SegmentPresentationState())
        display = self._display_event(
            {**event, "targetTextZh": target_text},
            state,
            now,
            "final",
            "translation_terminal",
        )
        display["phase"] = phase
        self.states.pop(segment_id, None)
        return display

    def _display_event(
        self,
        event: dict[str, Any],
        state: SegmentPresentationState,
        now: float,
        display_kind: str,
        reason: str,
    ) -> dict[str, Any]:
        target_text = str(event.get("targetTextZh") or "")
        previous_text = state.last_visible_text
        interval_ms = (
            round((now - state.last_visible_at) * 1000)
            if state.last_visible_at is not None else None
        )
        state.last_visible_at = now
        state.last_visible_text = target_text
        state.visible_update_count += 1
        first_wait_ms = (
            round((now - state.first_partial_at) * 1000)
            if state.first_partial_at is not None else 0
        )
        return {
            **{key: value for key, value in event.items() if key.startswith("translationUnit") or key in {"sourceSegmentIds", "sourceFinals"}},
            "type": "caption.display",
            "segmentId": event.get("segmentId"),
            "audioStartMs": event.get("audioStartMs"),
            "audioEndMs": event.get("audioEndMs"),
            "sourceTextEn": event.get("sourceTextEn", ""),
            "targetTextZh": target_text,
            "displayKind": display_kind,
            "phase": "streaming" if display_kind == "partial" else "final",
            "presentationPolicy": self.policy,
            "presentationReason": reason,
            "presentationMetrics": {
                "visibleCharacterCount": chinese_character_count(target_text),
                "visibleCharactersAdded": max(
                    0,
                    chinese_character_count(target_text)
                    - chinese_character_count(previous_text),
                ),
                "visibleUpdateIntervalMs": interval_ms,
                "firstPartialToVisibleMs": first_wait_ms,
                "visibleUpdateCount": state.visible_update_count,
                "endsAtReadableBoundary": bool(READABLE_BOUNDARY_RE.search(target_text)),
            },
            "uxMetrics": event.get("uxMetrics", {}),
        }
