import os
import pickle
from functools import cache

import networkx as nx
import numpy as np
import osmnx as ox
import partridge as ptg
from networkx import MultiDiGraph
from openlifeworlds.tracking_decorator import TrackingDecorator
from shapely import Point
from shapely.geometry import shape


@TrackingDecorator.track_time
def load_transit_graph(
    source_path,
    results_path,
    query,
    geojson_feature,
    year=2024,
    start_hour=None,
    end_hour=None,
    average_wait_time_min=None,
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
    gtfs_file_path = os.path.join(
        source_path,
        f"{area_prefix}-public-transport-gtfs-{year}-00",
        f"{area_prefix}-public-transport-gtfs-{year}-00.zip",
    )
    graph_file_path = os.path.join(
        results_path,
        f"{area_prefix}-partridge",
        f"{area_prefix}-transit-{year}-{time_window_suffix}.graphml",
    )
    pickle_file_path = os.path.join(
        results_path,
        f"{area_prefix}-partridge",
        f"{area_prefix}-transit-{year}-{time_window_suffix}.pkl",
    )
    geojson_nodes_file_path = os.path.join(
        results_path,
        f"{area_prefix}-partridge",
        f"{area_prefix}-transit-{year}-{time_window_suffix}-nodes.geojson",
    )
    geojson_edges_file_path = os.path.join(
        results_path,
        f"{area_prefix}-partridge",
        f"{area_prefix}-transit-{year}-{time_window_suffix}-edges.geojson",
    )

    # Check if result needs to be generated
    if clean or not os.path.exists(pickle_file_path):
        #
        # Load and filter GTFS data
        #

        # Identify service IDs that are active on the first date
        service_ids_by_date = ptg.read_service_ids_by_date(gtfs_file_path)
        service_ids_first_date = list(service_ids_by_date)[0]
        service_ids_on_first_date = service_ids_by_date.get(service_ids_first_date)

        # Use Partridge to load ONLY the service active on that date
        feed = ptg.load_feed(
            gtfs_file_path,
            view={"trips.txt": {"service_id": service_ids_on_first_date}},
        )

        #
        # Build public transport graph
        #

        # Extract stops and stop times
        stops = feed.stops
        stop_times = feed.stop_times

        # Create a transit graph
        graph = nx.MultiDiGraph()

        # Add stops as nodes
        for _, stop in stops.iterrows():
            graph.add_node(
                f"transit_{stop.stop_id}",
                x=stop.stop_lon,
                y=stop.stop_lat,
                node_type="transit",
            )

        # Add transit edges (hop between stops)
        sorted_stop_times = stop_times.sort_values(["trip_id", "stop_sequence"])
        sorted_stop_times["next_stop_id"] = sorted_stop_times.groupby("trip_id")[
            "stop_id"
        ].shift(-1)
        sorted_stop_times["next_arrival_time"] = sorted_stop_times.groupby("trip_id")[
            "arrival_time"
        ].shift(-1)
        sorted_stop_times["travel_time"] = (
            sorted_stop_times["next_arrival_time"] - sorted_stop_times["departure_time"]
        )

        edges = sorted_stop_times.dropna()
        avg_edges = (
            edges.groupby(["stop_id", "next_stop_id"])["travel_time"]
            .median()
            .reset_index()
        )

        #
        # Calculate travel time
        #

        if start_hour is not None and end_hour is not None:
            # Define active window (e.g., 8 AM to 10 AM)
            WINDOW_SECONDS = (end_hour - start_hour) * 3600

            # Filter stop_times to this window (based on departure_time seconds)
            valid_stop_times = sorted_stop_times[
                (sorted_stop_times.departure_time >= start_hour * 3600)
                & (sorted_stop_times.departure_time < end_hour * 3600)
            ].copy()

            # Group by edge
            edge_stats = (
                valid_stop_times.groupby(["stop_id", "next_stop_id"])
                .agg(
                    median_travel_time=("travel_time", "median"),
                    trip_count=("trip_id", "count"),
                )
                .reset_index()
            )

            # Calculate dynamic wait time
            def calculate_cost(row):
                # Frequency: number of trips per window
                trips = row["trip_count"]

                if trips == 0:
                    return np.inf

                # Headway: average seconds between vehicles
                # e.g., 3600 seconds window / 6 trips = 600 seconds (10 min) headway
                headway_seconds = WINDOW_SECONDS / trips

                # Average wait: is half the headway (assuming random arrival)
                avg_wait = min(headway_seconds / 2, 1800)

                # Total cost: in-vehicle time + waiting time
                return row["median_travel_time"] + avg_wait

            # Apply the calculation
            edge_stats["weight"] = edge_stats.apply(calculate_cost, axis=1)

            # Add edges to graph
            for _, row in edge_stats.iterrows():
                u = f"transit_{row.stop_id}"
                v = f"transit_{row.next_stop_id}"

                graph.add_edge(
                    u,
                    v,
                    weight=row["weight"],
                    travel_time=row["median_travel_time"],
                    wait_time=row["weight"] - row["median_travel_time"],
                    edge_type="transit",
                )

            print("Graph built with Frequency-Based Waiting Times!")
        elif average_wait_time_min is not None:
            # Add edges to graph
            for _, row in avg_edges.iterrows():
                u = f"transit_{row.stop_id}"
                v = f"transit_{row.next_stop_id}"

                graph.add_edge(
                    u,
                    v,
                    weight=row.travel_time + average_wait_time_min * 60,
                    travel_time=row.travel_time,
                    wait_time=average_wait_time_min * 60,
                    edge_type="transit",
                )
        else:
            raise ValueError(
                "You must specify either start_hour/end_hour or average_wait_time_min"
            )

        # Truncate graph to geojson feature
        graph = truncate_by_geojson(graph, geojson_feature)

        # Set graph CRS
        graph.graph["crs"] = "EPSG:4326"
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


def build_bounding_box_with_padding(geojson_feature: {}) -> []:
    min_x, min_y, max_x, max_y = geojson_feature["properties"]["bounding_box"]

    padding_horizontal = abs(max_x - min_x) * 0.1
    padding_vertical = abs(max_y - min_y) * 0.1

    return [
        min_x - padding_horizontal,
        min_y - padding_vertical,
        max_x + padding_horizontal,
        max_y + padding_vertical,
    ]


def truncate_to_bounding_box(graph: MultiDiGraph, bounding_box: []) -> MultiDiGraph:
    min_x, min_y, max_x, max_y = bounding_box

    # Identify nodes within the bounding box
    nodes_to_keep = [
        node
        for node, data in graph.nodes(data=True)
        if min_x <= data.get("x") <= max_x and min_y <= data.get("y") <= max_y
    ]

    return graph.subgraph(nodes_to_keep).copy()


def truncate_by_geojson(graph: MultiDiGraph, geojson_feature):
    polygon = shape(geojson_feature["geometry"])

    nodes_to_keep = []

    for node, data in graph.nodes(data=True):
        # Check if the polygon contains the point
        if polygon.contains(Point(data["x"], data["y"])):
            nodes_to_keep.append(node)

    return graph.subgraph(nodes_to_keep).copy()


def save_graph_as_graphml(graph: MultiDiGraph, file_path):
    # Make results path
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    # Save graph
    nx.write_graphml(graph, path=file_path)


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
    return nx.read_graphml(file_path, force_multigraph=True)


@cache
def load_graph_from_pickle(file_path) -> MultiDiGraph:
    with open(file_path, "rb") as file:
        return pickle.load(file)
