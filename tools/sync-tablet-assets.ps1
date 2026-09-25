param(
    [string]$TabletRoot = (Join-Path $PSScriptRoot '..'),
    [string]$RendererRoot = (Join-Path $PSScriptRoot '..\desktop\renderer')
)

$ErrorActionPreference = 'Stop'
$tablet = (Resolve-Path -LiteralPath $TabletRoot).ProviderPath
$renderer = (Resolve-Path -LiteralPath $RendererRoot).ProviderPath
$views = Join-Path $tablet 'app\src\main\assets\pine-views'
$sampler = Join-Path $tablet 'app\src\main\assets\pine-sampler'
if (-not (Test-Path -LiteralPath $views) -or -not (Test-Path -LiteralPath $sampler)) {
    throw 'Tablet asset directories are missing.'
}

$copied = 0
Get-ChildItem -LiteralPath $views -File | ForEach-Object {
    if ($_.Name -eq 'talk-dot.js') { return }
    $source = Join-Path $renderer $_.Name
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $_.FullName
        $copied++
    }
}
foreach ($name in @('sfx-tv.js', 'sfx-tv.css', 'sampler-air.js',
                   'sampler-feed.js', 'sampler.js')) {
    $source = Join-Path $renderer $name
    $target = Join-Path $sampler $name
    if ((Test-Path -LiteralPath $source) -and (Test-Path -LiteralPath $target)) {
        Copy-Item -LiteralPath $source -Destination $target
        $copied++
    }
}

foreach ($name in @('sfx-tv.js', 'sfx-tv.css')) {
    $panelHash = (Get-FileHash -LiteralPath (Join-Path $views $name) -Algorithm SHA256).Hash
    $samplerHash = (Get-FileHash -LiteralPath (Join-Path $sampler $name) -Algorithm SHA256).Hash
    if ($panelHash -ne $samplerHash) {
        throw "Panel and sampler differ for $name."
    }
}
$scriptHash = (Get-FileHash -LiteralPath (Join-Path $views 'script-page.js') -Algorithm SHA256).Hash
$sourceHash = (Get-FileHash -LiteralPath (Join-Path $renderer 'script-page.js') -Algorithm SHA256).Hash
if ($scriptHash -ne $sourceHash) {
    throw 'The tablet script view is not the canonical renderer copy.'
}
Write-Output "Synced $copied tablet assets from $renderer"
