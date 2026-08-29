"""Layer-aware, direction-aware network topology.

The graph is built from source node and edge identities.  It intentionally does
not merge near-coincident coordinates: a bridge crossing a road at the same
planar position remains disconnected unless the source data contains a shared
node.  This follows the topology principles in OpenStreetMap's data model.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from math import hypot
from types import MappingProxyType

from .models import Direction, Edge, Node


@dataclass(frozen=True, slots=True)
class Traversal:
    """A permitted directed traversal of one physical edge."""

    edge_id: str
    tail: str
    head: str
    reversed: bool = False

    @property
    def id(self) -> str:
        return f"{self.edge_id}:{'r' if self.reversed else 'f'}"


@dataclass(frozen=True, slots=True)
class SnapResult:
    """Nearest eligible source node and its planar distance."""

    node_id: str
    distance: float
    component_id: str


class DirectedTopology:
    """Deterministic directed multigraph over source-identified physical edges."""

    def __init__(self, nodes: Iterable[Node], edges: Iterable[Edge]) -> None:
        node_map: dict[str, Node] = {}
        for node in nodes:
            if node.id in node_map:
                raise ValueError(f"duplicate node id: {node.id}")
            node_map[node.id] = node

        edge_map: dict[str, Edge] = {}
        outgoing: dict[str, list[Traversal]] = defaultdict(list)
        incoming: dict[str, list[Traversal]] = defaultdict(list)
        for edge in edges:
            if edge.id in edge_map:
                raise ValueError(f"duplicate edge id: {edge.id}")
            if edge.u not in node_map or edge.v not in node_map:
                raise ValueError(f"edge {edge.id} references a missing endpoint")
            edge_map[edge.id] = edge
            if edge.direction in (Direction.BOTH, Direction.FORWARD):
                traversal = Traversal(edge.id, edge.u, edge.v, False)
                outgoing[edge.u].append(traversal)
                incoming[edge.v].append(traversal)
            if edge.direction in (Direction.BOTH, Direction.REVERSE):
                traversal = Traversal(edge.id, edge.v, edge.u, True)
                outgoing[edge.v].append(traversal)
                incoming[edge.u].append(traversal)

        for node_id in node_map:
            outgoing[node_id].sort(key=lambda arc: (arc.head, arc.edge_id, arc.reversed))
            incoming[node_id].sort(key=lambda arc: (arc.tail, arc.edge_id, arc.reversed))

        self._nodes = MappingProxyType(node_map)
        self._edges = MappingProxyType(edge_map)
        self._outgoing = {key: tuple(value) for key, value in outgoing.items()}
        self._incoming = {key: tuple(value) for key, value in incoming.items()}
        self._component_by_node: dict[str, str] | None = None

    @classmethod
    def from_edges(cls, nodes: Iterable[Node], edges: Iterable[Edge]) -> DirectedTopology:
        """Construct a topology, validating all identifiers and directions."""

        return cls(nodes, edges)

    @property
    def nodes(self) -> Mapping[str, Node]:
        return self._nodes

    @property
    def edges(self) -> Mapping[str, Edge]:
        return self._edges

    def node(self, node_id: str) -> Node:
        return self._nodes[node_id]

    def edge(self, edge_id: str) -> Edge:
        return self._edges[edge_id]

    def outgoing(self, node_id: str) -> tuple[Traversal, ...]:
        return self._outgoing.get(node_id, ())

    def incoming(self, node_id: str) -> tuple[Traversal, ...]:
        return self._incoming.get(node_id, ())

    def traversals(self) -> Iterator[Traversal]:
        for node_id in sorted(self._nodes):
            yield from self.outgoing(node_id)

    def validate(self) -> tuple[str, ...]:
        """Return non-fatal topology warnings suitable for a build manifest."""

        warnings: list[str] = []
        for edge in self._edges.values():
            u = self._nodes[edge.u]
            v = self._nodes[edge.v]
            if u.layer != v.layer and not (edge.bridge or edge.tunnel):
                warnings.append(
                    f"edge {edge.id} changes layer {u.layer}->{v.layer} "
                    "without bridge/tunnel metadata"
                )
            if edge.geometry:
                start = edge.geometry[0]
                end = edge.geometry[-1]
                forward_error = hypot(start[0] - u.x, start[1] - u.y) + hypot(
                    end[0] - v.x, end[1] - v.y
                )
                reverse_error = hypot(start[0] - v.x, start[1] - v.y) + hypot(
                    end[0] - u.x, end[1] - u.y
                )
                if min(forward_error, reverse_error) > max(1.0, edge.length_m * 0.02):
                    warnings.append(f"edge {edge.id} geometry endpoints do not match its nodes")
        return tuple(sorted(warnings))

    def weak_components(self) -> tuple[frozenset[str], ...]:
        """Return weakly connected components, largest first and deterministically tied."""

        neighbours: dict[str, set[str]] = {node_id: set() for node_id in self._nodes}
        for edge in self._edges.values():
            neighbours[edge.u].add(edge.v)
            neighbours[edge.v].add(edge.u)

        remaining = set(self._nodes)
        components: list[frozenset[str]] = []
        while remaining:
            seed = min(remaining)
            queue = deque([seed])
            found = {seed}
            remaining.remove(seed)
            while queue:
                node_id = queue.popleft()
                for neighbour in sorted(neighbours[node_id]):
                    if neighbour in remaining:
                        remaining.remove(neighbour)
                        found.add(neighbour)
                        queue.append(neighbour)
            components.append(frozenset(found))
        return tuple(sorted(components, key=lambda values: (-len(values), min(values))))

    def component_by_node(self) -> Mapping[str, str]:
        """Map each node to a stable component ID based on its smallest node ID."""

        if self._component_by_node is None:
            result: dict[str, str] = {}
            for component in self.weak_components():
                component_id = min(component)
                result.update({node_id: component_id for node_id in component})
            self._component_by_node = result
        return MappingProxyType(self._component_by_node)

    def snap_node(
        self,
        x: float,
        y: float,
        *,
        max_distance: float,
        eligible_components: frozenset[str] | None = None,
        layer: int | None = None,
    ) -> SnapResult | None:
        """Snap to the nearest eligible node without merging or changing topology."""

        if max_distance < 0:
            raise ValueError("max_distance must be non-negative")
        component_map = self.component_by_node()
        options: list[tuple[float, str]] = []
        for node_id, node in self._nodes.items():
            if layer is not None and node.layer != layer:
                continue
            component_id = component_map[node_id]
            if eligible_components is not None and component_id not in eligible_components:
                continue
            distance = hypot(node.x - x, node.y - y)
            if distance <= max_distance:
                options.append((distance, node_id))
        if not options:
            return None
        distance, node_id = min(options)
        return SnapResult(node_id, distance, component_map[node_id])

    def replace_edges(self, replacements: Mapping[str, Edge]) -> DirectedTopology:
        """Return a new graph with explicitly identified physical edges replaced."""

        unknown = set(replacements).difference(self._edges)
        if unknown:
            raise KeyError(f"unknown edge ids: {sorted(unknown)}")
        edges = [replacements.get(edge_id, edge) for edge_id, edge in self._edges.items()]
        return DirectedTopology(self._nodes.values(), edges)
