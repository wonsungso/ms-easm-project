from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree
from zipfile import ZipFile


def test_public_templates_do_not_publish_personal_author_metadata() -> None:
    docs = Path(__file__).parents[1] / "docs"
    for name in ("assessment-result-template.xlsx", "assessment-report-template.pptx"):
        with ZipFile(docs / name) as archive:
            root = ElementTree.fromstring(archive.read("docProps/core.xml"))
        for tag in (
            "{http://purl.org/dc/elements/1.1/}creator",
            "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}lastModifiedBy",
        ):
            neutral_author = root.findtext(tag) in (None, "", "EASM")
            assert neutral_author, (name, tag)


def test_module_installation_examples_use_a_repository_placeholder() -> None:
    notes = (Path(__file__).parents[1] / "docs" / "api-notes.md").read_text(encoding="utf-8")
    repositories = re.findall(r"(?:Find|Save)-Module[^\n]+-Repository\s+(\S+)", notes)
    assert repositories and set(repositories) == {"$repository"}


def test_screenshot_guide_references_registered_existing_images() -> None:
    docs = Path(__file__).parents[1] / "docs"
    guide = docs.parent / "README.md"
    manifest = json.loads((docs / "manifest.json").read_text(encoding="utf-8"))["authentication"]
    references = {
        (guide.parent / value).resolve()
        for value in re.findall(r"!\[[^\]]*\]\(([^)]+\.png)\)", guide.read_text(encoding="utf-8"))
    }
    expected = {(docs / image["file"]).resolve() for image in manifest["images"]}
    assert len(expected) == 17
    assert references <= expected
    for path in references:
        assert path.is_file(), path


def test_korean_terms_follow_microsoft_learn() -> None:
    root = Path(__file__).parents[1]
    for path in [root / "README.md", *(root / "docs").glob("*.md"), *(root / "demo").glob("*.md")]:
        text = path.read_text(encoding="utf-8")
        assert "후원자" not in text, path
        assert "민감도 라벨" not in text, path
    assert "스폰서" in (root / "docs" / "checklist.md").read_text(encoding="utf-8")


def test_captured_images_are_real_pngs_with_highlight_metadata() -> None:
    directory = Path(__file__).parents[1] / "docs"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["authentication"]
    assert manifest["highlight_color"] == "#d40000"
    assert manifest["account_banner_excluded"] is True
    assert manifest["account_identifiers_masked"] is True
    assert "가렸고" in manifest["display_text_editing"]
    assert manifest["application_and_sp_created"] is True
    assert manifest["credentials_modified"] is True
    assert manifest["credential_counts_before_cleanup"] == {"certificates": 1, "client_secrets": 0}
    assert manifest["collection"]["administrator_fallback"] is False
    assert manifest["collection"]["collect_exit"] == 0
    assert manifest["collection"]["issues_preserved"] == 0
    assert manifest["collection"]["agents_found"] == 10
    assert manifest["collection"]["entra_with_consent"]["blueprints"] == 9
    assert manifest["collection"]["entra_with_consent"]["agent_identities"] == 9
    assert manifest["collection"]["mandatory_findings"] == 22
    assert manifest["collection"]["configured_graph_permissions"] == 3
    assert manifest["collection"]["verified_azure_role_assignments"] == 15
    assert manifest["collection"]["assessment_revision"] == 5
    assert manifest["collection"]["identity_mismatch_exit"] == 1
    assert manifest["collection"]["package_exit"] == 0
    for key in ("temporary_app_deleted", "temporary_sp_deleted", "reader_assignments_deleted", "private_key_deleted"):
        assert manifest["cleanup"][key] is True
    for image in manifest["images"]:
        data = (directory / image["file"]).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert data[12:16] == b"IHDR"
        width, height = struct.unpack(">II", data[16:24])
        assert width >= 300 and height >= (
            120 if image.get("capture_element") == "confirmation_dialog" else 300
        )
        if image.get("capture_element") in ("customer_terminal", "codespaces_terminal"):
            assert image["highlight_count"] == 0 and image["highlight_not_applicable"]
            fields = (
                ("hostname_masked", "subscription_and_principal_masked", "client_id_masked", "home_path_masked")
                if image["capture_element"] == "customer_terminal" else
                ("username_masked", "tenant_id_masked", "subscription_ids_masked", "client_id_masked")
            )
            assert all(image[key] for key in fields)
            assert len(image["mask_boxes_px"]) == 5
            if image["capture_element"] == "codespaces_terminal":
                assert width == 800
                assert image["size_px"] == [width, height]
        else:
            assert image["highlight_count"] > 0
    assert manifest["images"][1]["client_id_masked"] is True
    assert manifest["images"][2]["certificate_registered"] is True
    assert manifest["images"][4]["subscription_and_principal_masked"] is True
    assert manifest["images"][5]["configured_permission_count"] == 3
    assert manifest["images"][6]["consent_granted"] is True
    assert {image["file"] for image in manifest["images"] if image.get("captured_on") == "2026-11-05"} >= {
        "imgs/14-cost-reader.png", "imgs/15-log-reader.png", "imgs/16-security-reader.png",
        "imgs/17-foundry-reader.png", "imgs/18-foundry-permissions.png", "imgs/19-entra-confirm.png",
    }


def test_screenshot_notes_match_the_documented_example() -> None:
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "`easmagent-diagnostic`" in readme
    assert "**[" not in readme
    assert "docs/imgs/12-entra-consent.png" in readme
    step3 = readme.split("## Step 4.", 1)[1].split("## Step 5.", 1)[0]
    for image in ("10-reader-role.png", "17-foundry-reader.png", "12-entra-consent.png"):
        assert f"(docs/imgs/{image})" in step3
    assert "[**customer-setup.zip**](docs/downloads/customer-setup.zip)" in step3
    assert (root / "docs" / "downloads" / "customer-setup.zip").is_file()
    assert "python3 -m zipfile -e customer-setup.zip customer-setup" in step3
    assert "bash setup.sh login" in step3 and "bash setup.sh apply" in step3
    assert "bash scripts/setup.sh login" not in step3


def test_setup_success_example_masks_identifiers_and_covers_all_grants() -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    example = readme.split("## Step 4.", 1)[1].split("## Step 5.", 1)[0]
    assert not re.search(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", example, re.I)
    assert "(docs/imgs/20-customer-setup-success.png)" in example
    assert "```text" not in example
    manifest = json.loads(
        (Path(__file__).parents[1] / "docs" / "manifest.json").read_text(encoding="utf-8"),
    )
    screenshot = next(image for image in manifest["authentication"]["images"]
                      if image["file"] == "imgs/20-customer-setup-success.png")
    assert "고객이 제공한" in screenshot["source"]
    assert screenshot["account_identifiers_masked"] is True


def test_ms_collection_step_uses_existing_certificate_without_shell_variable_dependency() -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    step4 = readme.split("## Step 5.", 1)[1].split("## Step 6.", 1)[0]
    assert "저장소 루트" in step4
    assert "Step 2에서 사용한 동일 Codespaces 터미널" in step4
    assert 'AZURE_CLIENT_CERTIFICATE_PATH="$(python3 scripts/certificate_path.py)" &&' in step4
    assert "read -r -p '위 인증서의 전체 경로: '" not in step4
    assert "$cert_dir" not in step4
    assert 'bash scripts/setup.sh verify --certificate-path "$AZURE_CLIENT_CERTIFICATE_PATH" &&' in step4
    assert "(docs/imgs/21-codespaces-collection-success.png)" in step4


def test_cleanup_commands_and_masked_reference_screenshot_are_preserved() -> None:
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    step5 = readme.split("## Step 6.", 1)[1].split("## 점검 항목", 1)[0]
    for text in ("IAM", "먼저 회수", "다른 활성·적격 할당", "certificate-path", "임시 PIM", "보관 기간"):
        assert text in step5
    assert "bash setup.sh cleanup-plan" in step5 and "bash setup.sh cleanup-apply" in step5
    manifest = json.loads((root / "docs" / "manifest.json").read_text(encoding="utf-8"))
    image = next(image for image in manifest["authentication"]["images"]
                 if image["file"] == "imgs/22-diagnostic-app-delete.png")
    assert image["deletion_executed"] is False
    assert image["highlight_count"] == 1
    assert all(image[key] for key in ("tenant_name_masked", "client_id_masked",
                                      "application_object_id_masked", "tenant_id_masked"))


def test_summary_table_links_resolve_to_checklist_sections_with_images() -> None:
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    detail = (root / "docs" / "checklist.md").read_text(encoding="utf-8")

    anchors = set(re.findall(r'<a id="([^"]+)"></a>', detail))
    links = re.findall(r"^\| \[([A-Z]{2}-SY-[P\d]+)\]\(docs/checklist\.md#([^)]+)\)", readme, re.M)
    assert len(links) == 26
    assert {target for _, target in links} == anchors
    assert len(re.findall(r"^## [A-Z]{2}-SY-\d+ ", detail, re.M)) == 26
    images = re.findall(r"^!\[[^\]]+\]\((portal/imgs/[^)]+\.png)\)$", detail, re.M)
    assert images and all((root / "docs" / image).is_file() for image in images)
    assert "<img" not in readme and not re.search(r"^\|.*!\[", readme, re.M)
    assert "## Agent 365 등록부 교차 확인" not in detail
    for code in ("DP-SY-15", "OE-SY-22"):
        section = re.search(rf"^## {code} .+?(?=^## |\Z)", detail, re.M | re.S)
        assert section and "| 충족 분자 |" in section[0] and "| 한계 |" in section[0]


def test_current_assessment_docs_do_not_include_transition_narrative() -> None:
    root = Path(__file__).parents[1]
    for path in (root / "README.md", root / "docs" / "api-notes.md", root / "docs" / "checklist.md"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"criteria-agent365|기본 v1|공통 평가 v2|공통 등록부 v2|v1·v2|v1 점수|기존 API 평가", text)


def test_summary_lists_all_controls_without_new_item_markers() -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    assert "| 점검 내용 | 수집 방법 | 수집 |" in readme
    methods = [
        line.split("|")[4].strip() for line in readme.splitlines()
        if re.match(r"^\| \[[A-Z]{2}-SY-\d+\]", line)
    ]
    assert len(methods) == 26 and all("→" in method for method in methods)
    assert "신규 추가" not in readme
    rows = re.findall(r"^\| \[([A-Z]{2}-SY-\d+)\].+$", readme, re.M)
    assert len(rows) == 26
    for line in readme.splitlines():
        match = re.match(r"^\| \[([A-Z]{2}-SY-\d+)\]", line)
        if match:
            fields = [field.strip() for field in line.strip("|").split("|")]
            assert len(fields) == 5 and fields[-1] == "✅"
    assert "추가 제안 13개" not in readme and "점수 산정에는 포함하지 않음" not in readme


def test_consolidated_document_links_and_collapsed_demo_are_preserved() -> None:
    root = Path(__file__).parents[1]
    docs = root / "docs"
    assert {path.name for path in docs.glob("*.md")} == {
        "api-notes.md", "checklist.md", "connected-platforms.md",
    }
    for path in [root / "README.md", *docs.glob("*.md"), *(root / "demo").glob("*.md")]:
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            target = unquote(target.split("#", 1)[0].strip("<>"))
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            assert (path.parent / target).exists(), (path.name, target)
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert readme.count("<details>") == 3
    assert "<details open" not in readme
    assert "수집은 나중에 수동 실행" in readme
    assert "raw-data-<타임스탬프>.json" in readme
    assert "AI Agent Governance Readiness 진단 결과 보고서 (프로세스·System 통합)_<수집일>.xlsx" in readme
    assert "results.zip" not in readme and "report.html" not in readme
    assert "docs/assessment-result-template.xlsx" in readme
    assert "bash demo/run.sh --apply --collect" in readme
    assert "bash demo/run.sh --apply\n" in readme
    manifests = json.loads((docs / "manifest.json").read_text(encoding="utf-8"))
    assert (docs / "imgs").is_dir() and not list(docs.glob("*.png"))
    assert {path.name for path in (docs / "imgs").glob("*.png")} == {
        Path(image["file"]).name for image in manifests["authentication"]["images"]
    }
    assert not (docs / "images").exists()
