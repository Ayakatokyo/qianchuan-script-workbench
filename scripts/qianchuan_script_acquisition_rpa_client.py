"""Legacy Qianchuan connector wrapper over the shared gateway."""
from rpa_gateway import (RpaGateway as _Gateway, RpaAuthorizationError, RpaClientError, RpaContractError, RpaTaskError, RpaTaskResult, poll_existing_task, validate_business_params)
from date_policy import validate_period
from qianchuan_script_acquisition_gate import FirstBatchCsvGate
CONNECTOR_CODE = "rpa.conn.juliang.qc.material.analysis.video.live.diagnosis"
class RpaGateway(_Gateway):
    def __init__(self, transport=None, environ=None):
        super().__init__(transport, environ, connector_code=CONNECTOR_CODE)


def invoke_once(gateway, detail, rpa_shop, params, *, on_submitted=None, execution_gate=None, attempt=1, **poll_options):
    if not isinstance(execution_gate, FirstBatchCsvGate):
        raise RpaContractError("详情 RPA 必须通过 acquire/continue-acquire 的首批 CSV 门禁执行")
    execution_gate.assert_submission_allowed(str(params.get("material_id") or ""), attempt)
    if params.get("date_type") != "CUSTOM":
        raise RpaContractError("本工作台详情 RPA 必须使用 CUSTOM 起止日期")
    validate_period(params.get("custom_start_date"), params.get("custom_end_date"))
    validated = validate_business_params(detail, params)
    execution_gate.claim_submission(str(params.get("material_id") or ""), attempt)
    gateway.authorize(rpa_shop)
    task_id = gateway.submit(detail, rpa_shop, validated)
    if not isinstance(task_id, str) or not task_id:
        raise RpaTaskError("RPA submit returned no task_group_id")
    if on_submitted is not None:
        on_submitted(task_id)
    result = poll_existing_task(gateway, task_id, **poll_options)
    if result.task_group_id != task_id:
        raise RpaTaskError("RPA result task identity mismatch")
    return result
