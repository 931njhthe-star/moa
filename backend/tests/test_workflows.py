import pytest

from app import config
from app.services import workflows


def test_quick_workflow_is_one_bounded_case():
    cases = workflows.build_cases(mode="quick", fault_type="F-1", target=None,
                                  repetitions=10, injection_seconds=120)
    assert len(cases) == 1
    assert cases[0] == {"fault_type": "F-1", "target": "order_interpreter_primary", "seconds": 120}


def test_full_workflow_has_25_cases_and_alternates_backend_targets():
    cases = workflows.build_cases(mode="full", fault_type="F-1", target=None,
                                  repetitions=1, injection_seconds=1)
    assert len(cases) == 25
    f3_targets = [case["target"] for case in cases if case["fault_type"] == "F-3"]
    assert f3_targets == ["moa-a-backend-1", "moa-b-backend-1", "moa-a-backend-1",
                          "moa-b-backend-1", "moa-a-backend-1"]


@pytest.mark.parametrize("fault_type,target", [
    ("F-1", "moa-a-backend-1"),
    ("F-3", "order_interpreter_primary"),
    ("F-6", "moa-a-backend-1"),
])
def test_custom_workflow_rejects_wrong_target(fault_type, target):
    with pytest.raises(ValueError):
        workflows.build_cases(mode="custom", fault_type=fault_type, target=target,
                               repetitions=1, injection_seconds=1)


def test_workflow_start_is_blocked_outside_lab_before_database_access(monkeypatch):
    monkeypatch.setattr(config, "ENVIRONMENT", "production")
    monkeypatch.setattr(workflows.db, "transaction", lambda **_: pytest.fail("DB must not be touched"))
    with pytest.raises(PermissionError):
        workflows.create_run(mode="quick", fault_type="F-1", target=None,
                             repetitions=1, injection_seconds=1)


@pytest.mark.parametrize("repetitions,seconds", [(0, 1), (11, 1), (1, 0), (1, 121)])
def test_workflow_limits_are_enforced(repetitions, seconds):
    with pytest.raises(ValueError):
        workflows.build_cases(mode="custom", fault_type="F-2", target=None,
                              repetitions=repetitions, injection_seconds=seconds)
