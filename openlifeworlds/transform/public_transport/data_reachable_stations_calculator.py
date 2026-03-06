import geopandas as gpd
import pandas as pd
from shapely import concave_hull


def calculate_reachable_stations_convex_hull(
    points_utm,
    buffer_meters,
    bus_gdf=None,
    ferry_gdf=None,
    sbahn_gdf=None,
    tram_gdf=None,
    ubahn_gdf=None,
) -> gpd.GeoDataFrame:
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

    # Identify stations within the reachable area using spatial join
    bus_points_gdf = gpd.sjoin(bus_gdf, reachable_gdf, predicate="within")
    ferry_points_gdf = gpd.sjoin(ferry_gdf, reachable_gdf, predicate="within")
    sbahn_points_gdf = gpd.sjoin(sbahn_gdf, reachable_gdf, predicate="within")
    tram_points_gdf = gpd.sjoin(tram_gdf, reachable_gdf, predicate="within")
    ubahn_points_gdf = gpd.sjoin(ubahn_gdf, reachable_gdf, predicate="within")

    return gpd.GeoDataFrame(
        pd.concat(
            [
                clean_geodataframe(bus_points_gdf, type="bus"),
                clean_geodataframe(ferry_points_gdf, type="ferry"),
                clean_geodataframe(sbahn_points_gdf, type="s-bahn"),
                clean_geodataframe(tram_points_gdf, type="tram"),
                clean_geodataframe(ubahn_points_gdf, type="u-bahn"),
            ],
            ignore_index=True,
        ),
        geometry="geometry",
        crs="EPSG:4326",
    )


def calculate_reachable_stations_concave_hull(
    points_utm,
    concave_hull_ratio,
    buffer_meters,
    allow_holes=False,
    bus_gdf=None,
    ferry_gdf=None,
    sbahn_gdf=None,
    tram_gdf=None,
    ubahn_gdf=None,
) -> (dict[str, int], gpd.GeoDataFrame):
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

    # Identify stations within the reachable area using spatial join
    bus_points_gdf = gpd.sjoin(bus_gdf, reachable_gdf, predicate="within")
    ferry_points_gdf = gpd.sjoin(ferry_gdf, reachable_gdf, predicate="within")
    sbahn_points_gdf = gpd.sjoin(sbahn_gdf, reachable_gdf, predicate="within")
    tram_points_gdf = gpd.sjoin(tram_gdf, reachable_gdf, predicate="within")
    ubahn_points_gdf = gpd.sjoin(ubahn_gdf, reachable_gdf, predicate="within")

    return {
        "bus": len(bus_points_gdf),
        "ferry": len(ferry_points_gdf),
        "s-bahn": len(sbahn_points_gdf),
        "tram": len(tram_points_gdf),
        "u-bahn": len(ubahn_points_gdf),
    }, gpd.GeoDataFrame(
        pd.concat(
            [
                clean_geodataframe(bus_points_gdf, type="bus"),
                clean_geodataframe(ferry_points_gdf, type="ferry"),
                clean_geodataframe(sbahn_points_gdf, type="s-bahn"),
                clean_geodataframe(tram_points_gdf, type="tram"),
                clean_geodataframe(ubahn_points_gdf, type="u-bahn"),
            ],
            ignore_index=True,
        ),
        geometry="geometry",
        crs="EPSG:4326",
    )


def calculate_reachable_stations_union_of_buffers(
    points_utm,
    buffer_meters,
    bus_gdf=None,
    ferry_gdf=None,
    sbahn_gdf=None,
    tram_gdf=None,
    ubahn_gdf=None,
) -> gpd.GeoDataFrame:
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

    # Identify stations within the reachable area using spatial join
    bus_points_gdf = gpd.sjoin(bus_gdf, reachable_gdf, predicate="within")
    ferry_points_gdf = gpd.sjoin(ferry_gdf, reachable_gdf, predicate="within")
    sbahn_points_gdf = gpd.sjoin(sbahn_gdf, reachable_gdf, predicate="within")
    tram_points_gdf = gpd.sjoin(tram_gdf, reachable_gdf, predicate="within")
    ubahn_points_gdf = gpd.sjoin(ubahn_gdf, reachable_gdf, predicate="within")

    return gpd.GeoDataFrame(
        pd.concat(
            [
                clean_geodataframe(bus_points_gdf, type="bus"),
                clean_geodataframe(ferry_points_gdf, type="ferry"),
                clean_geodataframe(sbahn_points_gdf, type="s-bahn"),
                clean_geodataframe(tram_points_gdf, type="tram"),
                clean_geodataframe(ubahn_points_gdf, type="u-bahn"),
            ],
            ignore_index=True,
        ),
        geometry="geometry",
        crs="EPSG:4326",
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
