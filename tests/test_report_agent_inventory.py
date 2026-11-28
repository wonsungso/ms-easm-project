from datetime import UTC, datetime, timedelta

from easm_agent.models import (
    Agent365Package,
    AgentEvidence,
    Collection,
    ConnectedAgentMetadata,
    CopilotAgentEvidence,
    CostHistoryEvidence,
    CostRecord,
    HistoricalCostRecord,
    LogSetting,
    ProposalObservation,
)
from easm_agent.report_agent_inventory import agent_report_records, monthly_inventory_cost

NOW = datetime(2026, 11, 27, tzinfo=UTC)


def test_unified_records_include_each_observed_platform_without_catalog_duplicates():
    data = Collection(
        collected_at=NOW,
        agents=[AgentEvidence(collected_at=NOW, platform="foundry", agent_id="foundry", detection_confidence="tag",
                              agent_name="Foundry", resource_id="/account/agent")],
        copilot_agents=[CopilotAgentEvidence(agent_id="bot", environment_id="env", platform="agent_builder",
                                            last_published_at=NOW)],
        agent365_packages=[
            Agent365Package(package_id="azure-copy", platform="Foundry"),
            Agent365Package(package_id="aws", platform="AmazonBedrock", connected_metadata=ConnectedAgentMetadata(
                published_status="Published", source_agent_id_sha256="a" * 64, region="ap-northeast-1")),
            Agent365Package(package_id="snow", platform="SnowflakeAI"),
        ],
    )
    records = agent_report_records(data)
    assert len(records) == 4
    assert [record.published for record in records] == [None, True, True, None]
    assert [record.lifecycle_confirmed for record in records] == [True, True, True, None]
    assert records[0].lifecycle_status == "생성·등록 확인"
    assert "실행 성공은 별도" in records[0].lifecycle_basis
    assert records[2].identifier_sha256 == "a" * 64
    assert records[0].identifier_kind == "Foundry Agent ID"


def test_host_is_excluded_even_with_deployment_evidence_and_registry_is_retained():
    host = AgentEvidence(collected_at=NOW, platform="langchain", agent_id="host", detection_confidence="tag",
                         agent_name="Host")
    data = Collection(
        collected_at=NOW, agents=[host],
        agent365_packages=[Agent365Package(package_id="external", platform="AmazonBedrock",
            connected_metadata=ConnectedAgentMetadata(source_agent_id_sha256="b" * 64))],
    )
    records = agent_report_records(data)
    assert len(records) == 1
    assert records[0].lifecycle_confirmed is True and records[0].published is None
    host.deployed_at = NOW
    assert agent_report_records(data) == records


def test_monthly_matching_requires_exact_observed_cost_rows_not_historical_assumptions():
    agent = AgentEvidence(collected_at=NOW, platform="foundry", agent_id="host", detection_confidence="tag",
                          agent_name="Host", resource_id="/sites/host")
    data = Collection(
        collected_at=NOW, agents=[agent],
        costs=[CostRecord(subscription_id="sub", resource_id="/sites/host", amount=2.0,
                          currency="USD", usage_date="20261120")],
        report_evidence=[CostHistoryEvidence(
            kind="cost_history", code="OT-SY-34", source_kind="official_admin_read",
            source_ref="azure-costmanagement-2023-03-01", scope="observed AI cost",
            observed_at=NOW, period_start=datetime(2026, 6, 1, tzinfo=UTC), period_end=NOW,
            complete=True, population_complete=True, reason=None,
            records=[HistoricalCostRecord(subject="cost", evidence_ids=["/sites/host"],
                                          occurred_at=datetime(2026, 11, 20, tzinfo=UTC),
                                          amount=2.0, currency="USD", attributed_amount=None)],
        )],
    )
    assert monthly_inventory_cost(data) == {"202611": 2.0}
    data.agents.append(agent.model_copy(update={"agent_id": "shared"}))
    assert monthly_inventory_cost(data) == {"202611": 0.0}
    data.costs[0].amount = 3.0
    assert monthly_inventory_cost(data) == {"202611": None}


def test_host_scope_removes_exclusive_evidence_but_preserves_shared_foundry_resources():
    data = Collection(
        collected_at=NOW,
        agents=[
            AgentEvidence(collected_at=NOW, platform="custom", agent_id="host", agent_name="Host",
                          detection_confidence="tag", resource_id="/host", cost_resource_ids=["/shared"]),
            AgentEvidence(collected_at=NOW, platform="foundry", agent_id="agent", agent_name="Agent",
                          detection_confidence="tag", resource_id="/project", cost_resource_ids=["/shared"]),
        ],
        costs=[
            CostRecord(subscription_id="sub", resource_id=rid, amount=2, currency="USD", usage_date="20261120")
            for rid in ("/HOST", "/shared")
        ],
        logs=[LogSetting(subscription_id="sub", resource_id="/host", enabled=True)],
        resources=[{"id": "/host", "tags": {"agent-type": "custom-agent"}}, {"id": "/shared"}],
        proposal_observations=[
            ProposalObservation(code="BI-SY-12", subject="/host", kind="agent_host"),
            ProposalObservation(code="BI-SY-14", subject="/host", kind="policy_resource"),
            ProposalObservation(code="DS-SY-05", subject="/account", kind="ai_account"),
        ],
        report_evidence=[CostHistoryEvidence(
            kind="cost_history", source_kind="official_admin_read", source_ref="cost",
            scope="observed AI cost", observed_at=NOW, complete=True, population_complete=True, reason=None,
            period_start=NOW - timedelta(days=2), period_end=NOW,
            records=[HistoricalCostRecord(subject=rid, evidence_ids=[rid], occurred_at=NOW - timedelta(days=1),
                                          amount=2, currency="USD") for rid in ("/host", "/shared")],
        )],
        facts={"resource_metrics": [{"resource_id": "/host"}, {"resource_id": "/account"}]},
    )
    assert data.exclude_host_candidates()
    assert [agent.platform for agent in data.agents] == ["foundry"]
    assert [row.resource_id for row in data.costs] == ["/shared"]
    assert data.logs == []
    assert [row.subject for row in data.proposal_observations] == ["/account"]
    assert [row["id"] for row in data.resources] == ["/shared"]
    assert [row.subject for row in data.report_evidence[0].records] == ["/shared"]
    assert data.facts["resource_metrics"] == [{"resource_id": "/account"}]
    assert not data.exclude_host_candidates()
    assert data.facts["excluded_host_candidates"]["count"] == 1


def test_only_host_costs_do_not_become_zero_agent_costs():
    data = Collection(
        collected_at=NOW,
        agents=[AgentEvidence(collected_at=NOW, platform="langchain", agent_id="host",
                              agent_name="Host", detection_confidence="name_heuristic", resource_id="/host")],
        costs=[CostRecord(subscription_id="sub", resource_id="/host", amount=2, currency="USD")],
    )
    assert monthly_inventory_cost(data) == {}
    from easm_agent.api_grading import cost_measurement

    result = cost_measurement(data, data.agents)
    assert result.ratio is None and result.unavailable is not None
