from taskManager import OpenFOAMCaseGenerator

generator = OpenFOAMCaseGenerator(
    template_path="/home/sourav/1_CFD_Dataset/openfoam_caseGenerator/template",
    input_dir="/home/sourav/1_CFD_Dataset/generateInputs/Data/downloads",
    output_dir="/home/sourav/1_CFD_Dataset/1_Data"
)

generator.generate_all_cases()