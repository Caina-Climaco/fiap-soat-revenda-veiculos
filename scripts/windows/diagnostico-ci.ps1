# Salva em .setup\ci-diagnostico.txt o estado dos PRs e das execucoes do GitHub Actions,
# incluindo os logs dos passos que falharam. Uso:
#   powershell -ExecutionPolicy Bypass -File .\scripts\windows\diagnostico-ci.ps1 [-Execucoes 5]
param([int]$Execucoes = 5)
$ErrorActionPreference = "Continue"
$raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $raiz
$saida = Join-Path $raiz ".setup\ci-diagnostico.txt"
New-Item -ItemType Directory -Force -Path (Split-Path $saida) | Out-Null
$l = New-Object System.Collections.Generic.List[string]
$l.Add("Gerado em $(Get-Date -Format s)")
$l.Add("==== PRs abertos")
gh pr list --state open --json number,title,headRefName,mergeStateStatus --jq '.[] | "#\(.number) [\(.mergeStateStatus)] \(.headRefName) - \(.title)"' 2>&1 | ForEach-Object { $l.Add("$_") }
$l.Add("==== Ultimas execucoes")
$runs = gh run list --limit $Execucoes --json databaseId,workflowName,headBranch,status,conclusion,event,createdAt 2>&1 | Out-String
$l.Add($runs)
try { $lista = $runs | ConvertFrom-Json } catch { $lista = @() }
foreach ($r in $lista) {
    if ($r.conclusion -eq "failure") {
        $l.Add("==== FALHA: run $($r.databaseId) $($r.workflowName) ($($r.headBranch))")
        gh run view $r.databaseId --log-failed 2>&1 | Select-Object -Last 400 | ForEach-Object { $l.Add("$_") }
    }
}
$l | Out-File -Encoding utf8 $saida
Write-Host "Diagnostico salvo em $saida"
