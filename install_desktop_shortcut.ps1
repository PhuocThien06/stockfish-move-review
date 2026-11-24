$project = $PSScriptRoot
$launcher = Join-Path $project '.venv\Scripts\pythonw.exe'
$script = Join-Path $project 'stockfish_review.py'
$icon = Join-Path $project 'assets\stockfish_review.ico'

foreach ($path in @($launcher, $script, $icon)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Không tìm thấy: $path"
    }
}

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Stockfish Review.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.Arguments = '"' + $script + '"'
$shortcut.WorkingDirectory = $project
$shortcut.IconLocation = $icon + ',0'
$shortcut.Description = 'Mở Stockfish Review từ D:\Chess'
$shortcut.Save()
Write-Output $shortcutPath
