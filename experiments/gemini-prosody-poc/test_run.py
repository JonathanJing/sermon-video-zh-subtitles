import unittest
from run import validate, tokens

class ValidationTests(unittest.TestCase):
    def test_words_preserve_apostrophes(self):
        self.assertEqual(tokens("God's house—until?"), ["God's", 'house', 'until'])

    def test_reject_missing_words(self):
        data = {'sentences':[{'start_word':0,'end_word':1,'end_seconds':None}]}
        self.assertIn('incomplete_coverage', validate(data, 3, 60, 'audio'))

    def test_reject_invented_audio_in_silence(self):
        data = {'audio_status':'no_speech','sentences':[{'start_word':0,'end_word':2,'end_seconds':4}], 'emphasis':[{'word_index':1}]}
        self.assertIn('unsupported_audio_timestamp', validate(data,3,60,'silence'))
        self.assertIn('unsupported_emphasis', validate(data,3,60,'silence'))

    def test_silence_cannot_self_certify(self):
        data = {'audio_status':'matched','sentences':[{'start_word':0,'end_word':2,'end_seconds':4}]}
        self.assertIn('silence_not_detected',validate(data,3,60,'silence'))

    def test_reject_out_of_window(self):
        data = {'sentences':[{'start_word':0,'end_word':2,'end_seconds':61}]}
        self.assertIn('invalid_timestamp',validate(data,3,60,'audio'))

if __name__ == '__main__':
    unittest.main()
