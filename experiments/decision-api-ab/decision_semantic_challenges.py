"""Constructed semantic challenges, with author development labels only.

These fictional snippets are neither production media nor independently
adjudicated human gold. They test a single bounded semantic classification,
not a whole reviewer, audio listening, repair execution, or publication gate.
Expected labels stay outside shared evidence and model questions.
"""
from __future__ import annotations

from copy import deepcopy


RUBRICS = {
    "E01": (
        "Compare the complete reference sentence with the delivered units and "
        "their supplied neighboring context, including any explicit speaker "
        "attribution metadata. Classify only a material meaning change introduced "
        "by the delivered segmentation: changed negation, relation, or quotation "
        "speaker counts; harmless fragmentation or an ambiguity already present "
        "in the reference does not. Do not demand that each fragment stand alone "
        "when its supplied context resolves it. The reference is text evidence, "
        "not proof of what an unavailable recording said. Choose preserved when "
        "the delivered representation preserves the reference meaning; altered "
        "when supplied evidence establishes a new material change; otherwise "
        "insufficient_evidence when an incomplete unit export or unresolved "
        "reference prevents the comparison. Do not infer omitted evidence.",
        {
            "preserved": "Reference meaning remains available without a new ambiguity.",
            "altered": "A new material meaning or attribution change is demonstrable.",
            "insufficient_evidence": "The supplied reference or unit export cannot settle the comparison.",
        },
    ),
    "E02": (
        "Compare the frozen English source and Chinese draft for material meaning, "
        "not stylistic preference. Choose faithful for a meaning-preserving draft; "
        "semantic_error for a demonstrable negation reversal, omitted claim, "
        "unsupported added claim, or changed quotation attribution; choose "
        "insufficient_evidence if the supplied source is unresolved or incomplete "
        "at the disputed content. Do not use remembered scripture or invent a "
        "missing source passage. This is classification of the original draft, "
        "not a corrected translation or approval.",
        {
            "faithful": "Draft preserves all supplied material source meaning.",
            "semantic_error": "Supplied source establishes a material draft error.",
            "insufficient_evidence": "Missing or unresolved source prevents a justified verdict.",
        },
    ),
    "E03": (
        "Choose one semantic repair route, without executing it or approving "
        "content. Priority: source_ambiguity when supplied records establish that "
        "the upstream English itself has competing unresolved meanings; "
        "human_review when needed evidence is absent, or a human decision cannot "
        "be settled by the supplied records; open_text_revision when the English "
        "is settled and demonstrates a repairable Chinese meaning error; "
        "no_repair_needed when the settled source and draft agree materially. "
        "An existing pronoun ambiguity is not automatically a translation error. "
        "A reviewer disagreement alone does not force human_review when the "
        "supplied settled source clearly resolves it. Retain all formal approval "
        "and execution gates outside this classification.",
        {
            "no_repair_needed": "Settled source and draft materially agree.",
            "open_text_revision": "Settled English demonstrates a Chinese meaning error.",
            "source_ambiguity": "Upstream English meaning is explicitly unresolved.",
            "human_review": "Missing evidence or an unresolved human decision prevents bounded routing.",
        },
    ),
    "E04": (
        "Compare expected narration text with an ASR text representation. "
        "Classify semantic_match when a sufficiently supplied ASR reading has "
        "the same meaning, even with synonyms; text_discrepancy when the supplied "
        "ASR reading materially omits, adds, reverses, or misattributes meaning; "
        "audio_verification_required when blank, truncated, competing, or "
        "explicitly uncertain ASR evidence prevents a text verdict. Multiple "
        "ASR alternatives that materially agree do not require escalation merely "
        "because alternatives exist. No classification establishes what the "
        "actual audio said, diagnoses whether the fault is TTS or ASR, or "
        "replaces listening. No recording is supplied in these challenges.",
        {
            "semantic_match": "The supplied ASR text preserves the expected meaning.",
            "text_discrepancy": "The supplied ASR text contains a material meaning difference.",
            "audio_verification_required": "ASR text uncertainty or incompleteness prevents comparison.",
        },
    ),
    "E06": (
        "Assess the supplied study draft against its supplied source excerpt. "
        "Choose supported when its claims follow the source, including a faithful "
        "paraphrase or an invitation framed as reflection rather than a reported "
        "fact. Choose contradiction when the draft directly opposes an explicit "
        "source claim; unsupported when sufficient relevant source is supplied "
        "but the draft asserts an additional fact, guarantee, or attribution "
        "without support. Choose insufficient_evidence when the relevant source "
        "is missing or explicitly truncated at that point. Do not treat personal "
        "theological knowledge as source evidence. Classify the draft; do not "
        "rewrite it or claim human approval.",
        {
            "supported": "Supplied source supports the draft's material claims.",
            "contradiction": "Draft directly opposes an explicit source claim.",
            "unsupported": "Draft adds a factual claim or attribution absent from sufficient source.",
            "insufficient_evidence": "Relevant source is missing or incomplete.",
        },
    ),
    "E08": (
        "These are fictional feedback messages, not real user reports. Classify "
        "their single primary actionable concern: content_correction for an "
        "explicit text, meaning, or attribution complaint; playback_problem for "
        "an explicit loading, playback, seek, or synchronization problem; "
        "no_action_needed for clear praise or a resolved report without a request; "
        "clarification_needed when the message lacks a discernible concern or "
        "explicitly mixes independent concerns without naming a primary one. "
        "A reported complaint need not be verified to route it; classification "
        "does not confirm the complaint or imply automatic dispatch. Do not "
        "infer a bug from praise, or a content error from a playback complaint.",
        {
            "content_correction": "Primary concern explicitly alleges a content problem.",
            "playback_problem": "Primary concern explicitly alleges playback or synchronization trouble.",
            "no_action_needed": "Clear praise or resolved report without an actionable request.",
            "clarification_needed": "No unambiguous primary concern can be identified.",
        },
    ),
}


def _case(stage, slug, evidence, expected, family, severity="material"):
    instructions, choices = RUBRICS[stage]
    if expected not in choices:
        raise ValueError("challenge_expected_not_allowed")
    return {
        "caseId": f"{stage}.semantic.{slug}",
        "stageId": stage,
        "sharedEvidence": {
            "materialStatus": "fictional_constructed_example",
            **deepcopy(evidence),
        },
        "question": {
            "type": "choice",
            "name": "classification",
            "instructions": instructions,
            "choices": [{"value": value, "description": description}
                        for value, description in choices.items()],
        },
        "expected": expected,
        "sourceKind": "constructed_semantic_challenge",
        "challengeFamily": family,
        "severity": severity,
        "annotationStatus": "author_development_label_not_human_gold",
        "productionEligible": False,
    }


def build_challenges() -> list[dict]:
    """Return deterministic, newly allocated constructed challenge records."""
    cases = []

    # E01: source wording and supplied segmentation, never unavailable audio.
    for slug, sentence, units, context, expected, family in [
        ("causal-preserved", "We can forgive because we have received mercy.",
         ["We can forgive", "because we have received mercy."],
         {"before": "This is why forgiveness is possible.", "after": "Mercy comes first."},
         "preserved", "causal_relation"),
        ("negation-preserved", "Hope does not require us to deny our grief.",
         ["Hope does not require us", "to deny our grief."],
         {"before": "We can name our loss honestly.", "after": "Grief and hope can coexist."},
         "preserved", "negation_scope"),
        ("existing-ambiguity", "He encouraged her to return.",
         ["He encouraged her", "to return."],
         {"before": None, "after": None}, "preserved", "unchanged_source_ambiguity"),
        ("negation-lost", "Forgiveness does not mean calling harm good.",
         ["Forgiveness means", "calling harm good."],
         {"before": "We must name harm honestly.", "after": "Forgiveness is different from approval."},
         "altered", "negation_scope"),
        ("causal-reversed", "We serve because we are loved, not to earn love.",
         ["We are loved because we serve.", "We serve to earn love."],
         {"before": "Love is a gift.", "after": "Service is our response."},
         "altered", "causal_relation"),
        ("quotation-speaker", "My brother said, 'I will never forgive him,' but I disagreed.",
         [{"text": "My brother said, 'I will never forgive him,'", "quotationSpeaker": "the narrator"},
          {"text": "but I disagreed.", "speaker": "the narrator"}],
         {"before": "My brother and I disagreed about forgiveness.", "after": "I chose to forgive."},
         "altered", "quotation_attribution"),
        ("missing-unit-export", "If we remember the gift, we can respond with gratitude.",
         {"exportStatus": "truncated", "visibleUnits": ["If we remember the gift,"], "remainingUnits": None},
         {"before": None, "after": None}, "insufficient_evidence", "incomplete_unit_evidence"),
        ("unresolved-reference", None,
         ["Mercy makes restoration possible."],
         {"before": None, "after": None, "referenceCandidates":
          ["Mercy makes restoration possible.", "Mercy does not make restoration possible."]},
         "insufficient_evidence", "unresolved_source_evidence"),
        ("missing-quotation-reference", {"exportStatus": "truncated", "visibleText": "Someone told me,"},
         [{"text": "'I have given up,'", "quotationSpeaker": "the narrator"}],
         {"before": None, "after": None}, "insufficient_evidence", "quotation_source_missing"),
    ]:
        cases.append(_case("E01", slug,
            {"completeSentence": sentence, "units": units, "neighborContext": context},
            expected, family, "none" if expected == "preserved" else "material"))

    # E02: twelve cases include all requested material translation errors.
    for slug, source, draft, context, expected, family in [
        ("negation-faithful", "Faith does not remove every fear.", "信心并不会消除所有恐惧。", {}, "faithful", "negation"),
        ("paraphrase-faithful", "We can bring our grief to God without pretending to be cheerful.",
         "我们不必假装快乐，可以把悲伤带到神面前。", {}, "faithful", "meaning_preserving_paraphrase"),
        ("quotation-faithful", "A visitor told me, 'I cannot trust anyone.' That was her struggle, not my advice.",
         "一位来访者对我说：‘我无法相信任何人。’这是她的挣扎，并不是我的建议。", {}, "faithful", "quotation_attribution"),
        ("omission-control", "Listen patiently and speak honestly.", "要耐心聆听，也要诚实说话。", {}, "faithful", "complete_two_claims"),
        ("negation-reversal", "Grace is not a reward for flawless behavior.",
         "恩典是行为毫无瑕疵的人所得的奖赏。", {}, "semantic_error", "negation"),
        ("unsupported-promise", "Prayer gives us a place to express our pain.",
         "祷告让我们表达痛苦，并保证明天所有问题都会解决。", {}, "semantic_error", "unsupported_added_claim"),
        ("claim-omission", "We should apologize and restore what we damaged.",
         "我们应当道歉。", {}, "semantic_error", "omitted_obligation"),
        ("quotation-reassigned", "My skeptical friend said, 'No one cares about you.' I told him that was untrue.",
         "讲员说：‘没有人在乎你。’", {}, "semantic_error", "quotation_attribution"),
        ("source-negation-disputed", None, "爱不会使伤害变得合理。",
         {"sourceStatus": "unresolved", "sourceCandidates":
          ["Love does not make harm acceptable.", "Love makes harm acceptable."]},
         "insufficient_evidence", "unresolved_source_negation"),
        ("missing-quoted-section", "She then quoted the letter:", "她引用信中的话：‘我已经原谅你。’",
         {"sourceStatus": "truncated_after_colon", "quotedSection": None},
         "insufficient_evidence", "missing_quotation_source"),
        ("missing-conclusion", "His main point was that", "他的主要观点是耐心比速度更重要。",
         {"sourceStatus": "truncated_mid_sentence"}, "insufficient_evidence", "missing_source_claim"),
        ("disputed-referent", "He forgave him.", "父亲原谅了儿子。",
         {"sourceStatus": "unresolved_referents", "referentCandidates":
          ["father forgave son", "son forgave father"], "priorParagraph": None},
         "insufficient_evidence", "unresolved_source_reference"),
    ]:
        cases.append(_case("E02", slug,
            {"englishSource": source, "chineseDraft": draft, "sourceContext": context},
            expected, family, "none" if expected == "faithful" else "material"))

    # E03: route a semantic question; no error code, arithmetic or dispatch.
    for slug, evidence, expected, family in [
        ("paraphrase-no-repair", {"englishSource": "We can be honest about our weakness.",
          "chineseDraft": "我们可以坦诚承认自己的软弱。", "sourceStatus": "settled"},
         "no_repair_needed", "faithful_paraphrase"),
        ("unchanged-pronoun", {"englishSource": "He welcomed her.", "chineseDraft": "他欢迎了她。",
          "sourceStatus": "settled_text_with_unidentified_people", "reviewConcern": "The English does not name the people."},
         "no_repair_needed", "preserved_source_ambiguity"),
        ("review-dispute-resolved", {"englishSource": "Patience is not indifference.",
          "chineseDraft": "耐心并不等于冷漠。", "sourceStatus": "settled",
          "reviewComments": ["Negation is missing.", "The draft retains 并不."]},
         "no_repair_needed", "review_disagreement_resolved_by_source"),
        ("negation-text-repair", {"englishSource": "Forgiveness does not excuse harm.",
          "chineseDraft": "饶恕就是为伤害开脱。", "sourceStatus": "settled"},
         "open_text_revision", "settled_negation_error"),
        ("omission-text-repair", {"englishSource": "Ask for help and respect the other person's boundary.",
          "chineseDraft": "要寻求帮助。", "sourceStatus": "settled"},
         "open_text_revision", "settled_omitted_claim"),
        ("attribution-text-repair", {"englishSource": "The critic said, 'Hope is pointless.' The speaker rejected that claim.",
          "chineseDraft": "讲员认为盼望没有意义。", "sourceStatus": "settled"},
         "open_text_revision", "settled_attribution_error"),
        ("negation-source-dispute", {"englishSource": None, "chineseDraft": "我们应该放弃。",
          "sourceStatus": "unresolved", "sourceCandidates": ["We should give up.", "We should not give up."]},
         "source_ambiguity", "upstream_negation_dispute"),
        ("speaker-source-dispute", {"englishSource": "I cannot forgive him.", "chineseDraft": "我无法原谅他。",
          "sourceStatus": "unresolved_speaker", "speakerCandidates": ["pastor's advice", "visitor's quoted struggle"]},
         "source_ambiguity", "upstream_attribution_dispute"),
        ("reference-source-dispute", {"englishSource": "He asked him to leave.", "chineseDraft": "父亲请儿子离开。",
          "sourceStatus": "unresolved_reference", "sourceCandidates": ["father asked son", "son asked father"]},
         "source_ambiguity", "upstream_referent_dispute"),
        ("missing-source-review", {"englishSource": None, "chineseDraft": "我们必须先赔偿才能得到怜悯。",
          "sourceStatus": "not_supplied", "reviewConcern": "One reviewer alleges an added condition, but supplies no source."},
         "human_review", "missing_semantic_evidence"),
        ("human-decision-conflict", {"englishSource": "The visitor asked for privacy.",
          "chineseDraft": "来访者请求保护隐私。", "sourceStatus": "settled",
          "reviewConcern": "Two human records conflict about permission to include the visitor's identifying story.",
          "humanDecisionRecords": ["Permission granted", "Permission withdrawn"], "finalPermissionRecord": None},
         "human_review", "unresolved_human_content_decision"),
        ("missing-disputed-context", {"englishSource": "That was not what I meant.",
          "chineseDraft": "那不是我的意思。", "sourceStatus": "settled_visible_excerpt",
          "reviewConcern": "The proposed repair changes the earlier explanation, which is not supplied.",
          "repairAffectedSourceExcerpt": None},
         "human_review", "missing_repair_scope_evidence"),
    ]:
        cases.append(_case("E03", slug, evidence, expected, family,
            "none" if expected == "no_repair_needed" else "material"))

    # E04: compare textual representations, explicitly without audio evidence.
    for slug, expected_text, asr, extra, expected, family in [
        ("synonyms-match", "我们可以坦诚表达自己的悲伤。", "我们可以诚实地说出自己的哀伤。",
         {}, "semantic_match", "synonymous_asr_text"),
        ("order-match", "先聆听，再回应。", "回应之前，请先听对方说。",
         {}, "semantic_match", "meaning_preserving_reordering"),
        ("alternatives-agree", "爱不要求我们假装没有受伤。", None,
         {"asrAlternatives": ["爱并不要求我们假装没有受伤。", "爱不要求我们装作未曾受伤。"]},
         "semantic_match", "semantically_agreeing_alternatives"),
        ("negation-discrepancy", "我们不应该忽视受伤的人。", "我们应该忽视受伤的人。",
         {}, "text_discrepancy", "asr_negation_difference"),
        ("claim-discrepancy", "要道歉，也要补偿造成的损失。", "要道歉。",
         {}, "text_discrepancy", "asr_missing_claim"),
        ("speaker-discrepancy", "那位访客说他失去了盼望，讲员鼓励他继续寻求帮助。", "讲员说他失去了盼望。",
         {}, "text_discrepancy", "asr_attribution_difference"),
        ("competing-negation", "神的怜悯不是奖赏。", None,
         {"asrAlternatives": ["神的怜悯不是奖赏。", "神的怜悯是奖赏。"]},
         "audio_verification_required", "competing_asr_meanings"),
        ("blank-transcript", "你可以带着问题寻求帮助。", "",
         {"asrStatus": "no_reliable_text"}, "audio_verification_required", "missing_asr_text"),
        ("truncated-transcript", "我们不应当靠假装坚强来隐藏痛苦。", "我们不应当",
         {"asrStatus": "truncated_export", "remainingAsrText": None},
         "audio_verification_required", "incomplete_asr_evidence"),
    ]:
        cases.append(_case("E04", slug,
            {"expectedNarration": expected_text, "asrText": asr, "audioProvided": False, **extra},
            expected, family, "none" if expected == "semantic_match" else "material"))

    # E06: support, contradiction, unsupported addition and absent evidence.
    for slug, source, draft, extra, expected, family in [
        ("outline-supported", "We can admit our limitations and ask trusted people for help.",
         "大纲：承认自己的有限，并向可信赖的人寻求帮助。", {}, "supported", "faithful_outline"),
        ("reflection-supported", "A patient listener makes space for another person's grief.",
         "默想：今天我可以怎样给别人的悲伤留出被聆听的空间？", {}, "supported", "source_grounded_reflection"),
        ("paraphrase-supported", "Forgiveness does not require pretending the harm never happened.",
         "大纲：饶恕不是否认伤害发生过。", {}, "supported", "meaning_preserving_paraphrase"),
        ("contradicted-condition", "You do not have to hide your doubts before asking for help.",
         "大纲：必须先隐藏疑问，才可以寻求帮助。", {}, "contradiction", "negation_reversal"),
        ("contradicted-timing", "Reconciliation may take time; no timetable is promised.",
         "大纲：和解一定会在今天完成。", {}, "contradiction", "contradicted_guarantee"),
        ("contradicted-advice", "The speaker rejected the critic's claim that compassion is weakness.",
         "大纲：讲员教导我们，同情就是软弱。", {}, "contradiction", "attribution_reversal"),
        ("unsupported-event", "The speaker invited listeners to care for their neighbors.",
         "大纲：教会将在下周五晚七点组织探访活动。", {}, "unsupported", "invented_operational_fact"),
        ("unsupported-quotation", "The speaker said that listening patiently can help a grieving person.",
         "默想：神亲口说过‘耐心聆听就能消除所有悲伤’。", {}, "unsupported", "invented_scripture_attribution"),
        ("unsupported-promise", "The speaker encouraged honest prayer during difficulty.",
         "默想：只要诚实祷告，下一次工作申请就一定成功。", {}, "unsupported", "invented_outcome_guarantee"),
        ("missing-source", None, "大纲：讲员主张先恢复关系，再讨论责任。",
         {"sourceStatus": "not_supplied"}, "insufficient_evidence", "missing_source"),
        ("truncated-reason", "The reason for this invitation is", "大纲：这个邀请的理由是彼此之间已经有信任。",
         {"sourceStatus": "truncated_mid_sentence"}, "insufficient_evidence", "missing_source_reason"),
        ("missing-story-conclusion", "A family faced a difficult decision. The next part of the story is not included.",
         "大纲：这个家庭最终决定让父亲留在家里。", {"sourceStatus": "story_conclusion_not_supplied"},
         "insufficient_evidence", "missing_story_evidence"),
    ]:
        cases.append(_case("E06", slug,
            {"sourceExcerpt": source, "studyDraft": draft, **extra},
            expected, family, "none" if expected == "supported" else "material"))

    # E08: fictional reports only; route the reported concern, not a proven bug.
    for slug, feedback, expected, family in [
        ("praise", "今天的中文默想很清楚，谢谢你们！", "no_action_needed", "praise_without_request"),
        ("resolved", "刚才网络不好，现在音频已经恢复，暂时不需要帮助。", "no_action_needed", "resolved_without_request"),
        ("appreciation", "我已经找到西班牙语页面，感谢提供这个入口。", "no_action_needed", "successful_navigation"),
        ("negation-complaint", "字幕写着‘不要原谅’，但讲员原话是‘不要拒绝原谅’，请核对这句翻译。",
         "content_correction", "reported_translation_meaning"),
        ("quotation-complaint", "大纲把访客的怀疑写成了讲员的教导。请核对引语是谁说的。",
         "content_correction", "reported_attribution"),
        ("added-claim-complaint", "默想里写‘祷告就一定会升职’，我在英文来源没有找到这句话，请检查。",
         "content_correction", "reported_unsupported_content"),
        ("playback-stuck", "按播放后一直转圈，没有声音，文字页面能打开。",
         "playback_problem", "reported_loading_failure"),
        ("highlight-lag", "音频已经读下一句了，高亮仍停在前一句，请检查同步。",
         "playback_problem", "reported_synchronization"),
        ("seek-stops", "拖动到中间后音频就停了，再按播放也没有恢复。",
         "playback_problem", "reported_seek_behavior"),
        ("vague", "这个地方不对。", "clarification_needed", "missing_concern"),
        ("mixed-no-primary", "我想同时报告两件事：一处翻译漏了一句话，而且音频加载不了。两件事同样重要。",
         "clarification_needed", "multiple_independent_primary_concerns"),
        ("ambiguous-other", "我不是在说内容，也不是在说播放。我希望你们处理那个问题，但现在没法说明。",
         "clarification_needed", "explicitly_unspecified_concern"),
    ]:
        cases.append(_case("E08", slug,
            {"feedbackMessage": feedback, "feedbackStatus": "fictional_not_a_real_user_report"},
            expected, family, "none" if expected == "no_action_needed" else "material"))

    return cases
