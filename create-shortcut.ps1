$ErrorActionPreference = 'Stop'
$whistleRoot = $PSScriptRoot
$whistleShell = New-Object -ComObject WScript.Shell
# Windows Search indexes per-user Start-menu apps. Both entries always launch
# this checkout, so updating main updates what the user opens from Search.
$whistleFolders = @(
    $whistleShell.SpecialFolders.Item('Desktop'),
    $whistleShell.SpecialFolders.Item('Programs')
)
foreach ($whistleFolder in $whistleFolders) {
    $whistlePath = Join-Path $whistleFolder 'Whistle.lnk'
    $whistleShortcut = $whistleShell.CreateShortcut($whistlePath)
    $whistleShortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
    $whistleShortcut.Arguments = '"' + (Join-Path $whistleRoot 'Launch Whistle.vbs') + '"'
    $whistleShortcut.WorkingDirectory = $whistleRoot
    $whistleShortcut.Description = 'Record app, system, or microphone audio and transcribe it locally'
    $whistleShortcut.IconLocation = (Join-Path $whistleRoot 'bin\whistle.ico') + ',0'
    $whistleShortcut.Save()
    Write-Output $whistlePath
}
