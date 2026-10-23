#!/usr/bin/env python3
"""Strict reference-only native witness import. Never an oracle or serving lane.

This module reconstructs original source locators and transformations before
calling the recipient model's independent Checker. Audit reports are integrity
receipts, not substitutes for that second reconstruction. No source-tree scan,
router execution, scalar-slot creation, or native completion promotion occurs.
"""
import collections
import copy
import glob
import hashlib
import importlib.util
import json
from pathlib import Path
import re

SCHEMA = 'sg-feasible-reference-witness-v1'
IDENTITY_TRANSFORM = 'identity; independently rechecked under full base query'
PREFIX_TRANSFORM = 'reanchor only initial contiguous walking prefix from model footpath durations; ride/intermediate/egress events fixed'
HEX = re.compile(r'[0-9a-f]{64}')


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def canonical_sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def same_json(left, right):
    return canonical(left) == canonical(right)


def strict_json(text):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'duplicate JSON key: ' + key)
            out[key] = value
        return out
    return json.loads(text, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON: ' + value)))


def offered_queries(workload):
    result = {}
    for item in workload['items']:
        q = item['query']
        require(isinstance(q, dict) and isinstance(q.get('id'), str) and q['id'], 'malformed offered query')
        require(q['id'] not in result, 'duplicate offered query ID')
        result[q['id']] = item
    return result


def bind_recipient(expected, dataset_sha, query):
    key = (dataset_sha, query['id'])
    require(key not in expected or same_json(expected[key], query), 'same query ID has different full recipient query/caps/horizon')
    expected[key] = query


def reanchor_prefix(checker, journey, departure):
    result = copy.deepcopy(journey)
    now, seconds, count = departure, 0, 0
    for leg in result['legs']:
        if leg['kind'] != 'walk':
            break
        require(leg['ref'] in checker.walks, 'unknown initial walking footpath')
        duration = checker.walks[leg['ref']]['duration']
        require(type(duration) is int and duration >= 0, 'invalid model walking duration')
        leg['departure'], leg['arrival'] = now, now + duration
        now += duration
        seconds += duration
        count += 1
    return result, seconds, count


def validate_source_walk_anchor(checker, journey, source_ready):
    now = source_ready
    for leg in journey['legs']:
        if leg['kind'] != 'walk':
            break
        require(leg['ref'] in checker.walks, 'unknown source walking-prefix footpath')
        duration = checker.walks[leg['ref']]['duration']
        require(leg['departure'] == now and leg['arrival'] == now + duration,
                'invalid original source walking-prefix anchor/duration')
        now += duration


def object_slices(text, start=0):
    """Exact source query bytes, with duplicate object keys rejected."""
    decoder = json.JSONDecoder()
    def ws(index):
        while index < len(text) and text[index].isspace():
            index += 1
        return index
    pos = ws(start)
    require(pos < len(text) and text[pos] == '{', 'expected workload object')
    pos, result = ws(pos + 1), {}
    while text[pos] != '}':
        key, pos = decoder.raw_decode(text, pos)
        require(key not in result, 'duplicate workload object key')
        pos = ws(pos)
        require(text[pos] == ':', 'invalid workload delimiter')
        begin = ws(pos + 1)
        _, end = decoder.raw_decode(text, begin)
        result[key] = (begin, end)
        pos = ws(end)
        if text[pos] == ',':
            pos = ws(pos + 1)
        else:
            require(text[pos] == '}', 'invalid workload delimiter')
    return result


def workload_fragments(text, workload):
    begin, _ = object_slices(text)['items']
    pos, result = begin + 1, {}
    decoder = json.JSONDecoder()
    for item in workload['items']:
        while text[pos].isspace() or text[pos] == ',':
            pos += 1
        a, b = object_slices(text, pos)['query']
        fragment, qid = text[a:b], item['query']['id']
        require(strict_json(fragment) == item['query'] and qid not in result, 'exact query fragment mismatch/duplicate')
        result[qid] = fragment
        _, pos = decoder.raw_decode(text, pos)
    return result


class DonorLineage:
    """Optional versioned ancestry sensitivity, distinct from adapter-family LOFO.

    Unknown aliases fail closed when explicit lineage is enabled. Multiple
    ancestry labels preserve hybrid tags: any shared tag excludes that donor.
    """
    def __init__(self, path, read_bound):
        self.payload = None
        self.groups = {}
        self.path = str(Path(path).resolve()) if path else None
        if not path:
            return
        payload = read_bound(path)
        require(payload.get('schema') == 'sg-donor-ancestry-algorithms-v1' and type(payload.get('version')) is int
                and payload['version'] > 0, 'invalid donor-lineage schema/version')
        contract = payload.get('contract')
        require(isinstance(contract, dict) and HEX.fullmatch(contract.get('sha256', '')), 'lineage contract binding missing')
        read_bound(contract['path'], contract['sha256'])
        algorithms = payload.get('algorithms')
        require(isinstance(algorithms, dict) and algorithms, 'missing donor-lineage algorithms')
        for algorithm, entry in algorithms.items():
            require(isinstance(algorithm, str) and isinstance(entry, dict), 'invalid donor-lineage algorithm')
            groups = entry.get('ancestry_groups')
            require(isinstance(entry.get('adapter_family'), str) and isinstance(groups, list) and groups
                    and all(isinstance(g, str) and g for g in groups) and len(set(groups)) == len(groups),
                    'invalid donor-lineage ancestry groups')
            evidence = entry.get('source_evidence')
            require(isinstance(evidence, list) and evidence, 'donor-lineage source evidence missing')
            for source in evidence:
                require(isinstance(source, dict) and isinstance(source.get('path'), str), 'invalid lineage source evidence')
                if source.get('sha256'):
                    source_path = Path(source['path'])
                    if not source_path.is_absolute():
                        source_path = Path(__file__).resolve().parents[1] / source_path
                    read_bound(source_path, source['sha256'], True)
                else:
                    require(algorithm == 'independent_scalar_oracle' and source.get('qualification'), 'unbound native lineage source')
        for algorithm, entry in algorithms.items():
            self.groups[algorithm] = tuple(sorted(entry['ancestry_groups']))
        require(self.groups.get('independent_scalar_oracle') is not None, 'oracle lineage must be explicit and independent')
        oracle = set(self.groups['independent_scalar_oracle'])
        require(all(not oracle.intersection(g) for a, g in self.groups.items() if a != 'independent_scalar_oracle'), 'oracle lineage mixed with native sources')
        self.payload = payload

    @property
    def enabled(self):
        return self.payload is not None

    def group(self, algorithm, family=None):
        if not self.enabled:
            return (family or algorithm,)
        require(algorithm in self.groups, 'unknown algorithm in explicit donor lineage: ' + algorithm)
        require(family is None or self.payload['algorithms'][algorithm]['adapter_family'] == family,
                'donor-lineage adapter-family mismatch: ' + algorithm)
        return self.groups[algorithm]

    def report(self):
        return {'enabled': self.enabled, 'config': self.path,
                'version': self.payload['version'] if self.enabled else None,
                'scope': 'conservative shared-ancestry sensitivity, not claim of identical implementation; original adapter-family LOFO retained',
                'resolved_algorithm_groups': self.groups}


class ReferenceImporter:
    def __init__(self, patterns, root, inputs, sha, legacy, lineage):
        self.root, self.inputs, self.sha, self.legacy, self.lineage = Path(root), inputs, sha, legacy, lineage
        self.exports = sorted({str(Path(p).resolve()) for pattern in patterns for p in glob.glob(pattern)})
        require(not patterns or self.exports, 'feasible-reference glob matched no files')
        self.cache, self.receipts, self.seen_occurrences, self.processed_models = {}, [], set(), set()
        self.file_bindings, self.derived = {}, {}
        self.total_imported = self.total_matched = self.total_occurrences = 0
        self.per_source = collections.defaultdict(collections.Counter)
        self.inventory = []
        self.offers = {}
        self.source_runs, self.status_rechecked_sources = {}, set()
        if not self.exports:
            self.inv = None
            return
        inv_path = self.root / 'analysis/summarize_native_auxiliary_v1.py'
        # Qualify the sole imported source-envelope helper before executing it.
        for path in self.exports:
            directory = Path(path).parent
            manifest = self.read_bound(directory / 'ARTIFACT_SHA256.json')
            require(isinstance(manifest, dict) and HEX.fullmatch(manifest.get('REPORT.json', '')), 'reference report SHA binding missing')
            report = self.read_bound(directory / 'REPORT.json', manifest['REPORT.json'])
            helpers = report.get('helper_files', {})
            expected_helper_sha = helpers.get(str(inv_path.resolve()))
            require(isinstance(expected_helper_sha, str) and HEX.fullmatch(expected_helper_sha), 'reference source-envelope helper binding missing')
            self.bind_file(inv_path, expected_helper_sha)
        spec = importlib.util.spec_from_file_location('native_reference_source_envelope_v1', inv_path)
        self.inv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.inv)
        for path in self.exports:
            self._receipt(Path(path))

    @staticmethod
    def stat_identity(path):
        stat = Path(path).stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def bind_file(self, path, expected=None):
        path = Path(path).resolve(strict=True)
        stamp = self.stat_identity(path)
        if str(path) in self.file_bindings:
            old_stamp, digest = self.file_bindings[str(path)]
            require(stamp == old_stamp, 'reference source changed after hash binding: ' + str(path))
        else:
            digest = self.sha(path)
            require(stamp == self.stat_identity(path), 'reference source changed while hashing: ' + str(path))
            self.file_bindings[str(path)] = (stamp, digest)
        require(expected is None or digest == expected, 'reference source SHA mismatch: ' + str(path))
        require(str(path) not in self.inputs or self.inputs[str(path)] == digest, 'reference source changed during evaluation')
        self.inputs[str(path)] = digest
        return path, digest

    def read_bound(self, path, expected=None, as_text=False):
        path, digest = self.bind_file(path, expected)
        key = (str(path), digest, as_text)
        if key not in self.cache:
            text = path.read_bytes().decode('utf-8')
            require(self.stat_identity(path) == self.file_bindings[str(path)][0], 'reference source changed while reading')
            self.cache[key] = text if as_text else strict_json(text)
        return self.cache[key]

    def close_batch(self):
        for path, (stamp, digest) in self.file_bindings.items():
            require(self.stat_identity(path) == stamp and self.sha(path) == digest,
                    'reference source changed before model batch acceptance: ' + path)
        self.cache.clear()
        self.derived.clear()
        self.file_bindings.clear()

    def _validate_offer_ledger(self, report, offers):
        runs, run_keys, campaign_plans = report.get('runs'), set(), {}
        require(isinstance(runs, list), 'reference source runs missing')
        for run in runs:
            campaign = str(Path(run['campaign']).resolve())
            run_key = (campaign, run['run_id'])
            require(run_key not in run_keys, 'duplicate reference source run ledger')
            run_keys.add(run_key)
            plan_path = Path(campaign) / 'plan.json'
            require(Path(run['frozen_plan_path']).resolve() == plan_path, 'reference run plan path differs')
            plan = self.read_bound(plan_path, run['frozen_plan_sha256'])
            campaign_plans[campaign] = plan
            specs = [s for s in plan['runs'] if s['id'] == run['run_id']]
            require(len(specs) == 1 and plan.get('evaluation_mode') == 'diagnostic', 'reference run not unique diagnostic native source')
            spec = specs[0]
            driver = self.inv.driver_for(spec['argv'])
            require(driver == run['driver'] and spec.get('family') == run['family']
                    and spec.get('window') == 'weekday-' + run['window'] + '-20261020', 'reference run driver/family/window differs')
            workload_path = Path(self.inv.flag(spec['argv'], '-queries')).resolve()
            require(workload_path == Path(run['workload_path']).resolve(), 'reference offered workload path differs')
            workload = self.read_bound(workload_path, run['workload_sha256'])
            require(workload.get('dataset_sha256') == run['dataset_sha256'], 'reference offered workload model differs')
            expected = self.inv.expected_items(workload, driver, spec['argv'])
            require(run_key not in self.source_runs, 'source run repeated across reference exports')
            self.source_runs[run_key] = {'report': run, 'plan': plan, 'spec': spec, 'expected': expected}
            rows = [x for x in offers if str(Path(x['campaign']).resolve()) == campaign and x['run_id'] == run['run_id']]
            require(len(rows) == len(expected) == run['offered'], 'reference run missing offered workload rows')
            seen = set()
            for row in rows:
                qid = row['query']['id']
                require(qid in expected and qid not in seen, 'duplicate/unknown offered reference row')
                seen.add(qid)
                native_q = expected[qid]['query']
                require(same_json(row['offered_native_query'], native_q) and same_json(row['query'], native_q.get('base', native_q))
                        and row['stratum'] == expected[qid]['stratum'], 'full offered reference query/stratum set differs')
                for field in ('family', 'window', 'dataset_path', 'dataset_sha256', 'workload_path', 'workload_sha256', 'frozen_plan_path', 'frozen_plan_sha256'):
                    require(row[field] == run[field], 'offered reference run provenance differs: ' + field)
                for field in ('native_algorithm', 'native_driver', 'native_source_sha256', 'native_routing_sha256',
                        'native_binary_sha256', 'command_sha256', 'result_sha256', 'source_process_status',
                        'native_manifest_sha256', 'native_pass_sha256', 'native_pass_file'):
                    require(row.get(field) == run.get(field), 'offered reference optional source provenance differs: ' + field)
            require(sum(r['native_complete'] for r in rows) == run['native_complete_rows'], 'source native completion denominator differs')
        require(all((str(Path(x['campaign']).resolve()), x['run_id']) in run_keys for x in offers), 'offered reference has no unique source run')
        for campaign, plan in campaign_plans.items():
            selected = {(campaign, s['id']) for s in plan['runs'] if s.get('family') in {'tad', 'range_raptor', 'trip_based'}
                        and s.get('window') in {'weekday-' + w + '-20261020' for w in ('evening', 'midday', 'morning', 'overnight')}}
            require(selected == {key for key in run_keys if key[0] == campaign}, 'missing/extra selected native source runs')

    def recheck_source_statuses(self, dataset_sha):
        """Derive presence/native completion for every matched-model offer.

        Independent materialization-status descriptions still belong to the
        source audit. Missing/invalid source bindings can never assert present
        or complete rows. Nonrecipient-model statuses remain explicitly asserted.
        """
        for source_key, source in self.source_runs.items():
            run, plan, spec, expected = (source[name] for name in ('report', 'plan', 'spec', 'expected'))
            if run['dataset_sha256'] != dataset_sha:
                continue
            offers = [o for o in self.offers.values() if (str(Path(o['campaign']).resolve()), o['run_id']) == source_key]
            if run.get('binding_status') == 'invalid_or_unresolved':
                require(all(o['native_row_present'] is False and o['native_complete'] is False for o in offers),
                        'invalid source binding claims present/complete offered rows')
                continue
            require(run.get('binding_status') == 'freeze_command_runtime_manifest_pass_bound', 'unknown source run binding status')
            campaign, run_dir = Path(source_key[0]), Path(source_key[0]) / source_key[1]
            freeze_ref = plan['auxiliary_input_source_freeze']
            freeze_path = Path(freeze_ref['path'])
            if not freeze_path.is_absolute():
                freeze_path = campaign / freeze_path
            freeze = self.read_bound(freeze_path, freeze_ref['sha256'])
            command = self.read_bound(run_dir / 'command.json', run['command_sha256'])
            result_path = run_dir / 'result.json'
            require(result_path.exists() == (run.get('result_sha256') is not None), 'source ledger result presence differs')
            result = self.read_bound(result_path, run['result_sha256']) if result_path.exists() else None
            argv, driver, role, recorded = self.inv.validate_envelope(spec, command, result, freeze, run_dir, campaign)
            self.bind_file(argv[0], command['binary']['sha256'])
            algorithm = self.inv.algorithm(argv, driver)
            require(run['native_source_sha256'] == role['go_source_hash_sha256']
                    and run['native_routing_sha256'] == role['routing_file_list_sha256']
                    and run['native_binary_sha256'] == command['binary']['sha256'], 'source ledger native provenance differs')
            require(run['source_process_status'] == {key: (result or {}).get(key) for key in
                    ('ok', 'returncode', 'termination', 'timed_out', 'source_contents_unchanged')}, 'source ledger process status differs')
            manifest_path = run_dir / 'artifact' / ('manifest.json' if driver in {'tadbench', 'profilebench'} else 'summary.json')
            rows, selected = {}, []
            if manifest_path.exists():
                manifest = self.read_bound(manifest_path, run['native_manifest_sha256'])
                self.inv.validate_manifest(manifest, command, role, driver, algorithm, dataset_sha, run['workload_sha256'])
                for desc in manifest.get('passes', manifest.get('summaries', [])):
                    if desc.get('warmup') or desc.get('forced') or desc.get('algorithm', algorithm) != algorithm:
                        continue
                    name = desc['file']
                    require(Path(name).name == name and name not in {'.', '..'}, 'unsafe source ledger pass name')
                    payload = self.read_bound(manifest_path.parent / name, desc['sha256'])
                    require(payload.get('algorithm') == algorithm and payload.get('warmup') is False
                            and payload.get('repetition') == desc.get('repetition') == 0, 'source ledger pass header differs')
                    selected.append(payload)
                    require(run.get('native_pass_sha256') == desc['sha256'] and run.get('native_pass_file') == name,
                            'source ledger selected pass provenance differs')
                require(len(selected) <= 1, 'source ledger has duplicate ordinary passes')
                if selected:
                    for row in selected[0]['records']:
                        query = row['query']; qid = query.get('base', query)['id']
                        require(qid in expected and qid not in rows and same_json(query, expected[qid]['query'])
                                and row.get('stratum') == expected[qid]['stratum'], 'source ledger raw row locator/query differs')
                        rows[qid] = row
                    require(set(rows) == set(expected), 'source ledger ordinary pass misses offered records')
                else:
                    require(not run.get('native_pass_sha256') and not run.get('native_pass_file'), 'source ledger claims nonexistent selected pass')
            else:
                require(not run.get('native_manifest_sha256'), 'source ledger manifest became missing')
            for offer in offers:
                row = rows.get(offer['query']['id'])
                complete_field = 'completed' if driver == 'familybench' else 'complete'
                complete = bool(row and row.get(complete_field) is True and not row.get('error'))
                require(offer['native_row_present'] == (row is not None) and offer['native_complete'] == complete,
                        'source ledger row presence/native completion differs from exact pass')
                require(offer.get('original_native_status') == (self.inv.row_status(row, driver) if row else None),
                        'source ledger native status differs from exact pass')
            self.status_rechecked_sources.add(source_key)

    def _receipt(self, path):
        directory = path.parent
        manifest = self.read_bound(directory / 'ARTIFACT_SHA256.json')
        require(isinstance(manifest, dict), 'reference artifact hash manifest missing')
        for name in (path.name, 'REPORT.json', 'OFFERED_NATIVE_ROWS.jsonl', 'FEASIBLE_REFERENCE_SCHEMA.json'):
            require(name in manifest and HEX.fullmatch(manifest[name]), 'reference receipt binding missing: ' + name)
            self.read_bound(directory / name, manifest[name], as_text=name.endswith('.jsonl'))
        report = self.read_bound(directory / 'REPORT.json', manifest['REPORT.json'])
        schema = self.read_bound(directory / 'FEASIBLE_REFERENCE_SCHEMA.json', manifest['FEASIBLE_REFERENCE_SCHEMA.json'])
        require(schema.get('properties', {}).get('schema', {}).get('const') == SCHEMA, 'reference schema document differs')
        require(report.get('feasible_reference_schema_sha256') == manifest['FEASIBLE_REFERENCE_SCHEMA.json'], 'audit schema SHA differs')
        require(report.get('schema') == 'sg-native-transit-independent-audit-v1', 'reference audit report schema differs')
        helper_files = report.get('helper_files', {})
        inventory_path = str((self.root / 'analysis/summarize_native_auxiliary_v1.py').resolve())
        self.bind_file(inventory_path, helper_files.get(inventory_path))
        require(inventory_path in helper_files, 'source-envelope helper missing from audit receipt')
        offers = []
        for line in self.read_bound(directory / 'OFFERED_NATIVE_ROWS.jsonl', manifest['OFFERED_NATIVE_ROWS.jsonl'], True).splitlines():
            offer = strict_json(line)
            key = (offer['dataset_sha256'], offer['campaign'], offer['run_id'], canonical_sha(offer['query']))
            require(key not in self.offers, 'duplicate offered native reference row')
            require(type(offer.get('native_complete')) is bool and type(offer.get('native_row_present')) is bool,
                    'reference offered status booleans malformed')
            self.offers[key] = offer
            offers.append(offer)
        require(report.get('offered_native_rows') == len(offers), 'full reference-source offered denominator mismatch')
        runs = report.get('runs')
        require(isinstance(runs, list) and sum(r['offered'] for r in runs) == len(offers), 'reference per-run denominator mismatch')
        for run in runs:
            offered = [x for x in offers if x['campaign'] == run['campaign'] and x['run_id'] == run['run_id']]
            require(len(offered) == run['offered'], 'reference run missing offered rows')
        self._validate_offer_ledger(report, offers)
        occurrence_count = sum(1 for line in self.read_bound(path, manifest[path.name], True).splitlines() if line)
        require(occurrence_count == report.get('feasible_reference_witness_occurrences'), 'full witness occurrence denominator mismatch')
        receipt = {'path': str(path), 'report': report, 'manifest': manifest, 'offers': offers, 'total_occurrences': occurrence_count,
                   'schema_sha256': manifest['FEASIBLE_REFERENCE_SCHEMA.json'], 'imported': 0, 'matched': 0, 'occurrences': 0}
        self.receipts.append(receipt)

    def _source(self, z, receipt):
        p, q = z['provenance'], z['query']
        source_key = (z['dataset_sha256'], p['campaign'], p['run_id'], canonical_sha(q))
        require(source_key in self.offers, 'witness has no full offered-source denominator row')
        offer = self.offers[source_key]
        require(offer['native_row_present'] is True, 'witness claims missing source row')
        require(z['native_family'] == p['family'] == offer['family'] and z['donor_family'] == p['donor_family'] == offer['donor_family'], 'native/donor family provenance mismatch')
        require(p['source_native_complete'] == offer['native_complete'] and p['source_independent_row_status'] == offer['status'], 'source independent/completion status mismatch')
        campaign = Path(p['campaign']).resolve()
        plan_path = campaign / 'plan.json'
        require(Path(p['frozen_plan_path']).resolve() == plan_path, 'source frozen-plan path mismatch')
        plan = self.read_bound(plan_path, p['frozen_plan_sha256'])
        specs = [s for s in plan['runs'] if s['id'] == p['run_id']]
        require(len(specs) == 1 and plan.get('evaluation_mode') == 'diagnostic', 'source run is not unique diagnostic native offer')
        spec = specs[0]
        freeze_ref = plan['auxiliary_input_source_freeze']
        freeze_path = Path(freeze_ref['path'])
        if not freeze_path.is_absolute():
            freeze_path = campaign / freeze_path
        freeze = self.read_bound(freeze_path, freeze_ref['sha256'])
        require(freeze.get('all_csa_execution_excluded') is True, 'reference source includes excluded CSA execution')
        run_dir = campaign / p['run_id']
        command = self.read_bound(run_dir / 'command.json', p['command_sha256'])
        result_path = run_dir / 'result.json'
        require(Path(p['command_path']).resolve() == (run_dir / 'command.json').resolve()
                and Path(p['result_path']).resolve() == result_path.resolve(), 'source process paths differ')
        require(result_path.exists() == (p['result_sha256'] is not None), 'source process result presence differs')
        result = self.read_bound(result_path, p['result_sha256']) if result_path.exists() else None
        process_status = {key: (result or {}).get(key) for key in ('ok', 'returncode', 'termination', 'timed_out', 'source_contents_unchanged')}
        require(p['source_process_status'] == process_status, 'source process status provenance differs')
        argv, driver, role, recorded = self.inv.validate_envelope(spec, command, result, freeze, run_dir, campaign)
        require(p['native_algorithm'] == self.inv.algorithm(argv, driver) and p['native_driver'] == driver,
                'source native algorithm/driver provenance differs')
        require(p['source_input_freeze'] == freeze_ref, 'source input freeze provenance differs')
        require(driver in {'tadbench', 'profilebench', 'familybench'}, 'nontransit/unknown reference source driver')
        require(spec.get('family') == z['native_family'], 'source plan native-family mismatch')
        require(p['native_source_sha256'] == role['go_source_hash_sha256'] and
                p['native_routing_sha256'] == role['routing_file_list_sha256'] and
                p['native_binary_sha256'] == command['binary']['sha256'], 'source build/routing/binary provenance mismatch')
        self.bind_file(argv[0], p['native_binary_sha256'])
        dataset_path = Path(self.inv.flag(argv, '-dataset')).resolve()
        workload_path = Path(self.inv.flag(argv, '-queries')).resolve()
        require(dataset_path == Path(p['dataset_path']).resolve() and z['dataset_sha256'] == p['dataset_sha256'], 'source model binding mismatch')
        self.bind_file(dataset_path, z['dataset_sha256'])
        require(workload_path == Path(p['workload_path']).resolve(), 'source workload path mismatch')
        workload = self.read_bound(workload_path, p['workload_sha256'])
        require(workload.get('dataset_sha256') == z['dataset_sha256'], 'source workload model differs')
        expected = self.inv.expected_items(workload, driver, argv)
        require(q['id'] in expected and same_json(expected[q['id']]['query'], offer['offered_native_query']), 'source query does not match full offered request')
        require(same_json(offer['offered_native_query'].get('base', offer['offered_native_query']), q), 'source base-query/caps/horizon differs')
        fragment_key = (str(workload_path), p['workload_sha256'])
        if fragment_key not in self.derived:
            self.derived[fragment_key] = workload_fragments(self.read_bound(workload_path, p['workload_sha256'], True), workload)
        fragments = self.derived[fragment_key]
        require(fragments[q['id']] == z['query_exact_workload_json_utf8'], 'exact source query bytes mismatch')
        artifact = run_dir / 'artifact'
        manifest_path = artifact / ('manifest.json' if driver in {'tadbench', 'profilebench'} else 'summary.json')
        manifest = self.read_bound(manifest_path, p['native_manifest_sha256'])
        require(Path(p['native_manifest_path']).resolve() == manifest_path.resolve(), 'source manifest path differs')
        algorithm = self.inv.algorithm(argv, driver)
        self.inv.validate_manifest(manifest, command, role, driver, algorithm, z['dataset_sha256'], p['workload_sha256'])
        name = p['native_pass_file']
        require(isinstance(name, str) and Path(name).name == name and name not in {'.', '..'}, 'unsafe reference pass path')
        descriptors = [d for d in manifest.get('passes', manifest.get('summaries', [])) if d.get('file') == name]
        require(len(descriptors) == 1, 'reference pass missing/duplicate descriptor')
        desc = descriptors[0]
        require(desc.get('sha256') == p['native_pass_sha256'] and desc.get('warmup') is False and not desc.get('forced')
                and desc.get('repetition') == p['native_repetition'] == 0 and p['native_warmup'] is False, 'reference pass is not exact ordinary pass')
        payload = self.read_bound(artifact / name, p['native_pass_sha256'])
        require(Path(p['native_pass_path']).resolve() == (artifact / name).resolve(), 'source pass path differs')
        require(payload.get('algorithm') == desc.get('algorithm', algorithm) == algorithm and payload.get('warmup') is False
                and payload.get('repetition') == 0 and isinstance(payload.get('records'), list), 'source pass header mismatch')
        index = p['native_record_index']
        require(type(index) is int and 0 <= index < len(payload['records']), 'source row locator invalid')
        row = payload['records'][index]
        require(same_json(row['query'], offer['offered_native_query']) and same_json(row['query'], p['source_native_query']), 'source located row full query differs')
        qid_matches = [r for r in payload['records'] if r.get('query', {}).get('base', r.get('query', {})).get('id') == q['id']]
        require(len(qid_matches) == 1, 'duplicate source rows')
        complete_key = 'completed' if driver == 'familybench' else 'complete'
        require(p['source_native_complete'] == (row.get(complete_key) is True and not row.get('error')), 'source native completion claim differs')
        stage, point, branch = p['native_stage'], p['source_point_index'], p['source_branch']
        require(stage in ('raw', 'final'), 'invalid source witness stage')
        if driver == 'profilebench':
            require(row['raw']['query'] == row['query'], 'source Raw.Query differs')
            if branch == 'transit_point':
                points = row['raw'].get('transit_points', []) if stage == 'raw' else row.get('final_points', [])
                require(type(point) is int and 0 <= point < len(points), 'source profile point index invalid')
                node = points[point]
                obj = node['journey'] if stage == 'raw' else node['validated']
                require(p['source_ready'] == node['latest_ready'] == p['source_latest_ready']
                        and q['departure'] <= p['source_ready'] <= row['query']['ready_window_end_inclusive'], 'source profile readiness differs/outside profile')
            elif branch == 'direct_walking':
                require(point is None and p['source_ready'] == q['departure'], 'source direct branch readiness/index differs')
                obj = row['raw']['direct_walking']['journey_at_window_start'] if stage == 'raw' else row['final_direct']
            else:
                raise ValueError('unknown source profile branch')
        else:
            require(branch == 'point_journey' and p['source_ready'] == q['departure'], 'source point branch/readiness differs')
            values = row.get(stage, [])
            require(type(point) is int and 0 <= point < len(values), 'source point witness index invalid')
            obj = values[point]
        original = obj.get('journey', obj)
        require(canonical_sha(original) == p['source_saved_journey_canonical_sha256'], 'original source-witness hash differs')
        locator = (str(campaign), p['run_id'], p['native_pass_sha256'], index, stage, branch, point)
        require(locator not in self.seen_occurrences, 'duplicate feasible-reference occurrence locator')
        self.seen_occurrences.add(locator)
        return original, obj, driver, algorithm, offer, locator

    def check_occurrence(self, z, receipt, checker, expected):
        fields = {'schema', 'kind', 'reference_only', 'scalar_optimality_claim', 'search_completeness_claim',
            'dataset_sha256', 'query', 'query_canonical_json_utf8', 'query_canonical_sha256',
            'query_exact_workload_json_utf8', 'query_exact_workload_bytes_sha256', 'native_family', 'donor_family', 'provenance', 'validated'}
        require(isinstance(z, dict) and set(z) == fields, 'missing/unknown feasible-reference fields')
        require(z.get('schema') == SCHEMA and z.get('kind') == 'independently_feasible_saved_native_witness'
                and z.get('reference_only') is True and z.get('scalar_optimality_claim') is False
                and z.get('search_completeness_claim') is False, 'reference cannot mint scalar/native completion authority')
        require(not (set(z) & {'result', 'weight', 'weight_index', 'complete', 'found', 'candidate_complete', 'delivery_k'}), 'oracle/serving fields forbidden in feasible reference')
        q, p = z['query'], z['provenance']
        require(HEX.fullmatch(z['dataset_sha256']) and isinstance(q, dict) and isinstance(p, dict), 'malformed reference model/query/provenance')
        require(type(p.get('source_native_complete')) is bool and type(p.get('source_feasible_at_emitted_ready')) is bool
                and type(p.get('native_repetition')) is int and type(p.get('saved_witness_occurrence_index')) is int
                and p['saved_witness_occurrence_index'] >= 0, 'malformed reference provenance types')
        require(z['query_canonical_json_utf8'] == canonical(q) and z['query_canonical_sha256'] == canonical_sha(q), 'reference full canonical query binding mismatch')
        fragment = z['query_exact_workload_json_utf8']
        require(hashlib.sha256(fragment.encode()).hexdigest() == z['query_exact_workload_bytes_sha256'] and strict_json(fragment) == q, 'reference exact query bytes/hash mismatch')
        key = (z['dataset_sha256'], q['id'])
        require(key not in expected or same_json(expected[key], q), 'reference same query ID differs in full recipient query/caps/horizon')
        require(p['materialized_ready'] == q['departure'] and p['readiness_contract'] == 'original base query readiness; fixed latest arrival', 'reference materialized readiness/horizon differs')
        original, source_obj, driver, algorithm, offer, locator = self._source(z, receipt)
        ready = p['source_ready']
        require(type(ready) is int and q['departure'] <= ready <= q['latest_arrival'], 'source readiness outside fixed horizon')
        source_q = copy.deepcopy(q)
        source_q['departure'] = ready
        validate_source_walk_anchor(checker, original, ready)
        source_error = None
        try:
            checker.query(source_q)
            checker.check(source_q, source_obj)
        except (self.legacy.ValidationError, KeyError, ValueError, TypeError) as exc:
            source_error = type(exc).__name__ + ': ' + str(exc)
        require(p['source_feasible_at_emitted_ready'] == (source_error is None)
                and p['source_ready_validation_error'] == source_error, 'source-ready feasibility provenance differs')
        if driver == 'profilebench':
            require(p['transformation'] == PREFIX_TRANSFORM, 'unknown profile transformation')
            transformed, seconds, count = reanchor_prefix(checker, original, q['departure'])
        else:
            require(p['transformation'] == IDENTITY_TRANSFORM, 'point witness must use identity transformation')
            transformed, seconds, count = copy.deepcopy(original), 0, 0
            for leg in original['legs']:
                if leg['kind'] != 'walk':
                    break
                seconds += checker.walks[leg['ref']]['duration']
                count += 1
        require(p['source_initial_walking_seconds'] == seconds, 'initial walking-prefix duration differs')
        require(p['transformed_journey_canonical_sha256'] == canonical_sha(transformed), 'transformation hash mismatch')
        checker.query(q)
        checked = checker.check(q, transformed)  # Raw journey only: never trust source-ready metrics.
        require(same_json(p['source_ready_query'], source_q), 'source readiness query/caps/horizon differs')
        require(p['transform_kind'] == ('reanchor_initial_contiguous_walks' if driver == 'profilebench' else 'identity')
                and p['transformed_initial_leg_count'] == (count if driver == 'profilebench' else 0), 'transform kind/prefix count differs')
        require(p['dataset_schema_version'] == checker.d['schema_version'] and p['dataset_id'] == checker.d['id'], 'source recipient model schema/id differs')
        require(checked == z['validated'], 'exported identity/metrics/pattern/journey differ from recipient reconstruction')
        group = self.lineage.group(algorithm)
        return key, checked, group, {'source': str(receipt['path']), 'source_schema_sha256': receipt['schema_sha256'],
                'source_audit_report_sha256': receipt['manifest']['REPORT.json'],
                'query_canonical_sha256': z['query_canonical_sha256'], 'native_family': z['native_family'],
                'donor_family': z['donor_family'], 'donor_group': group, 'algorithm': algorithm,
                'provenance': copy.deepcopy(p), 'independent_recheck': 'exact recipient model/full query/caps/fixed horizon',
                'reanchored_prefix_legs': count if driver == 'profilebench' else 0}

    def import_dataset(self, dataset_sha, checker, expected, pool, identity):
        if dataset_sha in self.processed_models:
            return
        self.processed_models.add(dataset_sha)
        self.recheck_source_statuses(dataset_sha)
        for receipt in self.receipts:
            path = Path(receipt['path'])
            for line_number, line in enumerate(self.read_bound(path, receipt['manifest'][path.name], True).splitlines(), 1):
                z = strict_json(line)
                if z.get('dataset_sha256') != dataset_sha:
                    continue
                key, checked, group, provenance = self.check_occurrence(z, receipt, checker, expected)
                receipt['occurrences'] += 1
                self.total_occurrences += 1
                source = (z['dataset_sha256'], z['provenance']['campaign'], z['provenance']['run_id'])
                self.per_source[source]['rechecked_occurrences'] += 1
                if key not in expected:
                    self.per_source[source]['unmatched_occurrences'] += 1
                    continue
                iv = identity(checked['identity'])
                entry = pool[key].setdefault(iv, {'journey': checked, 'families': set(), 'contributors': set(), 'donor_lineages': set()})
                require(entry['journey']['metrics'] == checked['metrics'] and entry['journey']['duration_seconds'] == checked['duration_seconds'], 'conflicting same-identity reference objective metrics')
                entry['families'].add(z['donor_family'])
                entry['contributors'].add('feasible_native_reference:' + z['provenance']['run_id'])
                entry.setdefault('donor_lineages', set()).add(group)
                entry.setdefault('reference_provenance', []).append(provenance)
                self.inventory.append({'dataset_sha256': dataset_sha, 'query_id': z['query']['id'],
                    'identity': checked['identity'], 'reference_only': True, **provenance})
                receipt['matched'] += 1
                self.total_matched += 1
                self.per_source[source]['matched_occurrences'] += 1
        self.close_batch()  # Bound native payloads never accumulate across model/window batches.

    def finalize(self, out):
        self.close_batch()
        source_metadata = {}
        source_statuses = collections.defaultdict(collections.Counter)
        for offer in self.offers.values():
            source = (offer['dataset_sha256'], offer['campaign'], offer['run_id'])
            source_metadata[source] = {key: offer.get(key) for key in ('family', 'donor_family', 'window',
                'workload_path', 'workload_sha256', 'frozen_plan_path', 'frozen_plan_sha256', 'native_source_sha256',
                'native_routing_sha256', 'native_binary_sha256', 'result_path', 'result_sha256', 'source_process_status')}
            source_statuses[source][offer['status']] += 1
            counts = self.per_source[source]
            counts['offered_rows'] += 1
            counts['source_native_complete_rows'] += offer['native_complete']
            counts['source_unknown_or_incomplete_rows'] += not offer['native_complete']
            counts['source_missing_rows'] += not offer['native_row_present']
        summary = {'schema': 'sg-feasible-native-reference-import-v1', 'source_exports': self.exports,
            'offered_native_reference_rows': len(self.offers), 'rechecked_witness_occurrences': self.total_occurrences,
            'matched_recipient_witness_occurrences': self.total_matched,
            'unrechecked_nonrecipient_model_occurrences': sum(r['total_occurrences'] - r['occurrences'] for r in self.receipts),
            'offered_serving_rows_added': 0, 'completed_serving_rows_added': 0, 'scalar_slots_added': 0,
            'source_denominators': [{'dataset_sha256': key[0], 'campaign': key[1], 'run_id': key[2],
                **source_metadata[key], 'independent_materialization_statuses_source_audit_asserted': dict(source_statuses[key]),
                'native_presence_and_completion_rechecked_from_pass': (str(Path(key[1]).resolve()), key[2]) in self.status_rechecked_sources,
                **dict(counts)}
                for key, counts in sorted(self.per_source.items())],
            'scope': 'feasible native witnesses enrich incomplete union only; source status/completion never promotes recipient serving completion or scalar optimality'}
        for name, value in [('FEASIBLE_REFERENCE_IMPORT.json', summary), ('FEASIBLE_REFERENCE_PROVENANCE.json', self.inventory)]:
            (Path(out) / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')
        return summary
