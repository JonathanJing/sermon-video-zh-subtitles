#!/usr/bin/env python3
"""Replace published page bytes in place through two guarded deploys.

Why this exists. The weekly publisher adds files and changes catalogs; it refuses to
overwrite a published page's bytes because the live release still hashes the old bytes.
A content correction therefore needs an explicit channel:

1. ``assets``: publish the replacement bytes while the catalogs and the previous release
   stay as they are. ``contract.validate_catalog_snapshot`` accepts that snapshot only when
   the page is named in ``allow_pending_replacements``; the pending set is written to
   ``staged-changes.json`` so the intermediate state is visible, never implied.
2. Deploy that snapshot and GET/SHA-verify the replacement assets (the caller's verify step).
3. ``finish``: publish the replacement release packages (``published_http_verified`` with the
   verification evidence) and the catalog targets that hash them. This snapshot is validated
   strictly, so the deployed state is consistent again.

Only existing released paths are accepted for replacement; ``extra_paths`` may add files under
the page's own ``/study/<pageId>/`` tree (the four-product study assets) and, in ``finish``,
rewrite ``/alignment/<pageId>.json``. The channel never adds pages or locales; new pages still go
through the normal assets -> releases -> catalogs flow.

Usage (through the ops runner):

  tools/ops/run.py published_page_replace assets \
      --baseline <live snapshot> --out <snapshot A> --page-id <id> \
      --replace-dir <dir mirroring public/>

  # deploy A, then verify the replacement assets over HTTP

  tools/ops/run.py published_page_replace finish \
      --assets <snapshot A> --out <snapshot B> --page-id <id> \
      --release-dir <dir with <locale>.json> --evidence <verify.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from . import baseline as bl
from . import contract as delivery_contract

V3, V4, V5 = 'multilingual-v3.json', 'multilingual-v4.json', 'multilingual-v5.json'


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _page(catalog, page_id):
    pages = [page for page in catalog['pages'] if page['id'] == page_id]
    delivery_contract.require(len(pages) == 1, 'Page must occur exactly once')
    return pages[0]


def _catalogs(public: Path) -> dict[str, dict]:
    found = {}
    for name in (V3, V4, V5):
        path = public / name
        if path.exists():
            found[name] = _read(path)
            delivery_contract.validate_catalog_schema(found[name])
    delivery_contract.require(V3 in found, 'Snapshot has no v3 catalog')
    return found


def _copy_snapshot(source: Path, out: Path) -> None:
    delivery_contract.require(not out.exists(), 'Use a new snapshot directory')
    out.mkdir(parents=True)
    shutil.copytree(source / 'public', out / 'public')
    shutil.copyfile(source / 'firebase.json', out / 'firebase.json')
    if (source / 'baseline-receipt.json').exists():
        shutil.copyfile(source / 'baseline-receipt.json', out / 'baseline-receipt.json')


def _seal(out: Path, changed: list[str], pending: list[str]) -> None:
    report = {**bl.catalog_report(out / 'public'), 'files': bl.files_report(out / 'public')}
    bl.write(out / 'seal-report.json', report)
    (out / 'staged-changes.json').write_text(json.dumps(
        {'changedPaths': changed, 'pendingReplacements': pending}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _check_page_local(paths: dict[str, bytes], page_id: str, *, allow_alignment: bool):
    for rel in paths:
        prefix = f'alignment/{page_id}.json' if allow_alignment else f'study/{page_id}/'
        ok = rel == f'alignment/{page_id}.json' if allow_alignment else rel.startswith(prefix)
        delivery_contract.require(ok, 'Extra file must stay inside the page\'s study tree: ' + rel)
        delivery_contract.require('..' not in Path(rel).parts and not Path(rel).is_absolute(), 'Unsafe extra path')


def replace_assets(baseline: Path, out: Path, page_id: str, files: dict[str, bytes], *,
                   extra_paths: dict[str, bytes] | None = None) -> dict:
    """Snapshot A: replacement bytes, unchanged catalogs, explicit pending page.

    ``extra_paths`` may add the page's four-product study files (``study/<pageId>/...``).
    """
    baseline, out = Path(baseline), Path(out)
    extra = dict(extra_paths or {})
    delivery_contract.validate_catalog_snapshot(baseline)
    catalogs = _catalogs(baseline / 'public')
    page = _page(catalogs.get(V5) or catalogs.get(V4) or catalogs[V3], page_id)
    public = baseline / 'public'
    delivery_contract.require(files, 'No replacement files')
    for rel in files:
        delivery_contract.require((public / rel).is_file(), 'Replacement must overwrite an existing published file: ' + rel)
        delivery_contract.require('..' not in Path(rel).parts and not Path(rel).is_absolute(), 'Unsafe replacement path')
    _check_page_local(extra, page_id, allow_alignment=False)
    for rel in extra:
        delivery_contract.require(not (public / rel).exists(), 'Extra file is already published: ' + rel)
    _copy_snapshot(baseline, out)
    for rel, data in {**files, **extra}.items():
        target = out / 'public' / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    pending = [page_id]
    _seal(out, ['/' + rel for rel in sorted({**files, **extra})], pending)
    delivery_contract.validate_catalog_snapshot(out, allow_pending_replacements=frozenset(pending))
    return {'snapshot': str(out), 'pageId': page_id, 'replaced': sorted('/' + rel for rel in files),
            'added': sorted('/' + rel for rel in extra),
            'pendingReplacements': pending, 'locales': sorted(page['targets'])}


def finish_replace(assets: Path, out: Path, page_id: str, releases: dict[str, bytes],
                   evidence_sha256: str, *, extra_paths: dict[str, bytes] | None = None) -> dict:
    """Snapshot B: replacement releases with HTTP evidence, catalogs rebound, strict validation."""
    assets, out = Path(assets), Path(out)
    extra = dict(extra_paths or {})
    delivery_contract.require(releases, 'No replacement releases')
    delivery_contract.require(len(evidence_sha256) == 64, 'Evidence must be a sha256')
    catalogs = _catalogs(assets / 'public')
    name = V5 if V5 in catalogs else V4 if V4 in catalogs else V3
    page = _page(catalogs[name], page_id)
    _copy_snapshot(assets, out)
    public = out / 'public'
    updates = {}
    for locale, data in releases.items():
        delivery_contract.require(locale in page['targets'], 'Release for an unpublished locale: ' + locale)
        release = json.loads(data)
        delivery_contract.validate_release_schema(release)
        delivery_contract.require(release['pageId'] == page_id and release['targetLocale'] == locale
                                  and release['status'] == 'published_http_verified'
                                  and release['httpVerification'].get('status') == 'pass'
                                  and release['httpVerification'].get('evidenceSha256') == evidence_sha256,
                                  'Replacement release is not http-verified: ' + locale)
        path = public / 'releases-v2' / page_id / f'{locale}.json'
        delivery_contract.require(path.is_file(), 'Replacement release must overwrite the published file: ' + str(path))
        path.write_bytes(data)
        updates[locale] = hashlib.sha256(data).hexdigest()
    target_catalogs = dict(catalogs)
    if V5 in target_catalogs:
        v5 = target_catalogs[V5]
        for locale, sha in updates.items():
            _page(v5, page_id)['targets'][locale]['releasePackageJsonSha256'] = sha
        delivery_contract.validate_catalog_schema(v5)
        v4 = delivery_contract.project_legacy_catalog_v4(v5)
        v3 = delivery_contract.project_human_catalog(v4)
        target_catalogs.update({V5: v5, V4: v4, V3: v3})
    elif V4 in target_catalogs:
        v4 = target_catalogs[V4]
        for locale, sha in updates.items():
            _page(v4, page_id)['targets'][locale]['releasePackageJsonSha256'] = sha
        delivery_contract.validate_catalog_schema(v4)
        target_catalogs.update({V3: delivery_contract.project_human_catalog(v4)})
    else:
        v3 = target_catalogs[V3]
        for locale, sha in updates.items():
            _page(v3, page_id)['targets'][locale]['releasePackageJsonSha256'] = sha
        delivery_contract.validate_catalog_schema(v3)
    written = []
    for catalog_name, value in target_catalogs.items():
        (public / catalog_name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
                                           encoding='utf-8')
        written.append(catalog_name)
    _check_page_local(extra, page_id, allow_alignment=True)
    for rel, data in extra.items():
        target = public / rel
        delivery_contract.require(target.is_file(), 'Extra file must overwrite an existing published file: ' + rel)
        target.write_bytes(data)
    _seal(out, ['/releases-v2/%s/%s.json' % (page_id, locale) for locale in updates] + written
          + ['/' + rel for rel in sorted(extra)], [])
    delivery_contract.validate_catalog_snapshot(out)
    return {'snapshot': str(out), 'pageId': page_id, 'releases': sorted(updates), 'catalogs': written,
            'evidenceSha256': evidence_sha256}


def _files_from(directory: Path) -> dict[str, bytes]:
    directory = Path(directory)
    delivery_contract.require(directory.is_dir(), 'Not a directory: ' + str(directory))
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in sorted(directory.rglob('*')) if path.is_file()}


def write_publish_config(baseline: Path, snapshot: Path, environment: str) -> dict:
    config = bl.publication_config(Path(baseline), Path(snapshot), environment=environment)
    bl.write(Path(snapshot) / 'publish-config.json', config)
    return {'snapshot': str(snapshot), 'baselineVersion': config['baseline_version']}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    a = sub.add_parser('assets', help='snapshot A: replacement bytes, catalogs unchanged')
    a.add_argument('--baseline', required=True, type=Path)
    a.add_argument('--out', required=True, type=Path)
    a.add_argument('--page-id', required=True)
    a.add_argument('--replace-dir', required=True, type=Path, help='files mirror public/, e.g. content/<pageId>/ko.json')
    a.add_argument('--environment', default='production')
    f = sub.add_parser('finish', help='snapshot B: replacement releases and catalogs')
    f.add_argument('--assets', required=True, type=Path)
    f.add_argument('--out', required=True, type=Path)
    f.add_argument('--page-id', required=True)
    f.add_argument('--release-dir', required=True, type=Path, help='<locale>.json replacement releases')
    f.add_argument('--evidence', required=True, type=Path, help='HTTP verification JSON with status pass')
    f.add_argument('--environment', default='production')
    args = parser.parse_args()
    if args.command == 'assets':
        result = replace_assets(args.baseline, args.out, args.page_id, _files_from(args.replace_dir))
        result['publishConfig'] = write_publish_config(args.baseline, args.out, args.environment)
    else:
        evidence = _read(args.evidence)
        delivery_contract.require(evidence.get('status') == 'pass', 'HTTP verification did not pass')
        releases = {path.stem: path.read_bytes() for path in sorted(args.release_dir.glob('*.json'))}
        result = finish_replace(args.assets, args.out, args.page_id, releases, _digest(args.evidence))
        result['publishConfig'] = write_publish_config(args.assets, args.out, args.environment)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
