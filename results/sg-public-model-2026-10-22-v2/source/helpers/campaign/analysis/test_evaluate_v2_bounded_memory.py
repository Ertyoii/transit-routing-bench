#!/usr/bin/env python3
"""Synthetic parity only. No router, model, final outcomes, or test workloads."""
import ast
import copy
import hashlib
import importlib.util
import json
import random
import tempfile
import unittest
from array import array
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACCEPTED_SHA = '499ede17fbf04a7bb5b2904b8f5929c816cdafc7952c7bb1e0be1278aec2551e'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


o = load('accepted_evaluator_memory_parity', HERE / 'evaluate_v2.py')
n = load('bounded_evaluator_memory_parity', HERE / 'evaluate_v2_bounded_memory.py')


def journey(duration, transfers=0, walking=0):
    return {'duration_seconds': duration, 'metrics': {'transfers': transfers, 'walking_seconds': walking}}


def row(score, lofo, i=0, complete=True):
    return {'dataset_sha256': 'synthetic', 'window': 'tiny', 'variant_id': str(i % 3),
            'stage': ['raw', 'final', 'display'][i % 3], 'stratum': str(i % 2),
            'complete': complete, 'score': score, 'leave_donor_family_out_signed': lofo}


def original_accumulate(buckets, value):
    for panel, key in [('full', 'score'), ('leave_family_out', 'leave_donor_family_out_signed')]:
        v = value[key]
        b = buckets.setdefault((value['dataset_sha256'], value['window'], value['variant_id'], value['stage'], value['stratum'], panel),
                               {'rows': 0, 'complete': 0, 'eligible': 0, 'covered': 0, 'missing': 0,
                                'counterexamples': 0, 'regrets': [], 'normalized': []})
        b['rows'] += 1
        b['complete'] += value['complete']
        b['eligible'] += v.get('eligible', 0)
        b['covered'] += v.get('covered', 0)
        b['missing'] += v.get('eligible', 0) if v.get('missing') else 0
        b['counterexamples'] += v.get('counterexample_slots', 0)
        b['regrets'] += v.get('regrets', [])
        b['normalized'] += v.get('normalized_regrets', [])


def summarize(buckets, evaluator):
    result = []
    for key, b in buckets.items():
        result.append((key, {**{k: v for k, v in b.items() if k not in ['regrets', 'normalized']},
                             'regret_score_seconds': evaluator.dist(b['regrets']),
                             'normalized_regret': evaluator.dist(b['normalized'])}))
    return result


class Parity(unittest.TestCase):
    def test_accepted_source_hash_unchanged(self):
        self.assertEqual(o.sha(HERE / 'evaluate_v2.py'), ACCEPTED_SHA)

    def test_scoring_and_safety_helpers_are_ast_identical(self):
        def functions(path):
            return {v.name: ast.dump(v, include_attributes=False) for v in ast.parse(path.read_text()).body
                    if isinstance(v, (ast.FunctionDef, ast.AsyncFunctionDef))}
        before, after = functions(HERE / 'evaluate_v2.py'), functions(HERE / 'evaluate_v2_bounded_memory.py')
        for name in before.keys() - {'sha', 'evaluate'}:
            self.assertEqual(before[name], after[name], name)

    def test_scores_random_finite_and_missing(self):
        rng = random.Random(20261021)
        weights = [{'transfer_seconds': rng.random() * 900, 'extra_walk_weight': rng.random() * 4}
                   for _ in range(393)]
        for _ in range(75):
            candidates = [journey(rng.randrange(7200), rng.randrange(6), rng.randrange(900))
                          for _ in range(rng.randrange(5))]
            reference = [journey(rng.randrange(7200), rng.randrange(6), rng.randrange(900))
                         for _ in range(rng.randrange(6))]
            complete = bool(rng.randrange(2))
            self.assertEqual(o.score_stage(candidates, reference, weights, complete),
                             n.score_stage(candidates, reference, weights, complete))

    def test_threshold_boundaries_and_signed_lofo_not_clipped(self):
        weights = [{'transfer_seconds': 0.0, 'extra_walk_weight': 0.0}] * 393
        for delta in [-120.0, -1.0000001e-7, -1e-7, 0.0, 0.00001, 30.0, 30.0000001,
                      30.0000002, 60.0, 120.0, 120.0000002]:
            ref = journey(1000.0)
            old = o.score_stage([journey(1000.0 + delta)], [ref], weights, True)
            new = n.score_stage([journey(1000.0 + delta)], [ref], weights, True)
            self.assertEqual(old, new)
            b = {}; n.accumulate_quality_row(b, row(new, copy.deepcopy(new)))
            self.assertEqual(o.dist(old['regrets']), n.dist(next(iter(b.values()))['regrets']))

    def test_quantiles_and_sorted_fmean_bit_exact(self):
        rng = random.Random(19)
        for count in [0, 1, 2, 3, 19, 20, 99, 100, 101, 393, 1025]:
            samples = [rng.uniform(-1e9, 1e9) for _ in range(count)]
            samples += ([0.0, -0.0, 1e-7, -1e-7] if count else [])
            self.assertEqual(json.dumps(o.dist(samples), sort_keys=True),
                             json.dumps(n.dist(array('d', samples)), sort_keys=True))

    def test_integer_float_ties_and_large_integers_keep_exact_json(self):
        for samples in [[0.0] * 390 + [0, 0, 0], [0, -0.0, 0.0, 0, -0.0],
                        [2 ** 53 + 1, 2 ** 53 + 2, 0, 0.0, -2 ** 53 - 1],
                        [10 ** 400, -10 ** 400, 0]]:
            compact = n.ExactRegretSamples(); compact.extend(samples)
            self.assertEqual([(type(v), v) for v in compact], [(type(v), v) for v in samples])
            # fmean intentionally has the original overflow behavior on huge ints.
            if max(abs(x) for x in samples) < 10 ** 300:
                self.assertEqual(json.dumps(o.dist(samples), sort_keys=True),
                                 json.dumps(n.dist(compact), sort_keys=True))

    def test_incremental_aggregation_matches_original(self):
        rng = random.Random(21)
        before, after = {}, {}
        weights = [{'transfer_seconds': rng.random() * 900, 'extra_walk_weight': rng.random() * 4}
                   for _ in range(393)]
        for i in range(60):
            candidate = [journey(rng.randrange(7200), rng.randrange(4), rng.randrange(900))] if i % 8 else []
            ref = [journey(rng.randrange(7200), rng.randrange(4), rng.randrange(900))] if i % 7 else []
            outside = [journey(rng.randrange(7200), rng.randrange(4), rng.randrange(900))] if i % 5 else []
            complete = bool(i % 9)
            value = row(o.score_stage(candidate, ref, weights, complete),
                        o.score_stage(candidate, outside, weights, complete), i, complete)
            original_accumulate(before, value)
            new = copy.deepcopy(value); n.accumulate_quality_row(after, new)
            expected = copy.deepcopy(value)
            for panel in ['score', 'leave_donor_family_out_signed']:
                v = expected[panel]
                v['regret_score_seconds'] = o.dist(v.pop('regrets', []))
                v['normalized_regret'] = o.dist(v.pop('normalized_regrets', []))
            self.assertEqual(expected, n.compact_quality_row(new))
            self.assertTrue(all('regrets' not in new[k] and 'normalized_regrets' not in new[k]
                                for k in ['score', 'leave_donor_family_out_signed']))
        self.assertEqual(json.dumps(summarize(before, o)), json.dumps(summarize(after, n)))
        self.assertTrue(all(isinstance(b['regrets'], array) and b['regrets'].typecode == 'd'
                            for b in after.values()))

    def test_streamed_json_array_bytes_match_empty_and_nested(self):
        cases = [[], [{'offered': 3}], [{'unicode': '雪', 'text': 'a\nb', 'nested': [None, True, {'n': -0.0}]}],
                 [{'a': []}, {'b': {'c': [1, 2, 3], 'empty': {}}}]]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'stream.json'
            for case in cases:
                sink = n.JsonArraySink(path)
                for value in case: sink.append(value)
                sink.close()
                self.assertEqual(path.read_text(), json.dumps(case, indent=2, sort_keys=True) + '\n')
                self.assertEqual(len(sink), len(case))
                self.assertEqual(sink.offered, sum(v.get('offered', 0) for v in case))

    def test_streamed_jsonl_bytes_match(self):
        values = [{'text': '雪\na'}, {'x': [1, 2], 'y': None}]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'stream.jsonl'; sink = n.JsonlSink(path)
            for value in values: sink.append(value)
            sink.close()
            self.assertEqual(path.read_text(), ''.join(json.dumps(v, separators=(',', ':')) + '\n' for v in values))

    def test_streaming_sha_matches_original(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'bytes'; path.write_bytes(bytes(range(256)) * 8193)
            self.assertEqual(n.sha(path), o.sha(path))


if __name__ == '__main__':
    unittest.main(verbosity=2)
