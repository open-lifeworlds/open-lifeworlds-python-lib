import json
import os
import warnings
from dataclasses import asdict

import yaml

from openlifeworlds.config.data_product_manifest_loader import File, QualityMetric
from openlifeworlds.tracking_decorator import TrackingDecorator

warnings.filterwarnings("ignore", category=UserWarning)


class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super(IndentDumper, self).increase_indent(flow, False)


@TrackingDecorator.track_time
def generate_geojson_property_completeness_metrics(
    data_product_manifest, config_path, data_transformation, results_path
):
    data_product_manifest_path = os.path.join(config_path, "data-product-manifest.yml")

    files = []

    for input_port_group in data_transformation.input_port_groups or []:
        for input_port in input_port_group.input_ports or []:
            for file in input_port.files or []:
                target_file_path = os.path.join(
                    results_path,
                    f"{input_port_group.id}-geojson",
                    file.target_file_name,
                )

                # Load geojson
                with open(
                    file=target_file_path, mode="r", encoding="utf-8"
                ) as geojson_file:
                    geojson = json.load(geojson_file, strict=False)

                    count = 0
                    count_all = 0

                    for source_file in file.source_files or []:
                        count_all += len(geojson["features"])

                        for feature in geojson["features"]:
                            if all(
                                f"{source_file.source_file_prefix}{property.name}"
                                in feature["properties"]
                                for property in source_file.attributes
                            ):
                                count += 1

                    files.append(
                        File(
                            name=file.target_file_name,
                            value=round((count / count_all * 100)),
                        )
                    )

                    print(
                        f"{str(count).rjust(4)} / {str(count_all).rjust(4)} ({str(round((count / count_all * 100))).rjust(3)}%) {file.target_file_name}"
                    )

    # Create the observability section if it does not exist
    if data_product_manifest.observability.quality is None:
        data_product_manifest.observability.quality = []

    # Remove existing metric if it exists
    data_product_manifest.observability.quality = list(
        filter(
            lambda metric: metric.name != "geojson_property_completeness",
            data_product_manifest.observability.quality,
        )
    )

    # Append the quality metric to the data product manifest
    data_product_manifest.observability.quality.append(
        QualityMetric(
            name="geojson_property_completeness",
            description="The percentage of geojson features that have all necessary properties",
            files=files,
        )
    )

    with open(data_product_manifest_path, "w") as file:
        yaml.dump(
            asdict(data_product_manifest),
            file,
            sort_keys=False,
            default_flow_style=False,
            Dumper=IndentDumper,
            allow_unicode=True,
            width=float("inf"),
            explicit_start=True,
        )
