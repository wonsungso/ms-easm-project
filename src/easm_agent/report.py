from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import unquote

from easm_agent.assessment_codes import ASSESSMENT_REVISION
from easm_agent.azure import redact
from easm_agent.models import Collection, Finding, load_criteria
from easm_agent.proposals import azure_agents
from easm_agent.provenance import digest
from easm_agent.report_backdata import metrics_by_key
from easm_agent.report_excel import write_workbook
from easm_agent.report_pptx import DEFAULT_CUSTOMER, DeckContext, write_presentation

RAW_PATTERN = "raw-data-*.json"
RUN_PATTERN = re.compile(r"(?P<stamp>\d{8}T\d{12}Z)(?:-(?P<sequence>\d+))?")


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.{uuid.uuid4().hex}.pending")
    try:
        staging.write_bytes(payload)
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def _stamp(data: Collection) -> str:
    return data.collected_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def report_stem(data: Collection | dict[str, Any]) -> str:
    from easm_agent.models import timestamp
    from easm_agent.report_integrated import KST

    instant = data.collected_at if isinstance(data, Collection) else timestamp(data.get("collected_at"))
    if instant is None:
        raise ValueError("보고서 파일명에 사용할 수집 시각이 없습니다.")
    return "AI Agent Governance Readiness 진단 결과 보고서 (프로세스·System 통합)_" + instant.astimezone(KST).strftime("%Y%m%d")


def report_name(data: Collection | dict[str, Any], run_stamp: str | None = None) -> str:
    return report_stem(data) + ".xlsx"


def raw_name(data: Collection, run_stamp: str | None = None) -> str:
    return f"raw-data-{run_stamp or _stamp(data)}.json"


def presentation_name(data: Collection | dict[str, Any], run_stamp: str | None = None) -> str:
    return report_stem(data) + ".pptx"


def report_workbook(directory: Path, data: Collection, result: dict[str, Any]) -> Path:
    current = directory / report_name(data)
    if current.is_file():
        return current
    for item in result.get("manifest", {}).get("files", []):
        name = item.get("path")
        if isinstance(name, str) and Path(name).name == name and name.endswith(".xlsx"):
            path = directory / name
            if path.is_file():
                return path
    source = latest_raw(directory)
    if source:
        return directory / ("report-" + source.stem.removeprefix("raw-data-") + ".xlsx")
    return current


def latest_raw(output: Path) -> Path | None:
    """Find the newest run, accepting legacy flat files and a directly selected run folder."""
    candidates = list(output.glob(RAW_PATTERN))
    for directory in output.glob("*"):
        if RUN_PATTERN.fullmatch(directory.name) and directory.is_dir() and not directory.is_symlink():
            candidates.extend(directory.glob(RAW_PATTERN))
    found = []
    for path in candidates:
        if not path.is_file() or path.is_symlink():
            continue
        run = RUN_PATTERN.fullmatch(path.parent.name)
        file_stamp = path.stem.removeprefix("raw-data-")
        file_run = RUN_PATTERN.fullmatch(file_stamp)
        stamp = run["stamp"] if run else file_run["stamp"] if file_run else file_stamp
        try:
            when = datetime.strptime(stamp, "%Y%m%dT%H%M%S%fZ" if run or file_run else "%Y%m%dT%H%M%SZ")
        except ValueError:
            continue
        sequence = int((run or file_run)["sequence"] or 0) if run or file_run else 0
        found.append(((when, sequence, path.name), path))
    return max(found, key=lambda entry: entry[0])[1] if found else None


def create_run_directory(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    sequence = 0
    while True:
        path = output / (stamp if sequence == 0 else f"{stamp}-{sequence}")
        try:
            path.mkdir()
        except FileExistsError:
            sequence += 1
        else:
            return path


def load_result(output: Path) -> dict[str, Any]:
    """Return collection/findings/mode/evidence/provenance/manifest saved in the newest raw-data file."""
    path = latest_raw(output)
    if path is None:
        raise ValueError(f"{RAW_PATTERN} 파일을 찾을 수 없습니다.")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("schema_version") != 1:
        raise ValueError("지원되지 않는 결과 스키마입니다.")
    revision = result["collection"].get("facts", {}).get("assessment_revision")
    if revision not in (None, ASSESSMENT_REVISION):
        raise ValueError(f"지원되지 않는 심사 기준 버전입니다: {revision}")
    codes = load_criteria()["items"]
    if any(row.get("se_code") not in codes for row in result.get("findings", [])):
        raise ValueError("알 수 없는 System Evidence 코드가 있습니다.")
    # Administrator reads from retired sources are not part of the current evidence contract.
    collection = result["collection"]
    if collection.get("admin_evidence"):
        collection["admin_evidence"] = [
            {key: value for key, value in row.items() if key not in ("window_start", "window_end", "counts")}
            for row in collection["admin_evidence"]
            if str(row.get("source", "")).startswith("powerplatform.")
        ]
    return result


class EvidenceLinks:
    """Resolve evidence references to safe local JSON files below the evidence directory."""

    def __init__(self, data: Collection, output: Path) -> None:
        self.output = output.resolve()
        directory = data.facts.get("evidence_directory")
        self.root = Path(directory).absolute() if directory and self.safe(str(directory)) else None

    @staticmethod
    def safe(value: str) -> bool:
        decoded = unquote(value).replace("\\", "/")
        return (
            not decoded.startswith("//")
            and ".." not in decoded.split("/")
            and not any(ord(char) < 32 for char in decoded)
            and "://" not in decoded
            and not re.search(r"(^|/)[^/]*:", decoded[2:] if re.match(r"^[A-Za-z]:/", decoded) else decoded)
        )

    def source(self, reference: str) -> Path | None:
        if self.root is None or not self.root.is_dir() or not self.safe(reference):
            return None
        path = Path(reference)
        # Reject Windows drive-relative paths, including on non-Windows test hosts.
        windows = PureWindowsPath(reference)
        if windows.drive and not windows.is_absolute():
            return None
        candidates = [path] if path.is_absolute() else [
            self.output / path, self.root / path,
            Path.cwd() / path,
        ]
        for candidate in candidates:
            try:
                if any(part.is_symlink() for part in (candidate, *candidate.parents)):
                    continue
                resolved = candidate.resolve()
                if not resolved.is_relative_to(self.root):
                    continue
                if resolved.suffix.lower() != ".json" or not resolved.is_file():
                    continue
            except (OSError, ValueError):
                continue
            return resolved
        return None


def normalize_result(
    data: Collection, findings: list[Finding], output: Path, mode: str,
) -> dict[str, Any]:
    if mode not in ("live", "fixture"):
        raise ValueError("지원되지 않는 데이터 구분입니다.")
    try:
        previous = load_result(output)
    except (OSError, KeyError, ValueError):
        previous = {}
    cached = previous.get("evidence", {})
    collection = data.model_dump(mode="json")
    rows = [finding.model_dump(mode="json") for finding in findings]
    refs: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "evidence_refs" and isinstance(item, list):
                    refs.update(ref for ref in item if isinstance(ref, str))
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(collection)
    collect(rows)
    links = EvidenceLinks(data, output)
    evidence: dict[str, Any] = {}
    references: list[dict[str, Any]] = []
    replacements: dict[str, str] = {}
    old_refs = previous.get("provenance", {}).get("references", [])
    for ref in sorted(refs):
        payload = None
        attached = False
        identifier = ref.removeprefix("evidence:") if ref.startswith("evidence:") else ""
        if not identifier:
            reference_sha256 = hashlib.sha256(redact(ref).encode("utf-8")).hexdigest()
            identifier = next((
                item["id"] for item in old_refs
                if (item.get("reference") == redact(ref) or item.get("reference_sha256") == reference_sha256)
                and item.get("status") == "attached"
            ), "")
        source = links.source(ref) if not ref.startswith("evidence:") else None
        if source is not None:
            try:
                payload = redact(json.loads(source.read_text(encoding="utf-8")))
                identifier, attached = digest(payload), True
            except (OSError, ValueError):
                pass
        elif identifier in cached and digest(cached[identifier]) == identifier:
            path = Path(ref)
            replayable = ref.startswith("evidence:") or (
                links.safe(ref) and not path.exists()
                and not any(part.is_symlink() for part in (path, *path.parents))
            )
            if replayable:
                payload, attached = cached[identifier], True
        if not attached:
            identifier = identifier if len(identifier) == 64 else hashlib.sha256(ref.encode()).hexdigest()
        replacements[ref] = "evidence:" + identifier
        replacements[redact(ref)] = "evidence:" + identifier
        if attached:
            evidence[identifier] = payload
        originals = [item for item in old_refs if item.get("id") == identifier]
        if ref.startswith("evidence:") and originals:
            for item in originals:
                updated = {
                    **item, "reference": "evidence:" + identifier if attached else item["reference"],
                    "sha256": identifier if attached else None,
                    "status": "attached" if attached else "not_found",
                    "detail": None if attached else "파일 확인불가 - 안전한 로컬 파일 연결 불가",
                }
                if updated not in references:
                    references.append(updated)
        else:
            references.append({
                "reference": "evidence:" + identifier if attached else redact(ref),
                "reference_sha256": hashlib.sha256(redact(ref).encode("utf-8")).hexdigest(),
                "id": identifier, "sha256": identifier if attached else None,
                "status": "attached" if attached else "not_found",
                "detail": None if attached else "파일 확인불가 - 안전한 로컬 파일 연결 불가",
            })

    def normalized(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: normalized(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalized(item) for item in value]
        if isinstance(value, str):
            return replacements.get(value, value)
        return value

    collection = normalized(redact(collection))
    collection["facts"]["data_mode"] = mode
    collection["facts"]["assessment_revision"] = ASSESSMENT_REVISION
    if "evidence_directory" in collection["facts"]:
        collection["facts"]["evidence_directory"] = "embedded:evidence"
    return {
        "schema_version": 1, "collection": collection, "findings": normalized(redact(rows)), "mode": mode,
        "evidence": evidence,
        "provenance": {
            "evidence_hash_scope": "SHA-256 - masked JSON, UTF-8, sorted keys, compact separators",
            "references": references,
            "unattached_evidence": [item for item in references if item["status"] != "attached"],
        },
        "manifest": {"credentials_included": False, "files": []},
    }


def write_reports(
    data: Collection, findings: list[Finding], output: Path, mode: str = "live",
    *, new_run: bool = True, customer: str = DEFAULT_CUSTOMER, interview_workbook: Path | None = None,
) -> Path:
    """Write a unique run folder, or rebuild an explicitly selected existing run."""
    if any(agent.platform in ("langchain", "custom") for agent in data.agents):
        raise ValueError("자체 호스트 후보가 포함된 결과는 package --reassess로 재평가한 후 보고서를 생성하세요.")
    output.mkdir(parents=True, exist_ok=True)
    previous = load_result(output) if not new_run and latest_raw(output) else {}
    previous_reports = [
        output / item["path"] for item in previous.get("manifest", {}).get("files", [])
        if isinstance(item.get("path"), str) and Path(item["path"]).name == item["path"]
        and Path(item["path"]).suffix in (".xlsx", ".pptx")
    ]
    if any(path.is_symlink() for path in previous_reports):
        raise ValueError("보고서 파일의 심볼릭 링크는 이름 변경 대상으로 사용할 수 없습니다.")
    result = normalize_result(data, findings, output, mode)
    if new_run:
        output = create_run_directory(output)
        run_stamp = output.name
    else:
        existing = latest_raw(output)
        run_stamp = existing.stem.removeprefix("raw-data-") if existing else (
            output.name if RUN_PATTERN.fullmatch(output.name) else None
        )
    normalized = Collection.model_validate(result["collection"])
    rows = [Finding.model_validate(row) for row in result["findings"]]
    workbook = output / report_name(normalized, run_stamp)
    if interview_workbook is None and not new_run:
        candidate = report_workbook(output, normalized, previous)
        if candidate.is_file():
            from openpyxl import load_workbook

            from easm_agent.report_integrated import is_integrated

            existing_book = load_workbook(candidate, read_only=True)
            if is_integrated(existing_book):
                interview_workbook = candidate
            existing_book.close()
    if interview_workbook is None and not new_run and workbook.is_file():
        from openpyxl import load_workbook

        from easm_agent.report_integrated import is_integrated

        existing_book = load_workbook(workbook, read_only=True)
        if is_integrated(existing_book):
            interview_workbook = workbook
        existing_book.close()
    if interview_workbook is not None:
        origin = {
            "kind": "provided_workbook",
            "sha256": hashlib.sha256(interview_workbook.read_bytes()).hexdigest(),
            "limit": "제공된 수동 입력을 보존. API가 확인·승인한 인터뷰·문서라는 뜻이 아님",
        }
        normalized.facts["manual_input_origin"] = origin
        result["collection"]["facts"]["manual_input_origin"] = origin
    presentation = output / presentation_name(normalized, run_stamp)
    staging = output / f".report.{uuid.uuid4().hex}.pending.xlsx"
    deck_staging = output / f".report.{uuid.uuid4().hex}.pending.pptx"
    try:
        if interview_workbook is None:
            write_workbook(normalized, rows, staging)
        else:
            write_workbook(normalized, rows, staging, interview_workbook=interview_workbook)
        write_presentation(staging, deck_staging, DeckContext(
            customer=customer, collected_at=normalized.collected_at,
            subscriptions=len(normalized.subscriptions), agents=len(azure_agents(normalized)),
            metrics=metrics_by_key(normalized, rows, mode), collection=normalized,
        ))
        payload = staging.read_bytes()
        deck_payload = deck_staging.read_bytes()
        result["manifest"] = {
            "product": "EASM", "mode": mode, "collected_at": normalized.collected_at.isoformat(),
            "files": [
                {"path": workbook.name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
                {"path": presentation.name, "bytes": len(deck_payload),
                 "sha256": hashlib.sha256(deck_payload).hexdigest()},
            ],
            "credentials_included": False,
            "data_hash_scope": "UTF-8 JSON with indent=2, excluding manifest",
            "data_sha256": hashlib.sha256(json_bytes({
                key: value for key, value in result.items() if key != "manifest"
            })).hexdigest(),
        }
        os.replace(staging, workbook)
        os.replace(deck_staging, presentation)
        atomic_write(output / raw_name(normalized, run_stamp), json_bytes(result))
        for path in previous_reports:
            if path not in (workbook, presentation) and path.is_file():
                path.unlink()
    finally:
        staging.unlink(missing_ok=True)
        deck_staging.unlink(missing_ok=True)
        if new_run and not any(output.iterdir()):
            output.rmdir()
    print(f"결과 파일: {workbook} / {presentation} / {output / raw_name(normalized, run_stamp)}")
    return workbook
