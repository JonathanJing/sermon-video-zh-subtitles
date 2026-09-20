import unittest
from analyze import compare
from run import shared

class ComparisonTests(unittest.TestCase):
    def test_invalid_result_not_scored(self):
        bad={'validation_errors':['invalid_word_coverage']}
        good={'validation_errors':[],'analysis':{'sentences':[{'end_word':1},{'end_word':3}]}}
        self.assertEqual(compare(bad,good),{'status':'excluded_invalid_output'})

    def test_forced_last_boundary_excluded(self):
        def record(ends):return {'validation_errors':[],'analysis':{'sentences':[{'end_word':x} for x in ends]}}
        self.assertEqual(compare(record([1,3]),record([2,3]))['jaccard'],0)

    def test_overlap_rejected(self):
        data={'audio_status':'not_supplied','limitations':[],'sentences':[{'start_word':0,'end_word':2,'punctuation':'.','tone':'text_inference'},{'start_word':2,'end_word':4,'punctuation':'.','tone':'text_inference'}]}
        self.assertIn('invalid_word_coverage',shared.validate(data,5,60,'text'))

if __name__=='__main__': unittest.main()
