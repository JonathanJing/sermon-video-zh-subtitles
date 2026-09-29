"""Chinese Layer 2 screen for the Sep 27 Drive sermon.

The embedded eight-reference boundary decision is source and hash bound.
It approves CUV selection rules, not the complete Chinese translation.
"""
from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from hashlib import sha256

try:
    from scripts.cuv_scripture import CuvError, CuvLibrary
    from scripts.language_review_plugins.common import (
        explicit_series_errors, has_unsafe_speech_markup, result,
    )
except ImportError:  # Direct producer execution from scripts/.
    from cuv_scripture import CuvError, CuvLibrary
    from language_review_plugins.common import (
        explicit_series_errors, has_unsafe_speech_markup, result,
    )


PLUGIN_ID = "zh-Hans-weekly-cuv-v1"
PLUGIN_VERSION = "2026-09-27-source-bound-cuv-approved-v1"
REQUIRED = ["spoken_chinese", "cuv_exact_quote", "number_name_reading", "tts_segmentation"]
CUV_EDITION_ID = "cmn-cu89s"

# Candidate scripture locations in the 31:31 Drive clip. This list grants no
# quote permission; every candidate needs a human direct/partial/paraphrase
# decision bound to the final English Source Package and anchor manifest.
CANDIDATE_VERSES = {
    "rev-4-2-3": {"REV 4:2", "REV 4:3", "REV 4:2-3"},
    "rev-4-8": {"REV 4:8"},
    "rev-4-10-11": {"REV 4:10", "REV 4:11", "REV 4:10-11"},
    "rev-5-1-4": {"REV 5:1", "REV 5:2", "REV 5:3", "REV 5:4", "REV 5:1-4"},
    "rev-5-5": {"REV 5:5"},
    "rev-5-6": {"REV 5:6"},
    "rev-5-9-10": {"REV 5:9", "REV 5:10", "REV 5:9-10"},
    "rev-5-12": {"REV 5:12"},
}

# Source units that can contain a direct quotation in the final 420-unit
# anchor. Adjacent speaker introductions and explanations are excluded.
CANDIDATE_QUOTE_UNITS = {
    "rev-4-2-3": {"0-u067", "0-u068"},
    "rev-4-8": {"0-u086", "0-u087"},
    "rev-4-10-11": {"0-u138", "0-u139"},
    "rev-5-1-4": {"0-u161", "0-u162", "0-u164", "0-u165", "0-u167", "0-u168"},
    "rev-5-5": {"0-u193", "0-u194", "0-u195"},
    "rev-5-6": {"0-u240"},
    "rev-5-9-10": {"0-u256", "0-u257", "0-u258"},
    "rev-5-12": {"0-u374", "0-u375"},
}

# Character offsets in the approved English source unit. These six units mix
# the speaker's introduction/explanation with a possible scripture quotation.
# Human choices may narrow the span, but cannot include the speaker's words.
MIXED_UNIT_QUOTE_LIMITS = {
    "0-u067": (26, 122),
    "0-u086": (39, 80),
    "0-u138": (50, 120),
    "0-u161": (0, 10),
    "0-u195": (0, 54),
    "0-u240": (9, 103),
}

# User confirmed the eight-candidate recommendation. Exact unit fragments
# were resolved from the pinned CUV library and final English anchor; the
# receipt records that the user did not review this JSON line by line.
# This static value is included in the plugin implementation hash.
APPROVED_BOUNDARY_REVIEW: dict | None = {'decision': 'approved',
 'humanApproval': True,
 'approvedBy': 'user',
 'sourceMediaSha256': '374662dc7c00993820360b2095e277ecd7ebf17bc4d873ccf7e2b76a6c7c7930',
 'englishSourcePackageJsonSha256': 'a0cf67203bae17bff080b2d1af41f88bdef786345a435021c2739d14f15394ac',
 'anchorManifestJsonSha256': '9805110b89021c23de4b20b46b44269572b4ac476d588c0a897a297039a065c5',
 'reviewWorksheetSha256': '2e37446fda7a23329c1a6135df7af6cb72a4e0debf89ea0b22ee2522d1a29e65',
 'cuvEditionId': 'cmn-cu89s',
 'approvedReceiptSha256': '22deab032d8445537841ded01e89223acbe748dec51b7a509d3ef0c95af27eca',
 'decisions': [{'candidateId': 'rev-4-2-3',
                'classification': 'partial_direct_quote',
                'paraphraseUnitIds': [],
                'parts': [{'sourceUnitId': '0-u067',
                           'englishStartOffset': 26,
                           'englishEndOffset': 122,
                           'englishExcerptSha256': 'c8f82fd453cc56f685ebe13a208e8f791b440200c0df8b72c44fbbf6e9961b51',
                           'reference': 'REV 4:2',
                           'cuvExcerpt': '我立刻被[圣]灵感动，见有一个宝座安置在天上，又有一位坐在宝座上。',
                           'cuvExcerptSha256': 'aec7b76d54bfd09a46afa14639fe89e875ad910b8842ae6b06e3e669a598da3a'},
                          {'sourceUnitId': '0-u068',
                           'englishStartOffset': 0,
                           'englishEndOffset': 141,
                           'englishExcerptSha256': '1450d14bc8c4bef97f18ffc5ddad80fc33183a67de78269b25bfe21399d15c3e',
                           'reference': 'REV 4:3',
                           'cuvExcerpt': '看那坐着的，好像碧玉和红宝石；又有虹围着宝座，好像绿宝石。',
                           'cuvExcerptSha256': '25e72b52060a2b47ab2920d14054f479002bf11704cb832da878fc225af7434d'}]},
               {'candidateId': 'rev-4-8',
                'classification': 'partial_direct_quote',
                'paraphraseUnitIds': [],
                'parts': [{'sourceUnitId': '0-u086',
                           'englishStartOffset': 39,
                           'englishEndOffset': 80,
                           'englishExcerptSha256': '6aaf9a5a95b0f819f3df00dd826524c23c1bf873f76bd95dfb5d495e03a56a42',
                           'reference': 'REV 4:8',
                           'cuvExcerpt': '圣哉！圣哉！圣哉！ 主 神是',
                           'cuvExcerptSha256': 'c810045b110271524a8ce018642b30b627eaf0ddd4de5970c01ff5ccef03f52e'},
                          {'sourceUnitId': '0-u087',
                           'englishStartOffset': 0,
                           'englishEndOffset': 36,
                           'englishExcerptSha256': 'a1653ea112d2343eb7f81bb8e5b7b02042dcdc8d9a577832400bdb9110a53d39',
                           'reference': 'REV 4:8',
                           'cuvExcerpt': '昔在、今在、 以后[永]在的全能者。',
                           'cuvExcerptSha256': '1960a58dbdd67b4f52b551ceb7eea296eeb4bfbc29ce60932af754442ac4a429'}]},
               {'candidateId': 'rev-4-10-11',
                'classification': 'partial_direct_quote',
                'paraphraseUnitIds': [],
                'parts': [{'sourceUnitId': '0-u138',
                           'englishStartOffset': 50,
                           'englishEndOffset': 120,
                           'englishExcerptSha256': '71545b8bf47d7eb903f4f1051fb6ed42117268df7ffbc6ffdb2fea53082d6155',
                           'reference': 'REV 4:11',
                           'cuvExcerpt': '我们的主，我们的 神， 你是配得荣耀、尊贵、权柄的；',
                           'cuvExcerptSha256': 'dea6c99117b8356fe9d7c50eed94f439e615af8c34d1d70279ced0141394fe42'},
                          {'sourceUnitId': '0-u139',
                           'englishStartOffset': 0,
                           'englishEndOffset': 82,
                           'englishExcerptSha256': '57a2a9843978d5864c5828efaa8d5b5dc4cb6bd705076a067efc7cbf1d6f4478',
                           'reference': 'REV 4:11',
                           'cuvExcerpt': '因为你创造了万物， 并且万物是因你的旨意被创造而有的。',
                           'cuvExcerptSha256': '66d17903ddef41e7ab0d0d1438f816a5297a630eb3deb2dd7a60e404e533f5d8'}]},
               {'candidateId': 'rev-5-1-4',
                'classification': 'partial_direct_quote',
                'paraphraseUnitIds': ['0-u167', '0-u168'],
                'parts': [{'sourceUnitId': '0-u161',
                           'englishStartOffset': 0,
                           'englishEndOffset': 10,
                           'englishExcerptSha256': '6457a935d094c5f54b554c6bdd6d7921f31672bba4e99bda68a9d88478b93a78',
                           'reference': 'REV 5:1',
                           'cuvExcerpt': '我看见',
                           'cuvExcerptSha256': 'bc2cf905e8a495c82c2833c6ec364fd61a197076f19eb8a9b81f67a4d8847ea6'},
                          {'sourceUnitId': '0-u162',
                           'englishStartOffset': 0,
                           'englishEndOffset': 111,
                           'englishExcerptSha256': 'ce6d92c27097628f78b6cc1afb5d77e0576353d14f71795a033dd655ea196344',
                           'reference': 'REV 5:1',
                           'cuvExcerpt': '坐宝座的右手中有书卷，里外都写着字，用七印封严了。',
                           'cuvExcerptSha256': '618ef6fd170484d41282eeb6bba61b430594523116bd7a560f5799f171187bf6'},
                          {'sourceUnitId': '0-u164',
                           'englishStartOffset': 0,
                           'englishEndOffset': 105,
                           'englishExcerptSha256': 'ddeed883a1d5de7a5557bc983d412e7eaa86cb292a9b1c2426692a22a5ec99a2',
                           'reference': 'REV 5:2',
                           'cuvExcerpt': '我又看见一位大力的天使大声宣传说：「有谁配展开那书卷，揭开那七印呢？」',
                           'cuvExcerptSha256': '170a61175a7e1ecbf502bd72884a941ba5ee6365b5ef54f6d56bc9e627f3d094'},
                          {'sourceUnitId': '0-u165',
                           'englishStartOffset': 0,
                           'englishEndOffset': 102,
                           'englishExcerptSha256': '79a141881454170b8e592824076c628b1478176118f874073733b004e2f61b69',
                           'reference': 'REV 5:3',
                           'cuvExcerpt': '在天上、地上、地底下，没有能展开、能观看那书卷的。',
                           'cuvExcerptSha256': '7ec32a3c2460dd907f18efe66151eb5fcb7babf5fb58d5430e94e190aeb703d4'}]},
               {'candidateId': 'rev-5-5',
                'classification': 'partial_direct_quote',
                'paraphraseUnitIds': [],
                'parts': [{'sourceUnitId': '0-u193',
                           'englishStartOffset': 0,
                           'englishEndOffset': 48,
                           'englishExcerptSha256': '2cf0d026b3fce99ceb79da3b887e20bf26e2e06083453f636098f90c896cf0df',
                           'reference': 'REV 5:5',
                           'cuvExcerpt': '长老中有一位对我说：「不要哭！',
                           'cuvExcerptSha256': '23f4dfee58182cd8fd1c2394ce24409ef1bc234154ac74c06475cfb7906c55d2'},
                          {'sourceUnitId': '0-u194',
                           'englishStartOffset': 0,
                           'englishEndOffset': 73,
                           'englishExcerptSha256': 'bd76354af8d02a76225deeac2791c1fcbcc90fcc7e055e83e791bc04a12f43fc',
                           'reference': 'REV 5:5',
                           'cuvExcerpt': '看哪，犹大支派中的狮子，大卫的根，他已得胜，',
                           'cuvExcerptSha256': '5578d35476cdd9cda826d4ac0a40fbdf0174c035b8802c531f0fee5c0e8c5e98'},
                          {'sourceUnitId': '0-u195',
                           'englishStartOffset': 0,
                           'englishEndOffset': 54,
                           'englishExcerptSha256': '948a03050eb095a20d87d4f8a7ab3cf90b79045710d28561cf4d1c243ec00768',
                           'reference': 'REV 5:5',
                           'cuvExcerpt': '能以展开那书卷，揭开那七印。」',
                           'cuvExcerptSha256': 'fb934da63cd1a1ee5b0f8be3bc87794ffbe08a67b29e3f77b4450ce5af230fbd'}]},
               {'candidateId': 'rev-5-6',
                'classification': 'partial_direct_quote',
                'paraphraseUnitIds': [],
                'parts': [{'sourceUnitId': '0-u240',
                           'englishStartOffset': 9,
                           'englishEndOffset': 103,
                           'englishExcerptSha256': 'dc7c9db6a827b47bc8c99082d388fb8b9394f2789eb03379b893eb103f224f38',
                           'reference': 'REV 5:6',
                           'cuvExcerpt': '有七角七眼，就是 神的七灵，奉差遣往普天下去的。',
                           'cuvExcerptSha256': '756760a7765c8417e436dd8df7f348c47a83257556c6839c10ae2d90f2dffde9'}]},
               {'candidateId': 'rev-5-9-10',
                'classification': 'partial_direct_quote',
                'paraphraseUnitIds': [],
                'parts': [{'sourceUnitId': '0-u256',
                           'englishStartOffset': 0,
                           'englishEndOffset': 53,
                           'englishExcerptSha256': 'ab0b7c2cc3779c8cc60436973a7f9ea81726503a2bf27590dfe9e15f54fe839e',
                           'reference': 'REV 5:9',
                           'cuvExcerpt': '你配拿书卷， 配揭开七印；',
                           'cuvExcerptSha256': '65c66d4f27fa5c57a68f03a63a303950a923527df400207e074f962a4c51a7b2'},
                          {'sourceUnitId': '0-u257',
                           'englishStartOffset': 0,
                           'englishEndOffset': 128,
                           'englishExcerptSha256': '310efee9d65f4d5b266eebab49793b6db4f3d27c4c5ded2831fadda4ce049573',
                           'reference': 'REV 5:9',
                           'cuvExcerpt': '因为你曾被杀， 用自己的血 从各族、各方、各民、各国中买了人来， 叫他们归于 神，',
                           'cuvExcerptSha256': 'ac15283e73686a75c454500a8ba0f36cd85881434235ceeaf03cebd67fa61bd8'},
                          {'sourceUnitId': '0-u258',
                           'englishStartOffset': 0,
                           'englishEndOffset': 81,
                           'englishExcerptSha256': '36652542d557b6c3b4fe191a5fd54abc44c30f2c16d4a098af92c1fc79f521f5',
                           'reference': 'REV 5:10',
                           'cuvExcerpt': '又叫他们成为国民， 作祭司归于 神， 在地上执掌王权。',
                           'cuvExcerptSha256': '82250697d5ff6c14eea6070b457d56b672f1116876876b6494aaad2b7245305d'}]},
               {'candidateId': 'rev-5-12',
                'classification': 'partial_direct_quote',
                'paraphraseUnitIds': [],
                'parts': [{'sourceUnitId': '0-u374',
                           'englishStartOffset': 0,
                           'englishEndOffset': 38,
                           'englishExcerptSha256': '92d5d30d78f6a592d51e881cd65c36c251f2a724d270524e51bc45434ecf6176',
                           'reference': 'REV 5:12',
                           'cuvExcerpt': '曾被杀的羔羊是配得',
                           'cuvExcerptSha256': '3c5d17048ddcff1d98517012ef7288badf409360268b14e1e91d9beddaffcd01'},
                          {'sourceUnitId': '0-u375',
                           'englishStartOffset': 0,
                           'englishEndOffset': 85,
                           'englishExcerptSha256': '67862c9bfbae73a4dba6e5ed65a9b4e14b9ca80824007361965bae24dc47bb50',
                           'reference': 'REV 5:12',
                           'cuvExcerpt': '权柄、丰富、智慧、能力、 尊贵、荣耀、颂赞的。',
                           'cuvExcerptSha256': '8bf03bb6e7fe82e32a5a55c23997d51595e288835b41329fdf95a1053fc13133'}]}]}


@lru_cache(maxsize=1)
def _library() -> CuvLibrary:
    return CuvLibrary.from_path()


def _approved_parts(policy: dict, approval: dict | None) -> tuple[dict[str, list[dict]], bool, str]:
    """Validate a human receipt, then index its exact CUV fragments by unit."""
    scope = policy.get("sourceScope", {})
    if not isinstance(approval, dict) or approval.get("humanApproval") is not True:
        return {}, False, "No human-reviewed quote-boundary receipt is embedded"
    if (approval.get("decision") != "approved"
            or approval.get("approvedBy") != "user"
            or approval.get("englishSourcePackageJsonSha256")
            != scope.get("englishSourcePackageJsonSha256")
            or approval.get("anchorManifestJsonSha256")
            != scope.get("anchorManifestSha256")):
        return {}, False, "Human boundary receipt belongs to another source or is not approved"
    decisions = approval.get("decisions")
    if (not isinstance(decisions, list) or len(decisions) != len(CANDIDATE_VERSES)
            or {row.get("candidateId") for row in decisions if isinstance(row, dict)}
            != set(CANDIDATE_VERSES)):
        return {}, False, "Human boundary receipt does not decide all eight candidates"
    parts_by_unit: dict[str, list[dict]] = {}
    try:
        for decision in decisions:
            kind = decision["classification"]
            parts = decision["parts"]
            paraphrase_units = decision["paraphraseUnitIds"]
            if kind not in {"direct_quote", "partial_direct_quote", "speaker_paraphrase"}:
                raise ValueError("unknown boundary classification")
            if not isinstance(parts, list) or (kind == "speaker_paraphrase") != (not parts):
                raise ValueError("quote parts do not match classification")
            allowed_units = CANDIDATE_QUOTE_UNITS[decision["candidateId"]]
            if (not isinstance(paraphrase_units, list)
                    or any(not isinstance(unit_id, str) for unit_id in paraphrase_units)
                    or len(paraphrase_units) != len(set(paraphrase_units))
                    or not set(paraphrase_units) <= allowed_units):
                raise ValueError("paraphrase units are invalid")
            # The producer reviews one English unit at a time. It cannot
            # prove a whole-verse quote assembled from several target groups.
            if (kind == "direct_quote"
                    and (len(parts) != 1 or _library().lookup(parts[0]["reference"])["text"]
                         != parts[0]["cuvExcerpt"])):
                raise ValueError("whole direct quote must fit one source unit")
            allowed = CANDIDATE_VERSES[decision["candidateId"]]
            quoted_units: set[str] = set()
            for part in parts:
                unit_id = part["sourceUnitId"]
                start, end = part["englishStartOffset"], part["englishEndOffset"]
                excerpt_hash = part["englishExcerptSha256"]
                reference, excerpt = part["reference"], part["cuvExcerpt"]
                if (not all(isinstance(value, str) and value.strip()
                            for value in (unit_id, reference, excerpt))
                        or unit_id not in allowed_units
                        or type(start) is not int or type(end) is not int
                        or start < 0 or end <= start
                        or not isinstance(excerpt_hash, str)
                        or re.fullmatch(r"[a-f0-9]{64}", excerpt_hash) is None):
                    raise ValueError("empty approved boundary field")
                lower, upper = MIXED_UNIT_QUOTE_LIMITS.get(unit_id, (0, float("inf")))
                if start < lower or end > upper:
                    raise ValueError("approved span includes speaker words")
                if reference not in allowed:
                    raise ValueError("scripture reference outside reviewed candidate")
                selected = _library().lookup(reference, excerpt=excerpt)
                if (selected["text"] != excerpt or selected["textSha256"]
                        != part["cuvExcerptSha256"]):
                    raise ValueError("approved excerpt differs from pinned CUV")
                quoted_units.add(unit_id)
                parts_by_unit.setdefault(unit_id, []).append(part)
            if (quoted_units & set(paraphrase_units)
                    or quoted_units | set(paraphrase_units) != allowed_units):
                raise ValueError("quote and paraphrase decisions do not cover candidate units")
    except (CuvError, KeyError, TypeError, ValueError):
        return {}, False, "Human boundary receipt or pinned CUV excerpt is invalid"
    return parts_by_unit, True, "Human boundary receipt and pinned CUV excerpts match this source"


def _review_group(policy: dict, english_units: list[dict], group: dict,
                  approval: dict | None) -> list[dict[str, str]]:
    if (policy.get("targetLocale") != "zh-Hans"
            or policy.get("languageReview", {}).get("requiredChecks") != REQUIRED):
        raise ValueError("Chinese weekly CUV policy differs from plugin")
    source_scope = policy.get("sourceScope", {})
    scripture = policy.get("scripture", {})
    ids = [unit.get("sourceUnitId") for unit in english_units]
    english = " ".join(unit.get("english", "") for unit in english_units)
    text = group["targetText"]
    source_hash = source_scope.get("englishSourcePackageJsonSha256")
    anchor_hash = source_scope.get("anchorManifestSha256")
    source_bound = (
        isinstance(source_hash, str) and re.fullmatch(r"[a-f0-9]{64}", source_hash) is not None
        and isinstance(anchor_hash, str) and re.fullmatch(r"[a-f0-9]{64}", anchor_hash) is not None
        and group.get("englishSourcePackageJsonSha256") == source_hash
        and group.get("sourceUnitIds") == ids
        and bool(ids) and len(ids) == len(set(ids))
    )
    parts_by_unit, receipt_valid, boundary_reason = _approved_parts(policy, approval)
    quote_ok = (source_bound and receipt_valid
                and scripture.get("editionId") == CUV_EDITION_ID
                and scripture.get("citationUseStatus") == "project_source_reviewed"
                and scripture.get("quoteCheckPolicy") == "source_bound_exact_quote")
    if quote_ok:
        for unit in english_units:
            uttered = unit["english"]
            for part in parts_by_unit.get(unit["sourceUnitId"], []):
                start, end = part["englishStartOffset"], part["englishEndOffset"]
                if (end > len(uttered)
                        or sha256(uttered[start:end].encode("utf-8")).hexdigest()
                        != part["englishExcerptSha256"]):
                    quote_ok = False
                    boundary_reason = "Exact English span differs from approved unit offsets"
                    break
            if not quote_ok:
                break
    if quote_ok:
        approved_here = Counter(part["cuvExcerpt"] for unit_id in ids
                                for part in parts_by_unit.get(unit_id, []))
        if any(text.count(excerpt) != count for excerpt, count in approved_here.items()):
            quote_ok = False
            boundary_reason = "Approved CUV excerpt is missing or repeated in this unit"
    if quote_ok:
        if any(excerpt in text and excerpt not in approved_here
               for parts in parts_by_unit.values() for excerpt in
               (part["cuvExcerpt"] for part in parts)
               if len(excerpt) >= 12):
            quote_ok = False
            boundary_reason = "CUV excerpt appears outside its approved English unit"
    if quote_ok:
        # A paraphrase choice cannot silently turn into an unapproved full
        # verse pasted by the translator. Partial choices likewise cannot
        # smuggle in a complete verse that the receipt did not select.
        for reference in {ref for refs in CANDIDATE_VERSES.values() for ref in refs
                          if re.fullmatch(r"REV [0-9]+:[0-9]+", ref)}:
            verse = _library().lookup(reference)["text"]
            if len(verse) >= 12 and verse in text and verse not in approved_here:
                quote_ok = False
                boundary_reason = "Unapproved complete CUV verse appears in this unit"
                break
    series_errors = explicit_series_errors(policy, english_units, text)
    spoken_ok = bool(re.search(r"[\u3400-\u9fff]", text)) and not series_errors
    spoken_ok = spoken_ok and not re.search(r"\b(?:TODO|TBD|PLACEHOLDER)\b", text, re.I)
    missing_names = []
    for term in policy["terminology"]["properNames"]:
        occurrences = [(unit, match) for unit in english_units
                       for match in re.finditer(re.escape(term["source"]),
                                                unit["english"], re.IGNORECASE)]
        if not occurrences:
            continue
        # The pinned CUV is authoritative inside an approved exact quote;
        # ordinary proper-name spellings still apply to speaker text.
        outside_quote = any(
            not (quote_ok and any(part["englishStartOffset"] <= match.start()
                                  and match.end() <= part["englishEndOffset"]
                                  for part in parts_by_unit.get(unit["sourceUnitId"], [])))
            for unit, match in occurrences
        )
        if outside_quote and (term["reviewStatus"] == "pending" or not term["target"]
                              or term["target"] not in text):
            missing_names.append(term["source"])
    digits = re.findall(r"(?<!\w)(?:\d{1,3}(?:,\d{3})+|\d+)(?!\w)", english)
    lost_digits = [number for number in digits if number not in text]
    number_name_ok = not missing_names and not lost_digits
    # The CUV display text itself contains [圣] and [永]. Strip only bracket
    # tokens that occur inside an approved excerpt for the speech-markup screen;
    # other bracketed markup remains unsafe.
    approved_brackets = {match.group() for unit_id in ids
                         for part in parts_by_unit.get(unit_id, [])
                         for match in re.finditer(r"\[[^]]+\]", part["cuvExcerpt"])} if quote_ok else set()
    spoken_utterances = list(group["targetUtterances"])
    for bracket in approved_brackets:
        spoken_utterances = [utterance.replace(bracket, bracket[1:-1])
                             for utterance in spoken_utterances]
    return [
        result(REQUIRED[0], spoken_ok, "Han, placeholder, and explicit series-title screen only"),
        result(REQUIRED[1], quote_ok, boundary_reason if source_bound else
               "English Source Package or unit identity differs"),
        result(REQUIRED[2], bool(number_name_ok),
               "Only explicit digits and reviewed name forms checked; meaning needs Sol and human review"
               + (f"; missing digits: {lost_digits}" if lost_digits else "")
               + (f"; missing names: {missing_names}" if missing_names else "")),
        result(REQUIRED[3], not has_unsafe_speech_markup(spoken_utterances),
               "Markup and utterance length screen only; audio remains Layer 3"),
    ]


def review_group(policy: dict, english_units: list[dict], group: dict) -> list[dict[str, str]]:
    return _review_group(policy, english_units, group, APPROVED_BOUNDARY_REVIEW)
