from pathlib import Path
from taskManager import OpenFOAMCaseGenerator

# ============================
# USER SETTINGS
# ============================
N_CASES_TO_MESH = 4  # How many cases to mesh in this run
N_PARALLEL_WORKERS = 4  # How many meshing operations simultaneously
AUTO_SUBMIT = True  # Automatically copy and submit after meshing

# ============================
# MAIN
# ============================
if __name__ == "__main__":
    generator = OpenFOAMCaseGenerator(
        template_path="/home/sourav/CFD_Dataset/openfoam_caseGenerator/template",
        input_dir="/home/sourav/CFD_Dataset/generateInputs/Data_test/downloads",
        output_dir="/home/sourav/CFD_Dataset/openFoamCases",
        deucalion_path="/projects/EEHPC-BEN-2026B02-011/cfd_data"
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
            if len(cases_to_mesh) >= N_CASES_TO_MESH:
                break

    if not cases_to_mesh:
        print("No cases need meshing.")
    else:
        print(f"Meshing {len(cases_to_mesh)} cases with {N_PARALLEL_WORKERS} workers...")
        
        # Parallel meshing
        generator.mesh_cases_parallel(cases_to_mesh, n_workers=N_PARALLEL_WORKERS)

        # Auto-submit if enabled
        if AUTO_SUBMIT:
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