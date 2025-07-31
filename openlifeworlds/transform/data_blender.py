import json
import os
import re
import warnings

import pandas as pd

from openlifeworlds.tracking_decorator import TrackingDecorator

warnings.filterwarnings("ignore", category=UserWarning)


@TrackingDecorator.track_time
def blend_data(
    data_product_manifest,
    data_transformation,
    source_path,
    results_path,
    clean=False,
    quiet=False,
):
    already_exists, converted, exception = 0, 0, 0

    for input_port_group in data_transformation.input_port_groups or []:
        # Initialize statistics
        json_statistics = {}

        statistics_file_path = os.path.join(
            results_path,
            f"{input_port_group.id}-statistics",
            f"{input_port_group.id}-statistics.json",
        )

        for input_port in input_port_group.input_ports or []:
            year = re.search(r"\b\d{4}\b", input_port.id).group()
            half_year = (
                re.search(r"\b\d{2}(?<!\d{4})\b", input_port.id).group()
                if re.search(r"\b\d{2}(?<!\d{4})\b", input_port.id)
                else "00"
            )

            # Build statistics structure
            if year not in json_statistics:
                json_statistics[year] = {}
            if half_year not in json_statistics[year]:
                json_statistics[year][half_year] = {}

            for file in input_port.files or []:
                target_file_path = os.path.join(
                    results_path,
                    f"{input_port_group.id}-geojson",
                    file.target_file_name,
                )
                geojson_template_file_path = os.path.join(
                    source_path, file.geojson_template_file_name
                )

                try:
                    # Load template geojson
                    geojson = load_geojson_file(geojson_template_file_path)

                    # Iterate over source files
                    for source_file in file.source_files or []:
                        source_file_path = os.path.join(
                            source_path, input_port.id, source_file.source_file_name
                        )

                        # Load statistics
                        csv_statistics = load_csv_file(source_file_path)

                        if (
                            file.target_file_name is not None
                            and file.geojson_template_file_name is not None
                        ):
                            # Iterate over features
                            for feature in sorted(
                                geojson["features"],
                                key=lambda feature: feature["properties"]["id"],
                            ):
                                id = feature["properties"]["id"]
                                area_sqm = feature["properties"]["area"]
                                area_sqkm = area_sqm / 1_000_000

                                population = 0
                                if file.population_file_name is not None:
                                    csv_population_dataframe = load_csv_file(
                                        os.path.join(source_path, file.population_file_name)
                                    )
                                    population = csv_population_dataframe \
                                    .loc[csv_population_dataframe["id"] == id] \
                                    .iloc[0]["inhabitants"]

                                # Build statistics structure
                                if id not in json_statistics[year][half_year]:
                                    json_statistics[year][half_year][id] = {}

                                # Filter statistics
                                statistic_filtered = csv_statistics[
                                    csv_statistics["id"].astype(str) == str(id)
                                ]

                                # Add ID and name attribute
                                json_statistics[year][half_year][id]["id"] = id
                                json_statistics[year][half_year][id]["name"] = (
                                    feature["properties"]["name"]
                                    if "name" in feature["properties"]
                                    else id
                                )

                                # Iterate over attributes
                                for attribute in source_file.attributes:
                                    if (
                                        attribute.name in statistic_filtered
                                        and len(statistic_filtered[attribute.name]) > 0
                                    ):
                                        # Look up value
                                        value = statistic_filtered[attribute.name].iloc[
                                            0
                                        ]

                                        try:
                                            # Convert value to float or int
                                            value = (
                                                float(value)
                                                if "." in str(value)
                                                else int(value)
                                            )
                                        except:
                                            pass
                                    elif (
                                        attribute.numerator in statistic_filtered
                                        and len(statistic_filtered[attribute.numerator])
                                        > 0
                                        and attribute.denominator_area_sqkm
                                    ):
                                        # Look up value
                                        value = statistic_filtered[
                                            attribute.numerator
                                        ].iloc[0]

                                        try:
                                            # Convert value to float or int
                                            value = (
                                                float(value)
                                                if "." in str(value)
                                                else int(value)
                                            )

                                            # Divide value by area in sqkm
                                            value /= area_sqkm
                                        except:
                                            pass
                                    elif (
                                        attribute.numerator in statistic_filtered
                                        and len(statistic_filtered[attribute.numerator])
                                        > 0
                                        and attribute.denominator_inhabitants
                                        and population != 0
                                    ):
                                        # Look up value
                                        value = statistic_filtered[
                                            attribute.numerator
                                        ].iloc[0]

                                        try:
                                            # Convert value to float or int
                                            value = (
                                                float(value)
                                                if "." in str(value)
                                                else int(value)
                                            )

                                            # Divide value by population
                                            value /= population
                                        except:
                                            pass
                                    else:
                                        continue

                                    try:
                                        # Convert value to float or int
                                        value = (
                                            float(value)
                                            if "." in str(value)
                                            else int(value)
                                        )

                                        feature["properties"][
                                            f"{source_file.source_file_prefix}{attribute.name}"
                                        ] = value
                                        json_statistics[year][half_year][id][
                                            f"{source_file.source_file_prefix}{attribute.name}"
                                        ] = value
                                    except:
                                        pass

                    # Save target geojson
                    if clean or not os.path.exists(target_file_path):
                        os.makedirs(os.path.dirname(target_file_path), exist_ok=True)
                        with open(
                            target_file_path, "w", encoding="utf-8"
                        ) as geojson_file:
                            json.dump(geojson, geojson_file, ensure_ascii=False)
                            converted += 1

                            not quiet and print(
                                f"✓ Convert {os.path.basename(target_file_path)}"
                            )
                    else:
                        already_exists += 1
                        not quiet and print(
                            f"✓ Already exists {os.path.basename(target_file_path)}"
                        )
                        continue

                except Exception as e:
                    exception += 1
                    not quiet and print(f"✗️ Exception: {str(e)}")

        # Save statistics
        if clean or not os.path.exists(statistics_file_path):
            os.makedirs(os.path.dirname(statistics_file_path), exist_ok=True)
            with open(statistics_file_path, "w", encoding="utf-8") as json_file:
                json.dump(json_statistics, json_file, ensure_ascii=False)
                converted += 1
                not quiet and print(
                    f"✓ Aggregate statistics {os.path.basename(statistics_file_path)}"
                )
        else:
            already_exists += 1
            not quiet and print(
                f"✓ Already exists {os.path.basename(statistics_file_path)}"
            )

    print(
        f"blend_data finished with already_exists: {already_exists}, converted: {converted}, exception: {exception}"
    )


def load_geojson_file(geojson_template_file_path):
    with open(
        file=geojson_template_file_path, mode="r", encoding="utf-8"
    ) as geojson_file:
        geojson = json.load(geojson_file, strict=False)
        return geojson


def load_csv_file(source_file_path):
    with open(source_file_path, "r") as csv_file:
        csv = pd.read_csv(csv_file, dtype=str)
        return csv
