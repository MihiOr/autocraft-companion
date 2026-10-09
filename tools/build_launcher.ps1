$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) {
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path -LiteralPath $compiler)) { throw '.NET Framework C# compiler was not found.' }
& $compiler /nologo /target:winexe /reference:System.Windows.Forms.dll "/win32icon:$repoRoot\src\companion.ico" "/out:$repoRoot\AutoCraft Companion.exe" "$PSScriptRoot\CompanionLauncher.cs"
if ($LASTEXITCODE -ne 0) { throw 'Launcher build failed.' }
Write-Host 'Built AutoCraft Companion.exe. Keep it in the main Companion folder beside src/.'
