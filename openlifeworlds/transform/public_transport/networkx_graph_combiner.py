import os
import pickle
from functools import cache

import networkx as nx
import osmnx as ox
import pandas as pd
from networkx import DiGraph, MultiDiGraph
from openlifeworlds.tracking_decorator import TrackingDecorator
from scipy.spatial import KDTree


@TrackingDecorator.track_time
def combine_graphs(
    results_path,
    query,
    walk_graph: MultiDiGraph,
    transit_graph: MultiDiGraph,
    year=2024,
    start_hour=None,
    end_hour=None,
    debug=False,
    clean=False,
    quiet=False,
) -> MultiDiGraph:
    # Define area prefix
    area_prefix = (
        "-".join(list(reversed(query.split(",")))[1:]).lower().replace(" ", "")
    )
    # Define time window suffix
    time_window_suffix = (
        f"{str(start_hour).zfill(2)}-{str(end_hour).zfill(2)}"
        if start_hour is not None and end_hour is not None
        else "avg"
    )

    # Define file paths
    graph_file_path = os.path.join(
        results_path,
        f"{area_prefix}-networkx",
        f"{area_prefix}-combined-{year}-{time_window_suffix}.graphml",
    )
    pickle_file_path = os.path.join(
        results_path,
        "berlin-networkx",
        f"{area_prefix}-combined-{year}-{time_window_suffix}.pkl",
    )
    geojson_nodes_file_path = os.path.join(
        results_path,
        f"{area_prefix}-networkx",
        f"{area_prefix}-{year}-{time_window_suffix}-combined-nodes.geojson",
    )
    geojson_edges_file_path = os.path.join(
        results_path,
        f"{area_prefix}-networkx",
        f"{area_prefix}-{year}-{time_window_suffix}-combined-edges.geojson",
    )

    # Check if result needs to be generated
    if clean or not os.path.exists(pickle_file_path):
        # Relabel nodes to string
        walk_graph = nx.relabel_nodes(walk_graph, str, copy=False)
        transit_graph = nx.relabel_nodes(transit_graph, str, copy=False)

        # Create a combined graph
        graph = nx.compose(walk_graph, transit_graph)

        # Get walk nodes and transit nodes positions
        walk_nodes_df = pd.DataFrame.from_dict(
            dict(walk_graph.nodes(data=True)), orient="index"
        )
        transit_nodes_df = pd.DataFrame.from_dict(
            dict(transit_graph.nodes(data=True)), orient="index"
        )

        # Build a KDTree for fast nearest-neighbor lookup
        tree = KDTree(walk_nodes_df[["x", "y"]])

        # Connect every transit stop to the nearest walk node
        for stop_id, stop_data in transit_nodes_df.iterrows():
            # Find nearest walk node
            dist, idx = tree.query([stop_data["x"], stop_data["y"]])
            nearest_walk_node = walk_nodes_df.index[idx]

            # Walk -> transit stop (onboarding)
            graph.add_edge(nearest_walk_node, stop_id, travel_time=0)
            # Transit stop -> walk (offboarding)
            graph.add_edge(stop_id, nearest_walk_node, travel_time=0)

        # Convert node IDs to integer
        graph = nx.convert_node_labels_to_integers(graph, label_attribute="original_id")

        # Save graph
        save_graph_as_graphml(graph, graph_file_path)
        save_graph_as_pickle(graph, pickle_file_path)
        debug and save_graph_as_geojson(
            graph, geojson_nodes_file_path, geojson_edges_file_path
        )

        not quiet and print(
            f"✓ Combine {os.path.basename(graph_file_path)} with {len(graph.nodes)} nodes and {len(graph.edges)} edges"
        )
        return graph
    else:
        not quiet and print(f"✓ Already exists {os.path.basename(graph_file_path)}")
        return load_graph_from_pickle(pickle_file_path)


def save_graph_as_graphml(graph: DiGraph, file_path):
    graph_save = graph.copy()

    # Clean edges
    for u, v, key, data in graph_save.edges(keys=True, data=True):
        # Convert shapely geometries to string (WKT format)
        if "geometry" in data:
            data["geometry"] = data["geometry"].wkt

        # Fix lists (OSMnx sometimes stores 'highway' as a list like ['tertiary', 'residential'])
        for k, val in data.items():
            if isinstance(val, list):
                data[k] = str(val)

    # Clean nodes
    for node, data in graph_save.nodes(data=True):
        for k, val in data.items():
            if isinstance(val, list):
                data[k] = str(val)

    # Make results path
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    # Save graph
    nx.write_graphml(graph_save, path=file_path)


def save_graph_as_pickle(graph: MultiDiGraph, file_path):
    # Make results path
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    # Save graph
    with open(file_path, "wb") as f:
        pickle.dump(graph, f)


def save_graph_as_geojson(graph: MultiDiGraph, nodes_file_path, edges_file_path):
    # Make results paths
    os.makedirs(os.path.dirname(nodes_file_path), exist_ok=True)
    os.makedirs(os.path.dirname(edges_file_path), exist_ok=True)

    # Convert graph to geo dataframes
    nodes_gdf, edges_gdf = ox.graph_to_gdfs(graph)

    # Force conversion to Lat/Lon (EPSG:4326)
    nodes_gdf = nodes_gdf.to_crs("epsg:4326")
    edges_gdf = edges_gdf.to_crs("epsg:4326")

    # Handle list columns
    for col in edges_gdf.columns:
        if edges_gdf[col].apply(lambda x: isinstance(x, list)).any():
            edges_gdf[col] = edges_gdf[col].astype(str)

    # Save as geojson
    nodes_gdf.to_file(filename=nodes_file_path, driver="GeoJSON")
    edges_gdf.to_file(filename=edges_file_path, driver="GeoJSON")


@cache
def load_graph(file_path):
    return nx.read_graphml(file_path)


@cache
def load_graph_from_pickle(file_path) -> MultiDiGraph:
    with open(file_path, "rb") as file:
        return pickle.load(file)
