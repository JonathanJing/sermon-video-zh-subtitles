"""Read local Git objects and run-bound artifacts; no production mutations/network."""
from pathlib import Path
import json,subprocess,hashlib
import argparse
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--run-dir',type=Path,required=True)
p.add_argument('--out-dir',type=Path,required=True)
p.add_argument('--repo-dir',type=Path,required=True)
args=p.parse_args()
OUT=args.out_dir.resolve();OUT.mkdir(parents=True,exist_ok=True)
RUN=args.run_dir.resolve()
REPO=args.repo_dir.resolve()
HERE=OUT; evidence={}

def digest(b):return hashlib.sha256(b).hexdigest()
def file(p):
 p=RUN/p;evidence[str(p.relative_to(RUN))]=digest(p.read_bytes());return p

def read(p):return json.loads(file(p).read_text())
def git(*args):return subprocess.check_output(['git','-C',str(REPO),*args])
commits=[]
for short in ['f446d8d','efb774b','4f61a26','5e8cfb5','834dfe4']:
 values=git('show','-s','--format=%H%n%P%n%aI%n%s',short).decode().strip().splitlines();patch=git('show','--format=','--binary',short);commits.append({'commit':values[0],'parents':values[1].split(),'authorDate':values[2],'subject':values[3],'patchSha256':digest(patch),'files':git('diff-tree','--no-commit-id','--name-only','-r',short).decode().splitlines()})
files=['scripts/build_full_video_app_release.py','scripts/assemble_multilingual_v3_update.py','scripts/review_target_language_audio.py','scripts/build_formal_dev_release_assets.py','experiments/sermon-dubbing-poc/web/published-weeks.mjs','apps/tongxing-ios/project.yml'];objects=[]
for c in ['f446d8d','4f61a26','5e8cfb5','834dfe4']:
 for p in files:
  raw=git('show',c+':'+p);objects.append({'gitPath':c+':'+p,'sha256':digest(raw),'bytes':len(raw)})
first=read('code-freeze-f446d8d.json');second=read('code-freeze.json')
bridges=['zh-publication-v1/generate_sidecars.py','ios-visibility-check-v1/prepare_dev_overlay_v1.py','multilingual-publication-v2/prepare_locale_app_v1.py','multilingual-publication-v2/prepare_asset_first_ko_es_v1.py','multilingual-publication-v2/merge_locale_release_v1.py','multilingual-publication-v2/deploy_catalog_checked_v1.py','multilingual-publication-v2/verify_final_ko_es_v1.py']
for p in bridges:file(p)
state={}
for p in ['zh-publication-v1/stage-client-window-v4/stage-manifest.json','zh-publication-v1/prepared-client-window-v4/preparation-manifest.json','zh-publication-v1/publication-http-final-v4.json','ios-visibility-check-v1/dev-candidate-v1/overlay-report.json','ios-visibility-check-v1/dev-http-receipt-v1.json','metadata-title-fix-v1/prod/metadata-revision-receipt.json','metadata-title-fix-v1/prod/final-http-receipt.json','metadata-title-fix-v1/dev/metadata-revision-receipt.json','multilingual-publication-v2/prepared-ko-leading60-v1/preparation-manifest.json','multilingual-publication-v2/prepared-es-leading60-v1/preparation-manifest.json','multilingual-publication-v2/catalog-ko-es-v1/prod-es/catalog-deploy-receipt.json','multilingual-publication-v2/catalog-ko-es-v1/dev-es-v3/catalog-deploy-receipt.json']:
 x=read(p);state[p]={k:x[k] for k in ['schemaVersion','status','profile','origin','baselineFiles','preservedFiles','addedFiles','newDefaultPageId','baselineCatalogSha256','newCatalogSha256','exitCode','metadata','audioAndCuesUnchanged'] if k in x}
for p in ['formal-layer3-prep-v1/stage-preparation-v1/approved-runtime-stage-v2/build-5b2c1ac/runtime-plan.json','formal-layer3-execution-v2/launch_formal_locale_reuse_timing62_v1.py','formal-layer3-postprocess-execution-v1/plan-preparation/compact_cpu.py']:file(p)
output={'schemaVersion':'runtime-evolution-delivery-audit-v1','scope':'local read-only Git/artifacts; commit authorship time is not deployment time; saved argv code is not by itself execution proof','startBoundary':{'firstExplicitFreezeAt':first['createdAt'],'firstExplicitExecutionCommit':first['executionCommit'],'devCommit':first['devCommit'],'pr237Commit':first['pr237Commit'],'secondFreezeAt':second['createdAt'],'secondExecutionCommit':second['executionCommit'],'repairCommits':second['repairCommits'],'deliveryPatchParent':git('rev-parse','4f61a26^').decode().strip(),'warning':'Delivery parent is not the initial production code freeze. Formal GPU code and later local delivery code have different frozen identities.'},'commits':commits,'gitObjects':objects,'runBridges':bridges,'selectedArtifactState':state,'runEvidenceSha256':evidence,'decisions':[{'kind':'new_code','commit':'4f61a26','behavior':'Chinese-only 8/9 asset stage profiles, exact source/track exception schemas, source-date metadata branch'},{'kind':'new_code','commit':'5e8cfb5','behavior':'Preserve original recording sourceWindow while clip playback uses local time; validate fingerprint original offsets'},{'kind':'new_code','commit':'834dfe4','behavior':'Nonempty selected locale subsets and v2 per-locale metadata approval; locale-bound review v4; dynamic duration label'},{'kind':'run_bridge','behavior':'Add KO/ES to existing page, which canonical assembler refuses to overwrite; preserve existing locale assets and unrelated files'},{'kind':'environment_delivery','behavior':'Beta consumed Dev; prod-only publication could not update its chooser; separate preserved Dev overlay needed'},{'kind':'explicit_policy_exception','behavior':'8 second gate not met by earlier schedules; later timing62 launcher and publication exception must retain bound user receipt, not be called automatic correctness repair'}]}
(HERE/'delivery-metrics.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'commits':len(commits),'gitObjects':len(objects),'bridges':len(bridges),'runEvidence':len(evidence)}))
