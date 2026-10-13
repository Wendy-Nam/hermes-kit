# Native Windows bootstrap for machines without a suitable host Python.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'

$Tag = 'v0.21.7'
$Commit = '71d34bad1045610252eda02ee79549436896e784'
$InstallerSha256 = '61824d6b47be29ab793d0e72872cf56cd7a3e99cbe40abeb177a6c9eef52f485'
$InstallerUrl = "https://raw.githubusercontent.com/NousResearch/hermes-agent/$Commit/scripts/install.ps1"

function Fail([string]$Message) { throw "Hermes Outbound bootstrap: $Message" }
function Test-PlainFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    return -not ((Get-Item -LiteralPath $Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)
}
if (-not $env:LOCALAPPDATA) { Fail 'LOCALAPPDATA가 없어 기본 설치 경로를 정할 수 없습니다.' }
$KitRoot = $PSScriptRoot
$Start = Join-Path $KitRoot 'start.py'
$Config = Join-Path $KitRoot 'setup.json'
if (-not (Test-Path -LiteralPath $Start -PathType Leaf)) { Fail 'start.py가 없습니다. 키트 ZIP을 다시 받아 압축을 완전히 푸세요.' }
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) { Fail 'setup.json이 없습니다. 키트 설정을 먼저 생성해 같은 폴더에 두세요.' }

$HermesHome = Join-Path $env:LOCALAPPDATA 'hermes-outbound'
$InstallDir = Join-Path $HermesHome 'hermes-agent'
$ToolsDir = Join-Path $HermesHome 'tools'
$Marker = Join-Path $InstallDir '.hermes-bootstrap-complete'
$Facts = Join-Path $ToolsDir 'facts.json'

$Mode = (Read-Host '사용 화면 app(기본, Hermes Desktop) / terminal').Trim().ToLowerInvariant()
if (-not $Mode) { $Mode = 'app' }
if ($Mode -notin @('app', 'terminal')) { Fail 'app 또는 terminal만 입력하세요.' }

function Get-ManagedPython {
    if (-not (Test-PlainFile $Facts)) { return $null }
    try { $data = Get-Content -LiteralPath $Facts -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { return $null }
    $entry = [string]$data.packages.python.entry
    if (-not $entry -or [IO.Path]::IsPathRooted($entry) -or $entry -notmatch '^[A-Za-z0-9._/\\-]+$') { return $null }
    if (($entry -split '[/\\]') -contains '..') { return $null }
    $candidate = Join-Path (Join-Path $ToolsDir $entry) 'python.exe'
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $null }
    $resolvedTools = [IO.Path]::GetFullPath($ToolsDir).TrimEnd('\') + '\'
    $resolved = [IO.Path]::GetFullPath($candidate)
    if (-not $resolved.StartsWith($resolvedTools, [StringComparison]::OrdinalIgnoreCase)) { return $null }
    return $resolved
}

function Test-Marker {
    if (-not (Test-PlainFile $Marker)) { return $false }
    try { $data = Get-Content -LiteralPath $Marker -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { return $false }
    return ([string]$data.pinnedCommit -eq $Commit)
}

function Test-DesktopPresent {
    $release = Join-Path $InstallDir 'apps\desktop\release'
    foreach ($folder in @('win-unpacked', 'win-ia32-unpacked', 'win-arm64-unpacked')) {
        if (Test-Path -LiteralPath (Join-Path (Join-Path $release $folder) 'Hermes.exe') -PathType Leaf) { return $true }
    }
    return $false
}

$ManagedPython = $null
if (Test-Path -LiteralPath $InstallDir) {
    if (-not (Test-Path -LiteralPath (Join-Path $InstallDir '.git') -PathType Container)) {
        Fail "기존 $InstallDir 은 공식 scoped checkout으로 확인되지 않아 보존했습니다. 새 home을 검토하세요."
    }
    if (-not (Test-Marker)) { Fail '기존 scoped checkout의 pinned commit 증거가 다릅니다. 자동 reset하지 않았습니다.' }
    $ManagedPython = Get-ManagedPython
    if (-not $ManagedPython) { Fail '기존 scoped checkout의 PM facts/runtime이 불완전합니다. 자동 재설치하지 않았습니다.' }
    if ($Mode -eq 'app' -and -not (Test-DesktopPresent)) {
        Fail '기존 scoped 설치에 Hermes Desktop 산출물이 없습니다. terminal을 선택하면 기존 runtime을 재사용합니다. 자동 reset/build하지 않았습니다.'
    }
    Write-Host "검증된 기존 Hermes runtime을 재사용합니다: $InstallDir"
} else {
    $globalHermes = Get-Command hermes -ErrorAction SilentlyContinue
    if ($globalHermes) { Write-Host "기존 전역 Hermes는 사용하거나 덮어쓰지 않습니다: $($globalHermes.Source)" }
    $temporary = Join-Path ([IO.Path]::GetTempPath()) ("hermes-outbound-bootstrap-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temporary | Out-Null
    try {
        $artifact = Join-Path $temporary "hermes-install-$Tag.ps1"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $InstallerUrl -OutFile $artifact
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifact).Hash.ToLowerInvariant()
        if ($actual -ne $InstallerSha256) { Fail 'installer SHA-256이 검토값과 다릅니다. 실행하지 않았습니다.' }
        New-Item -ItemType Directory -Force -Path $HermesHome | Out-Null
        $env:HERMES_HOME = $HermesHome
        $env:HERMES_RUNTIME_DIR = $ToolsDir
        $installerArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $artifact,
            '-Branch', 'main', '-Commit', $Commit, '-HermesHome', $HermesHome,
            '-InstallDir', $InstallDir, '-NonInteractive', '-SkipBrowser', '-SkipComputerUse')
        if ($Mode -eq 'app') { $installerArgs += '-IncludeDesktop' }
        $powerShellExe = (Get-Process -Id $PID).Path
        & $powerShellExe @installerArgs
        if ($LASTEXITCODE -ne 0) { Fail "공식 Hermes installer가 실패했습니다 (exit $LASTEXITCODE)." }
        if (-not (Test-Marker)) { Fail '설치 완료 marker의 pinned commit을 확인하지 못했습니다.' }
        $ManagedPython = Get-ManagedPython
        if (-not $ManagedPython) { Fail '설치된 PM facts에서 managed Python을 확인하지 못했습니다.' }
        if ($Mode -eq 'app' -and -not (Test-DesktopPresent)) { Fail 'installer는 성공했지만 Hermes Desktop 산출물을 확인하지 못했습니다.' }
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
    }
}

$env:HERMES_HOME = $HermesHome
$env:HERMES_RUNTIME_DIR = $ToolsDir
& $ManagedPython -P $Start --config $Config
exit $LASTEXITCODE
