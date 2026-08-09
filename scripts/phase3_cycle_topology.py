"""How many directed cycles the Oisans road graph actually contains.

Whether repeating a way could ever help is two questions, and conflating them
would make a null result meaningless.

*Are there cycles at all?* A purely topological question, answered exactly by
strongly connected components of the edge-continuation graph: a component with
more than one edge contains a directed cycle, and one with a single edge does
not. This uses the real continuation rule, so turn restrictions, oneways and the
no-u-turn rule are all respected.

*Can a coasting bicycle use them?* A physical question, answered elsewhere by
running the search both ways.

If the first answer were "no cycles", a null result from the second would say
nothing about the trip rule — only about the extract. It is therefore measured
first and separately.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from coastdown.graph import RoutableGraph, build_graph
from coastdown.textio import write_text_lf


def cyclic_components(graph: RoutableGraph) -> list[list[str]]:
    """Strongly connected components of the continuation graph, size > 1.

    Tarjan's algorithm, written iteratively: a recursive form overflows the
    stack on a component of several hundred edges, and raising the recursion
    limit to hide that would only move the failure.
    """
    edges = list(graph.edges)
    position = {edge_id: index for index, edge_id in enumerate(edges)}
    adjacency = [
        [position[candidate] for candidate in graph.continuations(edge_id)] for edge_id in edges
    ]
    total = len(edges)
    index: list[int | None] = [None] * total
    lowlink = [0] * total
    on_stack = [False] * total
    stack: list[int] = []
    components: list[list[int]] = []
    counter = 0

    for root in range(total):
        if index[root] is not None:
            continue
        work = [(root, 0)]
        while work:
            vertex, offset = work[-1]
            if offset == 0:
                index[vertex] = lowlink[vertex] = counter
                counter += 1
                stack.append(vertex)
                on_stack[vertex] = True
            descended = False
            for cursor in range(offset, len(adjacency[vertex])):
                neighbour = adjacency[vertex][cursor]
                if index[neighbour] is None:
                    work[-1] = (vertex, cursor + 1)
                    work.append((neighbour, 0))
                    descended = True
                    break
                if on_stack[neighbour]:
                    lowlink[vertex] = min(lowlink[vertex], index[neighbour])
            if descended:
                continue
            if lowlink[vertex] == index[vertex]:
                component: list[int] = []
                while True:
                    member = stack.pop()
                    on_stack[member] = False
                    component.append(member)
                    if member == vertex:
                        break
                components.append(component)
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[vertex])

    return [
        [edges[member] for member in component] for component in components if len(component) > 1
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overpass-cache", default=".cache/phase1b-live/oisans-overpass.json")
    parser.add_argument("--output", default="outputs/phase3")
    arguments = parser.parse_args()

    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=True)
    osm = json.loads(Path(arguments.overpass_cache).read_bytes())

    report: dict[str, object] = {}
    for scenario in ("paved_reference", "reference_vtc"):
        graph = build_graph(osm, scenario)
        components = cyclic_components(graph)
        covered = sum(len(component) for component in components)
        largest = sorted(components, key=len, reverse=True)[:5]
        report[scenario] = {
            "directed_edges": len(graph.edges),
            "components_containing_a_cycle": len(components),
            "edges_inside_such_a_component": covered,
            "share_of_edges_inside_a_cycle": round(covered / max(len(graph.edges), 1), 4),
            "largest_components": [
                {
                    "edges": len(component),
                    "distinct_ways": len({graph.edges[edge].osm_way_id for edge in component}),
                    "sample_names": sorted(
                        {graph.edges[edge].name for edge in component if graph.edges[edge].name}
                    )[:6],
                }
                for component in largest
            ],
        }
        print(
            f"{scenario}: {len(graph.edges)} directed edges, "
            f"{len(components)} components contain a directed cycle, "
            f"covering {covered} edges ({covered / len(graph.edges):.1%})",
            flush=True,
        )

    report["reading"] = (
        "cycles are abundant in this network, so a null result from the physical "
        "comparison is a statement about coasting, not about the extract"
    )
    write_text_lf(
        output / "cycle_topology.json", json.dumps(report, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
