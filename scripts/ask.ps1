<#
.SYNOPSIS
  Ask the user structured questions through a schemaui Web form.

.DESCRIPTION
  Same contract as ask.py / ask.sh, for Windows (and any
  PowerShell 7+ host): spawn `schemaui web --host 0.0.0.0`, print the form URL,
  open the user's browser, block until "Save & Exit", and leave the answer JSON
  under .schemaui/answers/.

  Stdout contract:
    SCHEMAUI_URL=http://127.0.0.1:8787/
    SCHEMAUI_LAN_URL=http://192.168.1.5:8787/   (only for wildcard hosts)
    SCHEMAUI_ANSWER=.schemaui/answers/<topic>-<timestamp>.json
    <answer JSON payload>                        (unless -StdoutEcho)
    SCHEMAUI_RESULT=<answer path>                (final line on success)

  Exit codes: 0 ok | 3 schemaui missing | 4 timeout | 5 session failed | 6 bad input

.EXAMPLE
  pwsh ask.ps1 -Schema ./question.json -Title "Deployment Config"

.EXAMPLE
  Get-Content schema.json -Raw | pwsh ask.ps1 -Schema - -Topic deploy-config
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$Schema,

  [string]$Config,
  [string]$Title,
  [string]$Description,
  [string]$Topic,
  [string]$Output,

  [Alias("Host")]
  [string]$BindHost = "0.0.0.0",

  [int]$Port = 8787,
  [int]$Timeout = 300,

  [switch]$NoOpen,
  [switch]$StdoutEcho,
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$EXIT_OK = 0
$EXIT_NO_BINARY = 3
$EXIT_TIMEOUT = 4
$EXIT_SESSION_FAILED = 5
$EXIT_BAD_INPUT = 6

function ConvertTo-Slug([string]$Text) {
  $slug = ($Text.ToLower() -replace "[^a-z0-9]+", "-").Trim("-")
  if ([string]::IsNullOrEmpty($slug)) { return "question" }
  return $slug
}

function ConvertTo-LocalUrl([string]$Url) {
  # http://0.0.0.0:8787/ -> http://127.0.0.1:8787/ (browsers need a concrete host)
  return $Url.Replace("://0.0.0.0", "://127.0.0.1").Replace("://[::]", "://127.0.0.1")
}

function Get-LanUrl([string]$Url) {
  if ($Url -notmatch "://(0\.0\.0\.0|\[::\])") { return $null }
  try {
    $udp = [System.Net.Sockets.UdpClient]::new()
    # TEST-NET-1 (RFC 5737); UDP Connect sends no traffic.
    $udp.Connect("192.0.2.1", 80)
    $lanIp = ($udp.Client.LocalEndPoint).Address.ToString()
    $udp.Dispose()
  } catch {
    return $null
  }
  return $Url.Replace("://0.0.0.0", "://$lanIp").Replace("://[::]", "://$lanIp")
}

function Quote-Arg([string]$Arg) {
  if ($Arg -match '[\s"]') { return '"' + ($Arg -replace '"', '\"') + '"' }
  return $Arg
}

function Open-Browser([string]$Url) {
  if ($NoOpen) { return }
  try {
    if ($IsWindows) { Start-Process $Url }
    elseif ($IsMacOS) { Start-Process "open" -ArgumentList $Url }
    else { Start-Process "xdg-open" -ArgumentList $Url }
  } catch {
    [Console]::WriteLine("could not auto-open a browser: $_")
  }
}

# --- validate inputs -------------------------------------------------------

$binary = $env:SCHEMAUI_BIN
if ($binary -and -not (Test-Path $binary)) {
  # allow a bare command name, not just a path
  $cmd = Get-Command $binary -ErrorAction SilentlyContinue
  $binary = if ($cmd) { $cmd.Source } else { $null }
}
if (-not $binary) {
  $cmd = Get-Command schemaui -ErrorAction SilentlyContinue
  if ($cmd) { $binary = $cmd.Source }
}
if (-not $binary) {
  [Console]::Error.WriteLine("schemaui binary not found (set SCHEMAUI_BIN or install schemaui-cli). Fall back to plain-text questions.")
  exit $EXIT_NO_BINARY
}

if ($Schema -eq "-") {
  $payload = [Console]::In.ReadToEnd()
  try { $null = $payload | ConvertFrom-Json } catch {
    [Console]::Error.WriteLine("invalid schema on stdin: $_. Fall back to plain-text questions.")
    exit $EXIT_BAD_INPUT
  }
} elseif (-not (Test-Path $Schema)) {
  [Console]::Error.WriteLine("schema file not found: $Schema. Fall back to plain-text questions.")
  exit $EXIT_BAD_INPUT
}
if ($Config -and -not (Test-Path $Config)) {
  [Console]::Error.WriteLine("config file not found: $Config")
  exit $EXIT_BAD_INPUT
}

if (-not $Topic) {
  if ($Title) { $Topic = $Title } else { $Topic = [IO.Path]::GetFileNameWithoutExtension($Schema) }
}
$slug = ConvertTo-Slug $Topic
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if ($Schema -eq "-") {
  $schemaDir = ".schemaui/schemas"
  New-Item -ItemType Directory -Force -Path $schemaDir | Out-Null
  $schemaFile = "$schemaDir/$slug-$stamp.json"
  [IO.File]::WriteAllText($schemaFile, $payload)
} else {
  $schemaFile = $Schema
}
if (-not $Output) { $Output = ".schemaui/answers/$slug-$stamp.json" }
New-Item -ItemType Directory -Force -Path (Split-Path $Output -Parent) | Out-Null

# --- session runner --------------------------------------------------------

function Invoke-SchemauiSession([int]$BindPort) {
  # Returns a hashtable: @{ Code = int; Announced = bool }
  # NOTE: `-o` is greedy (clap `num_args = 1..` + hyphen values): it swallows
  # every following token, including later flags. Every other flag comes before
  # the single trailing `-o`; extra destinations follow it space-separated.
  $argList = @("web", "--host", $BindHost, "--port", "$BindPort", "--schema", $schemaFile)
  if ($Config) { $argList += @("--config", $Config) }
  if ($Title) { $argList += @("--title", $Title) }
  if ($Description) { $argList += @("--description", $Description) }
  if ($Force) { $argList += "--force" }
  $argList += @("-o", $Output)
  if ($StdoutEcho) { $argList += "-" }
  $argString = ($argList | ForEach-Object { Quote-Arg $_ }) -join " "

  $errFile = [IO.Path]::GetTempFileName()
  $startParams = @{
    FilePath = $binary
    ArgumentList = $argString
    NoNewWindow = $true
    PassThru = $true
    RedirectStandardError = $errFile
  }
  if (-not $StdoutEcho) {
    $startParams.RedirectStandardOutput = [IO.Path]::GetTempFileName()
  }
  $proc = Start-Process @startParams

  # Wait for the "available at http://..." line (or an early exit).
  $url = $null
  for ($i = 0; $i -lt 100; $i++) {
    if (Test-Path $errFile) {
      $match = Select-String -Path $errFile -Pattern "https?://[^\s`"]+" -AllMatches -ErrorAction SilentlyContinue |
        Select-Object -First 1
      if ($match) { $url = $match.Matches[0].Value; break }
    }
    if ($proc.HasExited) { break }
    Start-Sleep -Milliseconds 100
  }

  if (-not $url) {
    $proc.WaitForExit()
    Get-Content $errFile -ErrorAction SilentlyContinue | ForEach-Object { [Console]::Error.WriteLine($_) }
    Remove-Item $errFile -ErrorAction SilentlyContinue
    return @{ Code = $EXIT_SESSION_FAILED; Announced = $false }
  }

  $localUrl = ConvertTo-LocalUrl $url
  [Console]::WriteLine("SCHEMAUI_URL=$localUrl")
  $lanUrl = Get-LanUrl $url
  if ($lanUrl) { [Console]::WriteLine("SCHEMAUI_LAN_URL=$lanUrl") }
  [Console]::WriteLine("SCHEMAUI_ANSWER=$Output")
  Open-Browser $localUrl
  [Console]::WriteLine("Form ready at $localUrl; waiting for Save & Exit...")

  $exited = $true
  if ($Timeout -gt 0) {
    $exited = $proc.WaitForExit($Timeout * 1000)
  } else {
    $proc.WaitForExit()
  }
  if (-not $exited) {
    $proc.Kill()
    Remove-Item $errFile -ErrorAction SilentlyContinue
    [Console]::Error.WriteLine("Timed out after ${Timeout}s waiting for the user; session killed. Fall back to plain-text questions.")
    return @{ Code = $EXIT_TIMEOUT; Announced = $true }
  }

  Get-Content $errFile -ErrorAction SilentlyContinue | ForEach-Object { [Console]::Error.WriteLine($_) }
  Remove-Item $errFile -ErrorAction SilentlyContinue
  if ($proc.ExitCode -ne 0) {
    [Console]::Error.WriteLine("schemaui exited with code $($proc.ExitCode); no answer was committed. Fall back to plain-text questions.")
    return @{ Code = $EXIT_SESSION_FAILED; Announced = $true }
  }
  return @{ Code = $EXIT_OK; Announced = $true }
}

$result = Invoke-SchemauiSession $Port
if ($result.Code -eq $EXIT_SESSION_FAILED -and -not $result.Announced -and $Port -ne 0) {
  [Console]::WriteLine("Port $Port unavailable; retrying with a random free port.")
  $result = Invoke-SchemauiSession 0
}

if ($result.Code -eq $EXIT_OK) {
  if (-not (Test-Path $Output)) {
    [Console]::Error.WriteLine("answer file missing: $Output")
    exit $EXIT_SESSION_FAILED
  }
  if (-not $StdoutEcho) { Get-Content $Output -Raw }
  [Console]::WriteLine("SCHEMAUI_RESULT=$Output")
}
exit $result.Code
