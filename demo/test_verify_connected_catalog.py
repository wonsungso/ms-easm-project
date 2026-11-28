import pytest

from demo.verify_connected_catalog import verify_catalog


@pytest.fixture
def result():
    return {
        "mode": "live",
        "collection": {
            "facts": {"agent365_registry_complete": True},
            "agent365_packages": [
                {"package_id": "pkg1", "platform": "Observed provider", "detail_complete": True},
                {"package_id": "pkg2", "detail_complete": False},
            ],
        },
    }


def test_reports_distinct_list_and_detail_outcomes(result):
    assert verify_catalog(result, ["pkg1", "pkg3", "pkg2"]) == [
        {"status": "observed", "platform": "Observed provider"},
        {"status": "not_found", "platform": None},
        {"status": "detail_incomplete", "platform": None},
    ]


def test_refuses_incomplete_or_fixture_result(result):
    result["collection"]["facts"]["agent365_registry_complete"] = False
    with pytest.raises(ValueError, match="완료되지 않았습니다"):
        verify_catalog(result, ["pkg1"])
    result["mode"] = "fixture"
    with pytest.raises(ValueError, match="실제 수집 결과"):
        verify_catalog(result, ["pkg1"])


def test_does_not_match_by_name_or_accept_duplicate_ids(result):
    package = result["collection"]["agent365_packages"][0]
    package["display_name"] = "demo"
    assert verify_catalog(result, ["demo"])[0]["status"] == "not_found"
    result["collection"]["agent365_packages"].append(package)
    with pytest.raises(ValueError, match="중복 패키지"):
        verify_catalog(result, ["pkg1"])
