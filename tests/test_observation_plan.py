from pathlib import Path

from agri_twin.application import (
    ExperimentalObservationPlan,
    ParameterIdentifiabilityAnalyzer,
    PlanStatus,
)
from agri_twin.domain import ParameterRegistry

ROOT = Path(__file__).parents[1]


def make_plan():
    registry = ParameterRegistry.from_repository(ROOT)
    report = ParameterIdentifiabilityAnalyzer(registry, repository_root=ROOT).analyze_all()
    return ExperimentalObservationPlan.from_identifiability_report(report), registry, report


def test_plan_is_derived_from_registry_and_serializable():
    plan, registry, report = make_plan()
    assert len(plan.items) == len(registry.records) == len(report.assessments)
    assert plan.real_data_available is False
    assert plan.campaign_status == "DESIGNED_NOT_EXECUTED"
    assert plan.to_dict() == ExperimentalObservationPlan.from_identifiability_report(report).to_dict()
    assert all(item.parameter_ids[0] in {record.parameter_id for record in registry.records} for item in plan.items)


def test_filters_cover_crops_varieties_plots_and_environments_without_inventing_varieties():
    plan, _, _ = make_plan()
    assert plan.for_crop("tomato")
    assert plan.for_crop("lettuce")
    assert plan.for_crop("apple")
    assert plan.for_variety("tomato", "RAF")
    assert plan.for_variety("pepper", "Lamuyo")
    assert plan.for_variety("grape", "Monastrell")
    assert plan.for_variety("plum", "Suplum 26")
    assert all(item.variety in {None, "RAF"} for item in plan.for_variety("tomato", "RAF"))
    assert plan.for_plot("plot_12010")
    assert plan.for_environment("OUTDOOR")


def test_plan_keeps_unknown_requirements_and_does_not_claim_measurement():
    plan, _, _ = make_plan()
    assert any(item.status is PlanStatus.UNKNOWN for item in plan.items)
    assert all(item.status is not PlanStatus.PLANNED or "does not mean measured" in item.notes for item in plan.items)
    assert plan.coverage()[PlanStatus.UNKNOWN.value] > 0
    assert plan.campaign_checklist()


def test_confounders_and_quality_contract_are_preserved():
    plan, _, _ = make_plan()
    assert plan.confounded_parameters()
    assert all("VALID" in item.quality_requirements and "MISSING" in item.quality_requirements for item in plan.items)
    assert all(item.measurement_method in {"TO_BE_DEFINED", None} for item in plan.items)


def test_registry_is_not_mutated():
    plan, registry, _ = make_plan()
    before = registry.records
    plan.for_parameter("radiation.rue")
    assert registry.records == before
