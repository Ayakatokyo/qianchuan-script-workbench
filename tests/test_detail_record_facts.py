import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_batch3_workbench import synthetic_run, plan_for, write_json
from detail_record_facts import index_attempt, select_detail_records
from workbench_reporting import render_summary
from workbench_analysis import prepare_analysis, check_analysis_result, publish_analysis, WorkbenchError


def indexed_run(root):
    run = synthetic_run(root)
    pack_path = run / "facts/qianchuan-script-source-pack.json"
    pack = json.loads(pack_path.read_text())
    indexes = []
    for mid in ("m1", "m2"):
        rows = [
            {"materialId": mid, "recordType": "crowd_analysis", "parseStatus": "parsed",
             "Dimensions": {"gender": "女", "age": age}, "Metrics": {"views": 0}, "extra": "原始信息"}
            for age in ("25-30", "31-35")
        ] + [{"materialId": mid, "recordType": "interaction_series", "parseStatus": "parsed", "durationSec": 1, "metricValue": 0}]
        csv = run / f"source-data/rpa/{mid}.csv"
        csv.parent.mkdir(parents=True, exist_ok=True)
        csv.write_text("recordType\x01materialId\n\x02interaction_series\x01" + mid + "\n")
        path = csv.with_suffix(".records.json")
        write_json(path, rows)
        files = [{"kind": kind, "path": p.relative_to(run).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                 for kind, p in (("csv", csv), ("records-json", path))]
        indexes.append(index_attempt(run, mid, {"identityState": "matched", "payloadFiles": files}))
    pack["detailSources"] = indexes
    write_json(pack_path, pack)
    render_summary(run)
    return run


class DetailRecordFactsTests(unittest.TestCase):
    def test_detail_offsets_and_numeric_filters_keep_original_row_references(self):
        with tempfile.TemporaryDirectory() as td:
            run = indexed_run(Path(td))
            index = json.loads((run / "facts/qianchuan-script-source-pack.json").read_text())["detailSources"][:1]
            selection = {"recordTypes": ["crowd_analysis"], "limitPerMaterial": 1}
            first = select_detail_records(run, index, ["m1"], selection)["m1"]["crowd_analysis"]
            second = select_detail_records(run, index, ["m1"], {**selection, "offsetPerMaterial": 1})["m1"]["crowd_analysis"]
            self.assertFalse(second["hasMore"])
            self.assertEqual(second["value"][0]["Dimensions"]["age"], "31-35")
            self.assertNotEqual(first["sourceRefs"], second["sourceRefs"])
            selection = {"recordTypes": ["interaction_series"], "filters": [
                {"field": "durationSec", "op": "gte", "value": 1},
                {"field": "durationSec", "op": "lte", "value": 1},
                {"field": "metricValue", "op": "in", "value": [0]}]}
            result = select_detail_records(run, index, ["m1"], selection)["m1"]["interaction_series"]
            self.assertEqual(result["returnedRecordCount"], 1)
            self.assertEqual(result["value"][0]["metricValue"], 0)

    def test_default_analysis_does_not_expand_detail_records(self):
        with tempfile.TemporaryDirectory() as td:
            run = indexed_run(Path(td))
            plan = Path(td) / "plan.json"
            write_json(plan, plan_for(run))
            result = prepare_analysis(run, plan)
            facts = json.loads((Path(result["outputPath"]) / "facts-slice.json").read_text())
            self.assertNotIn("detailEvidenceSources", facts)
            self.assertTrue(all("detailFields" not in m for m in facts["materials"]))

    def test_filtered_page_preserves_zero_and_publishes_bound_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            run = indexed_run(Path(td))
            plan = plan_for(run)
            plan["materialSelection"] = {"mode": "materialIds", "materialIds": ["m1"]}
            plan["detailSelection"] = {"recordTypes": ["crowd_analysis"],
                "fields": ["Dimensions", "Metrics.views"], "limitPerMaterial": 1,
                "filters": [{"field": "Dimensions.gender", "op": "eq", "value": "女"}]}
            path = Path(td) / "plan.json"
            write_json(path, plan)
            root = Path(prepare_analysis(run, path)["outputPath"])
            facts = json.loads((root / "facts-slice.json").read_text())
            entry = facts["materials"][0]["detailFields"]["crowd_analysis"]
            self.assertEqual(entry["matchingRecordCount"], 2)
            self.assertTrue(entry["hasMore"])
            self.assertEqual(entry["nextOffset"], 1)
            self.assertEqual(entry["value"][0]["Metrics"]["views"], 0)
            self.assertNotIn("extra", entry["value"][0])
            self.assertEqual(len(facts["detailEvidenceSources"]), 1)
            result = json.loads((root / "result-template.json").read_text())
            result["conclusions"] = [{"claim": "所选人群记录的观看指标为零。", "classification": "platformFact",
                "evidenceRefs": [{"materialId": "m1", "field": "detailRecord", "fieldId": "crowd_analysis", "sourceRefs": entry["sourceRefs"]}]}]
            output = Path(td) / "result.json"
            write_json(output, result)
            check_analysis_result(root, output)
            result["conclusions"][0]["evidenceRefs"][0]["fieldId"] = "interaction_series"
            write_json(output, result)
            with self.assertRaises(WorkbenchError):
                check_analysis_result(root, output)
            result["conclusions"][0]["evidenceRefs"][0]["fieldId"] = "crowd_analysis"
            write_json(output, result)
            self.assertEqual(publish_analysis(root, output)["deliveryStatus"], "awaiting_host_report")

    def test_source_change_and_identity_mismatch_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            run = indexed_run(Path(td))
            pack = json.loads((run / "facts/qianchuan-script-source-pack.json").read_text())
            source = pack["detailSources"][0]["sources"][0]
            self.assertIsNone(index_attempt(run, "m1", {"identityState": "mismatch", "payloadFiles": []}))
            plan = plan_for(run)
            plan["detailSelection"] = {"recordTypes": ["interaction_series"]}
            path = Path(td) / "plan.json"
            write_json(path, plan)
            root = Path(prepare_analysis(run, path)["outputPath"])
            result = json.loads((root / "result-template.json").read_text())
            entry = json.loads((root / "facts-slice.json").read_text())["materials"][0]["detailFields"]["interaction_series"]
            result["conclusions"] = [{"claim": "记录可用。", "classification": "platformFact", "evidenceRefs": [
                {"materialId": "m1", "field": "detailRecord", "fieldId": "interaction_series", "sourceRefs": entry["sourceRefs"]}]}]
            output = Path(td) / "result.json"
            write_json(output, result)
            (run / source["path"]).write_text("[]")
            with self.assertRaises(WorkbenchError):
                check_analysis_result(root, output)

    def test_missing_selected_fields_are_gaps(self):
        with tempfile.TemporaryDirectory() as td:
            run = indexed_run(Path(td))
            plan = plan_for(run)
            plan["detailSelection"] = {"recordTypes": ["crowd_analysis"], "fields": ["Metrics.missing"]}
            path = Path(td) / "plan.json"
            write_json(path, plan)
            root = Path(prepare_analysis(run, path)["outputPath"])
            facts = json.loads((root / "facts-slice.json").read_text())
            self.assertFalse(facts["materials"][0]["detailFields"]["crowd_analysis"]["available"])
            self.assertTrue(any(g["field"] == "crowd_analysis" for g in facts["gaps"]))
