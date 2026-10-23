"""Unexecuted draft: original synthetic projection fixtures plus reader seam."""
import ast
import copy
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

P=Path(__file__).with_name('project_runtime8_frontier_v2.py')
SPEC=importlib.util.spec_from_file_location('runtime8_projection_v2_fixture',P)
M=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(M)
original=ast.parse(P.with_name('test_project_runtime8_frontier_v1.py').read_text())
classes=[n for n in original.body if isinstance(n,ast.ClassDef)and n.name=='RuntimeProjectionTests']
assert len(classes)==1
exec(compile(ast.fix_missing_locations(ast.Module(body=classes,type_ignores=[])),str(P.with_name('test_project_runtime8_frontier_v1.py')),'exec'),globals())

class ProjectionLinearReaderSeam(unittest.TestCase):
    def parse(self,text):
        with tempfile.TemporaryDirectory()as directory:
            path=Path(directory)/'metrics.json';path.write_text(text)
            return list(M.array_rows(path))

    def test_unchanged_campaign_root_depth(self):
        self.assertEqual(M.ROOT,Path(__file__).resolve().parents[1])

    def test_object_domain_nested_escaped_and_chunk_boundaries(self):
        for padding in range(65520,65555):
            values=[{'s':'x'*padding+'\\" quote " backslash \\ brackets {}[] \u2603','n':[{},[1,2,{'k':'\\'}]]},{'id':'last'}]
            self.assertEqual(self.parse(json.dumps(values,ensure_ascii=True)),values)

    def test_duplicate_member_preserves_last_value(self):
        self.assertEqual(self.parse('[{"id":"first","id":"last"}]'),[{'id':'last'}])

    def test_nonfinite_decoder_semantics_preserved(self):
        row=self.parse('[{"x":NaN,"a":Infinity,"b":-Infinity}]')[0]
        self.assertTrue(math.isnan(row['x']));self.assertEqual(row['a'],math.inf);self.assertEqual(row['b'],-math.inf)

    def test_malformed_truncation_and_trailing_rejected(self):
        for text in ('[{},]','[{},,{}]','[{}{}]','[{"x":"\\q"}]','[{"x":[1,2}]','[{"x":"unfinished','[{}]x','[{}]]','[{}'):
            with self.subTest(text=text),self.assertRaises(ValueError):self.parse(text)

    def test_nonobject_window_metrics_fail_closed(self):
        for text in ('[1]','[true]','[null]','[[]]','["x"]'):
            with self.subTest(text=text),self.assertRaises(ValueError):self.parse(text)

    def test_reader_source_pin_refuses_changed_source_without_execution(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);reader=root/'analysis/lossless-storage-v1/runtime-window-consumer-v2/consumer.py'
            reader.parent.mkdir(parents=True);reader.write_text('raise AssertionError("must not execute")')
            with mock.patch.object(M,'ROOT',root),self.assertRaisesRegex(ValueError,'source changed'):
                list(M.array_rows(root/'not-opened.json'))

    def test_delegation_is_once_and_preserves_exact_object_identities(self):
        values=[{'id':'a','nested':[1,2]},{'id':'b'}];calls=[]
        class ReaderStop(Exception):pass
        def fake_exec(code,namespace):
            self.assertTrue(code.co_filename.endswith('runtime-window-consumer-v2/consumer.py'))
            def generate(path):calls.append(path);yield from values
            namespace.update(iter_array=generate,Stop=ReaderStop)
        with mock.patch('builtins.exec',side_effect=fake_exec):rows=list(M.array_rows('/synthetic/metrics.json'))
        self.assertEqual(calls,['/synthetic/metrics.json'])
        for got,want in zip(rows,values):self.assertIs(got,want)

if __name__=='__main__':unittest.main()
