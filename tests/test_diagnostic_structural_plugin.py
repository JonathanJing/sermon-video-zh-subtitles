"""Real deterministic surface checks; only HUMAN review context is simulated."""
from copy import deepcopy
from pathlib import Path
import runpy
import unittest

from scripts.language_review_plugins import diagnostic_structural as plugin
from scripts import sermon_diagnostic_context as diagnostic


def context():
    return dict(schemaVersion=diagnostic.SCHEMA,runId='1'*64,runConfigSha256='2'*64,
        storeSha256='3'*64,sourceCanonicalSha256='4'*64,anchorCanonicalSha256='5'*64,
        simulationAuthorizationRef='6'*64,continuationCodeCommit='7'*40,
        humanAcceptance='pending',productionEligible=False)


def fixtures(locale='zh-Hans'):
    names={'zh-Hans':'葛艾瑞','ko':'에릭 가이거','es':'Eric Geiger'}
    texts={'zh-Hans':'葛艾瑞讲到12个人。','ko':'에릭 가이거는 12명에 대해 이야기했습니다.',
           'es':'Eric Geiger habló de 12 personas.'}
    policy={'schemaVersion':'sermon-target-language-policy-v3','targetLocale':locale,
        'sourceScope':{'englishSourcePackageJsonSha256':'4'*64,'anchorManifestSha256':'5'*64},
        'languageReview':{'pluginId':plugin.PLUGIN_ID,'requiredChecks':plugin.REQUIRED[:]},
        'terminology':{'seriesTableSha256':'8'*64,'seriesNames':[],
            'properNames':[{'source':'Eric Geiger','target':names[locale],'reviewStatus':'pending'}]},
        'scripture':{'editionId':None,'citationUseStatus':'pending','quoteCheckPolicy':'references_only',
                     'referenceStyle':'References only; no direct scripture quotations.'}}
    units=[{'sourceUnitId':'unit-1','english':'Eric Geiger talked about 12 people.'}]
    group={'translationGroupId':'group-1','sourceUnitIds':['unit-1'],'targetUtterances':[texts[locale]],
        'targetText':texts[locale],'englishSourcePackageJsonSha256':'4'*64}
    return policy,units,group


def statuses(policy, units, group, ctx=None):
    return {row['checkId']:row['status'] for row in
        plugin.review_group(policy,units,group,diagnostic_context=context() if ctx is None else ctx)}


def replace_text(group, text):
    group.update(targetText=text,targetUtterances=[text])


class DiagnosticStructuralTests(unittest.TestCase):
    def test_all_locales_pass_real_surfaces_without_modifying_pending_approvals(self):
        for locale in plugin.LOCALES:
            with self.subTest(locale=locale):
                policy,units,group=fixtures(locale);ctx=context()
                before=deepcopy((policy,units,group,ctx))
                rows=plugin.review_group(policy,units,group,diagnostic_context=ctx)
                self.assertEqual([row['checkId'] for row in rows],plugin.REQUIRED)
                self.assertTrue(all(row['status']=='pass' for row in rows))
                self.assertEqual((policy,units,group,ctx),before)
                self.assertEqual(policy['terminology']['properNames'][0]['reviewStatus'],'pending')
                self.assertEqual(policy['scripture']['citationUseStatus'],'pending')
                self.assertFalse(ctx['productionEligible'])
                self.assertTrue(all(set(row)=={'checkId','status','evidence'} for row in rows))
                term=next(row for row in rows if row['checkId']=='term_surface_preservation')
                self.assertIn('Simulated HUMAN',term['evidence'])
                self.assertIn('not semantic approval',term['evidence'])

    def test_diagnostic_context_is_mandatory_and_cannot_grant_production(self):
        args=fixtures()
        with self.assertRaises(TypeError): plugin.review_group(*args)
        for ctx in (None,{},dict(context(),humanAcceptance='approved'),dict(context(),productionEligible=True),
                    dict(context(),simulationAuthorizationRef='wrong')):
            with self.subTest(ctx=ctx),self.assertRaises(ValueError):
                plugin.review_group(*args,diagnostic_context=ctx)

    def test_source_anchor_and_exact_ordered_group_ids_bind_context(self):
        mutations=(lambda p,u,g:p['sourceScope'].update(englishSourcePackageJsonSha256='0'*64),
            lambda p,u,g:p['sourceScope'].update(anchorManifestSha256='0'*64),
            lambda p,u,g:g.update(englishSourcePackageJsonSha256='0'*64),
            lambda p,u,g:g.update(sourceUnitIds=['other']),
            lambda p,u,g:g.update(translationGroupId='../../group'),
            lambda p,u,g:u.append(deepcopy(u[0])))
        for mutate in mutations:
            args=fixtures();mutate(*args)
            with self.assertRaises(ValueError):statuses(*args)
        p,u,g=fixtures();u.append({'sourceUnitId':'unit-2','english':'A second unit.'})
        g['sourceUnitIds']=['unit-2','unit-1']
        with self.assertRaisesRegex(ValueError,'source_unit_binding'):statuses(p,u,g)

    def test_checks_plugin_identity_and_locale_are_fixed(self):
        for update in ({'pluginId':'production-plugin'}, {'requiredChecks':plugin.REQUIRED[:-1]},
                       {'requiredChecks':list(reversed(plugin.REQUIRED))}):
            p,u,g=fixtures();p['languageReview'].update(update)
            with self.assertRaises(ValueError):statuses(p,u,g)
        p,u,g=fixtures();p['targetLocale']='fr'
        with self.assertRaises(ValueError):statuses(p,u,g)

    def test_pending_terms_still_fail_when_actual_target_surface_is_missing_or_wrong(self):
        replacements={'zh-Hans':'另一位讲员讲到12个人。','ko':'다른 사람이 12명에 대해 이야기했습니다.',
                      'es':'Otra persona habló de 12 personas.'}
        for locale in plugin.LOCALES:
            p,u,g=fixtures(locale);replace_text(g,replacements[locale])
            with self.subTest(locale=locale):
                self.assertEqual(statuses(p,u,g)['term_surface_preservation'],'fail')
                self.assertEqual(p['terminology']['properNames'][0]['reviewStatus'],'pending')
        p,u,g=fixtures('es');replace_text(g,'Eric Geigers habló de 12 personas.')
        self.assertEqual(statuses(p,u,g)['term_surface_preservation'],'fail')

    def test_unused_pending_null_terms_are_valid_without_changing_policy_or_coverage(self):
        for locale in plugin.LOCALES:
            for kind in ('seriesNames','properNames'):
                p,u,g=fixtures(locale)
                p['terminology'][kind].append(
                    {'source':'Unmentioned Series','target':None,'reviewStatus':'pending'})
                before=deepcopy((p,u,g))
                with self.subTest(locale=locale,kind=kind):
                    self.assertEqual(statuses(p,u,g)['term_surface_preservation'],'pass')
                    self.assertEqual((p,u,g),before)

    def test_matched_pending_null_term_blocks_even_with_other_target_text(self):
        for locale in plugin.LOCALES:
            for kind in ('seriesNames','properNames'):
                p,u,g=fixtures(locale)
                p['terminology'][kind].append(
                    {'source':'Unresolved Series','target':None,'reviewStatus':'pending'})
                u[0]['english']+=' The Unresolved Series begins.'
                with self.subTest(locale=locale,kind=kind):
                    self.assertEqual(statuses(p,u,g)['term_surface_preservation'],'fail')

    def test_new_source_hit_rechecks_previously_unused_pending_null_term(self):
        p,u,g=fixtures('es');p['terminology']['seriesNames']=[
            {'source':'Unseen','target':None,'reviewStatus':'pending'}]
        self.assertEqual(statuses(p,u,g)['term_surface_preservation'],'pass')
        u[0]['english']+=' He introduced the Unseen series.'
        self.assertEqual(statuses(p,u,g)['term_surface_preservation'],'fail')

    def test_reviewed_null_empty_or_unsafe_targets_fail_even_if_unmentioned(self):
        for target in ('','   ','<break>','\u202eunsafe',123):
            p,u,g=fixtures();p['terminology']['seriesNames']=[
                {'source':'Unmentioned Series','target':target,'reviewStatus':'pending'}]
            with self.subTest(target=target):
                self.assertEqual(statuses(p,u,g)['term_surface_preservation'],'fail')
        for review in ('project_established','human_reviewed'):
            p,u,g=fixtures();p['terminology']['seriesNames']=[
                {'source':'Unmentioned Series','target':None,'reviewStatus':review}]
            with self.subTest(review=review):
                self.assertEqual(statuses(p,u,g)['term_surface_preservation'],'fail')

    def test_unused_terms_still_validate_source_and_review_status(self):
        for mutation in ({'source':'   '},{'source':'<unsafe>'},{'reviewStatus':'approved'},
                         {'unexpectedField':'extra'}):
            p,u,g=fixtures();entry={'source':'Unmentioned Series','target':None,'reviewStatus':'pending'}
            entry.update(mutation);p['terminology']['seriesNames']=[entry]
            with self.subTest(mutation=mutation):
                self.assertEqual(statuses(p,u,g)['term_surface_preservation'],'fail')

    def test_source_term_boundary_does_not_match_unrelated_english_word(self):
        p,u,g=fixtures('es');p['terminology']['properNames']=[
            {'source':'Eric','target':'Erico','reviewStatus':'pending'}]
        u[0]['english']='A generic announcement mentioned 12 people.'
        replace_text(g,'Un anuncio mencionó a 12 personas.')
        self.assertEqual(statuses(p,u,g)['term_surface_preservation'],'pass')

    def test_explicit_series_term_surface_is_checked(self):
        p,u,g=fixtures('es');p['terminology']['seriesNames']=[
            {'source':'Unseen','target':'Invisible','reviewStatus':'pending'}]
        u[0]['english']='Eric Geiger introduced the Unseen series to 12 people.'
        self.assertEqual(statuses(p,u,g)['term_surface_preservation'],'fail')
        replace_text(g,'Eric Geiger presentó la serie Invisible a 12 personas.')
        self.assertEqual(statuses(p,u,g)['term_surface_preservation'],'pass')

    def test_wrong_target_script_fails_without_fabricating_semantic_result(self):
        for locale in ('zh-Hans','ko'):
            p,u,g=fixtures(locale);replace_text(g,'Eric Geiger spoke to 12 people.')
            self.assertEqual(statuses(p,u,g)['target_script'],'fail')
        p,u,g=fixtures('es');replace_text(g,'Eric Geiger 讲到12个人。')
        self.assertEqual(statuses(p,u,g)['target_script'],'fail')
        self.assertNotIn('semanticReview',g)

    def test_explicit_number_loss_change_and_substring_do_not_pass(self):
        for replacement in ('葛艾瑞讲到11个人。','葛艾瑞讲到112个人。','葛艾瑞讲到一些人。'):
            p,u,g=fixtures();replace_text(g,replacement)
            self.assertEqual(statuses(p,u,g)['number_surface_preservation'],'fail')
        p,u,g=fixtures();replace_text(g,'葛艾瑞讲到１２个人。')
        self.assertEqual(statuses(p,u,g)['number_surface_preservation'],'pass')
        u[0]['english']+=' Then 12 people returned.'
        self.assertEqual(statuses(p,u,g)['number_surface_preservation'],'fail')

    def test_unsafe_markup_controls_and_unbounded_utterances_fail(self):
        for suffix in ('<break/>','[pause]','{voice}','```','\n','\t','\u200b','\u202e','&lt;script&gt;'):
            p,u,g=fixtures();replace_text(g,g['targetText']+suffix)
            with self.subTest(suffix=suffix):self.assertEqual(statuses(p,u,g)['utterance_structure'],'fail')
        for utterances in (None,[],[''],[None],['甲']*65,['甲'*4097]):
            p,u,g=fixtures();g['targetUtterances']=utterances
            self.assertEqual(statuses(p,u,g)['utterance_structure'],'fail')
        p,u,g=fixtures();g['targetText']+='not in utterances'
        self.assertEqual(statuses(p,u,g)['utterance_structure'],'fail')

    def test_null_or_empty_target_never_passes(self):
        for target in (None,'',' ',123,[]):
            p,u,g=fixtures();g.update(targetText=target,targetUtterances=[target])
            result=statuses(p,u,g)
            self.assertTrue(all(value=='fail' for value in result.values()))

    def test_reference_only_no_edition_and_no_direct_quote_approval_are_mandatory(self):
        for update in ({'editionId':'NIV'},{'quoteCheckPolicy':'source_bound_exact_quote'},
                       {'quoteCheckPolicy':'pending'},{'approvedQuotes':['made up approval']}):
            p,u,g=fixtures();p['scripture'].update(update)
            self.assertEqual(statuses(p,u,g)['scripture_reference_only'],'fail')
        for claim in ('NIV','和合本','经上记着','RVR1960','está escrito'):
            p,u,g=fixtures();replace_text(g,g['targetText']+claim)
            self.assertEqual(statuses(p,u,g)['scripture_reference_only'],'fail')
        p,u,g=fixtures();u[0]['english']+=' Scripture says "a quote".'
        self.assertEqual(statuses(p,u,g)['scripture_reference_only'],'fail')

    def test_module_contract_is_explicitly_diagnostic_only(self):
        module=runpy.run_path(str(Path(plugin.__file__)))
        self.assertIs(module['DIAGNOSTIC_ONLY'],True)
        self.assertEqual(module['PLUGIN_ID'],'diagnostic-structural-v1')
        self.assertTrue(callable(module['review_group']))
        self.assertTrue(module['PLUGIN_VERSION'])


if __name__=='__main__':unittest.main()
