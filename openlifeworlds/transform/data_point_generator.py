import json
import os

import h3
import numpy as np
from shapely.geometry import Point
from shapely.geometry import shape

from openlifeworlds.tracking_decorator import TrackingDecorator


@TrackingDecorator.track_time
def generate_points_rectangle(
    results_path,
    query,
    geojson_feature,
    grid_spacing_meters=1_000,
    clean=False,
    quiet=False,
):
    """
    Generates points based in a rectangular grid in a given distance
    :param results_path: results path
    :param query: query
    :param geojson_feature: geojson_feature
    :param grid_spacing_meters: grid spacing in meters
    :param clean: clean
    :param quiet: quiet
    :return:
    """

    # Define area prefix
    area_prefix = (
        "-".join(list(reversed(query.split(",")))[1:]).lower().replace(" ", "")
    )

    # Define file paths
    points_geojson_path = os.path.join(
        results_path,
        f"{area_prefix}-points",
        f"{area_prefix}-points-{grid_spacing_meters}.geojson",
    )

    if clean or not os.path.exists(points_geojson_path):
        points = generate_points_in_rectangular_grid(geojson_feature, grid_spacing_meters)
        points_geojson = build_geojson(points)
        write_geojson_file(points_geojson_path, points_geojson, clean, quiet)
    else:
        print(f"✓ Already exists {os.path.basename(points_geojson_path)}")


def generate_points_in_rectangular_grid(geojson_feature, grid_spacing_meters):
    xmin, ymin, xmax, ymax = build_bounding_box_with_padding(geojson_feature)

    factor_degree_to_meters = (
        111000  # 1 degree of latitude is approximately 111000 meters
    )

    # Calculate latitude and longitude spacing for given grid spacing
    lat_spacing = grid_spacing_meters / factor_degree_to_meters
    lon_spacing = grid_spacing_meters / (
        factor_degree_to_meters * np.cos(np.radians(ymin))
    )

    # Generate grid points
    latitudes = np.arange(ymin, ymax, lat_spacing)
    longitudes = np.arange(xmin, xmax, lon_spacing)

    # Create a meshgrid of latitudes and longitudes
    grid_latitudes, grid_longitudes = np.meshgrid(latitudes, longitudes)

    # Flatten the meshgrid to get individual points
    points = np.vstack([grid_longitudes.ravel(), grid_latitudes.ravel()]).T

    # Filter points outside the features in the geojson
    points = [
        point for point in points if is_point_inside_feature(geojson_feature, point)
    ]

    return points


def build_bounding_box_with_padding(geojson_feature):
    min_x, min_y, max_x, max_y = geojson_feature["properties"]["bounding_box"]

    padding_horizontal = abs(max_x - min_x) * 0.1
    padding_vertical = abs(max_y - min_y) * 0.1

    return [
        min_x - padding_horizontal,
        min_y - padding_vertical,
        max_x + padding_horizontal,
        max_y + padding_vertical,
    ]


def is_point_inside_feature(geojson_feature, point):
    return shape(geojson_feature["geometry"]).contains(Point(point[0], point[1]))

@TrackingDecorator.track_time
def generate_points_hexagon(
    results_path,
    query,
    geojson_feature,
    hexagon_resolution=7,
    clean=False,
    quiet=False,
):
    """
    Generates points based on a hexagonal grid in a given resolution
    with 6 points per hexagon positioned halfway between the center and each corner
    """

    # Define area prefix
    area_prefix = (
        "-".join(list(reversed(query.split(",")))[1:]).lower().replace(" ", "")
    )

    # Define file paths
    points_geojson_path = os.path.join(
        results_path,
        f"{area_prefix}-points",
        f"{area_prefix}-points-{hexagon_resolution}.geojson",
    )

    if clean or not os.path.exists(points_geojson_path):
        points = generate_points_in_hexagonal_grid(geojson_feature, hexagon_resolution)
        points_geojson = build_geojson(points)
        write_geojson_file(points_geojson_path, points_geojson, clean, quiet)
    else:
        print(f"✓ Already exists {os.path.basename(points_geojson_path)}")


def generate_points_in_hexagonal_grid(geojson_feature, hexagon_resolution):

    # Build hexagons
    hexagons = h3.polygon_to_cells(
        h3.LatLngPoly([(lon, lat) for lon, lat in geojson_feature['geometry']['coordinates'][0]]),
        res=hexagon_resolution
    )

    points = []

    # Iterate over hexagons
    for hex_id in hexagons:
        # Get center
        center_lat, center_lon = h3.cell_to_latlng(hex_id)

        # Get Boundary Vertices [(lat, lng), (lat, lng), ...]
        boundary = h3.cell_to_boundary(hex_id)

        # Calculate the 6 halfway points
        hex_points = []
        for vertex_lat, vertex_lng in boundary:
            # Apply simple linear interpolation
            mid_lat = (center_lat + vertex_lat) / 2
            mid_lng = (center_lon + vertex_lng) / 2
            hex_points.append((mid_lat, mid_lng))

        points.extend(hex_points)

    return points




#
# Helpers
#

def build_geojson(points):
    return {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [point[0], point[1]]},
                "properties": {},
            }
            for point in points
        ],
    }


def write_geojson_file(target_file_path, geojson, clean, quiet):
    if clean or not os.path.exists(target_file_path):
        os.makedirs(os.path.dirname(target_file_path), exist_ok=True)
        with open(target_file_path, "w", encoding="utf-8") as geojson_file:
            json.dump(geojson, geojson_file, ensure_ascii=False)

            not quiet and print(
                f"✓ Generate points geojson {os.path.basename(target_file_path)}"
            )
    else:
        not quiet and print(f"✓ Already exists {os.path.basename(target_file_path)}")
