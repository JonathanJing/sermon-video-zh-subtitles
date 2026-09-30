"""Pure provider-cap/cost arithmetic regressions; no keys, network or inference."""
from copy import deepcopy
from decimal import localcontext
import json
import unittest

from scripts import sermon_provider_limits as limits


def payload(model='gpt-6-astra', text='synthetic input'):
    return {'model': model, 'reasoning_effort': 'medium',
            'messages': [{'role': 'system', 'content': 'Return JSON.'}, {'role': 'user', 'content': text}],
            'response_format': {'type': 'json_object'}}


def observation(**changes):
    value = {'requestedModel': 'gpt-6-astra', 'providerModel': 'gpt-6-astra', 'serviceTier': 'default',
        'elapsedSeconds': 0.0101, 'providerUsage': {'inputTokens': 100, 'outputTokens': 20,
            'cachedInputTokens': None, 'cacheWriteTokens': None, 'reasoningTokens': None, 'totalTokens': 120}}
    value.update(changes)
    return value


class ProviderLimitsTests(unittest.TestCase):
    def setUp(self):
        self.limits = deepcopy(limits.DEFAULT_REQUEST_LIMITS)

    def test_default_limits_are_closed_typed_and_return_detached_copy(self):
        checked = limits.validate_request_limits(self.limits)
        checked['maxCompletionTokens'] = 1
        self.assertEqual(self.limits['maxCompletionTokens'], 4096)
        self.assertEqual(self.limits['maxInputTokens'], 8192)
        for change in ({'schemaVersion': 'wrong'}, {'serviceTier': 'priority'}, {'model': 'other'},
                       {'maxInputTokens': True}, {'maxCompletionTokens': 1.0}, {'wallTimeMs': '300000'},
                       {'maxInputTokens': 0}, {'maxCompletionTokens': -1}, {'maxInputTokens': 16385},
                       {'maxCompletionTokens': 8193}, {'wallTimeMs': 300001}, {'wallTimeMs': float('inf')}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                limits.validate_request_limits(dict(self.limits, **change))
        for value in (None, {}, [], {key:value for key,value in self.limits.items() if key!='serviceTier'}):
            with self.assertRaises(ValueError): limits.validate_request_limits(value)

    def test_optional_larger_source_check_limits_are_explicit_not_default(self):
        source = dict(self.limits, maxInputTokens=16384, maxCompletionTokens=8192)
        bounded = limits.bounded_payload(payload(), source)
        self.assertEqual(bounded['max_completion_tokens'], 8192)
        self.assertEqual(limits.DEFAULT_REQUEST_LIMITS['maxCompletionTokens'], 4096)
        self.assertEqual(limits.RUN_TARGET_MICROUSD, 25_000_000)
        self.assertEqual(limits.RUN_HARD_CAP_MICROUSD, 40_000_000)

    def test_payload_cap_is_explicit_idempotent_and_does_not_mutate_or_truncate(self):
        request = payload(text='原样保留私有文本'); before = deepcopy(request)
        bounded = limits.bounded_payload(request, self.limits)
        self.assertEqual(request, before)
        self.assertEqual(bounded['messages'], request['messages'])
        self.assertEqual(bounded['max_completion_tokens'], 4096)
        self.assertEqual(bounded['service_tier'], 'default')
        self.assertEqual(limits.bounded_payload(bounded, self.limits), bounded)
        bounded['messages'][0]['content'] = 'changed'
        self.assertEqual(request, before)

    def test_api_effort_vocabulary_rejects_agent_only_ultra(self):
        for model in limits.SUPPORTED_MODELS:
            for effort in ('low', 'medium', 'high', 'xhigh', 'max'):
                limits.bounded_payload(dict(payload(model), reasoning_effort=effort), self.limits)
            with self.assertRaisesRegex(ValueError, 'unsupported_bounded_reasoning_effort'):
                limits.bounded_payload(dict(payload(model), reasoning_effort='ultra'), self.limits)

    def test_models_and_policy_efforts_are_allowlisted_never_rewritten(self):
        for model in limits.SUPPORTED_MODELS:
            for effort in limits.MODEL_REASONING_EFFORTS[model]:
                request = dict(payload(model), reasoning_effort=effort)
                selected = limits.bounded_payload(request, self.limits)
                self.assertEqual(selected['reasoning_effort'], effort)
                self.assertEqual(selected['model'], model)
        for change in ({'model':'gpt-6-sol','reasoning_effort':'ultra'}, {'model': 'gpt-6-astra-unknown'}, {'model': None}, {'model': []},
                       {'reasoning_effort': 'unlimited'}, {'reasoning_effort': 1},
                       {'max_completion_tokens': 4097}, {'max_completion_tokens': True},
                       {'service_tier': 'priority'}, {'n': 2}, {'max_tokens': 1}, {'stream': True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                limits.bounded_payload(dict(payload(), **change), self.limits)

    def test_only_bounded_text_chat_and_json_object_response_are_allowed(self):
        for messages in ([], 'text', [{}], [{'role':'user','content':None}],
                         [{'role':'tool','content':'x'}], [{'role':'user','content':['x']}],
                         [{'role':'user','content':'x','name':'extra'}],
                         [{'role':'user','content':'x'}]*17):
            with self.subTest(messages=messages), self.assertRaises(ValueError):
                limits.bounded_payload(dict(payload(), messages=messages), self.limits)
        for value in ({'type':'json_schema'}, {'type':'json_object','extra':True}, None):
            with self.assertRaises(ValueError):
                limits.bounded_payload(dict(payload(), response_format=value), self.limits)

    def test_exact_input_boundary_includes_unicode_json_and_protocol_overhead(self):
        base = payload(text='a')
        size = limits.request_bounds(base, self.limits)['inputTokens']
        fits = payload(text='a'*(self.limits['maxInputTokens']-size+1))
        self.assertEqual(limits.request_bounds(fits, self.limits)['inputTokens'], 8192)
        larger = deepcopy(fits); larger['messages'][-1]['content'] += 'a'; before = deepcopy(larger)
        with self.assertRaisesRegex(ValueError, 'input_bound_exceeded'):
            limits.bounded_payload(larger, self.limits)
        self.assertEqual(larger, before)
        ascii_size = limits.request_bounds(payload(text='aaa'), self.limits)['inputTokens']
        unicode_size = limits.request_bounds(payload(text='中文汉'), self.limits)['inputTokens']
        self.assertEqual(unicode_size-ascii_size, 6)
        with self.assertRaises(ValueError): limits.bounded_payload(payload(text='\ud800'), self.limits)

    def test_request_bounds_price_worst_input_and_full_reasoning_inclusive_output(self):
        for model, input_rate, output_rate in [('gpt-6-astra',12.5,50), ('gpt-6-sol',2.5,10)]:
            measured = limits.request_bounds(payload(model), self.limits)
            self.assertEqual(measured['requests'], 1)
            self.assertEqual(measured['outputTokens'], 4096)
            self.assertEqual(measured['wallTimeMs'], 300000)
            price = measured['inputTokens']*input_rate+4096*output_rate
            self.assertGreaterEqual(measured['costMicrousd'], price)
            self.assertLess(measured['costMicrousd']-price, 1)
            evidence = limits.request_cost_evidence(payload(model), self.limits)
            self.assertEqual(evidence['bounds'], measured)
            self.assertFalse(evidence['invoiceVerified'])
            self.assertEqual(evidence['priceSource'], limits.PRICE_SOURCES[model])
            self.assertEqual(evidence['priceVerifiedAt'], '2026-09-30')
            self.assertNotIn('synthetic input', json.dumps(evidence))

    def test_usage_requires_real_model_tier_token_counts_and_elapsed(self):
        for key in ('requestedModel','providerModel','serviceTier','providerUsage','elapsedSeconds'):
            observed = observation(); observed.pop(key)
            with self.subTest(key=key): self.assertIsNone(limits.usage_resolver(observed))
        for change in ({'requestedModel':'gpt-6-sol'}, {'providerModel':'unknown'},
                       {'actualModel':'gpt-6-sol'}, {'serviceTier':'priority'}, {'elapsedSeconds':None},
                       {'elapsedSeconds':-1}, {'elapsedSeconds':True}, {'elapsedSeconds':'1'},
                       {'elapsedSeconds':float('nan')}, {'elapsedSeconds':float('inf')},
                       {'elapsedSeconds':10**1000}, {'providerUsage':None}):
            with self.subTest(change=change): self.assertIsNone(limits.usage_resolver(observation(**change)))
        self.assertIsNone(limits.usage_resolver(None))

    def test_normalized_unknown_cache_fields_remain_unknown_but_price_is_conservative(self):
        observed = observation(); before = deepcopy(observed)
        value = limits.usage_resolver(observed)
        self.assertEqual(value, {'requests':1,'inputTokens':100,'outputTokens':20,'wallTimeMs':11,'costMicrousd':2250})
        evidence = limits.usage_cost_evidence(observed)
        self.assertIsNone(evidence['cachedInputTokens'])
        self.assertIsNone(evidence['cacheWriteTokens'])
        self.assertIsNone(evidence['reasoningTokens'])
        self.assertEqual(evidence['cacheDetailStatus'], 'unknown_or_partial')
        self.assertEqual(evidence['costStatus'], 'estimated_upper_bound')
        self.assertEqual(evidence['priceSource'], limits.PRICE_SOURCES['gpt-6-astra'])
        self.assertEqual(evidence['priceVerifiedAt'], '2026-09-30')
        self.assertFalse(evidence['invoiceVerified'])
        self.assertEqual(observed, before)

    def test_cached_input_is_not_double_counted_or_treated_as_free(self):
        observed = observation(); observed['providerUsage'].update(cachedInputTokens=60,cacheWriteTokens=40,reasoningTokens=15)
        value = limits.usage_resolver(observed)
        self.assertEqual(value['inputTokens'], 100)
        self.assertEqual(value['outputTokens'], 20)
        self.assertEqual(value['costMicrousd'], 2250)
        evidence = limits.usage_cost_evidence(observed)
        self.assertTrue(evidence['reasoningIncludedInOutputTokens'])
        self.assertEqual(evidence['cacheDetailStatus'], 'reported')

    def test_invalid_or_inconsistent_usage_is_unknown_not_zero(self):
        for change in ({'inputTokens':None}, {'outputTokens':None}, {'inputTokens':100.0},
                       {'inputTokens':True}, {'outputTokens':-1}, {'inputTokens':10**20},
                       {'cachedInputTokens':101}, {'cacheWriteTokens':101},
                       {'cachedInputTokens':60,'cacheWriteTokens':50}, {'reasoningTokens':21},
                       {'totalTokens':121}, {'totalTokens':float('nan')}, {'reasoningTokens':False}):
            observed = observation(); observed['providerUsage'].update(change)
            with self.subTest(change=change):
                self.assertIsNone(limits.usage_resolver(observed))
                self.assertIsNone(limits.usage_cost_evidence(observed)['costMicrousd'])
        self.assertIsNone(limits.usage_resolver(observation(providerUsage={'inputTokens':10**15,'outputTokens':10**15})))

    def test_rounding_is_upward_and_independent_of_decimal_context(self):
        observed = observation(requestedModel='gpt-6-sol',providerModel='gpt-6-sol',elapsedSeconds=1.000001,
            providerUsage={'inputTokens':101,'outputTokens':7})
        with localcontext() as context:
            context.prec = 2
            value = limits.usage_resolver(observed)
            bounds = limits.request_bounds(payload('gpt-6-sol'), self.limits)
        self.assertEqual(value['costMicrousd'], 323)
        self.assertEqual(value['wallTimeMs'], 1001)
        self.assertEqual(bounds, limits.request_bounds(payload('gpt-6-sol'), self.limits))

    def test_measured_zero_and_missing_data_are_distinct(self):
        measured = observation(elapsedSeconds=0,providerUsage={'inputTokens':0,'outputTokens':0})
        self.assertEqual(limits.usage_resolver(measured),
            {'requests':1,'inputTokens':0,'outputTokens':0,'wallTimeMs':0,'costMicrousd':0})
        measured['providerUsage'].pop('inputTokens')
        self.assertIsNone(limits.usage_resolver(measured))

    def test_actual_model_alias_requires_matching_requested_model(self):
        observed = observation(); observed['actualModel'] = observed.pop('providerModel')
        self.assertIsNotNone(limits.usage_resolver(observed))
        observed['providerModel'] = 'gpt-6-sol'
        self.assertIsNone(limits.usage_resolver(observed))


if __name__ == '__main__': unittest.main()
