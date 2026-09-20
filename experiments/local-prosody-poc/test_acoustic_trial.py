import unittest
from acoustic_trial import validate

class OutputContractTests(unittest.TestCase):
    def data(self,boundaries,emphasis=None):
        return {'boundaries':boundaries,'emphasis':emphasis or [],'limitations':[]}

    def test_duplicate_or_forced_tail_rejected(self):
        for indices in ([1,1],[4]):
            value=self.data([{'after_word':i,'kind':'sentence','evidence':'candidate'} for i in indices])
            self.assertIn('invalid_boundary_index',validate(value,5,'text'))

    def test_text_cannot_invent_acoustic_emphasis(self):
        self.assertIn('unsupported_emphasis',validate(self.data([], [{'word_index':1,'evidence':'loud'}]),5,'text'))

    def test_missing_schema_rejected(self):
        self.assertIn('invalid_boundaries',validate({},5,'text'))

    def test_phrase_and_sentence_are_distinct(self):
        value=self.data([{'after_word':1,'kind':'phrase','evidence':'internal pause'},{'after_word':3,'kind':'sentence','evidence':'complete'}])
        self.assertEqual(validate(value,5,'gap'),[])

if __name__=='__main__':unittest.main()
