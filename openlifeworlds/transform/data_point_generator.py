import json
import os

import numpy as np
from shapely.geometry import Point
from shapely.geometry import shape

from openlifeworlds.tracking_decorator import TrackingDecorator


@TrackingDecorator.track_time
def generate_points(
    source_path, results_path, grid_spacing_meters=1_000, clean=False, quiet=False
):
    """
    Generates points in a given grid
    :param source_path: source path
    :param results_path: results path
    :param grid_spacing_meters: grid spacing in meters
    :param clean: clean
    :param quiet: quiet
    :return:
    """

    city_geojson_path = os.path.join(
        source_path, "berlin-lor-city", "berlin-lor-city.geojson"
    )
    points_geojson_path = os.path.join(
        results_path, f"berlin-15-minute-city", f"points-{grid_spacing_meters}.geojson"
    )

    if clean or not os.path.exists(points_geojson_path):
        city_geojson = load_geojson_file(city_geojson_path)
        points = generate_points_in_grid(city_geojson, grid_spacing_meters)
        points_geojson = generate_geojson(points)
        write_geojson_file(points_geojson_path, points_geojson, clean, quiet)
    else:
        print(f"✓ Already exists {os.path.basename(points_geojson_path)}")


def load_geojson_file(geojson_template_file_path):
    with open(
        file=geojson_template_file_path, mode="r", encoding="utf-8"
    ) as geojson_file:
        return json.load(geojson_file, strict=False)


def generate_points_in_grid(geojson, grid_spacing_meters):
    xmin, ymin, xmax, ymax = geojson["features"][0]["properties"]["bounding_box"]
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
    points = [point for point in points if is_point_inside_any_feature(geojson, point)]

    return points


def generate_geojson(points):
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


#
# Helpers
#


def read_geojson_file(file_path):
    with open(file=file_path, mode="r", encoding="utf-8") as geojson_file:
        return json.load(geojson_file, strict=False)


def is_point_inside_any_feature(geojson, point):
    for feature in geojson["features"]:
        geometry = shape(feature["geometry"])
        if geometry.contains(Point(point[0], point[1])):
            return True
    return False


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
