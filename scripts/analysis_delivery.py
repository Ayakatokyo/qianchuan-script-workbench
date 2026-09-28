"""Local analysis delivery primitives; no network or model calls."""
from __future__ import annotations
from datetime import datetime, timezone
from functools import wraps
import hashlib
import html
import json
import os
from pathlib import Path
import tempfile
import time


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


def read_page(root, number):
    index = verify_pages(root)
    if number < 1 or number > len(index["pages"]):
        raise ValueError("page outside analysis handoff")
    page = read(local_file(root, index["pages"][number-1]["path"]))
    return {**page, "pageCount": len(index["pages"]), "nextPage": number+1 if number < len(index["pages"]) else None}


def render_delivery(root, title, identity, cards, limitations, sources):
    """Deterministic offline HTML; the adapter must first validate business evidence."""
    root = Path(root)
    inputs = {p: sha(local_file(root, p)) for p in sources}
    data = {"schemaVersion": 1, "title": title, "identity": identity,
            "conclusions": cards, "limitations": limitations, "inputHashes": inputs}
    esc = lambda value: html.escape(str(value), quote=True)
    blocks = []
    for card in cards:
        evidence = "".join("<tr><td>" + esc(e["material"]) + "</td><td>" + esc(e["field"]) + "</td><td><pre>" + esc(e["value"] if isinstance(e["value"], str) else json.dumps(e["value"], ensure_ascii=False)) + "</pre></td></tr>" for e in card["evidence"])
        blocks.append("<article><small>" + esc(card["type"]) + "</small><h2>" + esc(card["claim"]) + "</h2><details open><summary>核对依据</summary><table><thead><tr><th>素材</th><th>字段</th><th>真实值 / 原文</th></tr></thead><tbody>" + evidence + "</tbody></table></details></article>")
    counts = {}
    for card in cards:
        counts[card["type"]] = counts.get(card["type"], 0) + 1
    chart = "".join("<p>" + esc(k) + " <meter min='0' max='" + str(max(1, len(cards))) + "' value='" + str(v) + "'></meter> " + str(v) + "</p>" for k, v in counts.items())
    numeric = {}
    for card in cards:
        for entry in card["evidence"]:
            value = entry["value"]
            if entry.get("isMetric") and type(value) in (int, float):
                numeric.setdefault(entry["field"], {})[entry["material"]] = value
    for field, values in numeric.items():
        if len(values) < 2:
            continue
        low, high = min(0, min(values.values())), max(1, max(values.values()))
        chart += "<h2>" + esc(field) + " · 引用素材对比</h2>"
        chart += "".join("<p>" + esc(material) + " <meter min='" + str(low) + "' max='" + str(high) + "' value='" + str(value) + "'></meter> " + esc(value) + "</p>" for material, value in values.items())
    document = "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>" + esc(title) + "</title><style>body{max-width:1100px;margin:40px auto;padding:0 20px;font-family:system-ui;background:#f5f7fb;color:#203045}article,header,aside{background:white;border:1px solid #dde4ed;border-radius:12px;padding:24px;margin:20px 0}h2{font-size:20px}table{width:100%;border-collapse:collapse}td,th{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #eee}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;margin:0}small{color:#566c83}meter{width:180px} @media(max-width:650px){td,th{padding:6px}body{padding:0 10px}}</style><header><h1>" + esc(title) + "</h1><p>" + esc(identity.get("analysisId", "")) + " · " + str(len(cards)) + " 条结论</p><p>以下结论仅适用于本次所选素材；指标关联不代表因果。</p>" + chart + "</header>" + "".join(blocks) + "<aside><h2>缺口与限制</h2><ul>" + "".join("<li>" + esc(x) + "</li>" for x in limitations) + "</ul></aside></html>"
    folder = root / "analysis-report"
    write(folder / "report.json", data)
    write(folder / "index.html", document)
    receipt = {"schemaVersion": 1, "status": "completed", "verification": "passed", "identity": identity,
               "inputHashes": inputs, "outputs": {"report.json": sha(folder / "report.json"), "index.html": sha(folder / "index.html")}}
    write(folder / "receipt.json", receipt)
    verify_delivery(root)
    return {"status": "completed", "verification": "passed", "reportPath": str(folder / "index.html"), "receiptPath": str(folder / "receipt.json")}


def verify_delivery(root):
    root = Path(root)
    receipt = read(root / "analysis-report/receipt.json")
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
