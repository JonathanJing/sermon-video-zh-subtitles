"""Overlay the 1.26.16 Web UI on a complete live-bound Dev snapshot.

No content, review receipts, Hosting configuration or media are changed.
Publish the generated config through guarded_hosting_publish separately.
"""
import argparse
from pathlib import Path
import shutil
import subprocess

if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import delivery_contract as contract
from scripts import prepare_dev_simulated_publication as staging
from scripts import build_full_video_app_release as builder

UI_FILES = ('index.html', 'style.css', 'app.mjs', 'i18n.mjs',
            'published-weeks.mjs', 'reading-mode.mjs', 'locales-reader.mjs',
            'offline.mjs', 'offline-worker.js')


def prepare(baseline, out):
    base, out = Path(baseline).resolve(), Path(out).resolve()
    contract.require(not out.exists() and not out.is_relative_to(base), 'Unsafe UI update output')
    contract.validate_catalog_snapshot(base)
    receipt = staging.read(base / 'baseline-receipt.json')
    contract.require(receipt['project'] == staging.PROJECT and receipt['site'] == staging.SITE
                     and receipt['origin'] == staging.ORIGIN, 'Dev target only')
    # Resolve all local module imports before staging, including offline helpers.
    builder.runtime_web_files()
    out.mkdir(parents=True)
    shutil.copytree(base / 'public', out / 'public')
    shutil.copyfile(base / 'firebase.json', out / 'firebase.json')
    shutil.copyfile(base / 'baseline-receipt.json', out / 'baseline-receipt.json')
    changed = []
    for name in UI_FILES:
        source = builder.RUNTIME_WEB_ROOT / name
        target = out / 'public' / name
        contract.require(source.is_file(), 'Missing UI source: ' + name)
        if not target.exists() or staging.digest(source) != staging.digest(target):
            shutil.copyfile(source, target)
            changed.append('/' + name)
    before = {row['path']: row for row in staging.files_report(base / 'public')}
    after = staging.files_report(out / 'public')
    for row in after:
        if row['path'] not in changed:
            contract.require(row == before.get(row['path']), 'Preserved file changed: ' + row['path'])
    contract.require(set(before).issubset({row['path'] for row in after}), 'Existing file removed')
    staging.write(out / 'seal-report.json', {'catalogSha256': staging.digest(out / 'public/multilingual-v3.json'), 'files': after})
    contract.validate_catalog_snapshot(out)
    staging.write(out / 'publish-config.json', staging.publication_config(base, out))
    staging.write(out / 'ui-update-plan.json', {
        'status': 'prepared_not_deployed', 'webVersion': '1.26.16',
        'iosSourceCommit': 'a1e64190f5af33104a3b8839562d8901955031bb',
        'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=builder.ROOT, text=True).strip(),
        'changedPaths': changed, 'preservedFiles': len(before) - sum(path in before for path in changed),
        'modelCalls': 0, 'catalogUnchanged': True,
    })
    return {'status': 'prepared_not_deployed', 'changedPaths': changed, 'publishConfig': str(out / 'publish-config.json')}


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.baseline, args.out)))
