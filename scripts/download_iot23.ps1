param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\data\iot23\CTU-IoT-Malware-Capture-34-1')
)

$ErrorActionPreference = 'Stop'
$target = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $target -Force | Out-Null
$base = 'https://mcfp.felk.cvut.cz/publicDatasets/IoT-23-Dataset/IndividualScenarios/CTU-IoT-Malware-Capture-34-1'
$files = @(
    @{ Name = 'conn.log.labeled'; Uri = "$base/bro/conn.log.labeled" },
    @{ Name = 'README.source.md'; Uri = "$base/README.md" }
)
$records = @()
foreach ($file in $files) {
    $path = Join-Path $target $file.Name
    if (-not (Test-Path -LiteralPath $path)) {
        $partial = "$path.partial"
        Invoke-WebRequest -UseBasicParsing -Uri $file.Uri -OutFile $partial
        Move-Item -LiteralPath $partial -Destination $path
    }
    $checksum = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($file.Name -eq 'conn.log.labeled' -and $checksum -ne 'd69e49b2aae8c1bd33286936531658202dec47d989f0439bad3f8be180467a6e') {
        throw 'conn.log.labeled differs from the snapshot verified on 2026-10-08; inspect the file before proceeding.'
    }
    $records += @{
        file = $file.Name
        source_url = $file.Uri
        bytes = (Get-Item -LiteralPath $path).Length
        sha256 = $checksum
    }
}
$manifest = @{
    dataset = 'IoT-23'
    scenario = 'CTU-IoT-Malware-Capture-34-1'
    recorded_at_utc = [DateTime]::UtcNow.ToString('o')
    files = $records
    downloaded_pcap = $false
    downloaded_malware = $false
    checksum_note = 'Locally observed SHA256 of the public file; not an upstream digital signature.'
    usage_note = 'Review dataset license and README.source.md before redistribution or publication.'
}
$json = $manifest | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText((Join-Path $target 'download_manifest.json'), $json, [System.Text.UTF8Encoding]::new($false))
Write-Output "IoT-23 labeled logs: $target"
