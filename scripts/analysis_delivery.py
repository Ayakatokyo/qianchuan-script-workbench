"""Local analysis delivery primitives; no network or model calls."""
from __future__ import annotations
from datetime import datetime, timezone
from functools import wraps
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import unquote, urlsplit


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        f.write(content)
        temporary = f.name
    try:
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def local_file(root, relative):
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("delivery file missing or outside analysis root")
    return target


def prepare_pages(root, identity, records, sources, template, gaps):
    """Five whole records per page. Existing handoffs are immutable."""
    root = Path(root)
    source_hashes = {name: sha(local_file(root, name)) for name in sources}
    index_path = root / "handoff-index.json"
    if index_path.exists():
        index = verify_pages(root)
        if index["identity"] != identity or index["inputHashes"] != source_hashes:
            raise ValueError("handoff inputs changed; create a new analysis")
        return index
    pages = []
    for offset in range(0, len(records), 5):
        number = len(pages) + 1
        name = f"fact-pages/{number:04d}.json"
        write(root / name, {"identity": identity, "page": number, "records": records[offset:offset+5]})
        pages.append({"page": number, "path": name, "sha256": sha(root / name), "recordCount": len(records[offset:offset+5])})
    write(root / "result-template.json", template)
    index = {"schemaVersion": 1, "identity": identity, "inputHashes": source_hashes,
             "recordCount": len(records), "pageSize": 5, "pages": pages, "gaps": gaps,
             "template": {"path": "result-template.json", "sha256": sha(root / "result-template.json")},
             "templateStatus": "draft_requires_model", "instructions": "Read every required page. Copy the template to a new result file; replace empty claims and evidence. Never edit fact pages."}
    write(index_path, index)
    return index


def verify_pages(root):
    index = read(Path(root) / "handoff-index.json")
    entries = [{"path": p, "sha256": h} for p, h in index["inputHashes"].items()]
    entries += index["pages"] + [index["template"]]
    for item in entries:
        if sha(local_file(root, item["path"])) != item["sha256"]:
            raise ValueError("analysis handoff hash mismatch: " + item["path"])
    if sum(p["recordCount"] for p in index["pages"]) != index["recordCount"]:
        raise ValueError("analysis handoff record count mismatch")
    return index


def read_page(root, number, end_number=None, *, verified_index=None):
    index = verified_index if verified_index is not None else verify_pages(root)
    last = number if end_number is None else end_number
    if number < 1 or last < number or last > len(index["pages"]):
        raise ValueError("page outside analysis handoff")
    pages = [read(local_file(root, item["path"])) for item in index["pages"][number-1:last]]
    if end_number is None:
        return {**pages[0], "pageCount": len(index["pages"]), "nextPage": last+1 if last < len(index["pages"]) else None}
    return {"identity": index["identity"], "startPage": number, "endPage": last,
            "pages": pages, "pageCount": len(index["pages"]),
            "nextPage": last+1 if last < len(index["pages"]) else None}


class _LocalAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        for name in ("src", "poster"):
            if values.get(name):
                self.urls.append(values[name])
        if tag == "link" and values.get("href"):
            self.urls.append(values["href"])
        if values.get("srcset"):
            self.urls.extend(item.strip().split()[0] for item in values["srcset"].split(",") if item.strip())


def _asset_path(folder, parent, url):
    parsed = urlsplit(url.strip())
    if parsed.scheme == "data" or (not parsed.path and parsed.fragment):
        return None
    if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
        raise ValueError("report asset must be a local relative file: " + url)
    path = (parent / unquote(parsed.path)).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():
        raise ValueError("report asset missing or outside report directory: " + url)
    return path


_REPORT_ENTRIES = {"html": "index.html", "markdown": "report.md", "text": "report.txt"}


def _check_report_assets(folder, entry_name="index.html"):
    entry = local_file(folder, entry_name)
    if not entry.read_text(encoding="utf-8").strip():
        raise ValueError("host report is empty")
    pending = [entry]
    seen = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        if path.suffix.lower() == ".html":
            parser = _LocalAssets()
            parser.feed(path.read_text(encoding="utf-8"))
            urls = parser.urls + re.findall(r"url\(\s*['\"]?([^'\")]+)", path.read_text(encoding="utf-8"))
        elif path.suffix.lower() == ".css":
            css = path.read_text(encoding="utf-8")
            urls = re.findall(r"url\(\s*['\"]?([^'\")]+)", css)
            urls += re.findall(r"@import\s+['\"]([^'\"]+)", css)
        elif path.suffix.lower() == ".md":
            urls = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8"))
        else:
            continue
        pending.extend(target for url in urls if (target := _asset_path(folder, path.parent, url)) is not None)


def register_host_report(root, identity, sources, revision=None, report_format=None):
    """Seal a host-authored report after the caller verifies its analysis result."""
    root = Path(root).resolve()
    if revision is not None and not re.fullmatch(r"[0-9]{4}", revision):
        raise ValueError("report revision must be four digits")
    if revision is not None:
        existing = sorted(path.parent.name for path in (root / "analysis-report/revisions").glob("*/receipt.json"))
        if existing and revision <= existing[-1]:
            raise ValueError("report revision must be newer than the current revision")
    folder = root / "analysis-report" / "revisions" / revision if revision else root / "analysis-report"
    if (folder / "receipt.json").exists():
        raise ValueError("report receipt already exists; do not overwrite a delivered report")
    available = [name for name in _REPORT_ENTRIES.values() if (folder / name).is_file()]
    if report_format is None:
        if len(available) != 1:
            raise ValueError("report directory must contain exactly one entry: index.html, report.md or report.txt")
        entry_name = available[0]
        report_format = next(key for key, name in _REPORT_ENTRIES.items() if name == entry_name)
    else:
        if report_format not in _REPORT_ENTRIES:
            raise ValueError("unsupported report format")
        entry_name = _REPORT_ENTRIES[report_format]
        if available != [entry_name]:
            raise ValueError("report entry missing or multiple formats present")
    _check_report_assets(folder, entry_name)
    outputs = {}
    for path in folder.rglob("*"):
        if revision is None and path.is_relative_to(folder / "revisions"):
            continue
        if path.is_symlink():
            raise ValueError("report symlink is not allowed")
        if path.is_file():
            outputs[path.relative_to(folder).as_posix()] = sha(path)
    inputs = {name: sha(local_file(root, name)) for name in sources}
    receipt = {"schemaVersion": 3 if revision else 2, "status": "completed", "verification": "passed", "producer": "conversation_host",
               "identity": identity, "inputHashes": inputs, "outputs": outputs,
               "entryPath": entry_name, "format": report_format, "revision": revision}
    write(folder / "receipt.json", receipt)
    verify_delivery(root)
    return {"status": "completed", "deliveryStatus": "completed", "reportVerified": True,
            "reportPath": str(folder / entry_name), "receiptPath": str(folder / "receipt.json"), "revision": revision}


def has_report_receipt(root):
    folder = Path(root) / "analysis-report"
    return (folder / "receipt.json").is_file() or any((folder / "revisions").glob("*/receipt.json"))


def _verify_report_receipt(root, folder):
    receipt = read(folder / "receipt.json")
    version = receipt.get("schemaVersion")
    if version in (2, 3):
        entry = receipt.get("entryPath", "index.html")
        if (receipt.get("status") != "completed" or receipt.get("verification") != "passed"
                or receipt.get("producer") != "conversation_host"
                or receipt.get("identity", {}).get("analysisId") != root.name
                or not receipt.get("inputHashes") or entry not in receipt.get("outputs", {})
                or entry not in _REPORT_ENTRIES.values()
                or (receipt.get("format") is not None and _REPORT_ENTRIES.get(receipt["format"]) != entry)
                or (version == 3 and folder.name != receipt.get("revision"))):
            raise ValueError("invalid host report receipt")
        for name, digest in receipt["inputHashes"].items():
            if sha(local_file(root, name)) != digest:
                raise ValueError("host report input changed: " + name)
        actual = {path.relative_to(folder).as_posix(): sha(path) for path in folder.rglob("*")
                  if path.is_file() and path.name != "receipt.json"
                  and (folder != root / "analysis-report" or not path.is_relative_to(folder / "revisions"))}
        if actual != receipt["outputs"]:
            raise ValueError("host report output missing, added or changed")
        _check_report_assets(folder, entry)
        return receipt
    return None


def verify_delivery(root):
    root = Path(root)
    base = root / "analysis-report"
    folders = ([base] if (base / "receipt.json").is_file() else [])
    folders += sorted(path.parent for path in (base / "revisions").glob("*/receipt.json"))
    if not folders:
        raise ValueError("analysis report receipt missing")
    for folder in folders:
        checked = _verify_report_receipt(root, folder)
        if checked is not None:
            receipt = checked
            continue
        if folder != base:
            raise ValueError("invalid report revision receipt")
        receipt = read(folder / "receipt.json")
        if len(folders) > 1:
            raise ValueError("legacy report cannot be revised in place")
        break
    if receipt.get("schemaVersion") in (2, 3):
        return {**receipt, "reportPath": str(folders[-1] / receipt.get("entryPath", "index.html")),
                "revisionHistory": [str(folder / "receipt.json") for folder in folders]}
    if (receipt.get("schemaVersion") != 1 or receipt.get("status") != "completed"
            or receipt.get("verification") != "passed"
            or set(receipt.get("outputs", {})) != {"report.json", "index.html"}
            or not receipt.get("inputHashes")
            or receipt.get("identity", {}).get("analysisId") != root.name):
        raise ValueError("invalid analysis report receipt")
    data = read(root / "analysis-report/report.json")
    if data.get("identity") != receipt["identity"] or data.get("inputHashes") != receipt["inputHashes"]:
        raise ValueError("analysis report data and receipt differ")
    for p, digest in receipt["inputHashes"].items():
        if sha(local_file(root, p)) != digest:
            raise ValueError("analysis report input changed: " + p)
    for p, digest in receipt["outputs"].items():
        if sha(local_file(root / "analysis-report", p)) != digest:
            raise ValueError("analysis report output changed: " + p)
    return receipt


def timed_phase(name):
    """Record actual local calls only; no inferred model/backend wait duration."""
    def decorate(fn):
        @wraps(fn)
        def wrapped(root, *args, **kwargs):
            started = datetime.now(timezone.utc).isoformat()
            tick = time.monotonic()
            state, exit_code = "failed", 1
            try:
                result = fn(root, *args, **kwargs)
                exit_code = result if type(result) is int else 0
                state = (result.get("status") or result.get("workflowState") or "returned") if isinstance(result, dict) else ("returned" if not exit_code else "failed")
                return result
            finally:
                event = {"phase": name, "startedAt": started, "endedAt": datetime.now(timezone.utc).isoformat(),
                         "wallSeconds": round(time.monotonic()-tick, 6), "status": state, "exitCode": exit_code,
                         "scope": "local_call_wall_time_including_awaited_work"}
                path = Path(root)
                if path.is_dir():
                    with (path / "execution-events.jsonl").open("a", encoding="utf-8") as target:
                        target.write(json.dumps(event, ensure_ascii=False) + "\n")
        return wrapped
    return decorate


def field_summary(field, values, *, label=None):
    """Bounded examples for field discovery; never a substitute for complete evidence."""
    present = [(identity, value) for identity, value, available in values if available]
    def kind(value):
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "array"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, str):
            return "string"
        return "null"
    samples = []
    for identity, value in present[:1]:
        preview = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        samples.append({"materialId": identity, "preview": preview[:180], "truncated": len(preview) > 180,
                        "keys": list(value)[:12] if isinstance(value, dict) else None})
    return {"field": field, "label": label, "recordCount": len(values), "availableCount": len(present),
            "valueTypes": sorted({kind(value) for _, value in present}), "samples": samples}
