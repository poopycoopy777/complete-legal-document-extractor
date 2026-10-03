param(
  [Parameter(Mandatory=$true)][string]$File,
  [string]$Tag = "bisect"
)
$ErrorActionPreference = "Stop"
Set-Location D:\complete-legal-document-extractor
$commits = @(
  "9212a01","778fc50","4baa53d","aa2043e","79dde99","6786d47","41d45d3","4ee5fb0",
  "0d7f1f0","fb7772e","8101941","fcdcef7","7f8a00b","b7315ba","f2cd65e","eab73c7",
  "7a4abf2","906a58b"
)
foreach ($c in $commits) {
  $out = "output\bisect_${Tag}_$c.json"
  if (-not (Test-Path $out)) {
    .\.venv\Scripts\python.exe scripts\cmp_commits.py --commit $c --inputs $File --out $out | Out-Null
  }
}
for ($i = 0; $i -lt $commits.Count - 1; $i++) {
  $new = $commits[$i]; $old = $commits[$i+1]
  $a = "output\bisect_${Tag}_$old.json"
  $b = "output\bisect_${Tag}_$new.json"
  Write-Output "########## $old -> $new"
  & .\.venv\Scripts\python.exe scripts\diff_cmp.py $a $b
}
