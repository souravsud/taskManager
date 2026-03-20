import argparse
from pathlib import Path

from .config_utils import get_path_value, load_runtime_config
from .taskmanager import OpenFOAMCaseGenerator


def build_parser():
    parser = argparse.ArgumentParser(
        description="Generate OpenFOAM cases from template and metadata inputs."
    )
    parser.add_argument(
        "--config-path",
        default="taskmanager_config.yaml",
        help="Path to YAML config file (default: taskmanager_config.yaml).",
    )
    parser.add_argument(
        "--template-path",
        default=None,
        help="Optional override for paths.template_path from config.",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Optional override for paths.input_dir from config.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional override for paths.output_dir from config.",
    )
    parser.add_argument(
        "--cluster-path",
        default=None,
        help="Optional remote HPC cluster path used later for copy/submission workflows.",
    )
    return parser


def run_generate_cases(template_path, input_dir, output_dir, cluster_path=None):
    generator = OpenFOAMCaseGenerator(
        template_path=template_path,
        input_dir=input_dir,
        output_dir=output_dir,
        cluster_path=cluster_path,
    )
    generator.generate_all_cases()


def main(argv=None):
    args = build_parser().parse_args(argv)

    config, _ = load_runtime_config(args.config_path)

    template_path = get_path_value(args.template_path, config, "template_path")
    input_dir = get_path_value(args.input_dir, config, "input_dir")
    output_dir = get_path_value(args.output_dir, config, "output_dir")

    cluster_path = args.cluster_path
    if cluster_path is None:
        cluster_path = (
            config.get("cluster", {}).get("remote_base_path")
            or config.get("deucalion", {}).get("remote_base_path")
        )

    run_generate_cases(
        template_path=str(Path(template_path).expanduser()),
        input_dir=str(Path(input_dir).expanduser()),
        output_dir=str(Path(output_dir).expanduser()),
        cluster_path=cluster_path,
    )


if __name__ == "__main__":
    main()