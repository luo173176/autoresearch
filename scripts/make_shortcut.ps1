# ASCII-only shortcut creator (avoids encoding pitfalls)
$ErrorActionPreference = "Stop"
$desktop = [Environment]::GetFolderPath("Desktop")
Write-Output "DESKTOP=$desktop"
try {
    $bat = Get-ChildItem "E:\Users\luo17\AppData\Programs\Zcode\autoresearch" -Filter "*.bat" |
        Select-Object -First 1
    if (-not $bat) { throw "no .bat launcher found" }
    Write-Output "TARGET=$($bat.FullName)"
    $ws = New-Object -ComObject WScript.Shell
    $lnkPath = Join-Path $desktop "AutoResearch.lnk"
    $lnk = $ws.CreateShortcut($lnkPath)
    $lnk.TargetPath = $bat.FullName
    $lnk.WorkingDirectory = $bat.DirectoryName
    $lnk.Description = "AutoResearch Dashboard"
    $lnk.Save()
    Write-Output "SHORTCUT_OK: $lnkPath"
} catch {
    Write-Output "SHORTCUT_FAILED: $($_.Exception.Message)"
}
