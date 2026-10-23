"""Synthetic source fixtures for the create-only empirical-policy correction."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).absolute().parent

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

prior_tests = load('finite_prior_v2_resource_test_source', 'test_finite_result_analysis_v2.py')
policy = load('finite_empirical_policy_candidate', 'finite_result_analysis_v2_empirical_budget.py')
REF = dict(path='/tmp/prior-accepted-synthetic', sha256='a'*64)


class EmpiricalBudgetTests(prior_tests.NumericAuthorityTests):
    def fixture(self, mode='cap-window'):
        fixture = super().fixture(mode)
        request = fixture[2]
        request['empirical_output_budget_pools'] = []
        if mode == 'cap-window':
            request['metrics_recipe'] = dict(exact_preparation_serialization_bytes=0,
                nonpreparation_margin_bytes=17,
                nonpreparation_basis='EMPIRICAL_NOT_FIT_GUARANTEE',
                prior_accepted_request=REF, prior_numeric_acceptance=REF)
        return fixture

    def check(self, fixture):
        mode, window, request, names = fixture
        return policy.validate_numeric_request(mode, window, '/tmp/new-output', request, names)

    def pooled_fixture(self):
        fixture = self.fixture()
        request = fixture[2]
        names = [name for name in request['output_upper_bytes']
                 if not name.endswith('METRICS_BY_RUN.json')]
        removed = sum(request['output_upper_bytes'].pop(name) for name in names)
        request['empirical_output_budget_pools'] = [dict(output_names=names, budget_bytes=400000000,
            basis='EMPIRICAL_NOT_FIT_GUARANTEE', source_schema_delta_review_required=True,
            prior_accepted_request=REF, prior_numeric_acceptance=REF)]
        request['required_free_bytes'] += 400000000 - removed
        return fixture

    def test_one_shared_pool_is_counted_once_not_ten_times(self):
        got = self.check(self.pooled_fixture())
        self.assertEqual(got['all_output_upper_bytes'], 400000017)
        self.assertEqual(got['empirical_budget_pool_count'], 1)
        self.assertFalse(got['empirical_fit_guarantee'])

    def test_shared_pool_cannot_overlap_dedicated_metrics(self):
        fixture = self.pooled_fixture()
        fixture[2]['empirical_output_budget_pools'][0]['output_names'].append('v4-output/METRICS_BY_RUN.json')
        with self.assertRaises(ValueError): self.check(fixture)

    def test_shared_pool_cannot_hide_unqualified_or_duplicate_output(self):
        for name in ('not-qualified.json', 'REPORT.json'):
            fixture = self.pooled_fixture()
            fixture[2]['empirical_output_budget_pools'][0]['output_names'].append(name)
            with self.assertRaises(ValueError): self.check(fixture)

    def test_empirical_margin_is_not_a_proven_or_unlabelled_bound(self):
        for field, value in (('basis', 'PROVEN'), ('source_schema_delta_review_required', False),
                             ('prior_numeric_acceptance', None), ('budget_bytes', None)):
            fixture = self.pooled_fixture()
            fixture[2]['empirical_output_budget_pools'][0][field] = value
            with self.assertRaises(ValueError): self.check(fixture)

    def test_metrics_must_equal_exact_prep_plus_explicit_empirical_margin(self):
        fixture = self.pooled_fixture()
        fixture[2]['metrics_recipe']['exact_preparation_serialization_bytes'] = 1
        with self.assertRaises(ValueError): self.check(fixture)

    def test_metric_margin_ancestry_cannot_be_omitted(self):
        fixture = self.pooled_fixture()
        fixture[2]['metrics_recipe']['prior_accepted_request'] = None
        with self.assertRaises(ValueError): self.check(fixture)
