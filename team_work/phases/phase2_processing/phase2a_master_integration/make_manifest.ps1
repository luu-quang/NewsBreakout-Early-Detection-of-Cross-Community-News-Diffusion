$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path ".").Path
$masterPath = Join-Path $repoRoot "data\processed\master\articles_master.parquet"
$auditPath = Join-Path $repoRoot "data\processed\master\articles_audit.parquet"
$outPath = Join-Path $repoRoot "team_work\phases\phase2_processing\phase2a_master_integration\sample_output\master_build_manifest.json"

if (-not (Test-Path $masterPath)) {
    throw "Missing Phase 2A master output: $masterPath"
}
if (-not (Test-Path $auditPath)) {
    throw "Missing Phase 2A audit output: $auditPath"
}

$masterHash = (Get-FileHash -Algorithm SHA256 $masterPath).Hash.ToLower()
$auditHash = (Get-FileHash -Algorithm SHA256 $auditPath).Hash.ToLower()
$revision = (git rev-parse HEAD).Trim()

$manifest = [ordered]@{
    stage = "Phase 2A - Master Dataset Integration"
    builder = "src/integration/build_master.py"
    repository_revision = $revision

    master_output = "data/processed/master/articles_master.parquet"
    master_rows = 1223
    domestic_rows = 1221
    international_rows = 2
    master_sha256 = $masterHash

    audit_output = "data/processed/master/articles_audit.parquet"
    audit_rows = 1444
    audit_sha256 = $auditHash

    next_stage = "Phase 2B - Duplicate and Syndication Detection"
    next_stage_input = "data/processed/master/articles_master.parquet"
}

$manifest | ConvertTo-Json | Set-Content $outPath -Encoding UTF8
Write-Host "Wrote $outPath"
Write-Host "Master SHA256: $masterHash"
Write-Host "Audit  SHA256: $auditHash"
