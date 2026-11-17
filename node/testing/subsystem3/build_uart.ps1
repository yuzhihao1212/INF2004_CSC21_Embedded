param(
    [string]$ArmBin = 'C:/Program Files/Raspberry Pi/Pico SDK v1.5.1/gcc-arm-none-eabi/bin',
    [string]$MakeExe = 'C:/msys64/usr/bin/make.exe'
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../../..").Path
$savedPath = $env:PATH
$run = Get-Date -Format 'yyyyMMdd_HHmmss'
try {
    # Child-process lookup only; no persistent user/system environment changes.
    $env:PATH = "$ArmBin;$(Split-Path $MakeExe);$savedPath"
    Push-Location "$root/node/build_make"
    foreach ($smp in 0,1) {
        foreach ($test in 0,1) {
            $log = "$PSScriptRoot/logs/${run}_uart_smp${smp}_test${test}.txt"
            "HEAD $(git rev-parse HEAD), uncommitted working tree; no hardware run." | Out-File $log
            & $MakeExe CONSOLE=uart WIFI=none "SMP=$smp" "TEST=$test" -j4 >> $log 2>&1
            if ($LASTEXITCODE -ne 0) { throw "Build failed; see $log" }
            Write-Output "PASS cross-build SMP=$smp TEST=$test CONSOLE=uart WIFI=none; $log"
            Get-Content $log -Tail 4
        }
    }
} finally {
    Pop-Location
    $env:PATH = $savedPath
}
