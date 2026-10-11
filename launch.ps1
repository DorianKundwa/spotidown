<#
.SYNOPSIS
    SpotiDown Launcher PowerShell script
.DESCRIPTION
    Launches SpotiDown's backend and frontend using Python 3.10+.
#>

[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$CheckOnly,
    [switch]$AutoInstall,
    [int]$Port
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$argsList = @("launcher.py")
if ($NoBrowser)   { $argsList += "--no-browser" }
if ($CheckOnly)   { $argsList += "--check-only" }
if ($AutoInstall) { $argsList += "--auto-install" }
if ($Port)        { $argsList += "--port", $Port }

# Try py -3.12, py -3, or python
if (Get-Command "py" -ErrorAction SilentlyContinue) {
    try {
        & py -3.12 @argsList
        if ($LASTEXITCODE -eq 0) { exit 0 }
    } catch {}
    
    try {
        & py -3 @argsList
        if ($LASTEXITCODE -eq 0) { exit 0 }
    } catch {}
}

if (Get-Command "python" -ErrorAction SilentlyContinue) {
    & python @argsList
    exit $LASTEXITCODE
}

Write-Error "Python 3.10+ was not found on your system."
exit 1
