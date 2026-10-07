"""Small hand-written zh-Hans/ko/es sermon fixtures for machine QC tests."""
from __future__ import annotations

import math

from scripts import target_audio_auto_qc as audio_qc
from scripts.target_audio_predicted_schedule import speech_units

ENGLISH = [
    "Turn with me to Revelation 3:4, where Jesus speaks to the church in Sardis.",
    "He says there are a few people who have not soiled their clothes.",
    "For forty-four years she prayed for her son every single morning.",
    "Grace is not something we earn; it is a gift we receive.",
    "Some of you came here today carrying a heavy burden.",
    "Jesus does not leave us alone in our failures.",
    "In chapter two, verse four, he warns them that they have abandoned their first love.",
    "I want you to remember three things as we go home today.",
    "The church in Sardis had a reputation for being alive, but it was dead.",
    "We were made to walk with God, not to perform for him.",
    "Two thousand years later, these words still speak to us.",
    "Let us pray together and ask him to wake us up.",
    "She had twelve sons and forty daughters.",
]
TARGET = {
    "ko": [
        "요한계시록 3장 4절을 함께 보시겠습니다. 예수님께서 사데 교회에 말씀하십니다.",
        "그는 옷을 더럽히지 않은 사람이 몇 명 있다고 말합니다.",
        "그녀는 마흔네 해 동안 매일 아침 아들을 위해 기도했습니다.",
        "은혜는 우리가 얻어내는 것이 아니라 받는 선물입니다.",
        "오늘 여러분 중 어떤 분들은 무거운 짐을 지고 이 자리에 오셨습니다.",
        "예수님은 우리가 실패할 때 우리를 홀로 두지 않으십니다.",
        "2장 4절에서 그는 그들이 처음 사랑을 버렸다고 경고합니다.",
        "오늘 집에 돌아가실 때 세 가지를 기억하시기 바랍니다.",
        "사데 교회는 살아 있다는 평판이 있었지만 실제로는 죽어 있었습니다.",
        "우리는 하나님 앞에서 연기하기 위해서가 아니라 하나님과 동행하도록 지음 받았습니다.",
        "이천 년이 지난 지금도 이 말씀은 우리에게 말하고 있습니다.",
        "함께 기도하며 우리를 깨워 달라고 구합시다.",
        "그녀에게는 아들 열두 명과 딸 마흔 명이 있었습니다.",
    ],
    "es": [
        "Acompáñenme a Apocalipsis 3:4, donde Jesús habla a la iglesia de Sardis.",
        "Él dice que hay unas pocas personas que no han manchado sus vestiduras.",
        "Durante cuarenta y cuatro años ella oró por su hijo cada mañana.",
        "La gracia no es algo que ganamos; es un regalo que recibimos.",
        "Algunos de ustedes vinieron hoy cargando un peso muy grande.",
        "Jesús no nos deja solos en nuestros fracasos.",
        "En el capítulo dos, versículo cuatro, les advierte que han abandonado su primer amor.",
        "Quiero que recuerden tres cosas al volver hoy a casa.",
        "La iglesia de Sardis tenía fama de estar viva, pero estaba muerta.",
        "Fuimos creados para caminar con Dios, no para actuar delante de él.",
        "Dos mil años después, estas palabras todavía nos hablan.",
        "Oremos juntos y pidámosle que nos despierte.",
        "Ella tenía doce hijos y cuarenta hijas.",
    ],
    "zh-Hans": [
        "请和我一起翻到启示录3章4节，耶稣在这里对撒狄的教会说话。",
        "他说有几个人没有玷污自己的衣服。",
        "四十四年来，她每天早上都为儿子祷告。",
        "恩典不是我们赚来的，而是我们领受的礼物。",
        "今天在座有些人背着沉重的担子来到这里。",
        "耶稣不会在我们失败的时候丢下我们。",
        "在第二章第四节，他警告他们已经离弃了起初的爱。",
        "今天回家的时候，我希望你们记住三件事。",
        "撒狄的教会有活着的名声，其实却是死的。",
        "我们被造是为了与神同行，而不是在祂面前表演。",
        "两千年后，这些话仍然在对我们说话。",
        "让我们一起祷告，求祂唤醒我们。",
        "她有十二个儿子和四十个女儿。",
    ],
}
NAMES = {"ko": {"Jesus": "예수", "Sardis": "사데"},
         "es": {"Jesus": "Jesús", "Sardis": "Sardis"},
         "zh-Hans": {"Jesus": "耶稣", "Sardis": "撒狄"}}


def policy(locale: str, required: list[str] | None = None) -> dict:
    value = {"targetLocale": locale,
             "terminology": {"seriesNames": [], "properNames": [
                 {"source": source, "target": target, "reviewStatus": "project_established"}
                 for source, target in NAMES[locale].items()]}}
    if required is not None:
        value["languageReview"] = {"requiredChecks": required}
    return value


def groups(locale: str) -> list[dict]:
    return [{"groupId": f"g{index:03d}", "english": english, "targetText": target}
            for index, (english, target) in enumerate(zip(ENGLISH, TARGET[locale]), start=1)]


def speech_wav(seconds: float, rate: int = 8000) -> bytes:
    """Syllable-like 220 Hz bursts with short gaps, no internal pause > 0.2 s."""
    samples = []
    for index in range(int(seconds * rate)):
        t = index / rate
        envelope = 0.6 if (t % 0.25) < 0.2 else 0.0
        samples.append(envelope * math.sin(2 * math.pi * 220 * t))
    return audio_qc.encode_pcm16(samples, rate)


SEMANTIC_IDENTITY = {"backend": "fake-transport", "model": "fake-judge",
                     "modelRevision": "r1", "cacheNamespace": "qc-fixtures-v1",
                     "settings": {"reasoningEffort": "medium", "temperature": 0}}
PRIMARY_ASR = "small-asr"
SECONDARY_ASR = "large-asr"
ASR_SETTINGS = {PRIMARY_ASR: {"backend": "fake-asr", "language": "auto", "scoring": "token-ratio-v1"},
                SECONDARY_ASR: {"backend": "fake-asr-api", "language": "auto", "scoring": "token-ratio-v1"}}


def units(locale: str, seconds_per_unit: float = 0.17) -> list[dict]:
    rows = []
    for group in groups(locale):
        seconds = 0.2 + seconds_per_unit * speech_units(group["targetText"], locale)
        wav = speech_wav(seconds)
        rows.append({"groupId": group["groupId"], "text": group["targetText"],
                     "sourceSeconds": max(2.0, seconds * 0.9), "wav": wav,
                     "asr": {"primary": audio_qc.asr_opinion(group["targetText"], audio=wav, text=group["targetText"],
                                                             locale=locale, model=PRIMARY_ASR,
                                                             settings=ASR_SETTINGS[PRIMARY_ASR])}})
    return rows


def misheard(text: str) -> str:
    """A transcript that keeps only the first third of ``text``: well under the ASR threshold."""
    return text[:max(1, len(text) // 3)]


class FakeTts:
    """Fake TTS transport: renders distinct audio for each text and remembers what it said."""

    def __init__(self):
        self.said = {}

    def __call__(self, text, locale):
        seconds = 0.2 + 0.17 * speech_units(text, locale) + 0.001 * (len(self.said) + 1)
        wav = speech_wav(seconds)
        self.said[wav] = text
        return wav


class FakeAsr:
    """Fake ASR transport: hears the text only when the audio is this text's own clean render,
    and hears exactly what ``tts`` said in audio it rendered."""

    def __init__(self, locale: str, *, always_hears_expected_text: bool = False, tts: FakeTts | None = None):
        self.own = {row["text"]: row["wav"] for row in units(locale)}
        self.always = always_hears_expected_text  # A broken integration that echoes the expected text.
        self.tts = tts
        self.calls = []

    def __call__(self, role, wav, text, locale):
        self.calls.append(role)
        if self.always:
            heard = text
        elif self.tts is not None and wav in self.tts.said:
            heard = self.tts.said[wav]
        else:
            heard = text if self.own.get(text) == wav else misheard(text)
        model = PRIMARY_ASR if role == "primary" else SECONDARY_ASR
        return audio_qc.asr_opinion(heard, audio=wav, text=text, locale=locale, model=model,
                                    settings=ASR_SETTINGS[model])


class PerfectSemanticJudge:
    """Fake transport: back-translation recovers the English only for clean text."""

    def __init__(self, locale: str):
        self.clean = dict(zip(TARGET[locale], ENGLISH))
        self.calls = []

    def __call__(self, role, system, user, schema):
        self.calls.append(role)
        if role == "back_translator":
            return {"english": self.clean.get(user, "A different passage.")}
        import json
        pair = json.loads(user)
        if pair["ORIGINAL"] == pair["BACK-TRANSLATION"]:
            return {"status": "pass", "issues": []}
        return {"status": "fail", "issues": [{"kind": "meaning_shift", "severity": "major",
                                              "english": pair["ORIGINAL"],
                                              "backTranslation": pair["BACK-TRANSLATION"]}]}
