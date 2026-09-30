"""Full-snapshot leaderboard must not widen the accepted script/analysis scope."""
import hashlib
import json
import re
from pathlib import Path
import tempfile
import unittest

from tests.test_batch3_workbench import synthetic_run, write_json
from tests.test_workbench_report_html import Document
from workbench_reporting import build_summary, WorkbenchError
from workbench_report_html import render_html
from script_creation_contracts import validate_payload


def snapshot(run):
    rows = [
        {'dimensions': {'material_id': {'Value': f'm{i}'}, 'roi2_material_video_name': {'Value': f'素材{i}'}},
         'metrics': {'stat_cost_for_roi2': {'Value': i * 10, 'ValueStr': f'{i * 10}.00'},
                     'total_ecpm_for_roi2': {'Value': 12.34, 'ValueStr': '12.34'},
                     'video_play_finish_rate_for_roi2_v2': {'Value': i, 'ValueStr': f'{i}.00%'},
                     'unmapped_new_metric': {'Value': 0, 'ValueStr': '0'},
                     'invalid_nested': {'Value': {'url': 'https://private.invalid'}, 'ValueStr': 'private'}}}
        for i in range(1, 5)]
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    body = {'rows': rows, 'complete': True, 'recordCount': 4, 'rowsSha256': digest,
            'queryFingerprint': 'q', 'scopeFingerprint': 's'}
    path = run / 'source-data/material-report-snapshot.json'
    write_json(path, body)
    write_json(run / 'report-query-receipt.json', {
        'runId': run.name, 'status': 'completed', 'snapshotPath': 'source-data/material-report-snapshot.json',
        'snapshotSha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        **{key: body[key] for key in ('recordCount', 'rowsSha256', 'queryFingerprint', 'scopeFingerprint')}})
    return path


class FullLeaderboardTests(unittest.TestCase):
    def test_all_report_rows_and_metrics_do_not_widen_script_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            run = synthetic_run(Path(directory)); snapshot(run)
            summary, _, handoff = build_summary(run)
            board = summary['leaderboard']
            self.assertEqual(board['scope'], 'fullReport')
            self.assertEqual([m['materialId'] for m in board['materials']], ['m4', 'm3', 'm2', 'm1'])
            self.assertEqual(handoff['materialIds'], ['m1', 'm2'])
            self.assertEqual(len(summary['materials']), 2)
            self.assertEqual(board['materials'][0]['metricDisplay']['video_play_finish_rate_for_roi2_v2'], '4.00%')
            self.assertEqual(board['materials'][0]['metrics']['video_play_finish_rate_for_roi2_v2'], 4)
            self.assertNotIn('invalid_nested', board['metricDefinitions'])
            self.assertEqual(board['metricDefinitions']['total_ecpm_for_roi2']['label'], '整体千次展现费用')
            validate_payload(summary, 'summary-data.schema.json')

    def test_full_rows_stay_in_facts_but_not_in_detail_report(self):
        with tempfile.TemporaryDirectory() as directory:
            run = synthetic_run(Path(directory)); snapshot(run)
            summary, _, _ = build_summary(run)
            html = render_html(summary)
            doc = Document(html)
            model = json.loads(re.search(r'<script id="workbench-model" type="application/json">(.*?)</script>', html).group(1))
            rows = doc.find('tr', **{'class': 'material-row'})
            self.assertEqual(len(rows), 0)
            self.assertNotIn('素材4', doc.find('body')[0]['text'])
            self.assertEqual(len(model['materials']), 2)
            self.assertNotIn('筛选条件与排序字段', doc.find('body')[0]['text'])
            self.assertEqual(len(doc.find('dialog')), 1)
            self.assertTrue(any(field['id'] == 'unmapped_new_metric'
                                for item in model['materials'] for field in item['metrics']))
            self.assertNotIn('https://private.invalid', html)

    def test_altered_snapshot_fails_instead_of_showing_unverified_full_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            run = synthetic_run(Path(directory)); path = snapshot(run)
            body = json.loads(path.read_text()); body['rows'][0]['metrics']['stat_cost_for_roi2']['Value'] = 999
            write_json(path, body)
            with self.assertRaises(WorkbenchError): build_summary(run)

    def test_changed_rows_digest_rejected_even_when_file_digest_is_updated(self):
        with tempfile.TemporaryDirectory() as directory:
            run = synthetic_run(Path(directory)); path = snapshot(run)
            body = json.loads(path.read_text()); body['rows'].pop(); write_json(path, body)
            receipt_path = run / 'report-query-receipt.json'; receipt = json.loads(receipt_path.read_text())
            receipt['snapshotSha256'] = hashlib.sha256(path.read_bytes()).hexdigest(); write_json(receipt_path, receipt)
            with self.assertRaises(WorkbenchError): build_summary(run)

    def test_legacy_without_snapshot_does_not_invent_full_report(self):
        with tempfile.TemporaryDirectory() as directory:
            run = synthetic_run(Path(directory)); summary, _, handoff = build_summary(run)
            self.assertEqual(summary['leaderboard']['scope'], 'selectedMaterials')
            self.assertEqual(len(summary['leaderboard']['materials']), 2)
            self.assertEqual(len(handoff['materialIds']), 2)

    def test_raw_numeric_zero_and_display_dash_remain_distinct_in_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            run = synthetic_run(Path(directory)); snapshot(run)
            summary, _, _ = build_summary(run)
            item = summary['leaderboard']['materials'][0]
            item['metrics']['stat_cost_for_roi2'] = 0
            item['metricDisplay']['stat_cost_for_roi2'] = '-'
            doc = Document(render_html(summary))
            self.assertEqual(item['metrics']['stat_cost_for_roi2'], 0)
            self.assertEqual(item['metricDisplay']['stat_cost_for_roi2'], '-')
            self.assertFalse(doc.find('td'))


if __name__ == '__main__': unittest.main()
