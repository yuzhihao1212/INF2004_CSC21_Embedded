$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../../../..").Path
Push-Location $root
try {
    $s3 = 'node/app_program/subsystem3'
    $hostTests = 'node/testing/subsystem3/host'
    $exe = Join-Path $env:TEMP 'mosaic-s3-host-tests.exe'
    function Run-Test([string[]]$sources) {
        & gcc -std=c11 -Wall -Wextra -Werror -I $s3 -I node/app_program/subsystem5 @sources -o $exe
        if ($LASTEXITCODE -ne 0) { throw "Host compile failed: $LASTEXITCODE" }
        & $exe
        if ($LASTEXITCODE -ne 0) { throw "Host test failed: $LASTEXITCODE" }
    }
    Run-Test @("$s3/environment.c", "$hostTests/environment_host_test.c")
    Run-Test @("$s3/environment.c", "$s3/acd1100_protocol.c", "$hostTests/acd1100_host_test.c")
    Run-Test @("$s3/environment.c", "$s3/s3_telemetry.c", 'node/app_program/subsystem5/s5_protocol.c', "$hostTests/s5_environment_host_test.c")
    & gcc -std=c11 -Wall -Wextra -Werror -include "$hostTests/utk_mock.h" -I $s3 -I node/app_program/subsystem5 "$s3/environment.c" "$s3/acd1100_protocol.c" "$s3/drv_acd1100.c" "$s3/drv_dht22.c" "$s3/s3_telemetry.c" "$s3/environment_service.c" "$s3/task_environment.c" "$hostTests/service_host_test.c" -o $exe
    if ($LASTEXITCODE -ne 0) { throw 'Service test compile failed' }
    & $exe
    if ($LASTEXITCODE -ne 0) { throw 'Service test failed' }
    & gcc -std=c11 -Wall -Wextra -Werror -include "$hostTests/utk_mock.h" -I "$hostTests/registers" -I $s3 "$s3/drv_uart1.c" "$hostTests/uart_register_host_test.c" -o $exe
    if ($LASTEXITCODE -ne 0) { throw 'UART register test compile failed' }
    & $exe
    if ($LASTEXITCODE -ne 0) { throw 'UART register test failed' }
    & gcc -std=c11 -Wall -Wextra -Werror -include "$hostTests/startup_mock.h" -I $s3 "$s3/subsystem3.c" "$hostTests/startup_host_test.c" -o $exe
    if ($LASTEXITCODE -ne 0) { throw 'Startup test compile failed' }
    foreach ($scenario in 'success','consumer-create','consumer-start','environment-create','environment-start') {
        & $exe $scenario
        if ($LASTEXITCODE -ne 0) { throw "Startup test failed: $scenario" }
    }
    & gcc -std=gnu11 -Wall -Wextra -Werror -DTM_WIFI_CYW43=1 -I "$hostTests/sdk_mock" -I $s3 "$s3/drv_dht22_hw.c" "$hostTests/dht_hw_host_test.c" -o $exe
    if ($LASTEXITCODE -ne 0) { throw 'DHT hardware-boundary test compile failed' }
    & $exe
    if ($LASTEXITCODE -ne 0) { throw 'DHT hardware-boundary test failed' }
} finally { Pop-Location }
