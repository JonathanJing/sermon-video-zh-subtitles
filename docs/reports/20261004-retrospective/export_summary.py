"""Project only reviewable aggregate counts and relative input hashes; no raw text."""
import argparse
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--input-dir',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
def read(name):return json.loads((a.input_dir/name/'metrics.json').read_text())
v,au,h,o=[read(x) for x in ['versions','audio','handoffs','operations']]
def pick(d,keys):return {k:d[k] for k in keys}
summary={
 'schemaVersion':'production-retrospective-summary-v1',
 'sourceId':'resi-20261004-69ba7a66',
 'limitations':['Historical offline audit, not current HTTP or playback verification.','Usage missing is unknown, not zero.','No acoustic diagnosis of the missing initial 61-second WAV.','Heuristic operation classes are not per-category token attribution.'],
 'versions':{'runs':len(v['runs']),'reasonTotals':v['reasonTotals'],'exactPayloadDuplicateSummary':v['exactPayloadDuplicateSummary'],'sourceInputs':v['sourceInputs'], 'runsSummary':[pick(r,['path','apiAttempts','inputTokens','outputTokens','cacheObservations']) for r in v['runs']]},
 'audio':{'locales':{k:{**pick(x,['units','over8Seconds','over62Seconds','removedLeadingSeconds','scheduleStatus','schedulePolicy']), 'maxLagSeconds':x['maxLag']['endLagSeconds'],'asr':pick(x['asr'],['results','flagged','falsePositiveRate'])} for k,x in au['locales'].items()},'u172Discontinuity':au['u172Discontinuity'],'historicalStderrEvidence':[{k:v for k,v in x.items() if k!='sessionBasename'} for x in au['historicalStderrEvidence']],'evidenceSha256':au['evidenceSha256']},
 'handoffs':pick(h,['initialCoverage','receiptCoverage','initialApprovalHandoffs','inheritedHttpCatalogMismatch','evidence']),
 'operations':{'start':o['start'],'end':o['end'],'scopes':{k:pick(x,['outerToolCalls','functionCalls','customToolCalls','categories','commandClasses','literalCommandCount','uniqueLiteralCommands','exactRepeatedCommandOccurrences','spawnForkSettings','sleepRequestedSeconds','progressQuerySamples']) for k,x in o['scopes'].items()}}
}
summary['handoffs']['finalHttp']=[pick(x,['environment','files','matchedSnapshotFiles','ranges','range206','hasTimestamp','hasDeploymentVersion','catalogSha256','deviceAcceptance','venueAcceptance']) for x in h['finalHttp']]
summary['handoffs']['finalReleaseBindings']=[{**pick(x,['environment','locale','httpEvidenceHashMatchesRawReceipt','assetHashesMatchBothHttpReceipts','assetCount']), 'catalogReleaseShaMatches':x['catalogTarget']['releasePackageJsonSha256']==x['releaseSha256']} for x in h['finalReleaseBindings']]
summary['auditOutputSha256']={x:hashlib.sha256((a.input_dir/x/'metrics.json').read_bytes()).hexdigest() for x in ['versions','audio','handoffs','operations']}
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(f'Wrote aggregate summary: {a.output}')
