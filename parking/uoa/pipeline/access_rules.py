"""Overture access rules, evaluated per travel mode and direction.

build_layers.py keeps each segment's `access_restrictions` whole, one compact dict per rule:

    t  access type ('allowed', 'denied', 'designated')
    h  heading the rule is limited to ('forward' or 'backward'), if any
    m  modes the rule names (for example ['bicycle'] or ['motor_vehicle']), if any
    u  'using' limits (for example ['as_customer']), if any
    r  'recognized' limits (for example ['as_employee']), if any
    d  a time window ('during'), if any
    v  True when the rule is limited by vehicle dimensions (weight, height and so on)
    b  the [start, end] fraction of the segment the rule covers ('between'), if any

Edges run u -> v in the segment's own direction, so heading 'forward' is u -> v and 'backward'
is v -> u. The functions here need only the standard library, so SPAN's tests can check them.
"""

import json

# Overture's 'vehicle' covers bicycles; 'motor_vehicle', 'car', 'bus' and 'hgv' do not.
BIKE_MODES = frozenset({"bicycle", "vehicle"})


def rule_applies(rule, mode, heading):
    """Does one rule bind a daytime commuter on `mode` ('foot' or 'bicycle') going `heading`?"""
    if rule.get("d") or rule.get("v"):
        # Time windows and vehicle-dimension limits do not bind the commuters modelled here.
        return False
    if rule.get("u") or rule.get("r"):
        # Rules for particular users (customers, staff, destination traffic) neither open
        # nor close a link to the general public.
        return False
    h = rule.get("h")
    if h and (mode == "foot" or h != heading):
        # One-way rules bind vehicles in their own direction only, and never people on foot.
        return False
    modes = rule.get("m")
    if modes:
        modes = set(modes)
        if mode == "foot" and "foot" not in modes:
            return False
        if mode == "bicycle" and not modes & BIKE_MODES:
            return False
    return True


def access_open(rules, mode, heading, default):
    """Is the link open to `mode` going `heading`?

    Among the rules that apply, the most specific wins: a heading counts 2 and a named mode 1,
    and ties go to the later rule. With no applicable rule the link keeps its class default.

    A heading outranks a mode because Overture writes a one-way street as a rule that denies one
    heading to every mode, and OpenStreetMap's bicycle=yes or bicycle=designated as a rule that
    names bicycles with no heading. Those tags give bikes access; they do not exempt them from the
    one-way. A real exemption ("one-way except bicycles") names both the heading and the mode,
    so it still outranks the one-way.
    """
    best = None
    for rule in rules:
        if not rule_applies(rule, mode, heading):
            continue
        specificity = (2 if rule.get("h") else 0) + (1 if rule.get("m") else 0)
        if best is None or specificity >= best[0]:
            best = (specificity, rule.get("t"))
    if best is None:
        return bool(default)
    return best[1] != "denied"


def edge_rules(rules, start, end):
    """The rules that cover the edge from fraction `start` to `end` of its segment, as JSON.

    A rule limited to part of the segment ('between') applies only if that part overlaps the
    edge. The 'between' key is dropped from the result, which is None when no rule applies.
    """
    out = []
    for rule in rules:
        rule = dict(rule)
        span = rule.pop("b", None)
        if span and not max(start, span[0]) < min(end, span[1]) - 1e-9:
            continue
        out.append(rule)
    return json.dumps(out, separators=(",", ":")) if out else None
