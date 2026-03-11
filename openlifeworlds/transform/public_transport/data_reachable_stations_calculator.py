import geopandas as gpd
import pandas as pd
from shapely import concave_hull


def calculate_reachable_stations_convex_hull(
    points_utm,
    buffer_meters,
    transit_geodataframes=None,
) -> (dict[str, int], gpd.GeoDataFrame):
    # Calculate convex hull
    # Using unary_union directly on the GeoSeries of points to properly handle MultiPoint input for convex_hull if needed,
    # though usually convex_hull can take a MultiPoint.
    # However, points_utm is now a GeoSeries (projected).

    if transit_geodataframes is None:
        transit_geodataframes = {}

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

    geodataframes = [
        clean_geodataframe(
            gpd.sjoin(value, reachable_gdf, predicate="within"), type=key
        )
        for key, value in transit_geodataframes.items()
    ]

    return (
        {
            key: len(geodataframe)
            for key, geodataframe in zip(transit_geodataframes.keys(), geodataframes)
        },
        gpd.GeoDataFrame(
            pd.concat(
                geodataframes,
                ignore_index=True,
            ),
            geometry="geometry",
            crs="EPSG:4326",
        ),
    )


def calculate_reachable_stations_concave_hull(
    points_utm,
    concave_hull_ratio,
    buffer_meters,
    allow_holes=False,
    transit_geodataframes=None,
) -> (dict[str, int], gpd.GeoDataFrame):
    # Calculate concave hull
    # ratio=0.0 -> convex hull (rubber band)
    # ratio=1.0 -> the tightest fit (connecting the dots)
    # ratio=0.1 to 0.3 is usually the "sweet spot" for city reachability

    if transit_geodataframes is None:
        transit_geodataframes = {}

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

    geodataframes = [
        clean_geodataframe(
            gpd.sjoin(value, reachable_gdf, predicate="within"), type=key
        )
        for key, value in transit_geodataframes.items()
    ]

    return (
        {
            key: len(geodataframe)
            for key, geodataframe in zip(transit_geodataframes.keys(), geodataframes)
        },
        gpd.GeoDataFrame(
            pd.concat(
                geodataframes,
                ignore_index=True,
            ),
            geometry="geometry",
            crs="EPSG:4326",
        ),
    )


def calculate_reachable_stations_union_of_buffers(
    points_utm,
    buffer_meters,
    transit_geodataframes=None,
) -> (dict[str, int], gpd.GeoDataFrame):
    if transit_geodataframes is None:
        transit_geodataframes = {}

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

    geodataframes = [
        clean_geodataframe(
            gpd.sjoin(value, reachable_gdf, predicate="within"), type=key
        )
        for key, value in transit_geodataframes.items()
    ]

    return (
        {
            key: len(geodataframe)
            for key, geodataframe in zip(transit_geodataframes.keys(), geodataframes)
        },
        gpd.GeoDataFrame(
            pd.concat(
                geodataframes,
                ignore_index=True,
            ),
            geometry="geometry",
            crs="EPSG:4326",
        ),
    )


#
# Helpers
#


def clean_geodataframe(gdf: gpd.GeoDataFrame, type) -> gpd.GeoDataFrame:
    return gdf[["stop_name", "geometry"]].assign(
        stop_name=lambda x: x["stop_name"]
        .str.replace("(Berlin)", "")
        .str.replace("Berlin,", "")
        .str.strip(),
        type=type,
    )
