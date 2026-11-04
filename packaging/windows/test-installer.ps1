# Exercise the actual Inno installer, selected dependencies, upgrade and removal.
$ErrorActionPreference = 'Stop'
$repository = Split-Path (Split-Path $PSScriptRoot)
$installer = (Get-ChildItem "$repository/dist/*-setup.exe" | Select-Object -First 1).FullName
$logs = "$repository/dist/windows-test-logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$destination = Join-Path $env:RUNNER_TEMP 'EXHALE installer test with spaces'
$sentinel = Join-Path $env:RUNNER_TEMP 'exhale-project-preservation.txt'
Set-Content $sentinel 'User project data'

foreach ($selection in @('none', 'stardist', 'cellpose', 'both')) {
    $components = switch ($selection) {
        'none' { 'core' }
        'stardist' { 'core,stardist' }
        'cellpose' { 'core,cellpose' }
        'both' { 'core,stardist,cellpose' }
    }
    $process = Start-Process -FilePath $installer -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCANCEL',
        "/DIR=`"$destination`"", "/COMPONENTS=$components", "/LOG=`"$logs/$selection-setup.log`""
    ) -Wait -PassThru
    if (Test-Path "$destination/runtime.log") {
        Copy-Item "$destination/runtime.log" "$logs/$selection-runtime.log" -Force
    }
    if ($process.ExitCode -ne 0) { throw "Installer failed for $selection (exit $($process.ExitCode))" }
    $state = Get-Content "$destination/runtime/installed.json" | ConvertFrom-Json
    if ($state.backends -ne $selection) { throw "Incorrect backend selection: $($state.backends)" }
    if ((Get-ChildItem "$destination/runtime/env-*" -Directory).Count -ne 1) {
        throw 'Upgrade left multiple active environments'
    }
    $python = "$destination/runtime/$($state.environment)/Scripts/python.exe"
    $code = @'
import importlib.util, sys
selection = sys.argv[1]
assert (importlib.util.find_spec('tensorflow') is not None) == (selection in ('stardist', 'both'))
assert (importlib.util.find_spec('torch') is not None) == (selection in ('cellpose', 'both'))
assert (importlib.util.find_spec('dinov3') is not None) == (selection in ('cellpose', 'both'))
'@
    & $python -c $code $selection
    if ($LASTEXITCODE -ne 0) { throw "Unexpected dependencies for $selection" }
    $check = Start-Process "$destination/exhale.exe" -ArgumentList '--startup-check' -Wait -PassThru
    Copy-Item "$destination/runtime.log" "$logs/$selection-runtime.log" -Force
    if ($check.ExitCode -ne 0) { throw "Installed launcher startup failed for $selection" }
}

# The uninstall entry removes the private runtime as well as installed shortcuts.
$uninstall = Start-Process "$destination/unins000.exe" -ArgumentList @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$logs/uninstall.log`""
) -Wait -PassThru
if ($uninstall.ExitCode -ne 0) { throw "Uninstall failed: $($uninstall.ExitCode)" }
if (Test-Path "$destination/runtime") { throw 'Uninstall left the private runtime behind' }
if (Test-Path "$destination/exhale.exe") { throw 'Uninstall left the launcher behind' }
if ((Get-Content $sentinel) -ne 'User project data') { throw 'Uninstall affected external data' }
Write-Output 'All Windows installer selections, upgrades, startup checks and uninstall passed.'
