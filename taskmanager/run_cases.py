import argparse

from .config_utils import load_runtime_config, required_path
from .taskmanager import OpenFOAMCaseGenerator


def build_parser():
    parser = argparse.ArgumentParser(
        description="Mesh generated cases locally and optionally submit to HPC."
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="Optional path to YAML config file (default: packaged taskmanager config).",
    )
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    config, _ = load_runtime_config(args.config_path)

    run_settings = config.get("run_cases", {})
    n_cases_to_mesh = run_settings.get("n_cases_to_mesh", 4)
    n_parallel_workers = run_settings.get("n_parallel_workers", 4)
    auto_submit = run_settings.get("auto_submit", True)

    generator = OpenFOAMCaseGenerator(
        template_path=required_path(config, "template_path"),
        input_dir=required_path(config, "input_dir"),
        output_dir=required_path(config, "output_dir"),
        config_path=args.config_path,
    )

    print("\n" + "="*60)
    print("Checking for meshed cases pending copy/submission...")
    print("="*60 + "\n")

    ready_cases = generator.list_ready_cases()
    for case in ready_cases:
        print(f"Retrying copy/submission: {case.name}")
        generator.copy_and_submit(case)

    # Find cases that need meshing
    all_cases = sorted(generator.output_dir.iterdir())
    cases_to_mesh = []

    for case in all_cases:
        if not case.is_dir():
            continue

        status = generator.get_status(case)
        if status and status["mesh_status"] == "NOT_RUN":
            cases_to_mesh.append(case)
            if len(cases_to_mesh) >= n_cases_to_mesh:
                break

    if not cases_to_mesh:
        print("No cases need meshing.")
    else:
        print(f"Meshing {len(cases_to_mesh)} cases with {n_parallel_workers} workers...")

        # Parallel meshing
        generator.mesh_cases_parallel(cases_to_mesh, n_workers=n_parallel_workers)

        # Auto-submit if enabled
        if auto_submit:
            print("\n" + "="*60)
            print("Auto-submission enabled")
            print("="*60 + "\n")

            ready_cases = generator.list_ready_cases()
            for case in ready_cases:
                generator.copy_and_submit(case)

    # Report status
    print("\n" + "="*60)
    print("STATUS SUMMARY")
    print("="*60)

    ready = generator.list_ready_cases()
    print(f"✓ Ready for submission: {len(ready)}")

    failed = generator.list_failed_cases()
    if failed:
        print(f"✗ Failed meshing (needs manual intervention):")
        for case in failed:
            print(f"  - {case.name}")

    # Show submitted jobs
    submitted_cases = generator.list_cases_by_status(submitted=True)
    if submitted_cases:
        print(f"\n→ Submitted jobs: {len(submitted_cases)}")
        for case in submitted_cases:
            status = generator.get_status(case)
            job_id = status.get("job_id", "N/A")
            job_status = status.get("job_status", "N/A")
            print(f"  - {case.name}: Job {job_id} [{job_status}]")

    print("="*60)