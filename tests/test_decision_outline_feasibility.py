"""Offline outline experiment safety and evidence tests; no provider calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from scripts.experiments import decision_outline_feasibility as e
from scripts.experiments import decision_api_weekly_ab as ab

class OutlineFeasibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.manifest={"sources":[]}
        e.configure()
        for index in range(4):
            sid="new-source-"+str(index)
            notes={"schemaVersion":2,"slices":[{"index":1,"segmentEvidence":[
                {"id":"s1","textEn":"The speaker invites trust, not revenge.","textZh":"讲员邀请信靠，而非报复。"},
                {"id":"s2","textEn":"No deadline for justice is promised.","textZh":"没有承诺伸冤日期。"}]}],
                "outlineZh":[{"title":"Section "+str(i),"points":["讲员邀请信靠，而非报复。"],"sourceSliceIndexes":[1]} for i in range(6)]}
            source={"sourceId":sid,"notesFile":"artifacts/"+sid+"/notes.json",
                    "sourceRecordFile":"artifacts/"+sid+"/record.json","items":[]}
            for i in range(6):
                p={"index":i,"kind":"untouched_real"}
                if i>=2:p.update(kind="semantic_variant",parentSha256=ab.digest(notes["outlineZh"][i]),
                    patch={"points":["明天之前一定得到伸冤。"]},family="qualifier_inflation",authorExpectation="unsupported",
                    authorFramingExpectation="misleading")
                source["items"].append(p)
            for name,value in [("notesFile",notes),("sourceRecordFile",{"sourceUrl":"https://www.youtube.com/watch?v="+sid})]:
                path=self.root/source[name];path.parent.mkdir(parents=True,exist_ok=True);ab.atomic(path,value)
            self.manifest["sources"].append(source)
    def tearDown(self):self.temp.cleanup()
    def test_bound_blind_payload_has_all_claims_and_valid_references(self):
        cases,audit=e.build_cases(self.root,self.manifest)
        self.assertEqual(len(cases),24);self.assertEqual(len(audit),24)
        for c in cases:
            payload,bounds,kind=ab.payload_and_bounds(c,"B")
            self.assertEqual(c["payloadSha256"],ab.digest(payload))
            self.assertEqual(json.loads(payload["input"]),c["sharedEvidence"])
            for forbidden in ("authorExpectation","parentSha256","family","sourceStatus","severity"):
                self.assertNotIn(forbidden,payload["input"])
            self.assertEqual(len(c["sharedEvidence"]["claims"]),2)
            self.assertEqual(len(payload["questions"]),5)
            self.assertEqual(c["a"]["adapter"],"common_prechecks_only_not_content_baseline")
    def test_parent_and_original_source_identity_fail_closed(self):
        m=copy.deepcopy(self.manifest);m["sources"][0]["items"][2]["parentSha256"]="changed"
        with self.assertRaisesRegex(ValueError,"variant_parent_changed"):e.build_cases(self.root,m)
        m=copy.deepcopy(self.manifest);m["sources"][0]["sourceId"]="1bleOc_9pWk"
        with self.assertRaisesRegex(ValueError,"development_source_reused"):e.build_cases(self.root,m)
        source=self.manifest["sources"][0];ab.atomic(self.root/source["sourceRecordFile"],{"sourceUrl":"https://www.youtube.com/watch?v=wrong"})
        with self.assertRaisesRegex(ValueError,"source_identity_mismatch"):e.build_cases(self.root,self.manifest)
    def test_no_missing_english_or_duplicate_parent(self):
        m=copy.deepcopy(self.manifest);m["sources"][0]["items"][5]["index"]=4
        with self.assertRaisesRegex(ValueError,"six_distinct_parents_required"):e.build_cases(self.root,m)
        source=self.manifest["sources"][0];path=self.root/source["notesFile"];n=ab.read(path);n["slices"][0]["segmentEvidence"][0]["textEn"]=""
        ab.atomic(path,n)
        with self.assertRaisesRegex(ValueError,"missing_usable_english"):e.build_cases(self.root,self.manifest)
    def test_cached_receipt_restore_never_redispatches(self):
        cases,_=e.build_cases(self.root,self.manifest);c=cases[0]
        out=self.root/"offline"
        first=ab.measured_attempt(c,"B",mode="offline",directory=out)
        restored=ab.measured_attempt(c,"B",mode="offline",directory=out,
            dispatcher=lambda *a:self.fail("offline cache must not dispatch"))
        self.assertEqual(first["status"],"network_not_run");self.assertTrue(restored["restored"])
        changed=copy.deepcopy(c);changed["sharedEvidence"]["draft"]["title"]="changed"
        with self.assertRaisesRegex(ValueError,"cached_receipt_identity_changed"):
            ab.measured_attempt(changed,"B",mode="offline",directory=out)
if __name__=="__main__":unittest.main()
