import json
import os
from enum import Enum
from functools import cache

import geopandas as gpd
import networkx as nx
import pandas as pd
from openlifeworlds.tracking_decorator import TrackingDecorator
from shapely import Point, concave_hull
from tqdm import tqdm

from openlifeworlds.transform.public_transport.data_reachable_points_calculator import (
    calculate_reachable_points,
)


class ReachableAreaType(Enum):
    CONVEX_HULL = "convex-hull"
    CONCAVE_HULL = "concave-hull"
    UNION_OF_BUFFERS = "union-of-buffers"


@TrackingDecorator.track_time
def calculate_reachable_area(
    source_path,
    results_path,
    query,
    graph,
    hexagon_resolution=7,
    time_minutes=15,
    concave_hull_ratio=0.2,
    buffer_meters=200,
    year=2024,
    end_hour=None,
    start_hour=None,
    checkpoint_interval=100,
    debug=False,
    clean=False,
    quiet=False,
):
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

    # Define paths
    points_geojson_path = os.path.join(
        source_path,
        f"{area_prefix}-points",
        f"{area_prefix}-points-{hexagon_resolution}.geojson",
    )
    reachable_area_geojson_path = os.path.join(
        results_path,
        f"{area_prefix}-public-transport-{year}-{time_window_suffix}",
        f"{area_prefix}-points-{hexagon_resolution}-with-reachable-area.geojson",
    )
    checkpoint_path = reachable_area_geojson_path.replace(
        ".geojson", "-checkpoint.geojson"
    )

    if not clean and os.path.exists(reachable_area_geojson_path):
        print(f"✓ Already exists {os.path.basename(reachable_area_geojson_path)}")
        return

    if not clean and os.path.exists(checkpoint_path):
        print(f"Resuming from checkpoint: {os.path.basename(checkpoint_path)}")
        geojson = load_geojson_file(checkpoint_path)
    else:
        geojson = load_geojson_file(points_geojson_path)

    # Convert node IDs to integer
    graph = nx.convert_node_labels_to_integers(graph, label_attribute="original_id")

    # Estimate UTM CRS once to avoid re-calculation for every feature
    utm_crs = None
    if geojson["features"]:
        p0 = geojson["features"][0]["geometry"]["coordinates"]
        utm_crs = gpd.GeoSeries(
            [Point(p0[0], p0[1])], crs="EPSG:4326"
        ).estimate_utm_crs()

    processed_count = 0
    for feature in tqdm(
        geojson["features"],
        desc="Enhance features with reachable area",
        total=len(geojson["features"]),
        unit="feature",
    ):
        # Skip if already calculated (resumable)
        if (
            "reachable_area_convex_hull" in feature["properties"]
            and "reachable_area_concave_hull" in feature["properties"]
            and "reachable_area_union_of_buffers" in feature["properties"]
        ):
            continue

        point = feature["geometry"]["coordinates"]
        enhance_feature(
            results_path,
            area_prefix,
            graph,
            feature,
            Point(point[0], point[1]),
            time_minutes,
            hexagon_resolution,
            concave_hull_ratio,
            buffer_meters,
            debug,
            utm_crs,
        )

        processed_count += 1
        if processed_count % checkpoint_interval == 0:
            write_geojson_file(checkpoint_path, geojson, clean=True, quiet=True)

    write_geojson_file(
        reachable_area_geojson_path,
        geojson,
        clean,
        quiet,
    )

    # Clean up checkpoint
    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)


def enhance_feature(
    results_path,
    area_prefix,
    graph,
    feature,
    reference_point: Point,
    time_minutes=15,
    hexagon_resolution=7,
    concave_hull_ratio=0.2,
    buffer_meters=200,
    debug=False,
    utm_crs=None,
):
    reachable_points = calculate_reachable_points(graph, reference_point, time_minutes)

    # Project points to UTM once
    reachable_points_series = gpd.GeoSeries(reachable_points, crs="EPSG:4326")

    # Estimate CRS if not provided (fallback)
    if utm_crs is None:
        utm_crs = reachable_points_series.estimate_utm_crs()

    reachable_points_utm = reachable_points_series.to_crs(utm_crs)

    # Calculate reachable area
    reachable_area_convex_hull, reachable_area_convex_hull_gdf = (
        calculate_reachable_area_convex_hull(reachable_points_utm, buffer_meters)
    )
    reachable_area_concave_hull, reachable_area_concave_hull_gdf = (
        calculate_reachable_area_concave_hull(
            reachable_points_utm, concave_hull_ratio, buffer_meters
        )
    )
    reachable_area_union_of_buffers, reachable_area_union_of_buffers_gdf = (
        calculate_reachable_area_union_of_buffers(reachable_points_utm, buffer_meters)
    )

    # Add properties to feature
    feature["properties"]["reachable_area_convex_hull"] = reachable_area_convex_hull
    feature["properties"]["reachable_area_concave_hull"] = reachable_area_concave_hull
    feature["properties"]["reachable_area_union_of_buffers"] = (
        reachable_area_union_of_buffers
    )

    if debug:
        write_gdf_as_geojson(
            os.path.join(
                results_path,
                "berlin-reachable-area",
                f"{hexagon_resolution}",
                f"{area_prefix}-reachable-area-convex-hull-{reference_point.x}-{reference_point.y}.geojson",
            ),
            reachable_area_convex_hull_gdf,
            reference_point,
            clean=True,
            quiet=True,
        )
        write_gdf_as_geojson(
            os.path.join(
                results_path,
                "berlin-reachable-area",
                f"{hexagon_resolution}",
                f"{area_prefix}-reachable-area-concave-hull-{reference_point.x}-{reference_point.y}.geojson",
            ),
            reachable_area_concave_hull_gdf,
            reference_point,
            clean=True,
            quiet=True,
        )
        write_gdf_as_geojson(
            os.path.join(
                results_path,
                "berlin-reachable-area",
                f"{hexagon_resolution}",
                f"{area_prefix}-reachable-area-union-of-buffers-{reference_point.x}-{reference_point.y}.geojson",
            ),
            reachable_area_union_of_buffers_gdf,
            reference_point,
            clean=True,
            quiet=True,
        )

    return feature


def calculate_reachable_area_convex_hull(
    points_utm, buffer_meters
) -> (int, gpd.GeoDataFrame):
    # Calculate convex hull
    # Using unary_union directly on the GeoSeries of points to properly handle MultiPoint input for convex_hull if needed,
    # though usually convex_hull can take a MultiPoint.
    # However, points_utm is now a GeoSeries (projected).
    hull = points_utm.unary_union.convex_hull

    # Create geo series of the hull
    geo_series_projected = gpd.GeoSeries(hull, crs=points_utm.crs)

    # Add buffer
    geo_series_projected = geo_series_projected.buffer(buffer_meters)

    # Project to lat/lon
    reachable_shape_lat_lon = gpd.GeoSeries(
        geo_series_projected, crs=geo_series_projected.crs
    ).to_crs("EPSG:4326")[0]

    reachable_gdf = gpd.GeoDataFrame(
        index=[0], crs="epsg:4326", geometry=[reachable_shape_lat_lon]
    )

    return geo_series_projected.area.iloc[0], reachable_gdf


def calculate_reachable_area_concave_hull(
    points_utm, concave_hull_ratio, buffer_meters, allow_holes=False
) -> (int, gpd.GeoDataFrame):
    # Calculate concave hull
    # ratio=0.0 -> convex hull (rubber band)
    # ratio=1.0 -> the tightest fit (connecting the dots)
    # ratio=0.1 to 0.3 is usually the "sweet spot" for city reachability
    hull = concave_hull(
        points_utm.unary_union, ratio=concave_hull_ratio, allow_holes=allow_holes
    )

    # Create geo series
    geo_series_projected = gpd.GeoSeries(hull, crs=points_utm.crs)

    # Add buffer
    geo_series_projected = geo_series_projected.buffer(buffer_meters)

    # Project to lat/lon
    reachable_shape_lat_lon = gpd.GeoSeries(
        geo_series_projected, crs=geo_series_projected.crs
    ).to_crs("EPSG:4326")[0]

    reachable_gdf = gpd.GeoDataFrame(
        index=[0], crs="epsg:4326", geometry=[reachable_shape_lat_lon]
    )

    return geo_series_projected.area.iloc[0], reachable_gdf


def calculate_reachable_area_union_of_buffers(
    points_utm, buffer_meters
) -> (int, gpd.GeoDataFrame):
    # Optimized: Union points first (cheap), then buffer (fast)
    # This avoids unioning thousands of circles and leverages GEOS efficient MultiPoint buffering
    reachable_shape_meters = points_utm.unary_union.buffer(buffer_meters, resolution=4)

    # Project to lat/lon
    reachable_shape_lat_lon = gpd.GeoSeries(
        [reachable_shape_meters], crs=points_utm.crs
    ).to_crs("EPSG:4326")[0]

    reachable_gdf = gpd.GeoDataFrame(
        index=[0], crs="epsg:4326", geometry=[reachable_shape_lat_lon]
    )

    return reachable_shape_meters.area, reachable_gdf


@cache
def load_geojson_file(file_path):
    with open(file=file_path, mode="r", encoding="utf-8") as geojson_file:
        return json.load(geojson_file, strict=False)


def write_gdf_as_geojson(
    file_path, reachable_area_gdf, reference_point: Point, clean, quiet
):
    if not os.path.exists(file_path) or clean:
        # Make results path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Create a geo dataframe
        dataframe = pd.DataFrame(
            [
                {
                    "geometry": reachable_area_gdf.geometry,
                    "type": "reachable area",
                    "description": "15-min isochrone",
                },
                {
                    "geometry": Point(reference_point.x, reference_point.y),
                    "type": "reference point",
                    "description": "origin",
                },
            ]
        )
        gdf = gpd.GeoDataFrame(dataframe, geometry="geometry", crs="EPSG:4326")

        gdf.to_file(file_path, driver="GeoJSON")

        not quiet and print(
            f"✓ Generate reachable shape into {os.path.basename(file_path)}"
        )
    else:
        print(f"✓ Already exists {os.path.basename(file_path)}")


def write_geojson_file(file_path, geojson_content, clean, quiet):
    if not os.path.exists(file_path) or clean:
        # Make results path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, "w", encoding="utf-8") as geojson_file:
            json.dump(geojson_content, geojson_file, ensure_ascii=False)

            not quiet and print(f"✓ Generate points into {os.path.basename(file_path)}")
    else:
        print(f"✓ Already exists {os.path.basename(file_path)}")
