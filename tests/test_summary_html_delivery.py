import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_batch3_workbench import synthetic_run, write_json
from workbench_reporting import WorkbenchError, build_summary, render_summary, verify_handoff


class SummaryHtmlDeliveryTests(unittest.TestCase):
    def test_full_verified_script_and_metadata_are_projected_without_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            run = synthetic_run(Path(directory))
            path = run / 'facts/qianchuan-script-source-pack.json'
            pack = json.loads(path.read_text())
            pack['scripts'][0]['rawText'] = '完整脚本段落。' * 80
            write_json(path, pack)
            write_json(run / 'source-data/material-report-snapshot.json', {'rows': [
                {'dimensions': {'素材ID': {'Value': 'm1'}, 'roi2_material_video_name': {'Value': '报表素材名称'}}},
            ]})
            summary, _, _ = build_summary(run)
            self.assertEqual(summary['materials'][0]['materialName'], '报表素材名称')
            self.assertEqual(summary['materials'][0]['script']['text'], pack['scripts'][0]['rawText'])
            self.assertEqual(summary['materials'][0]['script']['formula'], {'labels': ['痛点开场']})
            self.assertEqual(summary['metricDefinitions']['stat_cost_for_roi2']['label'], '整体消耗')

    def test_html_receipt_and_handoff_are_bound_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            run = synthetic_run(Path(directory), state='partialFailed')
            reply = render_summary(run)
            html = run / 'overview/index.html'
            self.assertTrue(html.is_file())
            self.assertEqual(Path(reply['reportPath']), html.resolve())
            handoff, _, _ = verify_handoff(run)
            self.assertEqual(handoff['htmlReport']['sha256'], hashlib.sha256(html.read_bytes()).hexdigest())
            before = {p: p.read_bytes() for p in run.rglob('*') if p.is_file()}
            self.assertTrue(render_summary(run)['idempotent'])
            self.assertEqual(before, {p: p.read_bytes() for p in run.rglob('*') if p.is_file()})
            html.write_text(html.read_text() + 'tampered')
            with self.assertRaises(WorkbenchError):
                verify_handoff(run)

    def test_legacy_markdown_adds_html_without_changing_existing_handoff_or_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            run = synthetic_run(Path(directory))
            render_summary(run)
            (run / 'overview/index.html').unlink()
            receipt_path = run / 'overview/receipt.json'
            receipt = json.loads(receipt_path.read_text())
            receipt.pop('htmlReportSha256', None)
            receipt['outputs'] = [ref for ref in receipt['outputs'] if ref['path'] != 'overview/index.html']
            write_json(receipt_path, receipt)
            handoff_path = run / 'analysis-handoff.json'
            handoff = json.loads(handoff_path.read_text())
            handoff.pop('htmlReport', None)
            write_json(handoff_path, handoff)
            old_files = {path: path.read_bytes() for path in (handoff_path, run/'overview/report.md', run/'overview/summary-data.json')}
            reply = render_summary(run)
            self.assertTrue(Path(reply['reportPath']).is_file())
            self.assertEqual(old_files, {p:p.read_bytes() for p in old_files})
            verify_handoff(run)

    def test_html_failure_does_not_publish_overview_or_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            run = synthetic_run(Path(directory))
            with patch('workbench_reporting.render_html', side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError):
                    render_summary(run)
            self.assertFalse((run/'analysis-handoff.json').exists())
            self.assertFalse((run/'overview').exists())
            self.assertEqual(json.loads((run/'status.json').read_text())['state'], 'ready')
