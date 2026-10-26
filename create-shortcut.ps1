$ErrorActionPreference = 'Stop'
$whistleRoot = $PSScriptRoot
$whistleShell = New-Object -ComObject WScript.Shell
$whistleDesktop = $whistleShell.SpecialFolders.Item('Desktop')
$whistleShortcut = $whistleShell.CreateShortcut((Join-Path $whistleDesktop 'Whistle.lnk'))
$whistleShortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
$whistleShortcut.Arguments = '"' + (Join-Path $whistleRoot 'Launch Whistle.vbs') + '"'
$whistleShortcut.WorkingDirectory = $whistleRoot
$whistleShortcut.Description = 'Transcribe audio from a chosen window with local Whistle'
$whistleShortcut.IconLocation = (Join-Path $whistleRoot 'bin\whistle.ico') + ',0'
$whistleShortcut.Save()
Write-Output (Join-Path $whistleDesktop 'Whistle.lnk')
