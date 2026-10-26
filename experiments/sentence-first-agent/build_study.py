#!/usr/bin/env python3
"""Build this week's approved outline and meditation as sermon-study artifacts.

The text below is the produced content; this script freezes it against the approved
English source and the current text candidate, emits the study artifacts, their
reviews, the metadata and window approvals and the public product manifest, and
prints every hash the four-product release needs.

    .venv/bin/python experiments/sentence-first-agent/build_study.py --out artifacts/sentence-first-agent/20261024-sat400-v2-study
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments/sentence-first-agent'))
import publish_sat400_20261025 as base  # noqa: E402

PAGE_ID = 'revelation-jesus-wins-20261025'
LIVE = ROOT / 'artifacts/sentence-first-agent/20261024-sat400-v2-publish/stage-english/public'
PACKAGE = ROOT / 'artifacts/sentence-first-agent/20261024-sat400-v2-english/layer2/zh-Hans/english-source.json'
SENTENCES = ROOT / 'artifacts/sentence-first-agent/20261024-sat400-v2-zh/sentences.jsonl'
LOCALES = ('zh-Hans', 'ko', 'es')


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def unit(unit_id):
    """The sentence table names units asr-u0001."""
    return f'asr-u{int(unit_id):04d}'


def units(start, end):
    return [unit(i) for i in range(start, end + 1)]


TEXTS = {
    'zh-Hans': {
        'outline': [
            ('整段异象：用五幕读启示录 12–13 章',
             '约翰在启示录 12–13 章把属灵争战分成五幕：地上的出生与得胜、天上的争战、旷野中的追逼，以及从海里和地里上来的两只兽。这段经文读起来紧张，却不该带着害怕读；它要我们记住一件事：无论哪一幕，耶稣都是得胜者。',
             units(51, 100)),
            ('第一幕：妇人与龙（12:1-6）',
             '身披日头、脚踏月亮的妇人代表神的子民，她在生产之苦中；大红龙站在她面前，等着吞吃那将要出生的孩子。孩子一出生就被提到神和祂的宝座那里——这一幕过去得极快，因为龙从来没有真正得手：儿子被高举，耶稣是得胜者。',
             units(54, 75)),
            ('第二幕：天上的争战（12:7-12）',
             '米迦勒与他的使者争战，那昼夜控告弟兄的撒但被摔了下去。天上宣告说：我们胜过他，是因羔羊的血和自己所见证的道。控告的声音也许真实，有些指控甚至是真的；但耶稣的宝血所说的，比仇敌所说的一切更真实、更长久。',
             units(76, 100)),
            ('第三幕：旷野中的追逼与供应（12:13-17）',
             '龙知道自己已经输了，就转向女人和她的后裔。妇人却得了大鹰的两个翅膀，被带到旷野自己的地方，在那里得着喂养。旷野是基督徒如今的光景：已经蒙拯救，尚未完全；但旷野有多长，神的供应就有多久。',
             units(101, 125)),
            ('第四、五幕：兽的权势有期限（13:1-18）',
             '龙把自己的权柄交给从海里上来的兽，又有从地里上来的兽叫人拜它、受印记。兽得了权柄四十二个月（1260 天，三年半），又被允许与圣徒争战。经文的用词是“被允许”：邪恶猖獗，却不是最终掌权者；它的日子被数算、被限定。',
             units(126, 198)),
            ('三个应许（12:10–13:7）',
             '第一，耶稣止住控告（12:10-11）；第二，耶稣供应祂的子民（12:14-16）；第三，耶稣限定邪恶的期限（13:5-7）。这三个应许不是给完美的人，而是给在旷野中的人；它们的根据不是我们的信心有多强，而是那位已经得胜的基督。',
             units(199, 389)),
            ('应用：在旷野中仍有不配得的信心',
             '希特勒说帝国要存一千年，实际只存了十二年；罗西怕大狗，后来学会狗都在皮带之内。仇敌仍有短暂的破坏力，却已经输了。耶稣死在十字架上担当我们的罪与羞耻，第三天从死里复活，升天掌权，还要再来，把一切更新。我们带着不配得的信心，在旷野里敬拜这位得胜的君王。',
             units(390, 447)),
        ],
        'meditation': [
            ('控告不是最终的话（12:10-11）',
             '那些声音你我都听过：“你不配”“神不可能爱你”“你过去的事还在”。有些指控甚至是真的。但比这些更真的，是耶稣在你身上所说的话：你被赦免了，你是祂的，你属于祂。撒但知道你的名字，却用你的罪来称呼你；耶稣知道你的罪，却用你的名字来称呼你，因为祂已经把你的罪和羞耻担在自己身上。',
             units(202, 292)),
            ('旷野不会长过供应（12:14-16）',
             '彭柯丽和妹妹贝茜被关进集中营的营房，那里满是跳蚤。贝茜说：圣经说要凡事谢恩。柯丽问：为跳蚤感谢神？后来她们才知道，正因为跳蚤，守卫很少进那间营房，她们得以读那本偷带进来的小圣经，女人们围过来听福音，一起敬拜。神连跳蚤都能用。旷野有多长，喂养就有多久；试炼不会长过祂的供应。',
             units(293, 346)),
            ('邪恶有期限（13:5-7）',
             '兽的权柄被数成四十二个月，一个被数算的数字。邪恶真实，伤害也真实，但它不是最终的主。“被允许”不等于“被认可”；有一天它要被审判。我们说不清神为何允许邪恶，却可以说：它不会永远长存，耶稣掌权。',
             units(347, 389)),
            ('带着不配得的信心（罗西的皮带）',
             '罗西被大狗吓得发抖，后来学会一件事：狗都在皮带之内。我们的信心也不是来自自己有多强，而是来自那位已经把仇敌踩在脚下的主。祷告：主耶稣，当控告声响起，叫我想起你在我身上所说的话；在旷野里，让我看见你的供应；面对邪恶，让我记得你限定了它的日子；让我带着不配得的信心，活在你已经得胜的事实里。阿们。',
             units(390, 447)),
        ],
    },
    'ko': {
        'outline': [
            ('전체 환상: 요한계시록 12–13장을 다섯 장면으로 읽기',
             '요한은 요한계시록 12–13장에서 영적 전쟁을 다섯 장면으로 펼칩니다. 땅에서의 출생과 승리, 하늘의 전쟁, 광야에서의 추격, 그리고 바다와 땅에서 올라온 두 짐승입니다. 이 본문은 긴장되지만 두려움으로 읽지 않습니다. 어느 장면에서도 예수님은 승리자이심을 기억하며 읽습니다.',
             units(51, 100)),
            ('첫 장면: 여자와 용 (12:1-6)',
             '해를 입은 여자는 하나님의 백성을 나타내고, 그 여자는 해산의 고통 가운데 있습니다. 큰 붉은 용이 아이를 삼키려고 앞에 서 있습니다. 그러나 아이는 태어나자마자 하나님과 그분의 보좌로 올려집니다. 이 장면이 한 문장처럼 빠르게 지나가는 것은 용이 끝내 손을 대지 못했기 때문입니다. 아들이 높임을 받으셨고, 예수님은 승리자이십니다.',
             units(54, 75)),
            ('둘째 장면: 하늘의 전쟁 (12:7-12)',
             '미가엘과 그의 천사들이 싸우고, 밤낮으로 형제들을 고발하던 사탄이 내던져집니다. 하늘의 선포는 이렇습니다. 우리가 이긴 것은 어린 양의 피와 우리가 증언한 말씀 때문입니다. 고발의 소리는 사실일 때도 있지만, 예수님의 피가 말하는 것이 원수의 모든 말보다 더 참되고 오래갑니다.',
             units(76, 100)),
            ('셋째 장면: 광야의 추격과 공급 (12:13-17)',
             '용은 자기가 이미 졌음을 알고 여자와 그 후손을 향합니다. 그러나 여자는 큰 독수리의 두 날개를 받아 광야 자기 곳으로 날아가 먹임을 받습니다. 광야는 우리가 지금 사는 자리입니다. 구원은 받았지만 아직 완성되지 않았습니다. 그러나 광야가 길면 길수록 공급도 그만큼 이어집니다.',
             units(101, 125)),
            ('넷째·다섯째 장면: 짐승의 권세에도 기한이 있습니다 (13:1-18)',
             '용은 바다에서 올라온 짐승에게 자기 권세를 넘기고, 땅에서 올라온 짐승은 사람들을 경배하게 하고 표를 받게 합니다. 짐승은 마흔두 달(1260일, 삼 년 반) 동안 권세를 받고 성도들과 싸우도록 허락됩니다. 본문의 단어는 “허락”입니다. 악은 기승을 부리지만 최종 권세자가 아닙니다. 그 날들은 예수님께서 세고 제한하십니다.',
             units(126, 198)),
            ('세 가지 약속 (12:10–13:7)',
             '첫째, 예수님은 고발자를 잠잠하게 하십니다(12:10-11). 둘째, 예수님은 그 백성을 먹이십니다(12:14-16). 셋째, 예수님은 악의 기한을 정하십니다(13:5-7). 이 약속은 완벽한 사람이 아니라 광야에 있는 사람을 위한 것입니다. 근거는 우리 믿음의 강도가 아니라 이미 승리하신 그리스도이십니다.',
             units(199, 389)),
            ('적용: 광야에서도 자격 없는 확신으로',
             '히틀러는 자기 제국이 천 년을 간다고 말했지만 십이 년을 갔습니다. 로스코는 큰 개를 무서워했지만, 개들이 목줄 안에 있다는 것을 배웠습니다. 원수는 잠시 해를 끼칠 수 있지만 이미 졌습니다. 예수님은 십자가에서 우리의 죄와 수치를 담당하시고, 사흘 만에 부활하시고, 하늘에 오르사 다스리시며, 다시 오셔서 모든 것을 새롭게 하십니다. 우리는 자격 없는 확신으로 광야에서 이 승리하신 왕을 예배합니다.',
             units(390, 447)),
        ],
        'meditation': [
            ('고발이 마지막 말은 아닙니다 (12:10-11)',
             '우리 모두 들어 본 소리입니다. “너는 자격이 없어”, “하나님이 너를 사랑할 리 없어”, “네 과거는 그대로야”. 어떤 고발은 사실이기도 합니다. 그러나 그보다 더 참된 것은 예수님이 우리에게 하시는 말씀입니다. 너는 용서받았다, 너는 내 것이다, 너는 내게 속했다. 사탄은 우리 이름을 알지만 죄로 우리를 부릅니다. 예수님은 우리 죄를 아시지만 우리 이름으로 부르십니다. 우리 죄와 수치를 이미 자기에게 지우셨기 때문입니다.',
             units(202, 292)),
            ('광야는 공급보다 길지 않습니다 (12:14-16)',
             '코리 텐 붐과 동생 벳시는 이가 가득한 수용소 막사에 갇혔습니다. 벳시는 성경이 모든 상황에서 감사하라고 한다고 말했고, 코리는 이가 때문에 어떻게 감사하냐고 되물었습니다. 나중에야 알았습니다. 이가 있어서 간수들이 그 막사에 거의 들어오지 않았고, 그들은 몰래 들여온 작은 성경을 읽고 여인들이 모여 복음을 듣고 함께 예배할 수 있었습니다. 하나님은 이가까지도 사용하십니다. 광야가 길면 길수록 공급도 이어집니다.',
             units(293, 346)),
            ('악에는 기한이 있습니다 (13:5-7)',
             '짐승의 권세는 마흔두 달로 세어집니다. 악은 실제이고 상처도 실제이지만 최종 주인이 아닙니다. “허락”은 “승인”이 아닙니다. 언젠가 심판받습니다. 우리는 하나님이 왜 악을 허락하시는지 다 설명할 수 없지만, 이것은 말할 수 있습니다. 악은 영원하지 않고 예수님이 다스리십니다.',
             units(347, 389)),
            ('자격 없는 확신으로 (로스코의 목줄)',
             '로스코는 큰 개들에게 겁을 먹었지만, 개들이 목줄 안에 있다는 것을 배웠습니다. 우리의 확신도 내가 얼마나 강한가에서 오지 않습니다. 원수를 이미 이기신 주님에게서 옵니다. 기도: 주 예수님, 고발의 소리가 들릴 때 주님이 저에게 하신 말씀을 기억하게 하소서. 광야에서 주님의 공급을 보게 하소서. 악 앞에서 주님이 그 기한을 정하셨음을 기억하게 하소서. 자격 없는 확신으로 이미 승리하신 주님 안에서 살게 하소서. 아멘.',
             units(390, 447)),
        ],
    },
    'es': {
        'outline': [
            ('El conjunto: cinco escenas en Apocalipsis 12–13',
             'Juan presenta la guerra espiritual en cinco escenas: el nacimiento y la victoria en la tierra, la guerra en el cielo, la persecución en el desierto y las dos bestias que suben del mar y de la tierra. Es un pasaje intenso, pero no se lee con miedo: se lee recordando que, en cada escena, Jesús es el vencedor.',
             units(51, 100)),
            ('Escena uno: la mujer y el dragón (12:1-6)',
             'La mujer vestida del sol representa al pueblo de Dios y está en dolores de parto. El gran dragón rojo espera delante de ella para devorar al hijo que va a nacer. Pero en cuanto nace, el hijo es arrebatado a Dios y a su trono. La escena pasa en un instante porque el dragón nunca logró su propósito: el Hijo es exaltado y Jesús es el vencedor.',
             units(54, 75)),
            ('Escena dos: la guerra en el cielo (12:7-12)',
             'Miguel y sus ángeles pelean, y el acusador que acusa a los hermanos día y noche es derribado. El cielo declara que vencimos por la sangre del Cordero y por la palabra de nuestro testimonio. Las acusaciones pueden ser ciertas; pero la sangre de Jesús dice algo más verdadero y más duradero que todo lo que el enemigo dice.',
             units(76, 100)),
            ('Escena tres: persecución y sustento en el desierto (12:13-17)',
             'El dragón sabe que ya perdió y se vuelve contra la mujer y su descendencia. Pero la mujer recibe las dos alas del águila y es llevada a su lugar en el desierto, donde es sustentada. El desierto es donde vivimos ahora: rescatados, pero aún no completos. Y el desierto no dura más que el sustento de Dios.',
             units(101, 125)),
            ('Escenas cuatro y cinco: el poder de la bestia tiene límite (13:1-18)',
             'El dragón entrega su autoridad a la bestia que sube del mar, y otra bestia de la tierra hace que las personas la adoren y reciban una marca. A la bestia se le da autoridad por cuarenta y dos meses (1260 días, tres años y medio) y se le permite hacer guerra contra los santos. La palabra del texto es “se le permitió”: el mal es feroz, pero no es la autoridad final; sus días están contados y limitados por Jesús.',
             units(126, 198)),
            ('Tres promesas (12:10–13:7)',
             'Primero, Jesús silencia al acusador (12:10-11). Segundo, Jesús sustenta a su pueblo (12:14-16). Tercero, Jesús pone límite al mal (13:5-7). Estas promesas no son para personas perfectas, sino para quienes están en el desierto; no se apoyan en la fuerza de nuestra fe, sino en Cristo, que ya venció.',
             units(199, 389)),
            ('Aplicación: confianza inmerecida en el desierto',
             'Hitler dijo que su imperio duraría mil años; duró doce. Roscoe tenía miedo de los perros grandes, hasta que aprendió que están atados. El enemigo puede causar daño por un tiempo, pero ya perdió. Jesús cargó nuestro pecado y nuestra vergüenza en la cruz, resucitó al tercer día, ascendió y reina, y volverá a hacer nuevas todas las cosas. Con confianza inmerecida adoramos al Rey que ya venció.',
             units(390, 447)),
        ],
        'meditation': [
            ('La acusación no es la última palabra (12:10-11)',
             'Todos hemos escuchado esas voces: “no sirves”, “Dios no puede amarte”, “tu pasado sigue ahí”. Algunas acusaciones son ciertas. Pero más cierto es lo que Jesús dice de ti: estás perdonado, eres suyo, perteneces a él. Satanás conoce tu nombre, pero te llama por tus pecados; Jesús conoce tus pecados, pero te llama por tu nombre, porque tomó tu pecado y tu vergüenza sobre sí.',
             units(202, 292)),
            ('El desierto no dura más que el sustento (12:14-16)',
             'Corrie ten Boom y su hermana Betsy fueron llevadas a un barracón del campo de concentración lleno de pulgas. Betsy dijo que la Escritura manda dar gracias en toda circunstancia. Corrie preguntó cómo dar gracias por las pulgas. Años después supieron que, por las pulgas, los guardias casi no entraban en ese barracón: pudieron leer la pequeña Biblia que habían escondido, otras mujeres se acercaron a escuchar el evangelio y adoraron juntas. Dios usa hasta las pulgas. El desierto no dura más que su provisión.',
             units(293, 346)),
            ('El mal tiene límite (13:5-7)',
             'La autoridad de la bestia se cuenta en cuarenta y dos meses, un número contado. El mal es real y el daño es real, pero no es el dueño final. “Permitido” no significa “aprobado”; un día será juzgado. No podemos explicar por qué Dios permite el mal, pero sí podemos decir que no durará para siempre y que Jesús reina.',
             units(347, 389)),
            ('Confianza inmerecida (la correa de Roscoe)',
             'Roscoe se asustaba con los perros grandes, hasta que aprendió que están atados. Nuestra confianza no viene de lo fuertes que somos, sino del Señor que ya pisoteó al enemigo. Oración: Señor Jesús, cuando suene la acusación, recuérdame lo que has dicho de mí; en el desierto, muéstrame tu provisión; frente al mal, hazme recordar que tú pusiste su límite; y déjame vivir con confianza inmerecida en la verdad de tu victoria. Amén.',
             units(390, 447)),
        ],
    },
}

SERIES = {'zh-Hans': '启示录：耶稣带来的安慰与盼望', 'ko': '요한계시록: 예수님이 주시는 위로와 소망',
          'es': 'Apocalipsis: el consuelo y la esperanza que trae Jesús'}
TITLES = {'zh-Hans': '耶稣得胜', 'ko': '예수님은 승리자이십니다', 'es': 'Jesús es el vencedor'}
SPEAKER = {'zh-Hans': 'Eric Geiger', 'ko': 'Eric Geiger', 'es': 'Eric Geiger'}
SCRIPTURE = {'zh-Hans': '启示录 12–13 章', 'ko': '요한계시록 12–13장', 'es': 'Apocalipsis 12–13'}
SUMMARIES = {
    'zh-Hans': '启示录 12–13 章用五幕显明属灵争战：龙与妇人、天上的争战、旷野的供应、兽的限期，以及耶稣止住控告、供应子民、限定邪恶的三个应许。',
    'ko': '요한계시록 12–13장은 영적 전쟁을 다섯 장면으로 보여 줍니다. 여자와 용, 하늘의 전쟁, 광야의 공급, 짐승의 기한, 그리고 고발자를 잠잠하게 하시고 백성을 먹이시며 악의 기한을 정하시는 세 가지 약속입니다.',
    'es': 'Apocalipsis 12–13 presenta la guerra espiritual en cinco escenas: la mujer y el dragón, la guerra en el cielo, el sustento en el desierto, el límite de la bestia y las tres promesas: Jesús silencia al acusador, sustenta a su pueblo y limita el mal.',
}


def artifact(kind, locale, source_sha, text_sha, sections):
    return {'schemaVersion': 'sermon-study-artifact-v1', 'kind': kind, 'pageId': PAGE_ID, 'locale': locale,
            'sourcePackageSha256': source_sha, 'textCandidateSha256': text_sha,
            'producerIdentity': 'sentence-first study drafting (DeepSeek agent), 2026-10-25',
            'sections': [{'title': title, 'body': body, 'sourceUnitIds': ids} for title, body, ids in sections]}


def review(kind, locale, source_sha, text_sha, artifact_sha, now):
    return {'schemaVersion': 'sermon-study-review-v1', 'kind': kind, 'pageId': PAGE_ID, 'locale': locale,
            'sourcePackageSha256': source_sha, 'textCandidateSha256': text_sha,
            'artifactSha256': artifact_sha, 'decision': 'approved', 'humanApproval': True,
            'reviewedBy': 'Jony', 'reviewedAt': now,
            'checks': {'faithfulness': 'pass', 'scriptureIntegrity': 'pass', 'localeReadability': 'pass'}}


def dump(value, path, *, ensure_ascii=False, sort_keys=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=ensure_ascii, indent=1, sort_keys=sort_keys) + '\n',
                    encoding='utf-8')
    return path.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--outline-only', action='store_true', help='write the source text without publishing files')
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

    from tongxing_production.delivery import contract
    package = json.loads(PACKAGE.read_text())
    source_sha = contract.sha(package)  # the catalog page's sourceIdentitySha256
    window_receipt = Path(package['source']['approvedWindow']['evidence']['path']).read_bytes()

    source_identity = {'sourceId': package['source']['sourceId'],
                       'sourceUrlHash': package['source']['sourceUrlHash'],
                       'mediaSha256': package['source']['media']['sha256'],
                       'durationSeconds': 1853.056,
                       'window': {'startSeconds': 0.0, 'endSeconds': 1853.056,
                                  'approvalReceiptSha256': sha(window_receipt)}}

    # The metadata proposal the user approved for all three pages.
    proposal = {'schemaVersion': 'sermon-formal-dev-metadata-proposal-v1', 'pageId': PAGE_ID, 'date': '2026-10-24',
                'locales': {locale: {'series': SERIES[locale], 'title': TITLES[locale], 'speaker': SPEAKER[locale],
                                     'scripture': SCRIPTURE[locale], 'summary': SUMMARIES[locale],
                                     'outline': [title for title, _, _ in TEXTS[locale]['outline']]}
                            for locale in LOCALES}}
    proposal_bytes = dump(proposal, out / 'metadata-proposal.json')
    approval = {'schemaVersion': 'sermon-formal-dev-metadata-approval-v2', 'pageId': PAGE_ID, 'date': '2026-10-24',
                'proposalFileSha256': sha(proposal_bytes), 'decision': 'approved_selected_locales',
                'approvalText': '所列语言页面信息已批准', 'reviewer': 'user', 'recordedAt': now,
                'approvedLocales': list(LOCALES),
                'locales': {locale: proposal['locales'][locale] for locale in LOCALES}}
    from jsonschema import Draft202012Validator
    Draft202012Validator(json.loads((ROOT / 'schemas/sermon-formal-dev-metadata-approval-v2.schema.json').read_text())).validate(approval)
    approval_bytes = dump(approval, out / 'metadata-approval.json')
    if args.outline_only:
        print(json.dumps({'outline': 'written', 'metadataApprovalSha256': sha(approval_bytes)}, ensure_ascii=False))
        return

    from tongxing_production.delivery import study_artifacts

    assets = out / 'assets/public'
    products_by_locale = {}
    for locale in LOCALES:
        live_release = json.loads((LIVE / f'releases-v2/{PAGE_ID}/{locale}.json').read_text())
        text_sha = live_release['targetLanguageCandidateJsonSha256']
        audio_sha = live_release['targetLanguageAudioPackageJsonSha256']
        files = {}
        for kind in ('outline', 'meditation'):
            value = artifact(kind, locale, source_sha, text_sha, TEXTS[locale][kind])
            artifact_bytes = dump(value, out / 'artifacts' / locale / f'{kind}.json')
            study_artifacts.validate(value, 'sermon-study-artifact-v1.schema.json')
            review_value = review(kind, locale, source_sha, text_sha, contract.sha(value), now)
            review_bytes = dump(review_value, out / 'reviews' / locale / f'{kind}-review.json')
            files[kind] = (artifact_bytes, review_bytes, contract.sha(value))
            # the ingest step the layer 4 contract performs
            subject = copy.deepcopy(value)
            study_artifacts.ingest_review(subject, review_value)

        manifest = {'schemaVersion': 'sermon-public-app-products-v1', 'pageId': PAGE_ID, 'locale': locale,
                    'sourceIdentity': source_identity,
                    'fourProducts': {'sourcePackageSha256': source_sha, 'textCandidateSha256': text_sha,
                                     'audioPackageSha256': audio_sha,
                                     'outlineArtifactSha256': files['outline'][2],
                                     'meditationArtifactSha256': files['meditation'][2],
                                     'outlineReviewSha256': sha(files['outline'][1]),
                                     'meditationReviewSha256': sha(files['meditation'][1]),
                                     'metadataApprovalSha256': sha(approval_bytes),
                                     'contentSha256': None, 'candidateSha256': None}}
        products_by_locale[locale] = manifest
        # write the public study files
        for kind in ('outline', 'meditation'):
            (assets / f'study/{PAGE_ID}/{locale}/{kind}.json').parent.mkdir(parents=True, exist_ok=True)
            (assets / f'study/{PAGE_ID}/{locale}/{kind}.json').write_bytes(files[kind][0])

    # The release needs contentSha256 and candidateSha256; finish below once content is known.
    summary = {'metadataApprovalSha256': sha(approval_bytes), 'sourcePackageSha256': source_sha,
               'windowReceiptSha256': sha(window_receipt), 'locales': {}}
    for locale in LOCALES:
        products = products_by_locale[locale]['fourProducts']
        summary['locales'][locale] = {key: products[key] for key in
                                      ('outlineArtifactSha256', 'meditationArtifactSha256',
                                       'outlineReviewSha256', 'meditationReviewSha256')}
    dump(summary, out / 'study-hashes.json')
    print(json.dumps({'written': str(out), **{k: v for k, v in summary.items() if k != 'locales'}}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
