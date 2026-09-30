"""STAND's Overture access rules: when a link is open to walking or cycling, and in which direction.

The rules live in parking/uoa/pipeline/access_rules.py, which needs only the standard library.
Edges run u -> v in the segment's own direction, so heading 'forward' is u -> v. Overture writes a
one-way street as a rule that denies the direction against the traffic.
"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "parking/uoa/pipeline/access_rules.py"
spec = importlib.util.spec_from_file_location("stand_access_rules", MODULE)
assert spec and spec.loader
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)

OPPOSITE = {"forward": "backward", "backward": "forward"}


def rule(t, *, h=None, m=None, u=None, r=None, d=None, v=False, b=None):
    """One rule as build_layers.py stores it, with every key present and unused ones empty."""
    return {"t": t, "h": h, "m": m, "u": u, "r": r, "d": d, "v": v, "b": b}


@pytest.mark.parametrize("against", ["forward", "backward"])
@pytest.mark.parametrize(
    ("modes", "closes_contraflow"),
    [
        (None, True),
        (["vehicle"], True),
        (["bicycle"], True),
        (["motor_vehicle"], False),
        (["car"], False),
        (["bus"], False),
        (["foot"], False),
    ],
)
def test_one_way_closes_the_contraflow_to_bikes_only_when_it_covers_bikes(
    against, modes, closes_contraflow
):
    one_way = [rule("denied", h=against, m=modes)]
    assert access.access_open(one_way, "bicycle", OPPOSITE[against], True)
    assert access.access_open(one_way, "bicycle", against, True) is not closes_contraflow


@pytest.mark.parametrize("against", ["forward", "backward"])
@pytest.mark.parametrize("exemption_first", [False, True])
def test_one_way_except_bicycles_stays_open_both_ways_to_bikes(against, exemption_first):
    one_way = rule("denied", h=against)
    bikes_exempt = rule("allowed", h=against, m=["bicycle"])
    rules = [bikes_exempt, one_way] if exemption_first else [one_way, bikes_exempt]
    assert access.access_open(rules, "bicycle", against, True)
    assert access.access_open(rules, "bicycle", OPPOSITE[against], True)


@pytest.mark.parametrize("heading", ["forward", "backward"])
@pytest.mark.parametrize("modes", [None, ["foot"], ["vehicle"]])
def test_headings_never_bind_walking(heading, modes):
    assert access.access_open([rule("denied", h=heading, m=modes)], "foot", None, True)
    assert access.access_open([rule("denied", h=heading, m=modes)], "foot", heading, True)
    assert not access.access_open([rule("allowed", h=heading, m=modes)], "foot", None, False)


@pytest.mark.parametrize(
    "limit",
    [{"d": "Mo-Fr 07:00-09:00"}, {"v": True}, {"u": ["as_customer"]}, {"r": ["as_employee"]}],
    ids=["during", "vehicle_dimensions", "using", "recognized"],
)
@pytest.mark.parametrize(("mode", "heading"), [("bicycle", "forward"), ("foot", None)])
def test_limited_rules_neither_open_nor_close_a_link(limit, mode, heading):
    denied = {**rule("denied"), **limit}
    allowed = {**rule("allowed", m=[mode]), **limit}
    assert not access.rule_applies(denied, mode, heading)
    assert access.access_open([denied], mode, heading, True)
    assert not access.access_open([allowed], mode, heading, False)


# "No vehicles, pedestrians allowed": a named mode beats a rule with no mode.
WALKING_ONLY = [rule("denied"), rule("allowed", m=["foot"])]
# A cycleway closed to walking stays open to bikes.
CYCLEWAY_NO_WALKING = [rule("designated", m=["bicycle"]), rule("denied", m=["foot"])]
# A heading beats a rule with neither heading nor mode.
ONE_WAY_OVER_OPEN = [rule("allowed"), rule("denied", h="backward")]
# A mode with a heading beats the same mode alone.
BIKES_FORWARD_ONLY = [rule("denied", m=["bicycle"]), rule("allowed", h="forward", m=["bicycle"])]


@pytest.mark.parametrize("order", [1, -1], ids=["as_listed", "reversed"])
@pytest.mark.parametrize(
    ("rules", "mode", "heading", "default", "expected"),
    [
        (WALKING_ONLY, "foot", None, False, True),
        (WALKING_ONLY, "bicycle", "forward", True, False),
        (CYCLEWAY_NO_WALKING, "foot", None, True, False),
        (CYCLEWAY_NO_WALKING, "bicycle", "forward", False, True),
        (ONE_WAY_OVER_OPEN, "bicycle", "backward", True, False),
        (ONE_WAY_OVER_OPEN, "bicycle", "forward", False, True),
        (BIKES_FORWARD_ONLY, "bicycle", "forward", False, True),
        (BIKES_FORWARD_ONLY, "bicycle", "backward", True, False),
    ],
)
def test_the_most_specific_rule_wins_in_either_order(
    rules, mode, heading, default, expected, order
):
    assert access.access_open(rules[::order], mode, heading, default) is expected


@pytest.mark.parametrize(
    ("first", "second", "mode", "heading"),
    [
        (rule("allowed", m=["bicycle"]), rule("denied", m=["vehicle"]), "bicycle", "forward"),
        (rule("allowed"), rule("denied"), "foot", None),
        (rule("allowed", h="forward"), rule("denied", h="forward"), "bicycle", "forward"),
    ],
)
def test_ties_go_to_the_later_rule(first, second, mode, heading):
    assert not access.access_open([first, second], mode, heading, True)
    assert access.access_open([second, first], mode, heading, False)


def test_bicycle_access_does_not_lift_a_one_way():
    # OSM oneway=yes with bicycle=yes or bicycle=designated reaches Overture as a heading rule
    # for every mode plus a bicycle rule with no heading: bikes may use the link, with the flow.
    for access_type in ("allowed", "designated"):
        for rules in (
            [rule("denied", h="backward"), rule(access_type, m=["bicycle"])],
            [rule(access_type, m=["bicycle"]), rule("denied", h="backward")],
            [rule("denied", h="backward"), rule(access_type, m=["foot", "bicycle"])],
        ):
            assert access.access_open(rules, "bicycle", "forward", False)
            assert not access.access_open(rules, "bicycle", "backward", True)
            assert access.access_open(rules, "foot", None, True)


def test_a_contraflow_exemption_must_name_the_heading():
    # Overture writes "one-way except buses" as a rule naming both the heading and the mode.
    bus_contraflow = [rule("denied", h="backward"), rule("designated", h="backward", m=["bus"])]
    assert not access.access_open(bus_contraflow, "bicycle", "backward", True)
    bike_contraflow = [rule("denied", h="backward"), rule("allowed", h="backward", m=["bicycle"])]
    assert access.access_open(bike_contraflow, "bicycle", "backward", False)


@pytest.mark.parametrize("default", [True, False])
def test_the_class_default_stands_when_no_rule_applies(default):
    motor_only = [rule("denied", m=["motor_vehicle"]), rule("allowed", m=["bus"])]
    assert access.access_open([], "bicycle", "forward", default) is default
    assert access.access_open(motor_only, "bicycle", "forward", default) is default
    assert access.access_open(motor_only, "foot", None, default) is default


def test_designated_opens_a_link_and_vehicle_covers_bikes_but_not_walking():
    assert access.access_open([rule("designated", m=["bicycle"])], "bicycle", "forward", False)
    no_vehicles = [rule("denied", m=["vehicle"])]
    assert not access.access_open(no_vehicles, "bicycle", "backward", True)
    assert access.access_open(no_vehicles, "foot", None, True)


def without_between(r):
    return {key: value for key, value in r.items() if key != "b"}


def test_edge_rules_keep_a_partial_rule_only_on_edges_it_overlaps():
    one_way = rule("denied", h="backward")
    no_walking_at_end = rule("denied", m=["foot"], b=[0.5, 1.0])
    rules = [one_way, no_walking_at_end]
    unchanged = copy.deepcopy(rules)
    both = [without_between(one_way), without_between(no_walking_at_end)]
    # Edges that only touch the covered part at a shared connector do not get the rule.
    assert json.loads(access.edge_rules(rules, 0.0, 0.5)) == [without_between(one_way)]
    assert json.loads(access.edge_rules(rules, 0.0, 0.5 + 1e-12)) == [without_between(one_way)]
    assert json.loads(access.edge_rules(rules, 0.4, 0.6)) == both
    assert json.loads(access.edge_rules(rules, 0.5, 1.0)) == both
    assert json.loads(access.edge_rules(rules, 0.6, 0.7)) == both
    assert rules == unchanged


def test_edge_rules_drop_the_between_key_and_return_none_without_rules():
    kept = json.loads(access.edge_rules([rule("allowed", m=["bicycle"], b=[0.0, 1.0])], 0.2, 0.3))
    assert kept == [without_between(rule("allowed", m=["bicycle"]))]
    assert all("b" not in r for r in kept)
    assert access.edge_rules([], 0.0, 1.0) is None
    assert access.edge_rules([rule("denied", m=["foot"], b=[0.0, 0.25])], 0.5, 1.0) is None
