#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$installer = Join-Path (Split-Path $PSScriptRoot -Parent) 'install-windows.ps1'
$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($installer, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw ($errors | Out-String) }

function Assert-True($Condition, $Message) {
    if (-not $Condition) { throw $Message }
}

function Expect-Failure([scriptblock]$Action, [string]$Message) {
    try { & $Action }
    catch {
        Assert-True ($_.Exception.Message -like "*$Message*") "Unexpected error: $_"
        return
    }
    throw "Expected failure containing: $Message"
}

function Reset-Mock {
    $global:WslMock = @{
        Names = @("U`0b`0u`0n`0t`0u`0", 'Ubuntu-24.04')
        Kernel = '6.6.87-microsoft-standard-WSL2'
        ListExit = 0
        InstallExit = 0
        Calls = @()
        Bootstrap = ''
    }
}

function global:wsl.exe {
    $global:WslMock.Calls += ,@($args)
    $global:LASTEXITCODE = 0
    if ($args[0] -eq '--list') {
        $global:LASTEXITCODE = $global:WslMock.ListExit
        return $global:WslMock.Names
    }
    if ($args[3] -eq 'uname') { return $global:WslMock.Kernel }
    Assert-True ($args[3] -eq 'bash') 'Expected bash installer call.'
    Assert-True ($args[5] -match '^printf %s ([A-Za-z0-9+/=]+) \| base64 -d \| bash$') 'Bootstrap must use safe base64 transport.'
    $global:WslMock.Bootstrap = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Matches[1]))
    $global:LASTEXITCODE = $global:WslMock.InstallExit
}

try {
    Reset-Mock
    & $installer
    Assert-True ($global:WslMock.Calls.Count -eq 3) 'Expected list, kernel check and installation.'
    Assert-True ($global:WslMock.Bootstrap.Contains('install-wsl.sh')) 'Missing shared WSL installer.'
    Assert-True (-not $global:WslMock.Bootstrap.Contains("`r")) 'CRLF must not reach Bash.'

    Reset-Mock
    & $installer -Distribution 'Ubuntu-24.04'
    Assert-True ($global:WslMock.Calls[2][1] -eq 'Ubuntu-24.04') 'Selected distribution was not forwarded.'

    Reset-Mock
    Expect-Failure { & $installer -Distribution 'Other;echo injected' } 'No se encontro'
    Assert-True ($global:WslMock.Calls.Count -eq 1) 'Missing distribution must not execute a shell.'

    Reset-Mock
    $global:WslMock.ListExit = 1
    Expect-Failure { & $installer } 'WSL no esta listo'

    Reset-Mock
    $global:WslMock.Kernel = '4.4.0-Microsoft'
    Expect-Failure { & $installer } 'Se necesita WSL2'
    Assert-True ($global:WslMock.Calls.Count -eq 2) 'WSL1 must not install anything.'

    Reset-Mock
    $global:WslMock.InstallExit = 23
    Expect-Failure { & $installer } 'instalacion dentro de WSL fallo'
    Write-Host 'PASS: PowerShell syntax, distro selection, NUL output, WSL1 rejection, failure propagation, safe Bash transport.'
}
finally {
    Remove-Item Function:\wsl.exe
    Remove-Variable WslMock -Scope Global
}
# Expected native failures must not become the CI process exit code.
$global:LASTEXITCODE = 0
