#!/usr/bin/env python3
"""Static-only composition fixtures; run only in the owner's quiet slot."""
import copy
import importlib.util
import inspect
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


n = load('sealed_feasible_safe_fill_composition_tests', HERE / 'evaluate_v2_feasible_safe_fill_v4.py')
fill = load('sealed_fill_fixture_inputs', HERE / 'test_evaluate_v2_safe_fill_B_staged.py')
safe = load('sealed_safe_fixture_inputs', HERE / 'test_evaluate_v2_finite_safe_staged.py')
v2 = load('sealed_v2_fixture_inputs', HERE / 'test_evaluate_v2_certified_delivery_v2.py')


class SealedCompositionTests(unittest.TestCase):
    def test_exact_five_functions_are_qualified_B_aliases_without_rebinding(self):
        for name in ('normalize_serving_config', 'delivery_config', 'validate_delivery_binding',
                     'selected_delivery_ids', 'validate_reconstructed_delivery'):
            self.assertIs(getattr(n, name), getattr(n.delivery_contract, name), name)
        self.assertEqual(n.ACCEPTED_SAFE_FILL_B_EVALUATOR_SHA256,
                         'b95a3706d533c89e53a06a798d8b65815146c94fcdc5b0cb8f481ded300bee88')
        self.assertNotIn('delivery_contract.evaluate(', inspect.getsource(n.evaluate))

    def test_legacy_exact_contracts_and_ID_extraction_are_unchanged(self):
        for k in (3, 5):
            for config, row in ((v2.bounded(k), v2.bounded_row(k)), (v2.finite(k), v2.finite_row(k))):
                self.assertEqual(n.delivery_config(config, k), v2.n.delivery_config(config, k))
                self.assertEqual(n.selected_delivery_ids(row, config, k), v2.n.selected_delivery_ids(row, config, k))
                self.assertIsNone(n.validate_reconstructed_delivery(row, config, k, []))

    def test_safe_and_fill_validated_audits_match_sealed_parents(self):
        for empty in (False, True):
            config, row, final = safe.fixture(empty)
            self.assertEqual(n.validate_reconstructed_delivery(row, config, 3, final),
                             safe.E.validate_finite_safe_constraints(row, config, 3, final))
        for k in (3, 5):
            for count in (0, 1, 2, 3):
                config, row, final = fill.fixture(k, count)
                self.assertEqual(n.normalize_serving_config(config), fill.E.normalize_serving_config(config))
                self.assertEqual(n.selected_delivery_ids(row, config, k), fill.E.selected_delivery_ids(row, config, k))
                self.assertEqual(n.validate_reconstructed_delivery(row, config, k, final),
                                 fill.E.validate_reconstructed_delivery(row, config, k, final))

    def test_composed_contracts_reject_known_parent_tampering(self):
        config, row, final = safe.fixture()
        row['recommendation_quality']['finite20_safe_choices']['pointwise_constraints'][0]['repair_selected_score'] -= 1
        with self.assertRaises(ValueError): n.validate_reconstructed_delivery(row, config, 3, final)
        config, row, final = fill.fixture()
        row['recommendation_quality']['absolute_hybrid_fill_choices']['selection']['selected'].pop()
        with self.assertRaises(ValueError): n.validate_reconstructed_delivery(row, config, 3, final)
        config, row, final = fill.fixture()
        row['recommendation_quality']['absolute_hybrid_fill_choices']['config_value_sha256'] = '0'*64
        with self.assertRaises(ValueError): n.validate_reconstructed_delivery(row, config, 3, final)

    def test_reference_and_delivery_gates_stay_before_falsification_and_latency(self):
        source = inspect.getsource(n.evaluate)
        self.assertLess(source.index('validate_reconstructed_delivery('), source.index('reference_importer.import_dataset('))
        self.assertLess(source.index('reference_importer.import_dataset('), source.index('native_counterexamples=[]'))
        self.assertLess(source.index("x['status']='native_contract_counterexample'"),
                        source.index('accepted_first_answer=first_answer_acceptance('))
        self.assertIn("CANDIDATE_DELIVERY_CONTRACT_ROWS.jsonl", source)
        self.assertIn('candidate_aware_delivery_contract_rows=candidate_delivery_contract_count', source)
        self.assertEqual(n.reference_tools.__file__, str(HERE / 'feasible_reference_v1.py'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
