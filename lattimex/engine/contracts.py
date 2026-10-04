from __future__ import annotations

from typing import Any


VARIANT_OPTIONS: dict[str, dict[str, Any]] = {
    "fragility-only": {
        "orientationPolicy": "all",
        "supportRatio": 0.0,
        "enforceFragility": True,
        "enforceUnloadOrder": False,
    },
    "support-only": {
        "orientationPolicy": "all",
        "supportRatio": 0.75,
        "enforceFragility": False,
        "enforceUnloadOrder": False,
    },
    "loading-only": {
        "orientationPolicy": "all",
        "supportRatio": 0.0,
        "enforceFragility": False,
        "enforceUnloadOrder": False,
    },
    "no-support": {
        "orientationPolicy": "all",
        "supportRatio": 0.0,
        "enforceFragility": True,
        "enforceUnloadOrder": True,
    },
    "no-fragility": {
        "orientationPolicy": "all",
        "supportRatio": 0.75,
        "enforceFragility": False,
        "enforceUnloadOrder": True,
    },
    "no-lifo": {
        "orientationPolicy": "all",
        "supportRatio": 0.75,
        "enforceFragility": True,
        "enforceUnloadOrder": False,
    },
    "all-constraints": {
        "orientationPolicy": "all",
        "supportRatio": 0.75,
        "enforceFragility": True,
        "enforceUnloadOrder": True,
    },
}

TRUTH_VALUES = {"feasible", "infeasible", "unknown"}
ACCEPTED_STATUSES = {"heuristic-feasible"}
REJECTED_STATUSES = {
    "incompatible",
    "heuristic-unresolved",
    "invalid-placement",
    "error",
}
REQUIRED_SCOPE_FIELDS = (
    "dataset",
    "instance",
    "variant",
    "orientation_policy",
    "fleet_profile",
    "objective",
)


class ContractError(ValueError):
    """Raised when an experimental artifact violates its contract."""


def options_for_variant(variant: str) -> dict[str, Any]:
    try:
        return dict(VARIANT_OPTIONS[variant])
    except KeyError as exc:
        raise ContractError(f"Unknown 3L-CVRP loading variant (Gendreau et al., 2006): {variant}") from exc


def decision_from_status(status: str) -> str:
    if status in ACCEPTED_STATUSES:
        return "accept"
    return "reject"


def truth_is_strictly_proven(case: dict[str, Any]) -> bool:
    truth = case.get("truth", "unknown")
    if truth == "unknown":
        return True
    provenance = case.get("truth_provenance") or {}
    kind = provenance.get("kind")
    if kind == "external_validator":
        return provenance.get("passed") is True and bool(provenance.get("validator"))
    if kind == "synthetic_constructed":
        return True
    return False


def validate_loading_case(case: dict[str, Any], strict_truth: bool = True) -> None:
    required = ("case_id", "dataset", "instance", "route_id", "variant", "truth", "request")
    missing = [field for field in required if field not in case]
    if missing:
        raise ContractError(f"Loading case missing fields {missing}: {case.get('case_id', '<unnamed>')}")
    if case.get("contract") != "pen3q.3lcvrp.loading-case.v1":
        raise ContractError(f"Unexpected case contract: {case.get('contract')!r}")
    options_for_variant(str(case["variant"]))
    if case["truth"] not in TRUTH_VALUES:
        raise ContractError(f"Invalid truth label in {case['case_id']}: {case['truth']!r}")
    request = case["request"]
    if not isinstance(request, dict) or not isinstance(request.get("items"), list):
        raise ContractError(f"Invalid request/items in {case['case_id']}")
    if not request["items"]:
        raise ContractError(f"Empty route is not a Phase 1 unit: {case['case_id']}")
    vehicle = request.get("vehicle") or {}
    cargo = vehicle.get("cargoDimensions") or []
    if len(cargo) != 3 or any(float(value) <= 0 for value in cargo):
        raise ContractError(f"Invalid cargo dimensions in {case['case_id']}")
    if strict_truth and not truth_is_strictly_proven(case):
        raise ContractError(
            f"Truth label for {case['case_id']} lacks external-validator provenance"
        )


def validate_run_record(record: dict[str, Any], expected_phase: int | None = None) -> None:
    if record.get("contract") != "pen3q.3lcvrp.run.v1":
        raise ContractError(f"Unexpected run contract: {record.get('contract')!r}")
    if expected_phase is not None and int(record.get("phase", -1)) != expected_phase:
        raise ContractError(f"Expected phase {expected_phase}, got {record.get('phase')}")
    required = (
        "phase",
        "dataset",
        "instance",
        "variant",
        "config",
        "seed",
        "checkpoint_sec",
        "status",
        "routing_feasible",
        "loading_status",
        "feasible",
        "externally_validated",
        "vehicles",
        "distance",
        "runtime_sec",
    )
    missing = [field for field in required if field not in record]
    if missing:
        raise ContractError(f"Run record missing {missing}: {record.get('instance', '<unnamed>')}")
    if float(record["runtime_sec"]) < 0 or float(record["distance"]) < 0:
        raise ContractError("Runtime and distance must be non-negative")
    if int(record["vehicles"]) < 0:
        raise ContractError("Vehicle count must be non-negative")


def scopes_match(left: dict[str, Any], right: dict[str, Any]) -> tuple[bool, list[str]]:
    mismatches = [field for field in REQUIRED_SCOPE_FIELDS if left.get(field) != right.get(field)]
    return not mismatches, mismatches
