import io
import json
import math
import unittest
from unittest import mock
import test_consumer as T
C=T.C

class ShortReads(io.StringIO):
    def __init__(self,text,limit):super().__init__(text);self.limit=limit
    def read(self,size=-1):return super().read(min(size,self.limit) if size>=0 else self.limit)

def parse(text,limit=65536):
    with mock.patch.object(C.Path,'open',return_value=ShortReads(text,limit)):
        return list(C.iter_array('/synthetic/metrics.json'))

class LinearReader(unittest.TestCase):
    def test_every_chunk_split_escape_unicode_nesting(self):
        expected=[{'id':'a','s':'escaped \\" quote " backslash \\ and \u2603 braces{}[]','nested':[{'x':[1,2,{'s':'\\"'}]}]}, {'id':'b','v':[]}]
        text=json.dumps(expected,ensure_ascii=True,indent=2)
        for limit in range(1,100):self.assertEqual(parse(text,limit),expected,limit)

    def test_empty_and_whitespace(self):
        for text in ('[]',' \n\t[ \r\n ] \n\t','\u2003[]\u2003'):
            for limit in (1,2,7):self.assertEqual(parse(text,limit),[])

    def test_one_decode_per_complete_record(self):
        value=[{'id':'a','large':'a'*200000,'n':[{'s':'x'*90000}]},{'id':'b','v':None}]
        text=json.dumps(value);decoder=json.JSONDecoder();calls=[]
        class Count:
            def raw_decode(self,record):calls.append(len(record));return decoder.raw_decode(record)
        with mock.patch.object(C.json,'JSONDecoder',return_value=Count()):self.assertEqual(parse(text,17),value)
        self.assertEqual(len(calls),2)

    def test_nested_bracket_types_and_strings(self):
        value={'x':0}
        for _ in range(60):value={'array':[value,{'string':'}[\\"'}]}
        self.assertEqual(parse(json.dumps([value]),3),[value])

    def test_original_duplicate_member_last_value_semantics(self):
        self.assertEqual(parse('[{"id":"first","id":"last","nested":{"a":1,"a":2}}]',1),[{'id':'last','nested':{'a':2}}])

    def test_original_nonfinite_decoder_semantics(self):
        result=parse('[{"n":NaN,"p":Infinity,"m":-Infinity}]',2)[0]
        self.assertTrue(math.isnan(result['n']));self.assertEqual(result['p'],math.inf);self.assertEqual(result['m'],-math.inf)

    def test_duplicate_record_ids_fail_existing_exact_order_gate(self):
        rows=parse('[{"id":"a"},{"id":"a"}]',1)
        with self.assertRaises(C.Stop):C.need([r['id']for r in rows]==['a','b'],'Metrics lost/added/reordered runtime contributors')

    def test_missing_duplicate_and_trailing_delimiters(self):
        for text in ('[{}{}]','[{},,{}]','[{},]','[{}, ]','[{}]]','[{}]{}','[{}],','[{}] true','[{}] \n x'):
            for limit in (1,2,9):
                with self.subTest(text=text,limit=limit),self.assertRaises(C.Stop):parse(text,limit)

    def test_non_object_elements(self):
        for text in ('[1]','[[]]','[null]','[true]','["x"]','[{},3]','{}','null',''):
            with self.subTest(text=text),self.assertRaises(C.Stop):parse(text,1)

    def test_truncated_every_prefix(self):
        text='[{"x":[{"q":"\\\\\\\"\\u2603"},3]}]'
        self.assertEqual(parse(text,1),json.loads(text))
        for end in range(len(text)):
            with self.subTest(end=end),self.assertRaises(C.Stop):parse(text[:end],2)

    def test_invalid_grammar_is_decoder_authority(self):
        for text in ('[{"a":}]','[{"a" 1}]','[{"a":1,}]','[{"a":"\\q"}]','[{"a":"\\u12xx"}]','[{"a":[1,2}]','[{"a":[1,]}]','[{"a":01}]','[{"a":true false}]'):
            for limit in (1,3,65536):
                with self.subTest(text=text,limit=limit),self.assertRaises(C.Stop):parse(text,limit)

if __name__=='__main__':unittest.main()
