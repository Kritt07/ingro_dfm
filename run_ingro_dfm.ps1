## PowerShell script to launch Siemens NX and run the Ingro DFM extractor
# Save this file as `run_ingro_dfm.ps1` in the project root.
# It configures the PYTHONPATH so that the NX Open Python API can be imported
# and then starts NX with the extractor script.

# ---- Configuration ---------------------------------------------------------
$nxInstallPath = "C:\Program Files\Siemens\NX2506"
$nxExe = Join-Path $nxInstallPath "UGII.exe"
$scriptPath = "$(Resolve-Path .\nx_extractor_full.py)"

# Ensure the NX Open Python modules are on PYTHONPATH
$nxPythonPath = Join-Path $nxInstallPath "NXOpen\Python"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$env:PYTHONPATH;$nxPythonPath" } else { $nxPythonPath }

Write-Host "[Ingro DFM] PYTHONPATH set to: $env:PYTHONPATH"

# ---- Launch NX ------------------------------------------------------------
if (-Not (Test-Path $nxExe)) {
    Write-Error "NX executable not found at $nxExe. Check the installation path."
    exit 1
}

# Start NX and pass the script to be executed via the -batch option (if available).
# Some NX installations support the -batch flag: UGII.exe -batch -run <script>
# If -batch is not supported, the script can be run manually from inside NX.

Write-Host "[Ingro DFM] Starting Siemens NX..."
Start-Process -FilePath $nxExe -ArgumentList "-batch -run \"$scriptPath\"" -Wait

Write-Host "[Ingro DFM] NX process finished."
