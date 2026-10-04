# Salva em .setup\ci-diagnostico.txt o estado dos PRs e das execucoes do GitHub Actions,
# incluindo os logs dos passos que falharam. Uso:
#   powershell -ExecutionPolicy Bypass -File .\scripts\windows\diagnostico-ci.ps1 [-Execucoes 5]
#
# Sem expressoes --jq com aspas internas: o Windows PowerShell 5.1 corrompe aspas
# embutidas ao passar argumentos para executaveis nativos (o gh responde "unknown
# arguments"). O gh devolve JSON puro (--json) e a formatacao e feita aqui, com
# ConvertFrom-Json. Arquivo somente ASCII (Windows PowerShell 5.1).
param([int]$Execucoes = 5)

$ErrorActionPreference = "Continue"
# O gh escreve UTF-8; sem isto o PS 5.1 decodifica os acentos dos titulos com a pagina
# de codigo do console e o JSON chega corrompido.
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $raiz
$saida = Join-Path $raiz ".setup\ci-diagnostico.txt"
New-Item -ItemType Directory -Force -Path (Split-Path $saida) | Out-Null
$l = New-Object System.Collections.Generic.List[string]

# Executa o gh e devolve o JSON da saida padrao ja convertido (ou $null em caso de erro).
# A saida de erro do gh vai para o relatorio, nunca para o ConvertFrom-Json.
function GhJson {
    param([string[]]$Argumentos)
    $global:LASTEXITCODE = 0
    $bruto = @(& gh @Argumentos 2>&1)
    $codigo = $LASTEXITCODE
    $padrao = New-Object System.Collections.Generic.List[string]
    $erros = New-Object System.Collections.Generic.List[string]
    foreach ($item in $bruto) {
        if ($item -is [System.Management.Automation.ErrorRecord]) {
            $erros.Add($item.Exception.Message)
        } else {
            $padrao.Add("$item")
        }
    }
    if ($codigo -ne 0) {
        $l.Add("ERRO: gh $($Argumentos -join ' ') (codigo $codigo)")
        foreach ($e in $erros) { $l.Add("  $e") }
        return $null
    }
    $texto = ($padrao -join "`n").Trim()
    if (-not $texto) { return $null }
    try {
        # -InputObject (e nao pipeline): no PS 5.1 um array JSON sairia como um unico item.
        return (ConvertFrom-Json -InputObject $texto)
    } catch {
        $l.Add("ERRO: JSON invalido de gh $($Argumentos -join ' '): $($_.Exception.Message)")
        $l.Add($texto)
        return $null
    }
}

function Texto($valor) {
    if ($null -eq $valor -or "$valor" -eq "") { return "-" }
    return "$valor"
}

$l.Add("Gerado em $(Get-Date -Format s)")

$l.Add("==== PRs abertos")
$prs = GhJson @("pr", "list", "--state", "open", "--json", "number,title,headRefName,mergeStateStatus")
$qtdPrs = 0
foreach ($pr in $prs) {
    $qtdPrs++
    $l.Add("#$($pr.number) [$(Texto $pr.mergeStateStatus)] $($pr.headRefName) - $($pr.title)")
}
if ($qtdPrs -eq 0) { $l.Add("(nenhum)") }

$l.Add("==== Ultimas execucoes")
$runs = GhJson @("run", "list", "--limit", "$Execucoes", "--json", "databaseId,workflowName,headBranch,status,conclusion,event,createdAt")
$falhas = New-Object System.Collections.Generic.List[object]
$qtdRuns = 0
foreach ($r in $runs) {
    $qtdRuns++
    $l.Add(("{0} | {1} | {2} | {3} | {4}/{5} | {6}" -f $r.databaseId, $r.workflowName, $r.headBranch, $r.event, (Texto $r.status), (Texto $r.conclusion), $r.createdAt))
    if ($r.conclusion -eq "failure") { $falhas.Add($r) }
}
if ($qtdRuns -eq 0) { $l.Add("(nenhuma)") }

foreach ($r in $falhas) {
    $l.Add("==== FALHA: run $($r.databaseId) $($r.workflowName) ($($r.headBranch))")
    & gh run view "$($r.databaseId)" --log-failed 2>&1 | Select-Object -Last 400 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { $l.Add($_.Exception.Message) } else { $l.Add("$_") }
    }
}

$l | Out-File -Encoding utf8 $saida
Write-Host "Diagnostico salvo em $saida"
