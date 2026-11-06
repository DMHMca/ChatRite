# ChatRite Surface check. Run on the Surface Pro. It only reads information and tries a few installs
# inside a temporary folder (%TEMP%\chatrite-surface-check). It does not touch anything else.
# Result is saved to the Desktop as chatrite-surface-report.txt
$ErrorActionPreference = "Continue"
$report = Join-Path ([Environment]::GetFolderPath("Desktop")) "chatrite-surface-report.txt"
$work = Join-Path $env:TEMP "chatrite-surface-check"
New-Item -ItemType Directory -Force $work | Out-Null
$out = New-Object System.Collections.Generic.List[string]
function Add($t) { $out.Add($t); Write-Host $t }

Add "ChatRite Surface check, $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
Add "--- machine"
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
Add "CPU: $($cpu.Name)  cores=$($cpu.NumberOfCores) threads=$($cpu.NumberOfLogicalProcessors)"
Add "Architecture (PROCESSOR_ARCHITECTURE): $env:PROCESSOR_ARCHITECTURE   (real chip: $env:PROCESSOR_ARCHITEW6432)"
Add "Windows: $((Get-CimInstance Win32_OperatingSystem).Caption) build $((Get-CimInstance Win32_OperatingSystem).BuildNumber)"
Add "RAM GB: $([math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1))"
Add "--- NPU / drivers"
Get-PnpDevice -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match 'NPU|Hexagon|Neural|AI Boost' } | ForEach-Object { Add "$($_.FriendlyName)  [$($_.Status)]" }
Add "--- Python"
$found = @()
foreach ($c in @("py -0p", "where.exe python", "where.exe py")) { try { $r = cmd /c "$c 2>&1"; Add "> $c"; $r | ForEach-Object { Add "  $_" } } catch {} }
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($py) {
  Add "python = $py"
  Add (& python -c "import platform,struct,sys;print('python',sys.version.split()[0],platform.machine(),str(struct.calcsize('P')*8)+'-bit')" 2>&1 | Out-String).Trim()
} else { Add "No 'python' on the PATH." }
Add "--- tools"
foreach ($t in "winget","curl.exe","git") { Add ("$t : " + ((Get-Command $t -ErrorAction SilentlyContinue).Source)) }
Add "--- microphone devices"
Get-PnpDevice -Class AudioEndpoint -Status OK -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match 'Mic|Array' } | ForEach-Object { Add $_.FriendlyName }

if ($py) {
  Add "--- pip trials (in a temporary virtual environment)"
  $venv = Join-Path $work "venv"
  & python -m venv $venv 2>&1 | Out-Null
  $vp = Join-Path $venv "Scripts\python.exe"
  if (Test-Path $vp) {
    & $vp -m pip install --upgrade pip 2>&1 | Out-Null
    foreach ($pkg in "numpy","sounddevice","pystray","keyboard","onnxruntime","onnxruntime-qnn","faster-whisper","ctranslate2","huggingface_hub") {
      $r = & $vp -m pip install --only-binary=:all: $pkg 2>&1 | Select-Object -Last 2 | Out-String
      $ok = ($LASTEXITCODE -eq 0)
      Add ("{0,-18} {1}" -f $pkg, $(if ($ok) { "installs" } else { "FAILED: " + $r.Trim().Replace("`r`n"," ") }))
    }
    Add "--- ONNX Runtime providers"
    Add (& $vp -c "import onnxruntime as o;print(o.__version__, o.get_available_providers())" 2>&1 | Out-String).Trim()
  } else { Add "Could not create a virtual environment." }
}
$out | Set-Content -Path $report -Encoding utf8
Write-Host ""
Write-Host "Done. The report is on your Desktop: chatrite-surface-report.txt" -ForegroundColor Cyan
