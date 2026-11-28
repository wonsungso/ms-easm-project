"""Check Agent 365 catalog observations against independently verified package IDs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from easm_agent.models import Agent365Package
from easm_agent.report import load_result


def verify_catalog(result: dict[str, Any], package_ids: list[str]) -> list[dict[str, str | None]]:
    if not package_ids or len(set(package_ids)) != len(package_ids) or any(
        not key or key != key.strip() for key in package_ids
    ):
        raise ValueError("비어 있지 않은 서로 다른 Agent 365 패키지 ID를 지정하세요.")
    if result.get("mode") != "live":
        raise ValueError("실제 수집 결과만 검증할 수 있습니다. 합성 데이터는 E2E 증적이 아닙니다.")
    collection = result["collection"]
    if collection.get("facts", {}).get("agent365_registry_complete") is not True:
        raise ValueError("Agent 365 목록 조회가 완료되지 않았습니다. 수집 이슈를 확인하세요.")
    index: dict[str, Agent365Package] = {}
    for raw in collection["agent365_packages"]:
        package = Agent365Package.model_validate(raw)
        if package.package_id in index:
            raise ValueError("수집된 목록에 중복 패키지 ID가 있습니다.")
        index[package.package_id] = package
    checks = []
    for key in package_ids:
        row = index.get(key)
        checks.append({
            "status": "not_found" if row is None else (
                "observed" if row.detail_read_completed or row.detail_complete else "detail_incomplete"
            ),
            "platform": row.platform if row else None,
        })
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--package-id", action="append", required=True)
    args = parser.parse_args()
    try:
        checks = verify_catalog(load_result(args.run), args.package_id)
    except (KeyError, OSError, ValidationError):
        print("Agent 365 결과 파일을 읽거나 검증할 수 없습니다.", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if all(row["status"] == "observed" for row in checks) else 2


if __name__ == "__main__":
    raise SystemExit(main())
