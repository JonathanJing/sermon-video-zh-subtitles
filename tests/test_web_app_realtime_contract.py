import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class WebAppRealtimeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_js = (REPO_ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_realtime_caption_handler_accepts_public_sse_zh_only_payloads(self):
        app_js = self.app_js

        self.assertIn("function realtimeEventText(event)", app_js)
        self.assertIn("event.zh", app_js)
        self.assertIn("pushRealtimeEvent: handleRealtimeCaptionEvent", app_js)

    def test_ipad_mic_webrtc_creates_openai_translation_session(self):
        app_js = self.app_js

        self.assertIn("navigator.mediaDevices.getUserMedia", app_js)
        self.assertIn("new RTCPeerConnection()", app_js)
        self.assertIn('pc.createDataChannel("oai-events")', app_js)
        self.assertIn('model: "gpt-realtime-translate"', app_js)
        self.assertIn('targetLanguage: "zh"', app_js)
        self.assertIn('audioSourceKind: "ipad_mic"', app_js)
        self.assertIn('source: "ipad-mic"', app_js)
        self.assertIn('fetch("/api/admin/realtime/sessions"', app_js)
        self.assertIn('"Authorization": `Bearer ${session.clientSecret.value}`', app_js)

    def test_openai_realtime_events_are_normalized_and_persisted_to_backend(self):
        app_js = self.app_js

        self.assertIn("function handleRealtimeDataChannelMessage(raw)", app_js)
        self.assertIn("realtimeCaptionEventFromOpenAI(event)", app_js)
        self.assertIn("normalizeRealtimeOpenAIEvent: realtimeCaptionEventFromOpenAI", app_js)
        self.assertIn("extractRealtimeTranscriptText(event)", app_js)
        self.assertIn('type.includes("input_transcript")', app_js)
        self.assertIn('type.includes("output_transcript")', app_js)
        self.assertIn('? "input_transcript_final" : "input_transcript_delta"', app_js)
        self.assertIn(': isFinal ? "caption_final" : "caption_delta"', app_js)
        self.assertIn("payload.en = text", app_js)
        self.assertIn("payload.zh = text", app_js)
        self.assertIn('source: "openai-realtime-webrtc"', app_js)
        self.assertIn("postRealtimeSessionEvent(captionEvent)", app_js)
        self.assertIn('fetch(`/api/realtime/sessions/${encodeURIComponent(rt.sessionId)}/events`', app_js)
        self.assertIn('"X-Realtime-Event-Token": rt.eventToken', app_js)
        self.assertIn("response.ok", app_js)
        self.assertIn("backendPersistedEvents", app_js)
        self.assertIn("backendPersistFailures", app_js)
        self.assertIn("Realtime deltas 已保存", app_js)
        self.assertIn("后台保存 realtime delta 失败", app_js)
        self.assertIn('updateAdminEvidence("worker", `Realtime deltas 已保存 ${state.realtime.backendPersistedEvents} 条`)', app_js)

    def test_ipad_mic_realtime_failure_is_not_treated_as_successful_fallback(self):
        app_js = self.app_js

        self.assertIn("不使用浏览器本地听写代替 gpt-realtime-translate", app_js)
        self.assertIn('updateTestPassState("失败：Realtime 翻译未启动", "error")', app_js)
        self.assertIn('setStatus("Realtime 翻译未启动", "error")', app_js)
        self.assertIn('if (reason !== "realtime-startup-failed")', app_js)
        self.assertIn('if (reason === "realtime-startup-failed")', app_js)
        self.assertNotIn("OpenAI Realtime 未启动，退回浏览器本地听写测试", app_js)
        self.assertNotIn("await startBrowserSpeechMicFallback();", app_js)

    def test_openai_realtime_nested_transcript_payloads_are_supported(self):
        app_js = self.app_js

        self.assertIn("function extractRealtimeTranscriptText(event)", app_js)
        self.assertIn("event.input_transcript_delta", app_js)
        self.assertIn("event.output_transcript", app_js)
        self.assertIn("event.input_transcript?.delta", app_js)
        self.assertIn("event.output_transcript?.delta", app_js)
        self.assertIn("event.input_audio_transcription?.delta", app_js)
        self.assertIn('nestedRealtimeTranscriptValues(event.input_transcript, "delta")', app_js)
        self.assertIn("event.audio_transcript", app_js)
        self.assertIn('nestedRealtimeTranscriptValues(event.output_transcript, "delta")', app_js)
        self.assertIn('nestedRealtimeTranscriptValues(event.input_audio_transcription, "delta")', app_js)
        self.assertIn('nestedRealtimeTranscriptValues(event.response, "delta")', app_js)
        self.assertIn(
            '["delta", "text_delta", "transcript_delta", "input_transcript_delta", "output_transcript_delta", "input_audio_transcription_delta", "audio_transcript_delta"]',
            app_js,
        )
        self.assertIn("event.part?.transcript", app_js)
        self.assertIn("event.item?.content", app_js)
        self.assertIn("event.response?.output", app_js)
        self.assertIn("function realtimeContentTexts(content)", app_js)
        self.assertIn("function realtimeOutputTexts(output)", app_js)
        self.assertIn("function nestedRealtimeTranscriptValues(value, mode)", app_js)
        self.assertIn("function realtimeSegmentIdFromOpenAI(event)", app_js)

    def test_public_caption_view_subscribes_to_realtime_sse_current_session(self):
        app_js = self.app_js

        self.assertIn("function connectPublicRealtimeEvents()", app_js)
        self.assertIn('new EventSource("/api/realtime/sessions/current/events")', app_js)
        self.assertIn('["caption_delta", "caption_stable", "caption_final", "input_transcript_delta", "input_transcript_final"]', app_js)
        self.assertIn("handleRealtimeCaptionEvent(payload)", app_js)
        self.assertIn('setStatus("实时字幕更新中", "live")', app_js)
        self.assertIn('setSla("现场实时字幕", "live")', app_js)

    def test_admin_pipeline_polls_backend_generation_progress(self):
        app_js = self.app_js

        self.assertIn("function startAdminProgressPolling()", app_js)
        self.assertIn("state.adminProgressTimer = window.setInterval(() => refreshAdminProgress({ quiet: true }), 5000)", app_js)
        self.assertIn("function refreshAdminProgress(options = {})", app_js)
        self.assertIn('fetch(`/api/admin/sundays/${sunday}/progress`', app_js)
        self.assertIn("function updatePipelineFromAdminProgress(progress)", app_js)
        self.assertIn('progress.status === "missing"', app_js)
        self.assertIn('progress.pipelineStages', app_js)
        self.assertIn('["waiting", "active", "done", "failed"].includes(stage.state)', app_js)
        self.assertIn("adminProgressSummary(progress)", app_js)

    def test_public_caption_view_polls_live_playback_clock(self):
        app_js = self.app_js

        self.assertIn("function startLivePlaybackPolling()", app_js)
        self.assertIn("function loadInitialCloudRunDatePlayback()", app_js)
        self.assertIn("function upcomingSundayIsoDate()", app_js)
        self.assertIn('return [upcomingSundayIsoDate(), "current"];', app_js)
        self.assertIn("state.publicPlaybackSunday", app_js)
        self.assertIn('fetch(`/api/sundays/${encodeURIComponent(sunday)}/live-playback`', app_js)
        self.assertIn("function livePlaybackPlayheadMs(playback)", app_js)
        self.assertIn("segmentForPlayhead(playheadMs)", app_js)
        self.assertIn('["live", "paused"].includes(playback.mode)', app_js)
        self.assertIn('["idle", "ended"].includes(playback.mode)', app_js)
        self.assertIn("loadPublicPublishedSnapshot();", app_js)
        self.assertIn("state.livePlaybackFetchedAt", app_js)
        self.assertIn("state.livePlaybackAppliedMode", app_js)

    def test_admin_posts_live_playback_actions(self):
        app_js = self.app_js

        self.assertIn('data-action="live-playback-start"', (REPO_ROOT / "web" / "admin.html").read_text(encoding="utf-8"))
        self.assertIn("function postLivePlaybackAction(action, extra = {})", app_js)
        self.assertIn('fetch(`/api/admin/sundays/${encodeURIComponent(sunday)}/live-playback`', app_js)
        self.assertIn('postLivePlaybackAction("adjustOffset", { deltaMs })', app_js)
        self.assertIn('postLivePlaybackAction("jumpToSegment"', app_js)
        self.assertIn('state.livePlayback && ["live", "paused"].includes(state.livePlayback.mode)', app_js)

    def test_stable_correction_from_public_sse_marks_segment_stable(self):
        app_js = self.app_js

        self.assertIn('String(event.source || "").includes("stable-correction")', app_js)
        self.assertIn('event.type === "caption_stable"', app_js)
        self.assertIn('segment.note = "gpt-5.4-mini 稳定修正版。"', app_js)
        self.assertIn("segment.stable = Boolean(segment.stable || isStableCorrection || isStableCommit)", app_js)
        self.assertIn("appendRealtimeStage(segment, realtimeStage, event)", app_js)
        self.assertIn("segment.stabilizerWindow = event.stabilizerWindow", app_js)

    def test_admin_review_shows_realtime_draft_stable_final_history(self):
        app_js = self.app_js

        self.assertIn("function appendRealtimeStage(segment, stage, event)", app_js)
        self.assertIn("segment.realtimeStages = stages", app_js)
        self.assertIn("function realtimeStageHistoryLabel(stages, fallbackStage = \"\")", app_js)
        self.assertIn('labels.join(" / ")', app_js)
        self.assertIn('["draft", "stable", "final"]', app_js)
        self.assertIn("realtimeStageHistoryLabel(group.realtimeStages, group.realtimeStage)", app_js)


if __name__ == "__main__":
    unittest.main()
