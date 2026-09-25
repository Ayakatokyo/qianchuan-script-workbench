"""Injected, redacted, single-submit RPA client for script diagnosis."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Mapping
from urllib.parse import urlsplit

from http_transport import RuntimeContext as HttpRuntimeContext
from http_transport import build_runtime_transport


RUNNING_STATUSES = frozenset({"pending", "running"})
SUCCESS_STATUSES = frozenset({"completed", "partial_success"})
DEFAULT_CSV_MAX_BYTES = 100 * 1024 * 1024
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RpaClientError(RuntimeError):
    pass


class RpaAuthorizationError(RpaClientError):
    pass


class RpaTaskError(RpaClientError):
    pass


class RpaContractError(RpaClientError, ValueError):
    pass


def _schema_error(schema: dict[str, Any], params: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator
        errors = sorted(Draft202012Validator(schema).iter_errors(params), key=lambda item: tuple(str(part) for part in item.absolute_path))
    except Exception as exc:
        raise RpaContractError("invalid RPA JSON Schema") from exc
    if errors:
        raise RpaContractError("RPA business params failed Schema validation: " + "; ".join(error.message for error in errors))


def _type_matches(name: str, value: Any) -> bool:
    normalized = name.upper().replace("-", "_")
    if normalized in {"STRING", "STR", "TEXT", "DATE", "DATETIME"}:
        return isinstance(value, str)
    if normalized in {"INTEGER", "INT", "LONG"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if normalized in {"NUMBER", "FLOAT", "DOUBLE", "DECIMAL"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if normalized in {"ARRAY", "LIST"}:
        return isinstance(value, list)
    if normalized in {"OBJECT", "MAP", "JSON"}:
        return isinstance(value, dict)
    return True


def validate_business_params(detail: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise RpaContractError("business_params must be a JSON object")
    schema_text = detail.get("inParamJsonSchemaText")
    if schema_text is not None:
        if not isinstance(schema_text, str) or not schema_text.strip():
            raise RpaContractError("inParamJsonSchemaText must contain JSON Schema text")
        try:
            schema = json.loads(schema_text)
        except json.JSONDecodeError as exc:
            raise RpaContractError("RPA JSON Schema text is invalid") from exc
        _schema_error(schema, params)
        return params
    definitions = {str(item.get("param")): item for item in detail.get("inParamList", []) if isinstance(item, Mapping) and item.get("param")}
    if not isinstance(detail.get("inParamList"), list):
        raise RpaContractError("inParamList must be a list when Schema text is absent")
    unknown = sorted(set(params) - set(definitions))
    errors = [f"unknown field: {name}" for name in unknown]
    for name, definition in definitions.items():
        if definition.get("isRequired") is True and (name not in params or params[name] in (None, "")):
            errors.append(f"{name} is required")
        if name in params and params[name] is not None and definition.get("dataTypeEnum") and not _type_matches(str(definition["dataTypeEnum"]), params[name]):
            errors.append(f"{name} has invalid type")
    if errors:
        raise RpaContractError("RPA business params failed inParamList validation: " + "; ".join(errors))
    return params


@dataclass(frozen=True)
class RpaTaskResult:
    task_group_id: str
    status: str
    files: tuple[dict[str, Any], ...] = ()
    records: tuple[dict[str, Any], ...] = ()


def _account_id(account: Mapping[str, Any]) -> str:
    return str(account.get("shopId") or account.get("shop_id") or account.get("accountId") or account.get("id") or "").strip()


def poll_existing_task(gateway: Any, task_group_id: str, *, clock=time.monotonic, sleep=time.sleep, timeout_sec: float = 3600) -> RpaTaskResult:
    deadline = clock() + timeout_sec
    while True:
        if clock() >= deadline:
            raise RpaTaskError(f"RPA task timed out: {task_group_id}")
        result = gateway.poll(task_group_id)
        if not isinstance(result, RpaTaskResult):
            if isinstance(result, Mapping):
                result = RpaTaskResult(str(result.get("task_group_id") or task_group_id), str(result.get("status") or ""), tuple(result.get("files") or ()), tuple(result.get("records") or ()))
            else:
                raise RpaTaskError("RPA poll returned an invalid result")
        status = result.status.lower()
        if status in SUCCESS_STATUSES:
            return result
        if status == "failed":
            raise RpaTaskError(f"RPA task failed: {task_group_id}")
        if status not in RUNNING_STATUSES:
            raise RpaTaskError(f"RPA task returned unknown status: {result.status}")
        sleep(min(1.0, max(0.0, deadline - clock())))


def invoke_once(gateway: Any, detail: dict[str, Any], rpa_shop: str, params: dict[str, Any], *, clock=time.monotonic, sleep=time.sleep, timeout_sec: float = 3600) -> RpaTaskResult:
    validated = validate_business_params(detail, params)
    gateway.authorize(rpa_shop)
    task_id = gateway.submit(detail, rpa_shop, validated)
    if not isinstance(task_id, str) or not task_id:
        raise RpaTaskError("RPA submit returned no task_group_id")
    return poll_existing_task(gateway, task_id, clock=clock, sleep=sleep, timeout_sec=timeout_sec)


class RpaGateway:
    """Optional live transport wrapper; tests and offline runs inject a fake gateway."""

    def __init__(self, transport: Any = None, environ: Mapping[str, str] | None = None, *, connector_code: str):
        self.connector_code = connector_code
        self.transport = transport
        self.environ = dict(os.environ if environ is None else environ)
        self._detail: dict[str, Any] | None = None

    def _context(self) -> HttpRuntimeContext:
        return HttpRuntimeContext.from_environ(self.environ)

    def _transport(self) -> Any:
        if self.transport is None:
            self.transport = build_runtime_transport()
        return self.transport

    def _post(self, path: str, payload: dict[str, Any], *, timeout: float = 60) -> Any:
        context = self._context()
        response = self._transport().post(
            context.api_base + path,
            json=payload,
            headers={"Accept": "application/json", "Content-Type": "application/json;charset=UTF-8"},
            cookies={"YCSESSIONID": context.cookie_session},
            timeout=timeout,
        )
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        payload = response.json() if hasattr(response, "json") else response
        if not isinstance(payload, Mapping) or payload.get("success") is False:
            raise RpaClientError("RPA gateway returned failure")
        return payload

    def connector_detail(self) -> dict[str, Any]:
        payload = self._post("/dcConnector/v3/listByConnectorCode", {"connectorCode": self.connector_code})
        data = payload.get("data")
        matches = [item for item in data if isinstance(item, Mapping) and item.get("connectorCode") == self.connector_code] if isinstance(data, list) else []
        if len(matches) != 1:
            raise RpaClientError("RPA connector detail is unavailable or ambiguous")
        self._detail = dict(matches[0])
        return self._detail

    def list_accounts(self, detail: dict[str, Any]) -> list[dict[str, Any]]:
        context = self._context()
        payload = self._post("/adg/v1/agent/rpa/authorizations/query", {"authorization": context.authorization, "platform": detail.get("platformCode")})
        accounts = payload.get("data") if isinstance(payload, Mapping) else payload
        if isinstance(accounts, Mapping):
            accounts = accounts.get("accounts") or accounts.get("list")
        return list(accounts or [])

    def authorize(self, rpa_shop: str) -> dict[str, Any]:
        detail = self._detail or self.connector_detail()
        accounts = self.list_accounts(detail)
        for account in accounts:
            if _account_id(account) == str(rpa_shop).strip():
                return dict(account)
        raise RpaAuthorizationError("rpaShop is not authorized for the current credentials")

    def submit(self, detail: dict[str, Any], rpa_shop: str, params: dict[str, Any]) -> str:
        context = self._context()
        payload = self._post("/adg/v1/agent/fetch/tasks", {
            "authorization": context.authorization,
            "agent_session_id": context.agent_session,
            "data_source_type": "rpa",
            "platform": detail.get("platformCode"),
            "function_code": self.connector_code,
            "business_params": params,
            "shop_id": str(rpa_shop).strip(),
        }, timeout=30)
        data = payload.get("data") if isinstance(payload, Mapping) else None
        task_id = data.get("task_group_id") if isinstance(data, Mapping) else None
        if not isinstance(task_id, str) or not task_id:
            raise RpaTaskError("RPA submit returned no task_group_id")
        return task_id

    def poll(self, task_group_id: str) -> RpaTaskResult:
        context = self._context()
        payload = self._post("/adg/v1/agent/fetch/tasks/status", {"authorization": context.authorization, "task_group_id": task_group_id}, timeout=30)
        data = payload.get("data") if isinstance(payload, Mapping) else None
        data = data if isinstance(data, Mapping) else {}
        result_content = data.get("result_content")
        result_content = result_content if isinstance(result_content, Mapping) else {}
        status = data.get("status") or result_content.get("status") or ""
        files = data.get("files")
        if not isinstance(files, list):
            files = result_content.get("files")
        records = data.get("records")
        if not isinstance(records, list):
            records = data.get("payload")
        if not isinstance(records, list):
            records = result_content.get("records")
        if not isinstance(records, list):
            records = result_content.get("payload")
        return RpaTaskResult(
            task_group_id,
            str(status),
            tuple(files if isinstance(files, list) else ()),
            tuple(records if isinstance(records, list) else ()),
        )

    def download_csv(self, result: Mapping[str, Any], target: Path, *, max_bytes: int = DEFAULT_CSV_MAX_BYTES) -> Path:
        filename = str(result.get("fileName") or result.get("name") or "").strip()
        if not filename and result.get("fileUrl"):
            filename = Path(urlsplit(str(result["fileUrl"])).path).name
        if not filename or not _SAFE_FILENAME.fullmatch(filename) or Path(filename).name != filename:
            raise ValueError("unsafe filename")
        content = result.get("content")
        if content is None:
            if self.transport is None or not result.get("fileUrl"):
                raise RpaClientError("RPA result has no downloadable content")
            response = self._transport().get(result["fileUrl"], stream=True, timeout=3600)
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            content = b"".join(response.iter_content(chunk_size=1024 * 1024))
        if not isinstance(content, (bytes, bytearray)):
            raise ValueError("download content must be bytes")
        if len(content) == 0:
            raise ValueError("downloaded file is empty")
        if len(content) > max_bytes:
            raise ValueError("downloaded file size exceeds limit")
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
            os.replace(temporary, target)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise
        return target
