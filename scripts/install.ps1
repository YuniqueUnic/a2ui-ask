<#
.SYNOPSIS
  Install the schemaui engine (schemaui-cli) on Windows — auto-detecting installer.

.DESCRIPTION
  Strategy order (auto mode):
    1. schemaui already on PATH          -> report and exit 0
    2. prebuilt zip from GitHub releases -> ~\AppData\Local\Programs\schemaui\bin
    3. the same asset from the Gitee mirror, when GitHub is unreachable
    4. cargo binstall schemaui-cli       -> prebuilt via cargo
    5. cargo install schemaui-cli        -> build from source

  Only the download step has a mirror: the scoop / winget / Homebrew manifests
  all point their download URLs at github.com, so they cannot serve a user who
  cannot reach it. -Source gitee is the way out for those users.

.EXAMPLE
  pwsh scripts/install.ps1                # auto install
  pwsh scripts/install.ps1 -DryRun        # show the plan only
  pwsh scripts/install.ps1 -Source gitee  # force the domestic mirror
#>
[CmdletBinding()]
param(
  [switch]$DryRun,
  [ValidateSet("auto", "download", "scoop", "cargo")]
  [string]$Method = "auto",
  [ValidateSet("auto", "github", "gitee")]
  [string]$Source = "auto",
  [string]$Dir = "$env:LOCALAPPDATA\Programs\schemaui\bin"
)

$ErrorActionPreference = "Stop"

$GitHubRepo = "YuniqueUnic/schemaui"
$GiteeRepo = "Credhat/schemaui"

function Say([string]$Msg)  { [Console]::WriteLine("[a2ui-ask install] $Msg") }
function Fail([string]$Msg) { [Console]::Error.WriteLine("[a2ui-ask install] ERROR: $Msg"); exit 1 }

# --- 0. already installed? -------------------------------------------------
$existing = Get-Command schemaui -ErrorAction SilentlyContinue
if ($existing) {
  Say "schemaui is already installed: $($existing.Source)"
  exit 0
}

# --- 1. detect platform ----------------------------------------------------
if ($PSVersionTable.Platform -and $PSVersionTable.Platform -ne "Win32NT") {
  Fail "install.ps1 is the Windows installer; on this platform use scripts/install.sh"
}
$arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLower()
switch ($arch) {
  "x64"   { $targetArch = "x86_64" }
  "arm64" { $targetArch = "aarch64" }
  default { Fail "unsupported architecture: $arch" }
}
$asset = "schemaui-$targetArch-pc-windows-msvc.zip"
Say "detected platform: $targetArch-pc-windows-msvc"

# --- 2. resolve the download URL(s) ----------------------------------------
# The repo publishes both library (schemaui-v*) and CLI (schemaui-cli-v*)
# releases; the prebuilt binaries live on the CLI ones.
function Get-NewestCliTag([string]$ReleasesApi) {
  # Chosen by version rather than by the order the API returned it: Gitee does
  # not list releases newest-first.
  try {
    $releases = Invoke-RestMethod -Uri $ReleasesApi -TimeoutSec 20
  } catch {
    return $null
  }
  $versions = @(
    $releases |
      ForEach-Object { $_.tag_name } |
      Where-Object { $_ -match "^schemaui-cli-v(\d+\.\d+\.\d+)$" } |
      ForEach-Object { [version]$Matches[1] } |
      Sort-Object
  )
  if ($versions.Count -eq 0) { return $null }
  return "schemaui-cli-v$($versions[-1])"
}

function Get-GitHubUrl {
  $tag = Get-NewestCliTag "https://api.github.com/repos/$GitHubRepo/releases?per_page=100"
  if ($tag) {
    return "https://github.com/$GitHubRepo/releases/download/$tag/$asset"
  }
  # GitHub's own shortcut for the newest release; needs no API call.
  return "https://github.com/$GitHubRepo/releases/latest/download/$asset"
}

function Get-GiteeUrl {
  $tag = Get-NewestCliTag "https://gitee.com/api/v5/repos/$GiteeRepo/releases?per_page=100"
  # Gitee has no /releases/latest/download shortcut, so a tag we could not
  # resolve leaves nothing to fall back to.
  if (-not $tag) { return $null }
  return "https://gitee.com/$GiteeRepo/releases/download/$tag/$asset"
}

$urls = @(
  switch ($Source) {
    "github" { Get-GitHubUrl }
    "gitee"  { Get-GiteeUrl }
    "auto"   { Get-GitHubUrl; Get-GiteeUrl }
  }
) | Where-Object { $_ }
if ($urls.Count -eq 0) { Fail "could not resolve a download URL for $asset" }
Say "asset: $asset"
foreach ($candidate in $urls) { Say "url:   $candidate" }

if ($DryRun) {
  Say "dry-run: would install schemaui ($targetArch-pc-windows-msvc) into $Dir via method=$Method"
  exit 0
}

# --- 3. install ------------------------------------------------------------
function Install-Download {
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ("a2ui-ask-install-" + [Guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  try {
    # Every candidate is a different host serving the same asset, so the first
    # one that yields a runnable binary wins.
    foreach ($candidate in $urls) {
      $origin = ([Uri]$candidate).Host
      Say "downloading prebuilt binary from $origin…"
      try {
        $zip = Join-Path $tmp $asset
        Invoke-WebRequest -Uri $candidate -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $bin = Get-ChildItem -Path $tmp -Recurse -Filter "schemaui.exe" | Select-Object -First 1
        if ($bin) {
          New-Item -ItemType Directory -Force -Path $Dir | Out-Null
          Copy-Item $bin.FullName (Join-Path $Dir "schemaui.exe") -Force
          return $true
        }
      } catch { }
      Say "  $origin did not work"
    }
    return $false
  } finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
  }
}

function Install-Scoop {
  if (-not (Get-Command scoop -ErrorAction SilentlyContinue)) { return $false }
  scoop install https://raw.githubusercontent.com/$GitHubRepo/main/packaging/scoop/schemaui-cli.json
  return ($LASTEXITCODE -eq 0)
}

function Install-Cargo {
  if (Get-Command cargo-binstall -ErrorAction SilentlyContinue) {
    cargo binstall schemaui-cli --no-confirm
  } elseif (Get-Command cargo -ErrorAction SilentlyContinue) {
    cargo install schemaui-cli
  } else {
    return $false
  }
  return ($LASTEXITCODE -eq 0)
}

$ok = $false
switch ($Method) {
  "download" { $ok = Install-Download }
  "scoop"    { $ok = Install-Scoop }
  "cargo"    { $ok = Install-Cargo }
  "auto"     { $ok = (Install-Download) -or (Install-Scoop) -or (Install-Cargo) }
}
if (-not $ok) { Fail "all methods failed. See install.md for manual options." }

# --- 4. verify + PATH ------------------------------------------------------
if (-not (Get-Command schemaui -ErrorAction SilentlyContinue)) {
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  if (($userPath -split ";") -notcontains $Dir) {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$Dir", "User")
    Say "added $Dir to your user PATH (restart the terminal to pick it up)"
  }
  $env:Path = "$env:Path;$Dir"
}
if (Get-Command schemaui -ErrorAction SilentlyContinue) {
  Say "installed: $((Get-Command schemaui).Source)"
} else {
  Fail "installation finished but schemaui is not runnable"
}
Say "done. Try: schemaui web --schema <schema.json> --port 8787 -o answer.json"
