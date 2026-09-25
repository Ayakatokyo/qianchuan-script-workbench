import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from short_video_foundation.qianchuan_script_acquisition.verified_run import import_verified_run


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Batch3VerifiedRunTests(unittest.TestCase):
    def test_import_verified_run_verifies_hashes_and_does_not_mutate_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source-run"
            fact_pack = source / "fact-pack"
            leaderboard = {"materials": [{"materialId": "m1", "rank": 1, "metrics": {"综合成本": "10"}}]}
            scripts = {"scripts": [{"materialId": "m1", "text": "原始参考脚本", "parseStatus": "parsed", "sourceRefs": ["rpa/records/m1.json"]}]}
            leaderboard_path = fact_pack / "material-leaderboard.json"
            scripts_path = fact_pack / "scripts.json"
            write_json(leaderboard_path, leaderboard)
            write_json(scripts_path, scripts)
            manifest = {
                "schemaVersion": 1,
                "files": [
                    {"path": "material-leaderboard.json", "sha256": hashlib.sha256(leaderboard_path.read_bytes()).hexdigest()},
                    {"path": "scripts.json", "sha256": hashlib.sha256(scripts_path.read_bytes()).hexdigest()},
                ],
            }
            write_json(fact_pack / "manifest.json", manifest)
            before = {path: (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) for path in source.rglob("*") if path.is_file()}
            output = root / "output"
            result = import_verified_run(source, output)
            after = {path: (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) for path in source.rglob("*") if path.is_file()}
            self.assertEqual(before, after)
            payload = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(payload["scripts"][0]["rawText"], "原始参考脚本")
            self.assertNotIn(str(source), result.read_text(encoding="utf-8"))
            receipt = json.loads((output / "acquisition-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "completed")
            self.assertEqual(receipt["sourceRun"], str(source))

    def test_import_rejects_hash_mismatch_and_missing_required_fact_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source-run" / "fact-pack"
            write_json(source / "manifest.json", {"schemaVersion": 1, "files": [{"path": "scripts.json", "sha256": "0" * 64}]})
            write_json(source / "material-leaderboard.json", {"materials": []})
            write_json(source / "scripts.json", {"scripts": []})
            with self.assertRaisesRegex(ValueError, "hash"):
                import_verified_run(source.parent, root / "out")
            (source / "scripts.json").unlink()
            with self.assertRaisesRegex(ValueError, "scripts.json"):
                import_verified_run(source.parent, root / "out2")

    def test_import_accepts_root_scoped_source_files_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source-run"
            fact_pack = source / "fact-pack"
            fact_pack.mkdir(parents=True)
            leaderboard = {"materials": [{"materialId": "m1", "rank": 1, "metrics": {}}]}
            scripts = {"scripts": [{"materialId": "m1", "text": "参考脚本", "parseStatus": "parsed"}]}
            write_json(fact_pack / "material-leaderboard.json", leaderboard)
            write_json(fact_pack / "scripts.json", scripts)
            source_file = source / "source-data" / "receipt.json"
            source_file.parent.mkdir(parents=True)
            source_file.write_text("source receipt\n", encoding="utf-8")
            write_json(
                fact_pack / "manifest.json",
                {
                    "sourceFiles": [{
                        "path": "source-data/receipt.json",
                        "sha256": hashlib.sha256(source_file.read_bytes()).hexdigest(),
                        "sizeBytes": source_file.stat().st_size,
                    }]
                },
            )
            result = import_verified_run(source, root / "output")
            payload = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(payload["scripts"][0]["rawText"], "参考脚本")


if __name__ == "__main__":
    unittest.main()
