"""Source-bound deterministic screens for Resi media 15030286.

The frozen source split ``$1.5 million`` across two adjacent units.  Layer 2
must render the amount exactly once: the first unit carries the complete
amount and the second continues with the external firm.  The Spanish source
also names the official ``Seek the Good`` campaign in English; those exact
bound units may preserve the official title while all surrounding prose still
passes the ordinary untranslated-English screen. Official title evidence:
https://www.marinerschurch.org/seekthegood/

Version 2 adds the operator-approved corrections from the 2026-10-18 full
read of all three locales (decision bound to
``claude-review-20261018/corrections.md``; Jony approved the list in chat).
Each rule is bound to one frozen unit and its exact English: it names the
defect it rejects and the wording the operator approved, so a repair gets a
concrete instruction while the translator and the independent reviewer still
produce and judge the text.  A rule never edits text and never approves it.
"""
from __future__ import annotations

import re

try:
    from scripts.language_review_plugins.auto_qc_text_common import (
        REQUIRED, added_number_problems, number_problems, result,
        review_auto_group, untranslated_problems,
    )
except ImportError:
    from language_review_plugins.auto_qc_text_common import (
        REQUIRED, added_number_problems, number_problems, result,
        review_auto_group, untranslated_problems,
    )


SOURCE_SHA256 = "137fed8486da0ec4ea22258035a230f30172be43a016faa4c382b410f830e3a9"
# A clip states, in the free-text statement its policy receipt carries, which week it was cut from;
# only a line with this prefix may compare against another English package. See declared_clip_scope.
CLIP_SCOPE_PREFIX = "clip-scope: same-source-clip-v1 "
SOURCE_ID = "resi-weekend-live-15030286-351f-4afb-ba9d-96fbe127032b-20261017-1730"
AMOUNT_LEAD = ("chunk-0000-u024", "And in fact, reports said that Calendly, they spent $1.")
AMOUNT_TAIL = ("chunk-0000-u025", "5 million on an external firm to design that logo.")
SEEK_THE_GOOD = {
    "chunk-0007-u015": "The bar is low, which, by the way, this is another reason why I love the Seek the Good season.",
    "chunk-0007-u017": "So I want to invite you, all of us across all of our congregations, to engage with Seek the Good.",
}


def _amount_present(text: str, locale: str) -> bool:
    patterns = {
        "es": r"(?:\$\s*)?\d|\b(?:un|uno|cinco)\b.{0,20}\bmill[oó]n(?:es)?\b|\bmill[oó]n(?:es)?\b|\bd[oó]lares?\b",
        "ko": r"\d|(?:백오십|오백|일점오)\s*만|달러",
        "zh-Hans": r"\d|[一二两三四五六七八九十百千]+\s*[万萬]|[点點][五5]|百万|美元",
    }
    return re.search(patterns[locale], text, re.I) is not None


def _amount_problems(locale: str, unit_id: str, english: str, target: str) -> list[str] | None:
    if (unit_id, english) == AMOUNT_LEAD:
        expected = "They spent 1.5 million dollars."
        return number_problems(expected, target, locale) + added_number_problems(expected, target, locale)
    if (unit_id, english) == AMOUNT_TAIL:
        return (["$1.5 million must be rendered once in the preceding bound unit, not repeated here"]
                if _amount_present(target, locale) else [])
    return None


# English words the speaker says that are titles or initials, not untranslated prose.
SOURCE_BOUND_TITLES = {
    "chunk-0007-u015": ("Seek the Good",),
    "chunk-0007-u017": ("Seek the Good",),
    "chunk-0009-u002": ("J.R.R.", "J. R. R."),
}
# "one" that is a pronoun or "one more", not a quantity the target must say.
NONNUMERIC_ONE = {
    ("zh-Hans", "chunk-0000-u026"): "And since there's always time for one more pun, we can agree that they flushed that money right down the toilet.",
}

APPROVAL = "operator-approved correction (Jony, 2026-10-18, claude-review-20261018)"

# (locale, unit) -> (exact English, checkId, [(must_match, regex)], approved wording)
CORRECTIONS: dict[tuple[str, str], tuple[str, str, list[tuple[bool, str]], str]] = {}


def _rule(locale, unit, english, check, rules, approved):
    CORRECTIONS[(locale, unit)] = (english, check, rules, approved)


_ES_TU = "Use the informal tú/ustedes register the rest of this sermon uses; singular usted is not allowed"
for unit, english, approved in (
    ("chunk-0002-u004", "You and I are invited to be sent out into the world, to be missional, to represent Jesus to our world.",
     "Tú y yo estamos invitados a ser enviados al mundo, a vivir en misión, a representar a Jesús ante nuestro mundo."),
    ("chunk-0002-u006", "The world may reject our message, but you and I are invited to go and live on mission.",
     "Puede que el mundo rechace nuestro mensaje, pero tú y yo estamos invitados a ir y vivir en misión."),
    ("chunk-0004-u004", "And you and I would agree there is no news.",
     "Y tú y yo estaríamos de acuerdo en que no hay noticias."),
    ("chunk-0005-u012", "Because the same God who rescued us on mission is the same God who is inviting you and I to be on mission.",
     "Porque el mismo Dios que nos rescató en la misión es el mismo Dios que nos está invitando a ti y a mí a participar en la misión."),
    ("chunk-0005-u025", "When you go eat at an amazing restaurant, afterwards,",
     "Cuando vas a comer a un restaurante increíble, después,"),
    ("chunk-0007-u022", "You can be a faithful witness and still be opposed.",
     "Puedes ser un testigo fiel y aun así enfrentar oposición."),
    ("chunk-0009-u011", "Which means that you and I right now, we are invited to live in tension.",
     "Lo que significa que tú y yo, ahora mismo, estamos invitados a vivir en tensión."),
):
    _rule("es", unit, english, "register", [(False, r"\b[Uu]sted\b")], approved)
_rule("es", "chunk-0008-u031",
      "Then you go to the restroom for a bit and you come back to the movie and the movie is still, it's still this.",
      "register", [(False, r"\b[Uu]sted\b|\bLuego va\b|\bvuelve a la pel[ií]cula"), (True, r"\bvas\b")],
      "Luego vas al baño un momento y vuelves a la película, y la película sigue, sigue con lo mismo.")
_rule("es", "chunk-0007-u034", "Great.", "tts_segmentation",
      [(False, r"\bbien\b|\bgenial\b|\bexcelente\b"), (True, r"\b[Gg]ran\b")],
      "Un gran… (the cut-off start of \"Great fear fell\" in the next unit, not praise)")
_rule("es", "chunk-0009-u004",
      "He said, I am a Christian so that I do not expect history to be anything but a long defeat,",
      "tts_segmentation", [(False, r"»")],
      "Él dijo: «Soy cristiano, así que no espero que la historia sea otra cosa que una larga derrota, (the quotation continues into the next unit; do not close it here)")
_rule("es", "chunk-0009-u005", "though it contains some samples or glimpses of final victory.",
      "tts_segmentation", [(True, r"»\s*\.?\s*$"), (False, r"«")],
      "aunque contiene algunas muestras o destellos de la victoria final». (this unit ends the Tolkien quotation)")

_KO_FRIEND = "this is the classmate speaking casually to the pastor; keep the casual 반말 of 「야, 친구야, 나한테 관심 가져 줘서 고마워」"
_rule("ko", "chunk-0004-u020", "Thank you.", "register",
      [(False, r"감사합니다|감사해요"), (True, r"고마워")],
      "“정말 고마워.” (the classmate continues his quote; not the pastor thanking the audience)")
_rule("ko", "chunk-0004-u021",
      "But I want you to know the stuff that you're sharing, it just never even crosses my mind.",
      "register", [(False, r"당신|습니다|(?:^|[\s“\"])(?:제|저는|저도|저를|제가)\b")],
      "“그런데 네가 이야기하는 그런 건 내 머릿속에 전혀 떠오르지도 않는다는 걸 알아줬으면 좋겠어.” (" + _KO_FRIEND + ")")
_rule("ko", "chunk-0004-u022",
      "Like, I just never, I wouldn't, I don't even know why anyone would think about this stuff.",
      "register", [(False, r"당신|습니다|(?:^|[\s“\"])(?:제|저는|저도|저를|제가)\b")],
      "“그러니까 난 이런 생각을 전혀 해 본 적도 없고, 할 것 같지도 않아. 누가 왜 이런 생각을 하는지조차 모르겠어.” (" + _KO_FRIEND + ")")
_KO_MEAL = "the speaker is quoting what you would say casually to a friend; keep the 반말 of 「야, 들어 봐. 내가 이 식당에서 밥을 먹었어」"
for unit, english, approved in (
    ("chunk-0005-u029", "It changed my life.", "“그 식당이 내 인생을 바꿨어.”"),
    ("chunk-0005-u031", "I'll pray for the meal.", "식사 기도는 내가 할게."),
    ("chunk-0005-u032", "You pay for the meal.", "밥값은 네가 내."),
    ("chunk-0005-u033", "Let's go together.", "같이 가자."),
):
    _rule("ko", unit, english, "register",
          [(False, r"습니다|세요|십시오|갑시다|(?:^|[\s“\"])(?:제|저는|제가)(?=\s|$)")], approved + " (" + _KO_MEAL + ")")
_rule("ko", "chunk-0007-u009",
      "And I like to remind him, Hey, hey, Isaiah, here's how you can worship Jesus on the basketball court, okay?",
      "proper_names", [(False, r"아이제아"), (True, r"이사야")],
      "Use 이사야 for the speaker's son Isaiah, as in the previous unit")
_rule("ko", "chunk-0007-u011",
      "and you don't drop curse words like everyone else on the basketball court, you will stand out like a sore thumb.",
      "register", [(False, r"니다")],
      "그리고 농구장에서 다른 사람들처럼 욕설을 내뱉지 않으면, 확연히 눈에 띌 거야. (still the father's casual words to his son)")
_rule("ko", "chunk-0010-u007",
      "And he invites you and I to be logos on the earth, representing Jesus to the world.",
      "proper_names", [(False, r"로고스"), (True, r"로고")],
      "그리고 그는 여러분과 제가 이 땅에서 작은 로고가 되어 세상에 예수를 드러내도록 초대합니다. (“logos” here is the plural of logo, the sermon's brand-logo image, not the Logos/Word)")
_rule("ko", "chunk-0005-u041",
      "These are the two olive trees and the two lampstands that stand before the Lord of the earth.",
      "proper_names", [(False, r"올리브"), (True, r"감람나무")],
      "Use 감람나무 for olive trees, as the rest of this sermon does")
_KO_JOHN = "John narrates in the first person with 나/내, as in the surrounding scripture units"
for unit, english, need in (
    ("chunk-0003-u013", "So I went to the angel and asked him to give me the little scroll.", r"나는|내가"),
    ("chunk-0003-u014", "He said to me, take and eat it.", r"내게|나에게"),
    ("chunk-0003-u016", "Then I took the little scroll from the angel's hand and ate it.", r"나는|내가"),
):
    _rule("ko", unit, english, "register",
          [(False, r"(?:^|\s)(?:저는|저도|제게|제가|저에게)"), (True, need)], _KO_JOHN)

_rule("zh-Hans", "chunk-0010-u007",
      "And he invites you and I to be logos on the earth, representing Jesus to the world.",
      "proper_names", [(False, r"“道”|成为道|逻各斯"), (True, r"标志")],
      "他也邀请你我在地上成为一个个小小的标志，在世人面前代表耶稣。（这里的 logos 是 logo 的复数，指讲道开头的品牌标志比喻，不是“道”）")
_rule("zh-Hans", "chunk-0009-u004",
      "He said, I am a Christian so that I do not expect history to be anything but a long defeat,",
      "tts_segmentation", [(False, r"”")],
      "他说：“我是一个基督徒，所以我对历史的预期，无非就是一场漫长的失败，（引语延续到下一单元，这里不要闭合引号）")
_rule("zh-Hans", "chunk-0009-u005", "though it contains some samples or glimpses of final victory.",
      "tts_segmentation", [(True, r"”\s*$"), (False, r"“")],
      "尽管在历史中，也能看到最终胜利的一些缩影，或瞥见最终胜利的片段。”（本单元结束托尔金的引语）")
_rule("zh-Hans", "chunk-0007-u015",
      "The bar is low, which, by the way, this is another reason why I love the Seek the Good season.",
      "proper_names", [(False, r"寻求良善"), (True, r"Seek the Good")],
      "门槛很低。顺便说一句，这也是我喜欢 Seek the Good 活动季的另一个原因。（活动名与下一单元一致，保留英文 Seek the Good）")
# Jony's earlier approved zh revision (text-zh-proposed-revision-v2, decision 2026-10-18T06:38).
_rule("zh-Hans", "chunk-0000-u010", "They went from their old logo, which looked like this, to their new one here.",
      "numbers", [(False, r"这一个|1个")], "他们把原来长这样的旧标志，换成了这里这个新标志。")
_rule("zh-Hans", "chunk-0000-u026",
      "And since there's always time for one more pun, we can agree that they flushed that money right down the toilet.",
      "numbers", [(False, r"1个|一个双关")],
      "而且，既然总有时间再开个双关玩笑，那大家都能认同：他们真是把那笔钱直接冲进马桶里了。")
_rule("zh-Hans", "chunk-0000-u040",
      "You know, a puzzle has many different pieces, but they're supposed to come together to show one beautiful picture.",
      "numbers", [(False, r"1幅")], "大家知道，一幅拼图有许多不同的拼块，但这些拼块是要拼在一起，呈现出一幅美丽的图画。")
_rule("zh-Hans", "chunk-0008-u003", "They went up to heaven in a cloud while their enemies watched them.",
      "tts_segmentation", [(False, r"一旁")], "他们乘着云升上了天，他们的仇敌看着他们。")


def _correction(locale: str, unit_id: str, english: str, target: str):
    rule = CORRECTIONS.get((locale, unit_id))
    if rule is None or rule[0] != english:
        return None
    _, check, rules, approved = rule
    problems = [("contains" if not must else "lacks") + f" /{pattern}/"
                for must, pattern in rules if bool(re.search(pattern, target)) != must]
    evidence = (f"{APPROVAL}: " + ("; ".join(problems) + f"; approved wording: {approved}"
                                    if problems else "pass"))
    return check, not problems, evidence


def declared_clip_scope(policy: dict) -> str | None:
    """The English package this policy may review, when it declares a clip of this same sermon.

    The week's receipt statement carries a tagged line written when the clip policy was frozen:
    ``clip-scope: same-source-clip-v1 parent=<week package> sourceId=<source id>``. A policy
    without that line keeps the exact week binding."""
    scope = (policy.get("sourceScope") or {}) if isinstance(policy, dict) else {}
    statement = ((scope.get("termApprovalReceipt") or {}).get("userStatement") or "")
    line = next((row for row in statement.splitlines() if row.startswith(CLIP_SCOPE_PREFIX)), None)
    if line is None:
        return None
    facts = dict(part.split("=", 1) for part in line[len(CLIP_SCOPE_PREFIX):].split() if "=" in part)
    if facts.get("parent") != SOURCE_SHA256 or facts.get("sourceId") != SOURCE_ID:
        raise ValueError("15030286 plugin clip scope belongs to another week")
    expected = scope.get("englishSourcePackageJsonSha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("15030286 plugin clip scope has no English package binding")
    return expected


def review_15030286_group(policy: dict, english_units: list[dict], group: dict, *,
                          locale: str, forbidden_register: str) -> list[dict[str, str]]:
    # The frozen week protects the exact English package its corrections were approved against.
    # A clip cut from that sermon has its own package, so the comparison is made against the
    # clip's declared scope: clipping keeps every unit's own English and the same source id, so
    # a unit-matched rule can still fire and an unrelated package is still refused.
    expected = declared_clip_scope(policy) or SOURCE_SHA256
    if group.get("englishSourcePackageJsonSha256") != expected:
        raise ValueError("15030286 plugin source package differs")
    reviews = review_auto_group(
        policy, english_units, group, locale=locale, forbidden_register=forbidden_register)
    if len(english_units) != 1:
        return reviews
    unit_id, english = english_units[0]["sourceUnitId"], english_units[0]["english"]
    target = group["targetText"]
    amount = _amount_problems(locale, unit_id, english, target)
    if amount is not None:
        reviews = [
            result("numbers", not amount,
                   "Source-bound $1.5 million spans u024/u025 and must be rendered exactly once"
                   + ("; " + "; ".join(amount) if amount else "; pass"))
            if row["checkId"] == "numbers" else row for row in reviews]
    titles = SOURCE_BOUND_TITLES.get(unit_id, ())
    if titles:
        masked_english, masked_target = english, target
        for title in titles:
            masked_english = masked_english.replace(title, "")
            masked_target = masked_target.replace(title, "")
        problems = []
        if "Seek the Good" in titles and locale == "es" and "Seek the Good" not in target:
            problems.append("official title Seek the Good missing")
        problems += untranslated_problems(masked_english, masked_target, locale)
        reviews = [
            result("untranslated_source", not problems,
                   "Source-bound title or initials may stay in English; surrounding prose checked"
                   + ("; " + "; ".join(problems) if problems else "; pass"))
            if row["checkId"] == "untranslated_source" else row for row in reviews]
    if NONNUMERIC_ONE.get((locale, unit_id)) == english:
        problems = [p for p in number_problems(english, target, locale) if not p.startswith("missing number 1")]
        problems += added_number_problems(english, target, locale)
        reviews = [
            result("numbers", not problems,
                   "Source-bound: \"one more\" is not a quantity here"
                   + ("; " + "; ".join(problems) if problems else "; pass"))
            if row["checkId"] == "numbers" else row for row in reviews]
    correction = _correction(locale, unit_id, english, target)
    if correction is not None:
        check, ok, evidence = correction
        reviews = [(row if ok and row["status"] != "pass" else
                    result(check, ok and row["status"] == "pass",
                           (evidence + ("" if row["status"] == "pass" else "; also " + row["evidence"]))
                           if not ok else row["evidence"] + "; " + evidence))
                   if row["checkId"] == check else row for row in reviews]
    return reviews
