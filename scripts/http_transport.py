"""Shared environment-only HTTP transport."""
from __future__ import annotations
from dataclasses import dataclass
import json
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen

class ReportClientError(RuntimeError):
    pass


class UrlLibResponse:
    def __init__(self, body: bytes, status: int, headers: Mapping[str, Any] | None = None):
        self.content = body
        self.status_code = status
        self.headers = dict(headers or {})

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise ReportClientError(f"gateway returned HTTP {self.status_code}")

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))

    def iter_content(self, chunk_size: int = 1024 * 1024):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]


class UrllibTransport:
    """Standard-library transport so each Skill ZIP runs independently."""

    def _request(self, method: str, url: str, *, json_payload: Any = None, headers: Mapping[str, str] | None = None, cookies: Mapping[str, str] | None = None, timeout: float = 60) -> UrlLibResponse:
        request_headers = {str(key): str(value) for key, value in (headers or {}).items()}
        if cookies:
            request_headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
        body = None if json_payload is None else json.dumps(json_payload, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=body, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                return UrlLibResponse(response.read(), int(response.status), response.headers)
        except HTTPError as exc:
            return UrlLibResponse(exc.read(), int(exc.code), exc.headers)

    def post(self, url: str, **kwargs: Any) -> UrlLibResponse:
        return self._request("POST", url, json_payload=kwargs.get("json"), headers=kwargs.get("headers"), cookies=kwargs.get("cookies"), timeout=kwargs.get("timeout", 60))

    def get(self, url: str, **kwargs: Any) -> UrlLibResponse:
        return self._request("GET", url, headers=kwargs.get("headers"), cookies=kwargs.get("cookies"), timeout=kwargs.get("timeout", 60))


@dataclass(frozen=True)
class RuntimeContext:
    api_base: str
    authorization: str
    agent_session: str
    cookie_session: str

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "RuntimeContext":
        api_base = str(environ.get("ENV_BACKEND_HOST", "")).strip().rstrip("/")
        authorization = str(environ.get("YUCE_AUTHORIZATION", "")).strip()
        agent_session = str(environ.get("YUCE_SESSION_ID") or environ.get("YCSESSIONID") or authorization).strip()
        cookie_session = str(environ.get("YCSESSIONID") or authorization).strip()
        missing = [name for name, value in (("ENV_BACKEND_HOST", api_base), ("YUCE_AUTHORIZATION", authorization), ("session", agent_session), ("cookie session", cookie_session)) if not value]
        if missing:
            raise ReportClientError("missing report runtime environment: " + ", ".join(missing))
        return cls(api_base, authorization, agent_session, cookie_session)


def build_runtime_transport() -> UrllibTransport:
    return UrllibTransport()
