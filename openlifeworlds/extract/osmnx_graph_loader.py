import os
import pickle
from functools import cache

import networkx as nx
import osmnx as ox
from networkx import MultiDiGraph
from openlifeworlds.tracking_decorator import TrackingDecorator


@TrackingDecorator.track_time
def load_osmnx_graph(
    results_path,
    query,
    network_type="walk",
    walk_speed_kph=4.5,
    simplified=False,
    debug=True,
    clean=False,
    quiet=False,
) -> MultiDiGraph:
    # Define area prefix
    area_prefix = (
        "-".join(list(reversed(query.split(",")))[1:]).lower().replace(" ", "")
    )
    # Define simplified suffix
    simplified_suffix = "-simplified" if simplified else ""

    # Define file paths
    graph_file_path = os.path.join(
        results_path,
        f"{area_prefix}-osmnx",
        f"{area_prefix}{simplified_suffix}-{network_type}.graphml",
    )
    pickle_file_path = os.path.join(
        results_path,
        f"{area_prefix}-osmnx",
        f"{area_prefix}{simplified_suffix}-{network_type}.pkl",
    )
    geojson_nodes_file_path = os.path.join(
        results_path,
        f"{area_prefix}-osmnx",
        f"{area_prefix}{simplified_suffix}-{network_type}-nodes.geojson",
    )
    geojson_edges_file_path = os.path.join(
        results_path,
        f"{area_prefix}-osmnx",
        f"{area_prefix}{simplified_suffix}-{network_type}-edges.geojson",
    )

    # Check if result needs to be generated
    if clean or not os.path.exists(pickle_file_path):
        # Download graph
        ox.settings.log_console = True
        graph = ox.graph_from_place(
            query=query,
            network_type=network_type,
            simplify=simplified,
        )
        ox.settings.log_console = False

        # Project to UTM (meters) for accurate distance calculation
        graph = ox.project_graph(graph)

        # Iterate over all edges and set speed/time
        for u, v, key, data in graph.edges(keys=True, data=True):
            # Set speed
            data["speed_kph"] = walk_speed_kph

            # Calculate travel time
            if "length" in data:
                data["weight"] = data["length"] / (walk_speed_kph / 3.6)
            else:
                data["weight"] = 0

        # Project to EPSG:4326 (lat/lon) for saving
        graph = ox.project_graph(graph, to_crs="EPSG:4326")
        # Relabel nodes to string
        graph = nx.relabel_nodes(graph, str, copy=False)

        # Save graph
        save_graph_as_graphml(graph, graph_file_path)
        save_graph_as_pickle(graph, pickle_file_path)
        debug and save_graph_as_geojson(
            graph, geojson_nodes_file_path, geojson_edges_file_path
        )

        not quiet and print(
            f"✓ Load {os.path.basename(graph_file_path)} with {len(graph.nodes)} nodes and {len(graph.edges)} edges"
        )
        return graph
    else:
        not quiet and print(f"✓ Already exists {os.path.basename(graph_file_path)}")
        return load_graph_from_pickle(pickle_file_path)


def download_graph(query, network_type=None, custom_filter=None, simplify=False):
    ox.settings.log_console = True
    graph = ox.graph_from_place(
        query=query,
        simplify=simplify,
        retain_all=False,
        network_type=network_type,
        custom_filter=custom_filter,
    )
    ox.settings.log_console = False
    return graph


def save_graph_as_graphml(graph: MultiDiGraph, file_path):
    # Make results path
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    # Save graph
    ox.save_graphml(graph, filepath=file_path)


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
def load_graph(file_path) -> MultiDiGraph:
    return ox.load_graphml(file_path)


@cache
def load_graph_from_pickle(file_path) -> MultiDiGraph:
    with open(file_path, "rb") as file:
        return pickle.load(file)
