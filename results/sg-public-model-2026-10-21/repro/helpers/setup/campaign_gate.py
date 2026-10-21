"""Hash-bound evaluation workflow checks. Not an adversarial security boundary."""
import hashlib
import json
import datetime as dt
from pathlib import Path
import subprocess
from urllib.parse import urlparse

SCHEMA = 'predeclared-workload-registry-v1'
SEAL_SCHEMA = 'final-evaluation-seal-v1'
PUBLIC_FINAL_MODE = 'public_model_final_evaluation'
PUBLIC_SEAL_SCHEMA = 'public-model-final-evaluation-seal-v1'
FINAL_MODES = {'final_evaluation', PUBLIC_FINAL_MODE}
SPLITS = {'tune', 'validation', 'test', 'diagnostic'}
FINAL_NAMES = {'test', 'heldout', 'held_out', 'final', *FINAL_MODES}
SOURCE_POLICY = Path(__file__).resolve().parent / 'source-eligibility-policy.json'
POLICY = {
    'heldout_execution_gate': 'Requires an exact mode-specific finalist seal, registered test workloads, and a hash-bound data audit plus separate accepted review for the explicitly selected official or public-model tier; no SG execution is performed by checking artifacts.',
    'formal_sg_baseline_gate': 'Requires a separately reviewed latest-official LTA bus+rail qualification covering actual input hashes. Community/July model inputs remain provisional regardless of a matching seal.',
    'public_model_gate': 'Only explicit public_model_final_evaluation may qualify reviewed public-model input bytes, including known provisional community inputs. This tier never establishes latest-official authenticity or formal latest-official baseline eligibility.',
    'scope': 'Read-only artifact checks and local workflow consistency do not authorize execution or expand the approved task.',
    'security_claim': 'No adversarial tamper resistance, immutable timestamp, secrecy, access control, or independent data-truth attestation is claimed.',
}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def identity(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError(f'Not a regular file: {path}')
    return {'path': str(path), 'sha256': digest(path), 'bytes': path.stat().st_size}


def resolve(path, base):
    p = Path(path)
    return (p if p.is_absolute() else base / p).resolve(strict=True)


def check_identity(ref, base, label):
    if not isinstance(ref, dict) or not ref.get('path') or not ref.get('sha256'):
        raise ValueError(f'{label} requires path and predeclared sha256')
    actual = identity(resolve(ref['path'], base))
    if actual['sha256'] != ref['sha256'] or ('bytes' in ref and actual['bytes'] != ref['bytes']):
        raise ValueError(f'{label} content changed: {actual["path"]}')
    return actual


def module_root(cwd):
    cwd = Path(cwd).resolve(strict=True)
    for parent in (cwd, *cwd.parents):
        if (parent / 'go.mod').is_file():
            return parent
    return None


def metadata_split(meta, label):
    declared = meta.get('split')
    values = {item.get('split') for item in meta.get('items', [])}
    values.discard(None)
    if declared is not None:
        values.add(declared)
    if not values or len(values) != 1 or next(iter(values)) not in SPLITS:
        raise ValueError(f'{label} must declare one unambiguous recognized split')
    return next(iter(values))


def query_ids(path):
    q = json.loads(Path(path).read_text())
    if isinstance(q, list):
        items = q
    elif isinstance(q, dict) and isinstance(q.get('queries'), list):
        items = q['queries']
    elif isinstance(q, dict) and isinstance(q.get('items'), list):
        if any(not isinstance(x, dict) or not isinstance(x.get('query'), dict) for x in q['items']):
            raise ValueError(f'Malformed familybench item/query shape: {path}')
        items = [x['query'] for x in q['items']]
    else:
        raise ValueError(f'Unsupported registered query container: {path}')
    result = [x.get('id', x.get('query_id')) for x in items]
    if any(not isinstance(x, str) or not x for x in result) or len(set(result)) != len(result):
        raise ValueError(f'Registered workload requires distinct query IDs: {path}')
    return result


def validate_entry(entry, base):
    split = entry.get('split')
    if split not in SPLITS:
        raise ValueError('Registry entry has an unrecognized split')
    workload = check_identity(entry.get('workload'), base, 'Registered workload')
    metadata = check_identity(entry.get('metadata'), base, 'Registered metadata')
    meta = json.loads(Path(metadata['path']).read_text())
    if meta.get('queries_sha256') != workload['sha256']:
        raise ValueError('Metadata is not hash-bound to this registered workload')
    workload_contents = json.loads(Path(workload['path']).read_text())
    if isinstance(workload_contents, dict) and 'items' in workload_contents:
        if not workload_contents.get('dataset_sha256') or workload_contents['dataset_sha256'] != meta.get('dataset_sha256'):
            raise ValueError('Workload/metadata dataset SHA mismatch')
    if metadata_split(meta, metadata['path']) != split:
        raise ValueError('Registry split disagrees with hash-bound metadata')
    actual_ids = query_ids(workload['path'])
    metadata_ids = [x.get('query_id') for x in meta.get('items', [])]
    if len(set(metadata_ids)) != len(metadata_ids) or sorted(metadata_ids) != sorted(actual_ids):
        raise ValueError('Metadata/query ID coverage is not exact')
    return {**entry, 'workload': workload, 'metadata': metadata, 'metadata_contents': meta}


def load_registry(plan, base):
    ref = plan.get('workload_registry')
    if ref is None:
        return None
    registry_file = check_identity(ref, base, 'Predeclared registry')
    payload = json.loads(Path(registry_file['path']).read_text())
    if payload.get('schema') != SCHEMA or not isinstance(payload.get('entries'), list):
        raise ValueError('Unsupported workload registry schema')
    if payload.get('source_manifest') is not None:
        check_identity(payload['source_manifest'], Path(registry_file['path']).parent, 'Registry source manifest')
    entries = [validate_entry(e, Path(registry_file['path']).parent) for e in payload['entries']]
    by_hash, by_path, id_splits = {}, {}, {}
    for entry in entries:
        sha, path = entry['workload']['sha256'], entry['workload']['path']
        if sha in by_hash and (by_hash[sha]['split'] != entry['split'] or by_hash[sha]['metadata']['sha256'] != entry['metadata']['sha256']):
            raise ValueError('Workload SHA has conflicting split/metadata registrations')
        if path in by_path:
            raise ValueError('Workload path registered more than once')
        by_hash[sha], by_path[path] = entry, entry
        for item in entry['metadata_contents']['items']:
            id_splits.setdefault(item['query_id'], set()).add(entry['split'])
    if any('test' in splits and len(splits) > 1 for splits in id_splits.values()):
        raise ValueError('Registered test query ID also occurs in a development split')
    return {'file': registry_file, 'payload': payload, 'entries': entries, 'by_hash': by_hash, 'by_path': by_path,
            'test_query_ids': {qid for qid, splits in id_splits.items() if 'test' in splits}}


def flags(argv, name):
    result = []
    for i, arg in enumerate(argv):
        accepted = ('-' + name.lstrip('-'), '--' + name.lstrip('-'))
        if arg in accepted:
            if i + 1 >= len(argv):
                raise ValueError(f'Missing value for {name}')
            result.append(argv[i + 1])
        elif any(arg.startswith(flag + '=') for flag in accepted):
            result.append(arg.split('=', 1)[1])
    return result


def classify(bound_inputs, argv, cwd, registry=None, inspect_heldout=False):
    inputs = list(dict.fromkeys(str(Path(x).resolve(strict=True)) for x in bound_inputs))
    workloads = []
    has_unregistered_test_metadata = False
    for value in list(inputs):
        p = Path(value)
        if '.test.' in p.name:
            has_unregistered_test_metadata = True
        if p.suffix == '.json' and not p.name.endswith('.metadata.json'):
            sidecar = p.with_suffix('.metadata.json')
            if sidecar.is_file():
                meta = json.loads(sidecar.read_text())
                if meta.get('queries_sha256') is not None and meta['queries_sha256'] != digest(p):
                    raise ValueError(f'Adjacent metadata/query hash mismatch: {p}')
                if meta.get('split') in FINAL_NAMES or any(x.get('split') in FINAL_NAMES for x in meta.get('items', [])):
                    has_unregistered_test_metadata = True
                if str(sidecar) not in inputs:
                    inputs.append(str(sidecar))
        if p.name.endswith('.metadata.json'):
            meta = json.loads(p.read_text())
            if meta.get('split') in FINAL_NAMES or any(x.get('split') in FINAL_NAMES for x in meta.get('items', [])):
                has_unregistered_test_metadata = True
    query_values = list(flags(argv, '-queries'))
    if registry:
        for value in inputs:
            known = value in registry['by_path'] or digest(value) in registry['by_hash']
            overlapping_test_ids = False
            # Explicit JSON inputs can themselves be query workloads, even
            # without a -queries flag. Only promote unknown inputs with known
            # test-ID overlap here, not arbitrary non-workload configuration.
            if not known and Path(value).suffix == '.json' and not value.endswith('.metadata.json'):
                try:
                    overlapping_test_ids = bool(set(query_ids(value)) & registry['test_query_ids'])
                except (ValueError, TypeError, AttributeError, UnicodeError):
                    pass
            if known or overlapping_test_ids:
                if value not in query_values:
                    query_values.append(value)
    for value in query_values:
        p = resolve(value, cwd)
        actual = identity(p)
        entry = registry['by_hash'].get(actual['sha256']) if registry else None
        # A known path with changed bytes must never silently become unknown.
        if registry and str(p) in registry['by_path'] and entry is None:
            raise ValueError(f'Registered query path changed: {p}')
        if entry:
            sidecar = p.with_suffix('.metadata.json')
            if sidecar.is_file() and digest(sidecar) != entry['metadata']['sha256']:
                raise ValueError(f'Adjacent metadata differs from registry: {sidecar}')
            if entry['metadata']['path'] not in inputs:
                inputs.append(entry['metadata']['path'])
            workloads.append({'workload': actual, 'classification': entry['split'], 'registered': True,
                              'metadata': entry['metadata'], 'source_metadata': entry.get('source_metadata'),
                              'metadata_provenance': {k: v for k, v in entry['metadata_contents'].items() if k != 'items'},
                              'dataset_sha256': entry['metadata_contents'].get('dataset_sha256'),
                              'heldout_safe_qualification': False})
        else:
            overlaps = []
            if registry:
                try:
                    overlaps = sorted(set(query_ids(p)) & registry['test_query_ids'])
                except (ValueError, TypeError, json.JSONDecodeError):
                    pass
            workloads.append({'workload': actual, 'classification': 'unknown', 'registered': False,
                              'heldout_safe_qualification': False,
                              'registered_test_query_id_overlap': overlaps,
                              'reason': 'No matching predeclared workload SHA plus hash-bound metadata registration; diagnostic only.'})
    heldout = has_unregistered_test_metadata or any(w['classification'] == 'test' or w.get('registered_test_query_id_overlap') for w in workloads)
    if heldout and not inspect_heldout:
        raise ValueError('Held-out/test execution is prohibited, even with a matching finalist seal')
    return {'bound_inputs': inputs, 'registry': registry['file'] if registry else None,
            'classification': 'test' if heldout else ('unknown' if any(not w['registered'] for w in workloads) else ('no_query_workload' if not workloads else 'registered_development')),
            'workloads': workloads, 'heldout_detected': heldout, 'heldout_safe_qualification': False,
            'policy': POLICY, 'registry_provenance': registry['payload'].get('provenance') if registry else None}


def reject_execution_claims(plan, final_gate_passed=False):
    if plan.get('evaluation_mode', 'diagnostic') in FINAL_NAMES and not final_gate_passed:
        raise ValueError('Final/held-out execution requires a validated exact mode-specific seal and reviewed data qualification')
    if plan.get('heldout_safe') or plan.get('formal_sg_baseline'):
        raise ValueError('This runner cannot grant heldout-safe or formal SG baseline qualification')
    for run in plan.get('runs', []):
        if (run.get('split') in FINAL_NAMES or run.get('stage') in FINAL_NAMES or run.get('heldout_safe')) and not final_gate_passed:
            raise ValueError('Run requests prohibited held-out/final qualification or execution')


def registry_from_manifest(manifest_path):
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest = json.loads(manifest_path.read_text())
    entries = []
    for item in manifest.get('files', []):
        workload_path = resolve(item['path'], manifest_path.parent)
        metadata_path = workload_path.with_suffix('.metadata.json')
        entry = {'split': item['split'],
                 'workload': {'path': str(workload_path), 'sha256': item['sha256']},
                 'metadata': {'path': str(metadata_path), 'sha256': item['query_metadata_sha256']},
                 'source_metadata': item}
        validated = validate_entry(entry, manifest_path.parent)
        validated.pop('metadata_contents')
        entries.append(validated)
    if not entries:
        raise ValueError('Registry manifest has no workload entries')
    return {'schema': SCHEMA, 'source_manifest': identity(manifest_path),
            'provenance': {k: v for k, v in manifest.items() if k != 'files'},
            'entries': entries, 'policy': POLICY}


def source_tree_snapshot(root):
    root = Path(root).resolve(strict=True)
    # Capture tracked plus untracked nonignored source/support bytes, not only
    # .go files. Explicit input bindings cover separately stored dependencies.
    output = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'])
    records = []
    for raw in sorted(set(output.split(b'\0')) - {b''}):
        rel = raw.decode()
        p = root / rel
        if p.is_symlink():
            raise ValueError(f'Finalist source symlinks require an explicit resolved dependency contract: {p}')
        if not p.is_file():
            raise ValueError(f'Finalist source file missing: {p}')
        records.append({'path': rel, 'sha256': digest(p), 'bytes': p.stat().st_size})
    return {'root': str(root), 'file_count': len(records), 'manifest_sha256': canonical_hash(records), 'files': records}


def reviewed_data_qualification(plan, base, prepared):
    """Validate recorded review bindings, not the truth of an official-source claim."""
    manifest_file = check_identity(plan.get('data_qualification'), base, 'Official-data qualification manifest')
    manifest = json.loads(Path(manifest_file['path']).read_text())
    if manifest.get('schema') != 'official-lta-evaluation-qualification-v1':
        raise ValueError('Unrecognized official-data qualification schema')
    if manifest.get('formal_baseline_eligible') is not True or manifest.get('source_status') != 'reviewed_latest_official_lta_bus_and_rail':
        raise ValueError('Data is provisional, community-derived, stale, or not eligible for a formal latest-official LTA baseline')
    mbase = Path(manifest_file['path']).parent
    audit_file = check_identity(manifest.get('audit'), mbase, 'Official-data audit')
    review_file = check_identity(manifest.get('review'), mbase, 'Separate official-data review record')
    audit = json.loads(Path(audit_file['path']).read_text())
    review = json.loads(Path(review_file['path']).read_text())
    if audit.get('schema') != 'official-lta-data-audit-v1' or audit.get('formal_baseline_eligible') is not True:
        raise ValueError('Official-data audit does not qualify formal evaluation')
    if audit.get('data_origin') != 'official_lta' or audit.get('freshness') != 'latest_at_acquisition':
        raise ValueError('Audit does not establish the required latest-official acquisition scope')
    if audit.get('coverage') != {'bus': True, 'rail': True} or not audit.get('acquired_utc') or not audit.get('sources'):
        raise ValueError('Audit must record bus+rail scope, acquisition time and source evidence')
    artifacts = []
    for source in audit['sources']:
        parsed = urlparse(source.get('source_url', ''))
        if (parsed.scheme != 'https' or not parsed.hostname or
                not (parsed.hostname == 'lta.gov.sg' or parsed.hostname.endswith('.lta.gov.sg') or parsed.hostname == 'datamall2.mytransport.sg')
                or not source.get('acquired_utc') or source.get('source_owner') != 'Land Transport Authority'):
            raise ValueError('Audit source evidence requires official LTA acquisition URL, owner and timestamp, not a qualification boolean')
        artifacts.append(check_identity(source.get('artifact'), Path(audit_file['path']).parent, 'Audited official source artifact'))
    if (review.get('schema') != 'official-lta-data-review-v1' or review.get('decision') != 'accept_for_bound_evaluation_only'
            or review.get('reviewed_audit_sha256') != audit_file['sha256'] or not review.get('reviewer') or not review.get('basis')):
        raise ValueError('No matching separate accepted data-audit review record')
    try:
        parse = lambda s: dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
        acquired = parse(audit['acquired_utc'])
        checked = parse(audit['latest_checked_utc'])
        reviewed = parse(review['reviewed_utc'])
        expires = parse(manifest['valid_until_utc'])
        now = dt.datetime.now(dt.timezone.utc)
        if review['valid_until_utc'] != manifest['valid_until_utc'] or not (acquired <= checked <= reviewed <= now <= expires):
            raise ValueError('Data review freshness window is expired or inconsistent')
    except (KeyError, TypeError) as exc:
        raise ValueError('Qualification requires a reviewed, explicitly bounded latest-check/freshness window') from exc
    refs = manifest.get('inputs', [])
    if not refs:
        raise ValueError('Qualification manifest must bind the actual normalized input files')
    inputs = [check_identity(r, mbase, 'Qualified normalized input') for r in refs]
    approved = set(review.get('approved_input_sha256', []))
    audited = set(audit.get('normalized_input_sha256', []))
    actual_hashes = {x['sha256'] for x in inputs}
    source_policy = json.loads(SOURCE_POLICY.read_text())
    denied = {x['sha256'] for x in source_policy.get('denied_normalized_inputs', [])}
    if actual_hashes & denied:
        raise ValueError('Known provisional community/July normalized input is blocked for formal baseline regardless of seal or qualification labels')
    if set(audit.get('raw_source_sha256', [])) & set(source_policy.get('known_community_raw_sha256', [])):
        raise ValueError('Known provisional community raw source is blocked for formal baseline')
    if {x['sha256'] for x in artifacts} & set(source_policy.get('known_community_raw_sha256', [])):
        raise ValueError('Known provisional community raw artifact is blocked for formal baseline')
    if actual_hashes != approved or actual_hashes != audited:
        raise ValueError('Manifest/audit/review disagree on the qualified normalized input hashes')
    for run in prepared:
        def provisional(value):
            if not isinstance(value, dict):
                return False
            if (value.get('formal_baseline_eligible') is False or value.get('latest_official_transit_feed') is False or value.get('provisional') is True):
                return True
            status = str(value.get('source_status', '')).lower()
            return any(word in status for word in ('provisional', 'community', 'unofficial', 'synthetic'))
        workload_gate = run.get('workload_gate', {})
        if provisional(workload_gate.get('registry_provenance')):
            raise ValueError('Registry preserves provisional source qualification; cannot promote it through a finalist seal')
        for workload in workload_gate.get('workloads', []):
            if provisional(workload.get('source_metadata')) or provisional(workload.get('metadata_provenance')):
                raise ValueError('Workload metadata preserves provisional source qualification; final execution is blocked')
        datasets = flags(run['argv'], '-dataset')
        if len(datasets) != 1:
            raise ValueError('Final SG run requires exactly one explicitly bound -dataset input')
        actual = identity(resolve(datasets[0], Path(run['cwd'])))
        if actual['sha256'] not in actual_hashes:
            raise ValueError('Final run dataset is not covered by the reviewed official-data qualification')
    return {'manifest': manifest_file, 'manifest_contents': manifest, 'audit': audit_file, 'audit_contents': audit,
            'review': review_file, 'review_contents': review, 'inputs': inputs, 'audited_source_artifacts': artifacts,
            'qualification_kind': 'Hash-bound recorded review, not independent attestation of source truth', 'policy': POLICY}


def reviewed_public_model_qualification(plan, base, prepared):
    """Check bounded modeled-data review, never official authenticity or truth."""
    if plan.get('evaluation_mode') != PUBLIC_FINAL_MODE:
        raise ValueError('Public-model qualification requires explicit public_model_final_evaluation mode')
    manifest_file = check_identity(plan.get('data_qualification'), base, 'Public-model qualification manifest')
    manifest = json.loads(Path(manifest_file['path']).read_text())
    if (manifest.get('schema') != 'public-model-evaluation-qualification-v1'
            or manifest.get('evaluation_tier') != 'public_model'
            or manifest.get('source_status') != 'reviewed_public_model_bus_and_rail'):
        raise ValueError('Unrecognized or non-public modeled-data qualification tier/schema')
    mbase = Path(manifest_file['path']).parent
    audit_file = check_identity(manifest.get('audit'), mbase, 'Public-model data audit')
    review_file = check_identity(manifest.get('review'), mbase, 'Separate public-model review record')
    audit = json.loads(Path(audit_file['path']).read_text())
    review = json.loads(Path(review_file['path']).read_text())
    if (audit.get('schema') != 'public-model-data-audit-v1' or audit.get('data_origin') != 'public_model'
            or audit.get('coverage') != {'bus': True, 'rail': True}):
        raise ValueError('Public-model audit must identify modeled origin and bus+rail scope')
    # Retain original provisional provenance. An explicit public tier is not a
    # way to relabel community/model bytes as a latest-official baseline.
    for label, value in (('qualification', manifest), ('audit', audit)):
        if value.get('formal_baseline_eligible') is not False or value.get('latest_official_transit_feed') is not False:
            raise ValueError(f'Public-model {label} must explicitly deny formal/latest-official eligibility')
    def reject_official_claims(value):
        if not isinstance(value, dict):
            return
        if (value.get('formal_baseline_eligible') is True or value.get('formal_sg_baseline') is True
                or value.get('latest_official_transit_feed') is True
                or value.get('official_source_authenticity_established') is True
                or value.get('source_status') == 'reviewed_latest_official_lta_bus_and_rail'):
            raise ValueError('Public-model tier cannot make formal/latest-official authenticity claims')
    reject_official_claims(plan)
    reject_official_claims(plan.get('source_provenance'))
    for value in (manifest, audit, review):
        reject_official_claims(value)
    for field in ('model_assumptions', 'limitations'):
        if (not isinstance(audit.get(field), list) or not audit[field]
                or any(not isinstance(x, str) or not x.strip() for x in audit[field])):
            raise ValueError(f'Public-model audit requires explicit nonempty {field}')
    sources = audit.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ValueError('Public-model audit requires hash-bound public source evidence')
    artifacts = []
    for source in sources:
        parsed = urlparse(source.get('source_url', ''))
        if parsed.scheme != 'https' or not parsed.hostname or not source.get('source_owner') or not source.get('acquired_utc'):
            raise ValueError('Public-model source requires HTTPS URL, owner and acquisition timestamp')
        artifacts.append(check_identity(source.get('artifact'), Path(audit_file['path']).parent, 'Audited public source artifact'))
    if (review.get('schema') != 'public-model-data-review-v1'
            or review.get('evaluation_tier') != 'public_model'
            or review.get('decision') != 'accept_for_bound_public_model_evaluation_only'
            or review.get('reviewed_audit_sha256') != audit_file['sha256']
            or not review.get('reviewer') or not review.get('basis')):
        raise ValueError('No matching separate accepted public-model audit review record')
    try:
        parse = lambda s: dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
        acquired = parse(audit['acquired_utc'])
        reviewed = parse(review['reviewed_utc'])
        expires = parse(manifest['valid_until_utc'])
        now = dt.datetime.now(dt.timezone.utc)
        source_times = [parse(source['acquired_utc']) for source in sources]
        if (review['valid_until_utc'] != manifest['valid_until_utc']
                or not (acquired <= reviewed <= now <= expires)
                or any(t > reviewed for t in source_times)):
            raise ValueError('Public-model review validity window is expired or inconsistent')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Public-model qualification requires an explicit bounded review validity window') from exc
    refs = manifest.get('inputs', [])
    if not refs:
        raise ValueError('Public-model qualification must bind actual normalized input files')
    inputs = [check_identity(r, mbase, 'Qualified public-model input') for r in refs]
    actual_hashes = {x['sha256'] for x in inputs}
    if (actual_hashes != set(audit.get('normalized_input_sha256', []))
            or actual_hashes != set(review.get('approved_input_sha256', []))):
        raise ValueError('Public-model manifest/audit/review disagree on exact normalized input hashes')
    actual_datasets = []
    for run in prepared:
        workload_gate = run.get('workload_gate', {})
        reject_official_claims(workload_gate.get('registry_provenance'))
        for workload in workload_gate.get('workloads', []):
            reject_official_claims(workload.get('source_metadata'))
            reject_official_claims(workload.get('metadata_provenance'))
        datasets = flags(run['argv'], '-dataset')
        if len(datasets) != 1:
            raise ValueError('Public-model final run requires exactly one explicitly bound -dataset input')
        actual_datasets.append(identity(resolve(datasets[0], Path(run['cwd']))))
    if {(x['path'], x['sha256']) for x in actual_datasets} != {(x['path'], x['sha256']) for x in inputs}:
        raise ValueError('Public-model qualified input files must exactly equal the final plan datasets')
    return {'manifest': manifest_file, 'manifest_contents': manifest, 'audit': audit_file, 'audit_contents': audit,
            'review': review_file, 'review_contents': review, 'inputs': inputs, 'audited_source_artifacts': artifacts,
            'evaluation_tier': 'public_model', 'formal_baseline_eligible': False, 'latest_official_transit_feed': False,
            'official_source_authenticity_established': False,
            'qualification_kind': 'Hash-bound recorded review for bounded modeled use only; not authenticity or physical truth', 'policy': POLICY}


def qualification_binding(plan, base):
    """Bind even an explicitly provisional qualification without promoting it."""
    if plan.get('data_qualification') is None:
        return None
    manifest_file = check_identity(plan['data_qualification'], base, 'Data qualification manifest')
    manifest = json.loads(Path(manifest_file['path']).read_text())
    result = {'manifest': manifest_file, 'manifest_contents': manifest, 'supporting_files': []}
    for field in ('audit', 'review'):
        if manifest.get(field) is not None:
            result['supporting_files'].append(check_identity(manifest[field], Path(manifest_file['path']).parent, f'Data {field}'))
    if manifest.get('audit') is not None:
        audit_path = resolve(manifest['audit']['path'], Path(manifest_file['path']).parent)
        audit = json.loads(audit_path.read_text())
        for source in audit.get('sources', []):
            if source.get('artifact') is not None:
                result['supporting_files'].append(check_identity(source['artifact'], audit_path.parent, 'Audited raw source artifact'))
    for ref in manifest.get('inputs', []):
        result['supporting_files'].append(check_identity(ref, Path(manifest_file['path']).parent, 'Data qualification input'))
    return result
