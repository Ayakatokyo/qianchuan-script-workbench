"""Versioned input and state contracts for Qianchuan script acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from date_policy import validate_period
from errors import ContractError


SCRIPT_PARSE_STATUSES = frozenset({"parsed", "missing", "failed"})
ACQUISITION_STATES = frozenset(
    {
        "awaitingInput",
        "awaitingSelection",
        "querying",
        "rpaProcessing",
        "sourcePackBuilding",
        "sourcePackVerifying",
        "ready",
        "partialFailed",
        "failed",
    }
)


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{key} must be a non-empty string")
    return value.strip()


def _period(payload: Mapping[str, Any]) -> dict[str, str]:
    value = payload.get("period") or payload.get("dateRange")
    if not isinstance(value, Mapping):
        raise ContractError("period must contain startDate and endDate")
    start = _required_text(value, "startDate")
    end = _required_text(value, "endDate")
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
        if start_date.isoformat() != start or end_date.isoformat() != end:
            raise ValueError
    except ValueError as exc:
        raise ContractError("period dates must use YYYY-MM-DD") from exc
    if start_date > end_date:
        raise ContractError("period.startDate must not be after endDate")
    return {"startDate": start, "endDate": end}


@dataclass(frozen=True)
class LiveAcquire:
    api_shop: str
    rpa_shop: str
    advertiser_id: str | None = None
    top_n: int = 10
    material_filter_sort: dict[str, Any] | None = None
    timeout_sec: int = 600

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LiveAcquire":
        if not isinstance(payload, Mapping):
            raise ContractError("liveAcquire must be an object")
        top_n = payload.get("topN", 10)
        if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1:
            raise ContractError("topN must be a positive integer")
        timeout_sec = payload.get("timeoutSec", 600)
        if isinstance(timeout_sec, bool) or not isinstance(timeout_sec, int) or timeout_sec < 1:
            raise ContractError("timeoutSec must be a positive integer")
        return cls(
            api_shop=_required_text(payload, "apiShop"),
            rpa_shop=_required_text(payload, "rpaShop"),
            advertiser_id=_required_text(payload, "advertiserId") if "advertiserId" in payload else None,
            top_n=top_n,
            material_filter_sort=dict(payload.get("materialFilterSort") or {}),
            timeout_sec=timeout_sec,
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "apiShop": self.api_shop,
            "rpaShop": self.rpa_shop,
            "topN": self.top_n,
            "materialFilterSort": self.material_filter_sort or {},
            "timeoutSec": self.timeout_sec,
        }
        if self.advertiser_id is not None:
            result["advertiserId"] = self.advertiser_id
        return result


@dataclass(frozen=True)
class VerifiedRun:
    source_run: str

    @classmethod
    def from_value(cls, value: Any) -> "VerifiedRun":
        if isinstance(value, str):
            source_run = value
        elif isinstance(value, Mapping):
            source_run = value.get("sourceRun") or value.get("runRoot") or value.get("path")
        else:
            source_run = None
        if not isinstance(source_run, str) or not source_run.strip():
            raise ContractError("verifiedRun must identify a source run")
        return cls(source_run=source_run.strip())

    def to_dict(self) -> dict[str, str]:
        return {"sourceRun": self.source_run}


@dataclass(frozen=True)
class AcquisitionRequest:
    period: dict[str, str]
    live_acquire: LiveAcquire | None = None
    verified_run: VerifiedRun | None = None
    schema_version: int = 1

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AcquisitionRequest":
        if not isinstance(payload, Mapping):
            raise ContractError("acquisition request must be an object")
        present = [key for key in ("liveAcquire", "verifiedRun") if payload.get(key) is not None]
        if len(present) != 1:
            raise ContractError("exactly one of liveAcquire or verifiedRun is required")
        version = payload.get("schemaVersion", 1)
        if version != 1:
            raise ContractError("schemaVersion must be 1")
        live = LiveAcquire.from_dict(payload["liveAcquire"]) if present[0] == "liveAcquire" else None
        verified = VerifiedRun.from_value(payload["verifiedRun"]) if present[0] == "verifiedRun" else None
        period = _period(payload)
        if live is not None:
            period = validate_period(period["startDate"], period["endDate"])
        return cls(period=period, live_acquire=live, verified_run=verified, schema_version=version)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"schemaVersion": self.schema_version, "period": self.period}
        if self.live_acquire is not None:
            payload["liveAcquire"] = self.live_acquire.to_dict()
        if self.verified_run is not None:
            payload["verifiedRun"] = self.verified_run.to_dict()
        return payload
