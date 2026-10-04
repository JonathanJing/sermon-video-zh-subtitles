import copy
import unittest
from scripts import sermon_workflow_experiment as s

class WorkflowExperimentTests(unittest.TestCase):
    def setUp(self):
        self.p = {'schemaVersion': 'sermon-workflow-experiment-v1', 'arms': sorted(s.ARMS),
            'cacheModes': ['cold', 'hot'], 'blindAssignments': dict(zip(['A','B','C'], sorted(s.ARMS))),
            **{k:'a'*64 for k in s.IDENTITIES}}
        self.rows = [{'schemaVersion':'sermon-workflow-experiment-receipt-v1',
            'protocolSha256':s.validate_protocol(self.p), **{k:self.p[k] for k in s.IDENTITIES},
            'blindId':a, 'cacheMode':b, 'quality':{'status':'passed'}, 'evidenceSha256':'b'*64,
            'metrics':{k:None for k in s.METRICS}} for a in ['A','B','C'] for b in ['cold','hot']]
    def test_unknown_costs_remain_unknown_and_domains_separate(self):
        r=s.compare(self.p,self.rows)
        self.assertTrue(r['qualityComparable'])
        self.assertIsNone(r['blindMeasurements']['cold']['A']['apiCostMicrousd'])
        self.assertEqual(len(r['costDomains']),3)
    def test_source_mismatch_and_duplicates_rejected(self):
        bad=copy.deepcopy(self.rows);bad[0]['sourceSha256']='c'*64
        with self.assertRaises(ValueError):s.compare(self.p,bad)
        with self.assertRaises(ValueError):s.compare(self.p,self.rows+[self.rows[0]])
    def test_incomplete_or_failed_quality_cannot_claim_comparison(self):
        self.assertFalse(s.compare(self.p,self.rows[:-1])['qualityComparable'])
        self.rows[0]['quality']['status']='failed'
        self.assertFalse(s.compare(self.p,self.rows)['qualityComparable'])
    def test_invalid_counters_rejected(self):
        self.rows[0]['metrics']['gpuSeconds']=float('nan')
        with self.assertRaises(ValueError):s.compare(self.p,self.rows)
