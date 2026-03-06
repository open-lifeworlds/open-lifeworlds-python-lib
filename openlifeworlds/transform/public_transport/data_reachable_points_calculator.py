import math

import networkx as nx
import osmnx as ox
from networkx import MultiDiGraph
from shapely import MultiPoint, Point


def calculate_reachable_points(
    graph: MultiDiGraph,
    reference_point: Point,
    time_minutes: int,
):
    # Find nearest graph node to the reference point
    start_node_id = ox.distance.nearest_nodes(
        graph, reference_point.x, reference_point.y
    )

    nodes_within_range = nx.single_source_dijkstra_path_length(
        graph, start_node_id, cutoff=time_minutes * 60, weight="weight"
    )

    valid_coords = []
    # Iterate over the node IDs
    for node_id in nodes_within_range:
        # Access the node data directly from the global graph (Fast & Low Memory)
        data = graph.nodes[node_id]

        x, y = data.get("x"), data.get("y")

        # Strict check: Must be a number and must be finite (no Inf or NaN)
        if x is not None and y is not None and math.isfinite(x) and math.isfinite(y):
            valid_coords.append((x, y))

    return MultiPoint(valid_coords)
