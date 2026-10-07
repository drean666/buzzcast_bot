# ===================================================================
#  buzzcast - put the new build in your project folder.
#
#  Run this in PowerShell after downloading the buzzcast file from
#  the chat. It looks for it wherever your browser actually put it,
#  uses the newest one it finds, unpacks it into the project, and
#  then runs the test suite.
#
#  It contains no links on purpose: a link copied out of a chat
#  window arrives wrapped in [brackets](like this), and PowerShell
#  then asks for a URL that does not exist. A plain script cannot
#  be mangled that way.
# ===================================================================

$proj = "C:\Users\besta\Projects\buzzcast_bot"
$dirs = @(
    "$env:USERPROFILE\Downloads",
    "$env:USERPROFILE\Desktop",
    "$env:USERPROFILE\Documents",
    $proj,
    "$env:TEMP"
)

$hits = @()
foreach ($d in $dirs) {
    if (Test-Path $d) {
        $hits += Get-ChildItem -Path $d -Filter "buzzcast-*full*" -File -ErrorAction SilentlyContinue
    }
}

if ($hits.Count -eq 0) {
    ""
    "  NO BUILD FOUND."
    ""
    "  Looked in Downloads, Desktop, Documents, TEMP and the project folder."
    "  Click the buzzcast file card in the chat to download it, then run"
    "  this again. If your browser asks, keep the file - do not open it."
    ""
    return
}

$zip = $hits | Sort-Object LastWriteTime -Descending | Select-Object -First 1
"using   : " + $zip.FullName
"          " + [math]::Round($zip.Length / 1KB) + " KB, saved " + $zip.LastWriteTime

$others = $hits | Where-Object { $_.FullName -ne $zip.FullName }
if ($others) {
    "note    : older copies also found, ignoring them:"
    foreach ($o in $others) { "          " + $o.FullName }
}

cd $proj
Expand-Archive -Path $zip.FullName -DestinationPath $proj -Force
"unpacked into " + $proj

$line = (Get-Content ".\engine\__init__.py" | Select-String "__version__" | Select-Object -First 1).Line
"version : " + $line.Trim()
""
"running the tests - the first line must say 2.11.1 and the last must say 67/67."
""
python tests.py
