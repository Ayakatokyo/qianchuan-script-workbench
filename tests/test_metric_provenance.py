"""Regression coverage for live and historical report-backed metric evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from test_batch3_workbench import synthetic_run, plan_for, write_json, sha
from workbench_reporting import render_summary
from workbench_analysis import prepare_analysis, publish_analysis, verify_analysis, WorkbenchError, _build_fact_slice
from qianchuan_script_acquisition_fact_pack import bind_report_metric_sources


def snapshot_run(root):
    run = synthetic_run(root)
    pack_path = run / 'facts/qianchuan-script-source-pack.json'
    pack = json.loads(pack_path.read_text())
    rows = [{'materialId': m['materialId'], 'stat_cost_for_roi2': m['metrics']['stat_cost_for_roi2']} for m in pack['materials']]
    rows_sha = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    relative = 'source-data/material-report-snapshot.json'
    snapshot = {'complete': True, 'recordCount': 2, 'rows': rows, 'rowsSha256': rows_sha,
                'queryFingerprint': 'query', 'scopeFingerprint': 'scope'}
    write_json(run / relative, snapshot)
    digest = sha(run / relative)
    write_json(run / 'report-query-receipt.json', {'runId': run.name, 'status': 'completed', 'snapshotPath': relative,
        'snapshotSha256': digest, 'rowsSha256': rows_sha, 'recordCount': 2, 'queryFingerprint': 'query', 'scopeFingerprint': 'scope'})
    pack['selection'].update(reportSnapshotPath=relative, reportSnapshotSha256=digest)
    for m in pack['materials']:
        m['sourceRefs'] = []
    write_json(pack_path, pack)
    return run, pack


class MetricProvenanceTests(unittest.TestCase):
    def test_old_pack_derives_zero_and_field_evidence_without_overwriting(self):
        with tempfile.TemporaryDirectory() as d:
            run, pack = snapshot_run(Path(d))
            original = deepcopy(pack)
            bound = bind_report_metric_sources(pack, run)
            self.assertEqual(pack, original)
            ref = bound['materials'][0]['metricSourceRefs']['stat_cost_for_roi2'][0]
            self.assertIn('&row=0&materialId=m1&field=stat_cost_for_roi2', ref)
            self.assertEqual(bind_report_metric_sources(bound, run), bound)
            facts = _build_fact_slice(pack, plan_for(run), bound['materials'], 'a' * 64)
            self.assertEqual(facts['materials'][0]['metrics']['stat_cost_for_roi2']['value'], 0)
            self.assertTrue(facts['materials'][0]['metrics']['stat_cost_for_roi2']['available'])

    def test_rejects_snapshot_tampering_wrong_row_value_and_forged_ref(self):
        with tempfile.TemporaryDirectory() as d:
            run, pack = snapshot_run(Path(d))
            for mutate in ('value', 'identity', 'reference'):
                bad = deepcopy(pack)
                if mutate == 'value': bad['materials'][0]['metrics']['stat_cost_for_roi2'] = 12.5
                if mutate == 'identity': bad['materials'][0]['materialId'] = 'missing'
                if mutate == 'reference': bad['materials'][0]['metricSourceRefs'] = {'stat_cost_for_roi2': ['forged']}
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    bind_report_metric_sources(bad, run)
            path = run / pack['selection']['reportSnapshotPath']
            path.write_bytes(path.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'hash'):
                bind_report_metric_sources(pack, run)

    def test_missing_source_and_missing_value_have_distinct_gaps(self):
        with tempfile.TemporaryDirectory() as d:
            run, pack = snapshot_run(Path(d))
            pack['materials'][1]['metrics']['stat_cost_for_roi2'] = None
            facts = _build_fact_slice(pack, plan_for(run), pack['materials'], 'a' * 64)
            reasons = {g['reason'] for g in facts['gaps']}
            self.assertIn('metric_source_missing', reasons)
            self.assertIn('metric_value_missing', reasons)

    def test_prepare_publish_verify_binds_metrics_and_rechecks_source(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); run, pack = snapshot_run(root)
            render_summary(run)
            original = (run / 'facts/qianchuan-script-source-pack.json').read_bytes()
            plan = plan_for(run); path = root / 'plan.json'; write_json(path, plan)
            prepared = prepare_analysis(run, path); out = Path(prepared['outputPath'])
            facts = json.loads((out / 'facts-slice.json').read_text())
            self.assertEqual(facts['metricEvidencePolicy'], 'verified_report_fields_v1')
            result = {'schemaVersion': 1, 'runId': run.name, 'analysisId': out.name, 'operation': 'analysis',
                'sourcePackSha256': sha(run / 'facts/qianchuan-script-source-pack.json'),
                'planSha256': sha(out / 'validated-plan.json'), 'modelInputSha256': sha(out / 'model-input.json'),
                'conclusions': [{'claim': '首条素材消耗为零。', 'classification': 'platformFact', 'evidenceRefs': [{
                    'materialId': 'm1', 'field': 'metric', 'fieldId': 'stat_cost_for_roi2',
                    'sourceRefs': facts['materials'][0]['metrics']['stat_cost_for_roi2']['sourceRefs']}]}], 'limitations': []}
            result_path = root / 'result.json'; write_json(result_path, result)
            self.assertEqual(publish_analysis(out, result_path)['status'], 'completed')
            self.assertIn('analysis-result.json', verify_analysis(out))
            self.assertEqual((run / 'facts/qianchuan-script-source-pack.json').read_bytes(), original)
            snapshot = run / pack['selection']['reportSnapshotPath']; snapshot.write_bytes(snapshot.read_bytes() + b' ')
            with self.assertRaises(WorkbenchError): verify_analysis(out)

    def test_connector_document_uses_runtime_code(self):
        from qianchuan_script_acquisition_rpa_client import CONNECTOR_CODE
        text = (Path(__file__).parents[1] / 'SKILL.md').read_text()
        self.assertIn('`' + CONNECTOR_CODE + '`', text)
        self.assertNotIn('rpa_' + CONNECTOR_CODE, text)
