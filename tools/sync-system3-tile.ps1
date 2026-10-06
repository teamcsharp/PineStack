param(
    [string]$ProjectRoot = (Join-Path $PSScriptRoot '..'),
    [string]$RendererRoot = (Join-Path $PSScriptRoot '..\desktop\renderer')
)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath $ProjectRoot).ProviderPath
$renderer = (Resolve-Path -LiteralPath $RendererRoot).ProviderPath
$destinations = @('app\src\main\assets\pine-views', 'frontend', 'desktop\station-tools')
foreach ($relative in $destinations) {
    $directory = Join-Path $project $relative
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        throw "Shared tile asset directory is missing: $directory"
    }
}
foreach ($name in @('system3-message-tile.js', 'system3-message-tile.css')) {
    $source = Join-Path $renderer $name
    $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    foreach ($relative in $destinations) {
        $destination = Join-Path (Join-Path $project $relative) $name
        Copy-Item -LiteralPath $source -Destination $destination -Force
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $sourceHash) {
            throw "Shared tile copy differs: $destination"
        }
    }
}
Write-Output 'Synced canonical System3 tile JS/CSS to tablet, Messenger and desktop tools.'
