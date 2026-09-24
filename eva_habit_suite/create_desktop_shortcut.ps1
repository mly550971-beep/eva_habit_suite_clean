# create_desktop_shortcut.ps1
# --------------------------------
# Run this ONCE (double-click, or right-click -> "Run with PowerShell").
# It creates a "Eva + Habit Tracker" icon on your Desktop that runs
# start_both.bat with the custom icon.ico from this folder - so from now
# on, starting both apps is a double-click, not "open VS Code -> open
# run_both.py -> click Run".
#
# If Windows blocks the script from running (execution policy), open
# PowerShell yourself and run:
#   powershell -ExecutionPolicy Bypass -File create_desktop_shortcut.ps1

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TargetBat  = Join-Path $ProjectDir "start_both.bat"
$IconPath   = Join-Path $ProjectDir "icon.ico"
$DesktopDir = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopDir "Eva + Habit Tracker.lnk"

if (-not (Test-Path $TargetBat)) {
    Write-Host "Could not find start_both.bat at $TargetBat - run this script from inside the project folder."
    exit 1
}

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetBat
$Shortcut.WorkingDirectory = $ProjectDir
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = $IconPath
}
$Shortcut.Description = "Start Eva + Habit Tracker together"
$Shortcut.Save()

Write-Host "Done - 'Eva + Habit Tracker' shortcut created on your Desktop."
