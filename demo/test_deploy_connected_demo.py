from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from demo.deploy_connected_demo import (
    MODELS,
    deploy_aws,
    deploy_classic,
    harness_request,
    matching_harness,
    verify_role,
)

ACCOUNT = "123456789012"
ROLE = f"arn:aws:iam::{ACCOUNT}:role/Demo"


def test_aws_request_uses_region_specific_model_without_optional_services():
    session = pytest.importorskip("botocore.session").get_session()
    validate = pytest.importorskip("botocore.validate").validate_parameters
    operation = session.get_service_model("bedrock-agentcore-control").operation_model("CreateHarness")
    for region, model in MODELS.items():
        request = harness_request(region, ROLE, model)
        validate(request, operation.input_shape)
        assert request["memory"] == {"disabled": {}}
        assert request["tools"] == []
        assert request == harness_request(region, ROLE, model)
    assert harness_request("ap-northeast-2", ROLE, MODELS["ap-northeast-2"])["clientToken"] != (
        harness_request("ap-northeast-1", ROLE, MODELS["ap-northeast-1"])["clientToken"]
    )


def test_preflight_then_apply_without_overwriting(monkeypatch):
    boto3 = pytest.importorskip("boto3")
    sts, bedrock, harness = Mock(), Mock(), Mock()
    sts.get_caller_identity.return_value = {"Account": ACCOUNT, "Arn": ROLE}
    harness.list_harnesses.return_value = {"harnesses": []}
    harness.create_harness.return_value = {"harness": {"harnessId": "new-id"}}
    harness.get_harness.return_value = {"harness": {"status": "READY"}}
    session = Mock()
    clients = {"sts": sts, "bedrock": bedrock, "bedrock-agentcore-control": harness}
    session.client.side_effect = lambda name, **kwargs: clients[name]
    monkeypatch.setattr(boto3, "Session", lambda **kwargs: session)
    args = SimpleNamespace(
        account=ACCOUNT, profile="demo", execution_role=ROLE, region="ap-northeast-2", apply=False,
    )
    deploy_aws(args)
    harness.create_harness.assert_not_called()
    args.apply = True
    deploy_aws(args)
    harness.create_harness.assert_called_once()
    harness.get_harness.assert_called_once_with(harnessId="new-id")
    harness.list_harnesses.return_value = {
        "harnesses": [{"harnessName": "EasmSeoulSample", "status": "READY"}],
    }
    with pytest.raises(ValueError, match="덮어쓰지"):
        deploy_aws(args)
    harness.create_harness.assert_called_once()


def test_reject_wrong_identity_and_incomplete_pagination():
    with pytest.raises(ValueError, match="비루트"):
        verify_role({"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:root"}, ACCOUNT, ROLE)
    client = Mock()
    client.list_harnesses.return_value = {"harnesses": [], "nextToken": "repeat"}
    with pytest.raises(ValueError, match="반복"):
        matching_harness(client, "EasmSeoulSample")


@pytest.mark.parametrize("denied", [False, True])
def test_classic_prepares_or_preserves_service_denial(monkeypatch, denied):
    boto3 = pytest.importorskip("boto3")
    error = pytest.importorskip("botocore.exceptions").ClientError
    sts, client = Mock(), Mock()
    sts.get_caller_identity.return_value = {"Account": ACCOUNT, "Arn": ROLE}
    client.get_paginator.return_value.paginate.return_value = [{"agentSummaries": []}]
    client.create_agent.return_value = {"agent": {"agentId": "sample"}}
    client.get_agent.side_effect = [
        {"agent": {"agentStatus": "NOT_PREPARED"}},
        {"agent": {"agentStatus": "PREPARED"}},
    ]
    session = Mock()
    session.client.side_effect = lambda service, **kw: sts if service == "sts" else client
    monkeypatch.setattr(boto3, "Session", lambda **kw: session)
    args = SimpleNamespace(
        account=ACCOUNT, profile="demo", execution_role=ROLE, region="ap-northeast-1", apply=True,
    )
    if denied:
        client.create_agent.side_effect = error({
            "Error": {"Code": "AccessDeniedException", "Message": "Maintenance Mode"},
        }, "CreateAgent")
        with pytest.raises(error, match="Maintenance Mode"):
            deploy_classic(args)
        client.prepare_agent.assert_not_called()
    else:
        deploy_classic(args)
        client.prepare_agent.assert_called_once_with(agentId="sample")
    client.create_agent.assert_called_once()
