import argparse
import sys
import time

from .config_utils import load_runtime_config, required_path
from .taskmanager import OpenFOAMCaseGenerator


def build_parser():
    parser = argparse.ArgumentParser(
        description="Monitor submitted HPC jobs and update local status files."
    )
    parser.add_argument(
        "--config-path",
        default="taskmanager_config.yaml",
        help="Path to YAML config file (default: taskmanager_config.yaml).",
    )
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    config, _ = load_runtime_config(args.config_path)

    monitor_settings = config.get("monitor_jobs", {})
    check_interval_minutes = monitor_settings.get("check_interval_minutes", 120)
    max_iterations = monitor_settings.get("max_iterations", None)

    generator = OpenFOAMCaseGenerator(
        template_path=required_path(config, "template_path"),
        input_dir=required_path(config, "input_dir"),
        output_dir=required_path(config, "output_dir"),
        config_path=args.config_path,
    )

    iteration = 0

    try:
        while True:
            iteration += 1
            print(f"\n{'='*60}")
            print(f"Job Status Check - Iteration {iteration}")
            print(f"{'='*60}\n")

            # Get all submitted cases
            submitted_cases = generator.list_cases_by_status(submitted=True)

            if not submitted_cases:
                print("No submitted jobs to monitor.")
            else:
                active_jobs = []
                completed_jobs = []
                failed_jobs = []

                for case in submitted_cases:
                    case_name = case.name
                    job_status = generator.update_job_status(case)

                    status_obj = generator.get_status(case)
                    job_id = status_obj.get("job_id", "N/A")

                    print(f"{case_name}: Job {job_id} -> {job_status}")

                    if job_status in ["PENDING", "RUNNING"]:
                        active_jobs.append((case_name, job_id, job_status))
                    elif job_status in ["COMPLETED"]:
                        completed_jobs.append((case_name, job_id))
                    elif job_status in ["FAILED", "CANCELLED", "TIMEOUT"]:
                        failed_jobs.append((case_name, job_id, job_status))

                # Summary
                print(f"\n--- Summary ---")
                print(f"Active: {len(active_jobs)}")
                print(f"Completed: {len(completed_jobs)}")
                print(f"Failed: {len(failed_jobs)}")

                if failed_jobs:
                    print(f"\n⚠️  Failed jobs (needs investigation):")
                    for case_name, job_id, status in failed_jobs:
                        print(f"  - {case_name}: Job {job_id} [{status}]")

            # Exit if max iterations reached
            if max_iterations and iteration >= max_iterations:
                print(f"\nReached max iterations ({max_iterations}). Exiting.")
                break

            # Sleep until next check
            print(f"\nNext check in {check_interval_minutes} minutes...")
            time.sleep(check_interval_minutes * 60)

    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user (Ctrl+C).")
        sys.exit(0)