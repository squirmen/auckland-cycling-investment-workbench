import pytest

from cycling_investment_workbench.uncertainty import (
    MATERIAL_UNCERTAINTY_DIMENSIONS,
    ParameterSpec,
    evaluate_samples,
    frontier_stability,
    latin_hypercube,
    quantile,
    rank_stability,
    validate_material_uncertainty_design,
)


def test_latin_hypercube_occupies_each_stratum_once() -> None:
    samples = latin_hypercube((ParameterSpec("x", 0, 1),), 10, seed=7)
    ordered = sorted(sample["x"] for sample in samples)
    assert all(index / 10 <= value < (index + 1) / 10 for index, value in enumerate(ordered))
    assert samples == latin_hypercube((ParameterSpec("x", 0, 1),), 10, seed=7)


def test_supported_parameter_transforms_remain_in_bounds() -> None:
    specifications = (
        ParameterSpec("log", 1, 100, "loguniform"),
        ParameterSpec("tri", 0, 10, "triangular", 2),
    )
    samples = latin_hypercube(specifications, 50, seed=3)
    assert all(1 <= sample["log"] <= 100 for sample in samples)
    assert all(0 <= sample["tri"] <= 10 for sample in samples)


def test_rank_stability_reports_top_k_probability_and_intervals() -> None:
    draws = (
        {"a": 3, "b": 2, "c": 1},
        {"a": 2, "b": 3, "c": 1},
        {"a": 3, "b": 1, "c": 2},
    )
    result = rank_stability(draws, top_k=1)
    by_id = {item.candidate_id: item for item in result.candidates}
    assert result.baseline_order == ("a", "b", "c")
    assert by_id["a"].top_k_probability == pytest.approx(2 / 3)
    assert by_id["b"].top_k_probability == pytest.approx(1 / 3)
    assert result.mean_top_k_jaccard == pytest.approx(2 / 3)
    assert -1 <= result.mean_kendall_tau <= 1


def test_quantile_and_evaluator_are_deterministic() -> None:
    assert quantile([0, 10], 0.25) == pytest.approx(2.5)
    outputs = evaluate_samples(({"x": 1}, {"x": 2}), lambda sample: {"a": sample["x"] ** 2})
    assert outputs == ({"a": 1}, {"a": 4})


def test_material_design_requires_all_twelve_declared_dimensions() -> None:
    specifications = tuple(
        ParameterSpec(name, 0.5, 1.5) for name in MATERIAL_UNCERTAINTY_DIMENSIONS
    )
    assert validate_material_uncertainty_design(specifications) == (MATERIAL_UNCERTAINTY_DIMENSIONS)
    with pytest.raises(ValueError, match="missing"):
        validate_material_uncertainty_design(specifications[:-1])


def test_frontier_stability_reports_membership_and_jaccard() -> None:
    result = frontier_stability(
        (("a", "b"), ("a",), ("b",)),
        candidate_ids=("a", "b", "c"),
        baseline_frontier=("a", "b"),
    )
    assert result.membership_probability == pytest.approx({"a": 2 / 3, "b": 2 / 3, "c": 0})
    assert result.mean_jaccard == pytest.approx(2 / 3)
