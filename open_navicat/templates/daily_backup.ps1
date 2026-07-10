# Daily backup template — OpenNavicat (PowerShell)
# Usage: .\daily_backup.ps1 -ConnName "prod"

param(
    [string]$ConnName = "default",
    [string]$BackupDir = "./backups",
    [int]$RetentionDays = 7
)

New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

Write-Host "=== Daily backup: $ConnName ==="
opennavicat backup create $ConnName --output $BackupDir

Write-Host "=== Rotating backups older than $RetentionDays days ==="
Get-ChildItem -Path $BackupDir -Filter "*.sql" | Where-Object {
    $_.LastWriteTime -lt (Get-Date).AddDays(-$RetentionDays)
} | Remove-Item -Force

Write-Host "=== Done ==="
opennavicat backup list $ConnName
