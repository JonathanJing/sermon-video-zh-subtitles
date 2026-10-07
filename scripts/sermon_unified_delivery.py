"""Closed canonical App delivery adapter: reviewed products -> local candidate -> authorized publication.

inspect is local/read-only. execute defaults to prepare. Publication consumes an
existing exact-release authorization; no code path creates human approval. A
text or listening gate may be passed by an exact machine quality waiver; that
locale is released as machine_checked (release v4), never as human-reviewed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from jsonschema import Draft202012Validator, FormatChecker
from scripts import build_full_video_app_release as builder
from scripts import delivery_contract as d
from scripts import guarded_hosting_publish as publisher
from scripts import study_artifacts
from scripts.sermon_execution_harness import work_lock, atomic_json

ROOT = Path(__file__).resolve().parents[1]
MAPS = ('full_candidate', 'full_review_receipt', 'spoken_candidate', 'spoken_review_receipt',
        'audio_package', 'audio_review_receipt', 'audio_screening_receipt', 'full_content',
        'outline', 'outline_review', 'meditation', 'meditation_review')


def read(path):
    return json.loads(Path(path).read_text())


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load(config_path):
    path = Path(config_path).resolve()
    value = read(path)
    schema = read(ROOT / 'schemas/sermon-unified-delivery-v1.schema.json')
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    d.validate_intent(value['intent'], value['routes'])
    base = path.parent
    input_paths = []
    def bound(row):
        p = (base / row['path']).resolve()
        d.require(p.is_file() and file_sha(p) == row['sha256'], 'Delivery input changed: ' + p.name)
        input_paths.append(p)
        return p
    args = {'page_id': value['pageId'], 'date': value['date'], 'locales': value['locales'],
            'source_date_label': False, 'require_study': True}
    for name in ('source', 'metadata_approval', 'metadata_proposal'):
        args[name] = bound(value['inputs'][name])
    for name in MAPS:
        rows = value['inputs'][name]
        d.require(set(rows) == set(value['locales']), 'Delivery locale input coverage differs: ' + name)
        args[name] = [locale + '=' + str(bound(rows[locale])) for locale in value['locales']]
    work = (base / value['workRoot']).resolve()
    args['out'] = work / 'prepared'
    paths = {name: bound(value[name]) for name in ('releasePlan', 'httpVerification', 'authorization') if name in value}
    if 'baseline' in value:
        paths['baseline'] = (base / value['baseline']['path']).resolve()
        d.validate_catalog_snapshot(paths['baseline'])
        d.require(file_sha(paths['baseline'] / 'public/multilingual-v3.json') == value['baseline']['catalogSha256'], 'Baseline catalog binding changed')
    if 'releasePlan' in paths:
        plan = read(paths['releasePlan'])
        d.require(plan.get('schemaVersion') == 'sermon-locale-release-plan-v1'
                  and plan.get('pageId') == value['pageId']
                  and set(plan.get('locales', [])) == set(value['locales']), 'Release plan scope differs')
        d.require(type(plan.get('parentGeneration')) is int and plan['parentGeneration'] >= 0, 'Release plan generation required')
        if 'baseline' in paths:
            d.require(plan.get('baselineVersion') == value['baseline']['version']
                      and plan.get('baselineCatalogSha256') == d.sha(read(paths['baseline'] / 'public/multilingual-v3.json')), 'Release plan baseline differs')
    for destination in (work / 'prepared', work / 'sealed'):
        d.require(not any(path == destination or path.is_relative_to(destination) for path in input_paths), 'Output overlaps bound input')
        if 'baseline' in paths:
            d.require(destination != paths['baseline'] and not paths['baseline'].is_relative_to(destination) and not destination.is_relative_to(paths['baseline']), 'Output overlaps baseline')
    # Output state, independent acceptance, and authorization do not alter the
    # frozen production identity. Authorization explicitly binds its seal hash.
    material = {k: v for k, v in value.items() if k not in ('action', 'authorization', 'acceptance')}
    plan_hash = d.sha(material)
    return value, base, work, argparse.Namespace(**args), paths, plan_hash


def _products(value, args):
    source = builder.stage.read_package(args.source, 'sermon-english-source-package-v1.schema.json')
    d.require(source['status'] == 'ready_for_translation', 'English source is not approved')
    source_sha = builder.stage.canonical_sha(source)
    metadata = builder.formal_assets.checked_metadata(args.metadata_approval, args.metadata_proposal, args.page_id, args.date, args.locales, release_intent=value["intent"])
    maps = {name: builder.assignment_map(getattr(args, name), args.locales) for name in MAPS}
    joins = {}
    for locale in args.locales:
        d.validate_metadata(metadata['locales'][locale])
        full, full_sha, _ = builder.admitted_text(maps['full_candidate'][locale], maps['full_review_receipt'][locale], source_sha, locale)
        spoken, spoken_sha, _ = builder.admitted_text(maps['spoken_candidate'][locale], maps['spoken_review_receipt'][locale], source_sha, locale)
        content = read(maps['full_content'][locale])
        d.require(content.get('pageId') == args.page_id and content.get('targetLocale') == locale
                  and content.get('englishSourcePackageJsonSha256') == source_sha
                  and content.get('targetLanguageCandidateJsonSha256') == full_sha
                  and content.get('sourceMediaSha256') == source['source']['media']['sha256'], 'Full content source/page identity differs')
        if 'sourceWindow' in content:
            d.require(content['sourceWindow'].get('mediaSha256') == source['source']['media']['sha256']
                      and all(content['sourceWindow'].get(key) == source['source']['approvedWindow'][key]
                              for key in ('startSeconds', 'endSeconds')), 'Full content source window differs')
        audio = builder.stage.read_package(maps['audio_package'][locale], 'sermon-target-language-audio-package-v1.schema.json')
        review = read(maps['audio_review_receipt'][locale])
        # A listening waiver binds a machine-screened package; validate_review checks it exactly.
        d.require(audio['targetLocale'] == locale and audio['englishSourcePackageJsonSha256'] == source_sha
                  and audio['targetLanguageCandidateJsonSha256'] == spoken_sha
                  and (audio['status'] == 'human_reviewed' or builder.machine_basis.is_audio_waiver(review)), 'Audio product identity differs')
        from scripts.sermon_unified_reviews import validate_review
        validate_review('audio', maps['audio_review_receipt'][locale], inputs={'source': args.source,
                        'package': maps['audio_package'][locale], 'screening': maps['audio_screening_receipt'][locale]},
                        expected_source={'sourceId': source['source']['sourceId'], 'mediaSha256': source['source']['media']['sha256'], 'sourceUrlHash': source['source']['sourceUrlHash'], 'window': source['source']['approvedWindow']}, expected_locale=locale)
        studies = {name: read(maps[name][locale]) for name in ('outline', 'outline_review', 'meditation', 'meditation_review')}
        for kind in ('outline', 'meditation'):
            d.require(studies[kind]['pageId'] == args.page_id and studies[kind]['locale'] == locale, 'Study product page/locale differs')
        joins[locale] = study_artifacts.join_artifacts(source_sha=source_sha, text_sha=full_sha,
                                                       audio_sha=d.sha(audio), **studies)
        d.require(joins[locale]['status'] == 'complete', 'Four-product join incomplete')
        joins[locale]['candidateSha256'] = d.sha({'products': joins[locale]['candidateSha256'], 'metadataApproval': d.sha(metadata), 'contentSha256': file_sha(maps['full_content'][locale])})
    return source, joins


def _input_snapshot(value, base, paths):
    dependencies = {}
    def visit(path, expected=None, *, recursive=True, canonical=None):
        from scripts.sermon_release_workflow import _safe_path
        path = _safe_path(path)
        current = file_sha(path)
        d.require(expected is None or current == expected, 'Nested delivery input changed: ' + path.name)
        name = str(path)
        if name in dependencies:
            d.require(dependencies[name] == current, 'Nested delivery input changed during inspection')
            return
        dependencies[name] = current
        if not recursive or path.suffix.lower() != '.json':
            return
        document = read(path)
        d.require(canonical is None or d.sha(document) == canonical, 'Nested canonical JSON hash differs')
        def walk(node):
            if isinstance(node, dict):
                if {'path', 'sha256'} <= set(node):
                    visit(path.parent / node['path'], node['sha256'], canonical=node.get('jsonSha256'))
                else:
                    for child in node.values():
                        walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)
        walk(document)
    for name, rows in value['inputs'].items():
        for row in ([rows] if name in ('source', 'metadata_approval', 'metadata_proposal') else rows.values()):
            visit(base / row['path'], row['sha256'])
    for name in ('releasePlan', 'httpVerification'):
        if name in paths:
            visit(paths[name], recursive=False)
    for name in builder.RUNTIME_WEB_FILES:
        visit(builder.RUNTIME_WEB_ROOT / name, recursive=False)
    if 'baseline' in paths:
        baseline = paths['baseline']
        visit(baseline / 'seal-report.json', recursive=False)
        for row in read(baseline / 'seal-report.json')['files']:
            visit(baseline / 'public' / row['path'].lstrip('/'), row['sha256'], recursive=False)
    return {'dependencies': dependencies, 'inputsSha256': d.sha(dependencies)}


def freeze(config_path, output_path):
    """Create a new config binding the complete nested input inventory."""
    value, base, _, _, paths, _ = load(config_path)
    output_path = Path(output_path).resolve()
    d.require(output_path != Path(config_path).resolve(), 'Freeze requires a new configuration path')
    captured = _input_snapshot(value, base, paths)
    for name, rows in value['inputs'].items():
        for row in ([rows] if name in ('source', 'metadata_approval', 'metadata_proposal') else rows.values()):
            row['path'] = str((base / row['path']).resolve())
    for name in ('releasePlan', 'httpVerification', 'authorization'):
        if name in value:
            value[name]['path'] = str(paths[name])
    if 'baseline' in value:
        value['baseline']['path'] = str(paths['baseline'])
    value['workRoot'] = str((base / value['workRoot']).resolve())
    for endpoint in value.get('acceptance', []):
        endpoint['receipt']['path'] = str((base / endpoint['receipt']['path']).resolve())
        endpoint['evidenceRoot'] = str((base / endpoint['evidenceRoot']).resolve())
    value['inputSnapshotSha256'] = captured['inputsSha256']
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        d.require(read(output_path) == value, 'Frozen delivery configuration already differs')
    else:
        with output_path.open('x') as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write('\n')
    return inspect(output_path)


def inspect(config_path):
    value, base, work, args, paths, plan_hash = load(config_path)
    captured = _input_snapshot(value, base, paths)
    d.require(value.get('inputSnapshotSha256') in (None, captured['inputsSha256']), 'Delivery input snapshot changed; freeze a new revision')
    plan_hash = d.sha({'configuration': plan_hash, 'inputsSha256': captured['inputsSha256']})
    source, joins = _products(value, args)
    result = {'status': 'ready_to_prepare', 'planHash': plan_hash, 'kind': 'app_delivery',
              'pageId': value['pageId'], 'sourceIdentity': d.source_identity(source),
              'sourceUrlHash': source['source']['sourceUrlHash'], 'approvedWindow': source['source']['approvedWindow'],
              'sourceId': source['source']['sourceId'], 'mediaSha256': source['source']['media']['sha256'],
              'sourcePackageSha256': d.sha(source), 'locales': list(args.locales),
              'candidateSha256': d.sha({locale: joins[locale]['candidateSha256'] for locale in args.locales}),
              'fourProducts': 'validated', 'dependencies': captured['dependencies'], 'inputsSha256': captured['inputsSha256'],
              'snapshotBound': value.get('inputSnapshotSha256') == captured['inputsSha256'], 'validatedEndpoints': [], 'productionEligible': False,
              'deviceAcceptance': 'not_run', 'venueAcceptance': 'not_run', 'blockers': []}
    if args.out.exists():
        manifest, _ = builder.verified_assets(args.out)
        d.require(manifest['pageId'] == args.page_id and manifest['englishSourcePackageJsonSha256'] == d.sha(source), 'Prepared source differs')
        for locale in args.locales:
            d.require(manifest['releases'][locale].get('appCandidateSha256') == joins[locale]['candidateSha256'], 'Prepared four-product identity differs')
        result['status'] = 'local_candidate_verified'
    sealed = work / 'sealed'
    if sealed.exists():
        d.validate_catalog_snapshot(sealed)
        report = read(sealed / 'seal-report.json')
        d.require(report['pageId'] == args.page_id and report['origin'] == value['intent']['origin'], 'Sealed release target differs')
        d.require(report.get('appCandidateSha256s') == {locale: joins[locale]['candidateSha256'] for locale in args.locales}, 'Sealed four-product identity differs')
        result.update(status='ready_for_authorized_publication', catalogSha256=report['catalogSha256'], sealReportSha256=file_sha(sealed / 'seal-report.json'))
    if value.get('action', 'prepare') in ('publish', 'verify'):
        for field in ('baseline', 'releasePlan', 'httpVerification'):
            if field not in value:
                result['blockers'].append(field + '_required')
        if not sealed.exists():
            result['blockers'].append('sealed_candidate_required')
    return result


def _authorization(value, paths, state, sealed):
    d.require('authorization' in paths, 'Existing release authorization required')
    receipt = read(paths['authorization'])
    plan = read(paths['releasePlan'])
    # Existing release-workflow authorization shape, bound to the new immutable
    # seal report and explicit baseline snapshot generation from the release plan.
    expected = {'schemaVersion': 'sermon-release-authorization-v1', 'decision': 'approved',
                'sunday': value['date'], 'configSha256': state['planHash'],
                'project': value['intent']['project'], 'site': value['intent']['site'], 'origin': value['intent']['origin'],
                'buildReportSha256': file_sha(sealed / 'seal-report.json'),
                'parentReleaseId': value['baseline']['version'], 'parentGeneration': plan['parentGeneration']}
    d.require(all(receipt.get(k) == v for k, v in expected.items()) and bool(receipt.get('approvedBy')), 'Release authorization does not bind exact target/candidate/baseline')
    d.timestamp(receipt.get('approvedAt'))
    return receipt


def _reader(url):
    with urlopen(Request(url, headers={'Cache-Control': 'no-cache'}), timeout=120) as response:
        return response.status, response.read()


def _verify_publication(sealed, attempt, reader):
    report = read(sealed / 'seal-report.json')
    http = {'passed': False, 'failures': [], 'attemptId': attempt['attemptId'], 'deploymentSha256': d.sha(attempt),
            'origin': attempt['intent']['origin'], 'catalogSha256': report['catalogSha256'],
            'assetsSha256': d.sha(report['files']), 'startedAt': datetime.now(timezone.utc).isoformat(), 'checkedFiles': []}
    for row in report['files']:
        try:
            status, data = reader(http['origin'] + '/' + row['path'].lstrip('/'))
        except Exception:
            status, data = 0, b''
        ok = status == 200 and len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
        http['checkedFiles'].append({'path': row['path'], 'passed': ok, 'sha256': hashlib.sha256(data).hexdigest()})
        if not ok:
            http['failures'].append(row['path'])
    http.update(passed=not http['failures'], completedAt=datetime.now(timezone.utc).isoformat())
    atomic_json(sealed / 'publication-http-v2.json', http)
    return d.verify_attempt(attempt, http, intent=attempt['intent'], catalog_sha=report['catalogSha256'], assets_sha=d.sha(report['files']))


def _endpoints(value, base, sealed, state, reader):
    verified = []
    files = {('/' + row['path'].lstrip('/')): row['sha256'] for row in read(sealed / 'seal-report.json')['files']}
    for endpoint in value.get('acceptance', []):
        d.validate_intent(endpoint['intent'], value['routes'])
        path = (base / endpoint['receipt']['path']).resolve()
        d.require(file_sha(path) == endpoint['receipt']['sha256'], 'Endpoint receipt changed')
        receipt = read(path)
        d.require(receipt.get('readback', {}).get('schemaVersion') == 'sermon-client-readback-v2', 'Four-product endpoints require client readback v2')
        d.require(set(receipt['locales']) == set(value['locales']), 'Endpoint locale coverage incomplete')
        resources = receipt['readback']['resources']
        observed_paths = {row['url'].removeprefix(endpoint['intent']['origin']) for row in resources}
        # Current clients read v4 first; v3 is the human-only projection that older
        # builds read. Only a v4 reader can show a machine-checked locale.
        has_v4 = (sealed / 'public/multilingual-v4.json').exists()
        catalog = read(sealed / 'public' / ('multilingual-v4.json' if has_v4 else 'multilingual-v3.json'))
        page = next(page for page in catalog['pages'] if page['id'] == value['pageId'])
        machine = any(d.machine_checked(page['targets'][locale]) for locale in value['locales'])
        catalog_path = '/multilingual-v4.json' if machine or (has_v4 and '/multilingual-v4.json' in observed_paths) else '/multilingual-v3.json'
        required_paths = {catalog_path}
        if endpoint['name'] in ('dev', 'production_web'):
            required_paths.update('/' + name for name in builder.RUNTIME_WEB_FILES)
        audio_paths = {}
        study_requirements = {}
        for locale in value['locales']:
            release_path = page['targets'][locale]['releasePackageUrl']
            required_paths.add(release_path)
            release = read(sealed / 'public' / release_path.lstrip('/'))
            d.require(release['schemaVersion'] in d.FOUR_PRODUCT_RELEASES, 'Endpoint requires a four-product release (v3 or v4)')
            d.require(release['pageId'] == value['pageId'] and release['targetLocale'] == locale
                      and release['englishSourcePackageJsonSha256'] == state['sourcePackageSha256']
                      and release['sourceIdentity'] == state['sourceIdentity'], 'Endpoint release source/page identity differs')
            def study_reader(url):
                status, payload = reader(endpoint['intent']['origin'] + url)
                d.require(status == 200, 'Endpoint study HTTP failure')
                return payload
            d.validate_public_study(release, reader=study_reader)
            study_requirements[locale] = {kind: release['fourProducts'][kind + 'ArtifactSha256'] for kind in ('outline', 'meditation')}
            for asset in release['assets']:
                if asset['role'] in ('page', 'content', 'audio', 'captions', 'outline', 'meditation', 'product_manifest'):
                    required_paths.add(asset['path'])
                if asset['role'] == 'audio':
                    audio_paths[locale] = endpoint['intent']['origin'] + asset['path']
        d.require(required_paths <= observed_paths, 'Endpoint readback misses current locale resources')
        evidence_root = (base / endpoint['evidenceRoot']).resolve()
        for playback in receipt['playback']:
            evidence_path = (evidence_root / playback['evidencePath']).resolve()
            d.require(evidence_path.is_relative_to(evidence_root), 'Playback evidence outside root')
            telemetry = read(evidence_path)
            d.require(telemetry.get('audioUrl') == audio_paths.get(playback.get('locale')), 'Playback audio is not current locale asset')
        for row in resources:
            relative = row['url'].removeprefix(endpoint['intent']['origin'])
            d.require(files.get(relative) == row['sha256'], 'Endpoint resource does not bind current release')
        result = d.verify_client_acceptance(receipt, expected_intent=endpoint['intent'], candidate_sha=state['candidateSha256'],
                                            reader=reader, evidence_root=evidence_root, study_requirements=study_requirements)
        if result['status'] == 'pass':
            d.require(endpoint['name'] == endpoint['intent']['channel'], 'Endpoint channel differs')
            d.require(endpoint['name'] not in verified, 'Duplicate endpoint receipt')
            verified.append(endpoint['name'])
    return sorted(verified)


def execute(config_path, expected_plan_hash, *, reader=None, request=None, run=None):
    state = inspect(config_path)
    d.require(state['planHash'] == expected_plan_hash, 'Delivery plan changed since dispatch')
    d.require(state['snapshotBound'], 'Delivery input snapshot must be frozen before execution')
    value, base, work, args, paths, _ = load(config_path)
    with work_lock(work):
        fresh = inspect(config_path)
        d.require(fresh['planHash'] == expected_plan_hash, 'Delivery plan changed while acquiring lock')
        action = value.get('action', 'prepare')
        # Bind strict metadata/duration checks without exposing route documents
        # as mutable external configuration during builder execution.
        args.release_intent = work / 'bound-intent.json'
        args.routes = work / 'bound-routes.json'
        for path, document in ((args.release_intent, value['intent']), (args.routes, value['routes'])):
            if path.exists():
                d.require(read(path) == document, 'Bound route document changed')
            else:
                atomic_json(path, document)
        if not args.out.exists():
            d.require(action == 'prepare', 'Prepare the local candidate before publication')
            builder.prepare(args)
        sealed = work / 'sealed'
        if action == 'prepare':
            if 'httpVerification' in paths and 'baseline' in paths and 'releasePlan' in paths and not sealed.exists():
                plan = read(paths['releasePlan'])
                d.require(plan['baselineVersion'] == value['baseline']['version'], 'Locale plan baseline version differs')
                builder.seal(argparse.Namespace(prepared=args.out, http_verification=paths['httpVerification'],
                                               out=sealed, baseline=paths['baseline'], release_plan=paths['releasePlan']))
            final = inspect(config_path)
            return {**final, 'status': 'succeeded', 'artifact': 'verified', 'publication': 'not_started', 'productionEligible': False}
        d.require(not fresh['blockers'], 'Delivery prerequisites incomplete: ' + ','.join(fresh['blockers']))
        read_public = reader or _reader
        if action == 'publish':
            _authorization(value, paths, fresh, sealed)
            d.require(value.get('leaseBucket'), 'Remote publisher lease bucket required')
            kwargs = {} if run is None else {'run': run}
            attempt = publisher.publish(sealed, intent=value['intent'], routes=value['routes'],
                      baseline_version=value['baseline']['version'], baseline_catalog_sha=value['baseline']['catalogSha256'],
                      baseline_catalog_v4_sha=read(paths['baseline'] / 'seal-report.json').get('catalogV4Sha256'),
                      lease_bucket=value['leaseBucket'], request=request or publisher.authenticated_transport(), reader=read_public, **kwargs)
        else:
            attempt = read(sealed / 'deployment-attempt-v2.json')
            d.require(attempt['intent'] == value['intent'], 'Deployment intent differs')
        publication = _verify_publication(sealed, attempt, read_public)
        validated = _endpoints(value, base, sealed, fresh, read_public)
        complete = set(validated) == set(value['requiredEndpoints'])
        return {**fresh, 'status': 'succeeded' if complete else 'partial', 'artifact': 'verified',
                'publication': publication['publication'], 'validatedEndpoints': validated,
                'productionEligible': complete, 'deviceAcceptance': 'separate', 'venueAcceptance': 'not_run',
                'missingEndpoints': sorted(set(value['requiredEndpoints']) - set(validated))}
