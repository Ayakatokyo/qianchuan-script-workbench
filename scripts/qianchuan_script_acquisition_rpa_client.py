"""Legacy Qianchuan connector wrapper over the shared gateway."""
from rpa_gateway import (RpaGateway as _Gateway, RpaAuthorizationError, RpaClientError, RpaContractError, RpaTaskError, RpaTaskResult, poll_existing_task, validate_business_params)
CONNECTOR_CODE = "rpa.conn.juliang.qc.material.analysis.video.live.diagnosis"
class RpaGateway(_Gateway):
    def __init__(self, transport=None, environ=None):
        super().__init__(transport, environ, connector_code=CONNECTOR_CODE)


def invoke_once(gateway, detail, rpa_shop, params, *, on_submitted=None, **poll_options):
    validated = validate_business_params(detail, params)
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
