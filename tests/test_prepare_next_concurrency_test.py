"""Portable preparation checks; model/fixture execution is explicitly mocked."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

from scripts.experiments import prepare_next_concurrency_test as preparation
from tests import test_codex_layer2_diagnostic as chain


def test_register_rules_and_prompt_identity_are_locale_specific_before_freeze(tmp_path):
    helper = chain.DiagnosticChainTests()
    helper.setUp()
    try:
        sample = tmp_path / 'sample'; sample.mkdir()
        source = copy.deepcopy(helper.source)
        anchor = {'sourceUnits': [{'sourceUnitId': unit, 'english': 'Spoken source words ' * 12,
                                  'sourceSentenceId': 'sentence-' + str(index)}
                                 for index, unit in enumerate(('0-u066', '0-u067', '0-u068'))]}
        plan = [{'translationGroupId': 'g018', 'sourceUnitIds': ['0-u066', '0-u067', '0-u068']}]
        for name, value in [('source.json', source), ('anchor.json', anchor), ('group-plan.json', plan)]:
            (sample / name).write_text(json.dumps(value))
        baseline = tmp_path / 'baseline.json'; baseline.write_text(json.dumps(helper.policy))
        frozen = {}
        def capture(source, anchor, policy, plan, plugin, out, **kwargs):
            frozen[policy['targetLocale']] = copy.deepcopy(policy)
        with patch.object(preparation.quotes, 'freeze_quote_plugin', side_effect=lambda _s, _a, _p, policy, _b, _o: policy), \
             patch.object(preparation.diagnostic, 'freeze_fixture', side_effect=capture), \
             patch.object(preparation.diagnostic, 'load_fixture'):
            preparation.prepare(sample, baseline, helper.root / 'prepared', 'a' * 40)
        assert set(frozen) == {'zh-Hans', 'ko', 'es'}
        for locale, language, register in [('zh-Hans', 'Simplified Chinese', 'natural_spoken_simplified_chinese'),
                                           ('ko', 'Korean', 'natural_spoken_korean'),
                                           ('es', 'Spanish', 'natural_spoken_spanish')]:
            policy = frozen[locale]
            assert policy['languageReview']['registerRules'][0].startswith('Natural spoken ' + language + ';')
            assert policy['formatting']['speechRegister'] == register
            assert policy['componentSha256']['languageReview'] == preparation.policies.canonical_sha256(policy['languageReview'])
            assert locale in policy['translator']['promptVersion'] and locale in policy['reviewer']['promptVersion']
            assert all(row['reviewStatus'] == 'pending' for row in policy['terminology']['properNames'])
        assert 'Simplified Chinese' not in frozen['ko']['languageReview']['registerRules'][0]
        assert 'Simplified Chinese' not in frozen['es']['languageReview']['registerRules'][0]
        assert json.loads(baseline.read_text()) == helper.policy
    finally:
        helper.doCleanups()
