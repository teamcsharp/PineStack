# The sampler's C++ contract, cross-compiled for the tablet and run on it.
#
# There is no host C++ compiler on this build box, so "run the tests" means
# build them for arm64 with the NDK the app already uses and execute them on
# the device over adb. They need no audio device and no app - the core is
# pure C++17 - so /data/local/tmp is enough.
#
#   powershell -File tests\run-on-device.ps1
$ErrorActionPreference = "Stop"
$adb   = "C:\_tools\platform-tools\adb.exe"
$cmake = "C:\_tools\android-sdk\cmake\3.22.1\bin\cmake.exe"
$cpp   = Split-Path -Parent $PSScriptRoot
$build = Join-Path $cpp "build-arm64"

if (-not (Test-Path (Join-Path $build "build.ninja"))) {
  & $cmake -S $cpp -B $build -G Ninja `
    "-DCMAKE_TOOLCHAIN_FILE=C:/_tools/android-sdk/ndk/26.1.10909125/build/cmake/android.toolchain.cmake" `
    "-DANDROID_ABI=arm64-v8a" "-DANDROID_PLATFORM=android-30" "-DPINEBOX_SAMPLER_TESTS=ON"
}

$names = @("test_window","test_voices","test_mixer","test_analysis",
           "test_footprint","test_sixteen_level","test_audio_format","test_duck")
& $cmake --build $build --target $names
& $adb shell mkdir -p /data/local/tmp/pbtest
$failures = 0
foreach ($n in $names) {
  & $adb push (Join-Path $build "tests\$n") /data/local/tmp/pbtest/ | Out-Null
  # push clears the executable bit, so chmod goes AFTER every push, not once.
  & $adb shell chmod 755 /data/local/tmp/pbtest/$n
  # NO 2>&1 here. Windows PowerShell 5.1 wraps a native process's stderr in
  # an ErrorRecord and fails the script even when the exit code is zero, so
  # redirecting it turns a passing suite into a scary red wall. The test
  # binaries print their summary on stdout; failures print there too.
  $out = (& $adb shell /data/local/tmp/pbtest/$n) -join "`n"
  $m = [regex]::Match($out, '(\d+) case\(s\), (\d+) failure')
  $bad = [regex]::Matches($out, 'FAIL (\w+)') | ForEach-Object { $_.Groups[1].Value }
  $failures += [int]$m.Groups[2].Value
  Write-Output ("{0,-20} {1,3} cases, {2} failures {3}" -f $n, $m.Groups[1].Value, $m.Groups[2].Value, ($bad -join ", "))
}
Write-Output "----"
if ($failures -gt 0) { Write-Output "$failures failure(s)"; exit 1 }
Write-Output "green"
