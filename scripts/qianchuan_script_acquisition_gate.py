"""Durable first-batch CSV barrier for this package's detail RPA workflow."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from qianchuan_script_acquisition_receipt import atomic_json

GATE_FILENAME = "first-batch-csv-gate.json"
CONNECTOR_CODE = "rpa.conn.juliang.qc.material.analysis.video.live.diagnosis"
NO_CSV_MESSAGE = "首批素材详情任务均已结束，但没有返回有效 CSV 数据，当前入参可能有问题。已暂停本次运行后续所有 RPA、补位与重试；请核对店铺、广告主、RPA 授权账号、日期及素材参数后，由用户确认重新发起。"
UNCONFIRMED_MESSAGE = "首批素材详情任务状态尚未全部确认，已暂停本次运行后续所有 RPA、补位与重试。请先核对已有任务状态；不能据此判断入参错误，也不能自动重新提交。"


class RpaPausedError(RuntimeError):
    def __init__(self, gate: dict[str, Any]):
        self.gate = gate
        self.error_code = gate.get("errorCode") or "first_batch_result_unconfirmed"
        super().__init__(gate.get("message") or UNCONFIRMED_MESSAGE)


def assert_detail_rpa_not_paused(output_dir: Path) -> None:
    """Never clear a persisted barrier when reopening or changing input."""
    output_dir = Path(output_dir)
    path = output_dir / GATE_FILENAME
    if path.exists():
        try:
            gate = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            gate = {}
        if not isinstance(gate, dict) or gate.get("status") != "passed":
            raise RpaPausedError(gate if isinstance(gate, dict) else {})
    status_path = output_dir / "status.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return  # The acquisition entrypoint also rejects all existing runs.
        if isinstance(status, dict) and status.get("state") == "rpaPaused":
            raise RpaPausedError(status)


class FirstBatchCsvGate:
    def __init__(self, output_dir: Path, material_ids: list[str]):
        if (
            not isinstance(material_ids, list) or not 1 <= len(material_ids) <= 3
            or any(not isinstance(mid, str) or not mid.strip() or mid != mid.strip() for mid in material_ids)
            or len(set(material_ids)) != len(material_ids)
        ):
            raise ValueError("首批 CSV 门禁必须包含 1 至 3 个唯一、非空素材 ID")
        self.path = Path(output_dir) / GATE_FILENAME
        self._submission_lock = Lock()
        self._claimed: set[tuple[str, int]] = set()
        if self.path.exists():
            raise RpaPausedError(json.loads(self.path.read_text(encoding="utf-8")))
        self.payload: dict[str, Any] = {
            "schemaVersion": 1,
            "runId": Path(output_dir).name,
            "connectorCode": CONNECTOR_CODE,
            "status": "pending",
            "firstBatchMaterialIds": list(material_ids),
            "completedMaterialIds": [],
            "validCsvMaterialIds": [],
            "unknownMaterialIds": [],
            "errorCode": None,
            "message": None,
        }
        self._save()

    def _save(self) -> None:
        atomic_json(self.path, self.payload)

    def assert_submission_allowed(self, material_id: str, attempt: int) -> None:
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt not in {1, 2}:
            raise ValueError("RPA attempt must be 1 or 2")
        status = self.payload["status"]
        if status == "passed":
            return
        if status == "pending" and attempt == 1 and material_id in self.payload["firstBatchMaterialIds"]:
            return
        raise RpaPausedError(self.payload)

    def claim_submission(self, material_id: str, attempt: int) -> None:
        """A low-level caller cannot resubmit the same attempt with this gate."""
        with self._submission_lock:
            self.assert_submission_allowed(material_id, attempt)
            if (material_id, attempt) in self._claimed:
                raise RuntimeError("RPA attempt already started; do not resubmit")
            self._claimed.add((material_id, attempt))
            atomic_json(self.path.parent / "rpa-submission-claims.json", {
                "schemaVersion": 1, "runId": self.path.parent.name,
                "attempts": [{"materialId": mid, "attempt": number} for mid, number in sorted(self._claimed)],
            })

    def record_valid_csv(self, material_id: str) -> None:
        if material_id in self.payload["firstBatchMaterialIds"] and material_id not in self.payload["validCsvMaterialIds"]:
            self.payload["validCsvMaterialIds"].append(material_id)
            self.payload["validCsvMaterialIds"].sort(key=self.payload["firstBatchMaterialIds"].index)
            self._save()

    def record_result(self, material_id: str, *, terminal: bool) -> None:
        if material_id not in self.payload["firstBatchMaterialIds"]:
            return
        key = "completedMaterialIds" if terminal else "unknownMaterialIds"
        if material_id not in self.payload[key]:
            self.payload[key].append(material_id)
            self.payload[key].sort(key=self.payload["firstBatchMaterialIds"].index)
        observed = set(self.payload["completedMaterialIds"]) | set(self.payload["unknownMaterialIds"])
        if observed == set(self.payload["firstBatchMaterialIds"]):
            self.finish()
        else:
            self._save()

    def finish(self) -> None:
        if self.payload["status"] == "passed":
            return
        if self.payload["unknownMaterialIds"] or set(self.payload["completedMaterialIds"]) != set(self.payload["firstBatchMaterialIds"]):
            self.payload.update(status="unconfirmed", errorCode="first_batch_result_unconfirmed", message=UNCONFIRMED_MESSAGE)
        elif self.payload["validCsvMaterialIds"]:
            self.payload.update(status="passed", errorCode=None, message=None)
        else:
            self.payload.update(status="blocked", errorCode="first_batch_no_valid_csv", message=NO_CSV_MESSAGE)
        self._save()
