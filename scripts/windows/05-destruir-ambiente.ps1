# Destroi a plataforma local: terraform destroy (mesmo state do CD) se o cluster existir,
# depois kind delete cluster (o cluster e da CLI kind, nao do Terraform; ADR-005) e por
# fim remove o state. Os dados dos bancos (PVCs no no do kind) sao PERDIDOS.
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File .\scripts\windows\05-destruir-ambiente.ps1 [-Forcar]
#     -Forcar  nao pede confirmacao
#
# O state e sempre removido no final: sem cluster, nenhum recurso dele existe mais (os
# segredos serao gerados de novo na proxima subida). Uma falha do terraform destroy so
# gera aviso, porque o kind delete cluster apaga tudo de qualquer forma.
# Log: .setup\relatorio-ambiente-destruir.txt. Arquivo somente ASCII (Windows PowerShell 5.1).
param(
    [switch]$Forcar
)

$ErrorActionPreference = "Continue"
# Recarrega o PATH do registro: ferramentas instaladas pelo winget nesta sessao
# (kind, terraform) so aparecem em janelas novas do PowerShell.
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
$raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$tfDir = Join-Path $raiz "infra\terraform"
$log = Join-Path $raiz ".setup\relatorio-ambiente-destruir.txt"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
Start-Transcript -Path $log -Force | Out-Null

function Invocar {
    param([string]$Exe, [string[]]$Argumentos)
    Write-Host ">> $Exe $($Argumentos -join ' ')"
    $global:LASTEXITCODE = 0
    & $Exe @Argumentos 2>&1 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" }
    } | Out-Host
    return $LASTEXITCODE
}

function Falhar([string]$motivo) {
    Write-Host ""
    Write-Host "ERRO: $motivo"
    Write-Host "Log: $log"
    Stop-Transcript | Out-Null
    exit 1
}

function ClustersKind {
    $saida = @(& kind get clusters 2>$null)
    if ($LASTEXITCODE -ne 0) { return @() }
    return @($saida | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
}

Write-Host "05-destruir-ambiente.ps1 - $(Get-Date -Format s)"
foreach ($f in @("docker", "kind", "terraform")) {
    if (-not (Get-Command $f -ErrorAction SilentlyContinue)) { Falhar "'$f' nao encontrado no PATH." }
}
if ((Invocar "docker" @("version", "--format", "docker {{.Server.Version}}")) -ne 0) {
    Falhar "Docker Desktop nao responde. Inicie o Docker Desktop e tente de novo."
}

if (-not $Forcar) {
    Write-Host "Isto apaga o cluster kind 'revenda', os bancos (revenda e keycloak) e os segredos gerados."
    $resposta = Read-Host "Digite SIM para continuar"
    if ($resposta -cne "SIM") {
        Write-Host "Cancelado."
        Stop-Transcript | Out-Null
        exit 0
    }
}

# Mesmos caminhos do cd.yml e do 04-subir-ambiente.ps1
$perfil = $env:USERPROFILE -replace '\\', '/'
$stateDir = "$perfil/.revenda"
$statePath = "$stateDir/terraform.tfstate"
$env:TF_DATA_DIR = "$stateDir/terraform-data"
$env:TF_IN_AUTOMATION = "1"
$env:TF_INPUT = "0"
$env:KUBECONFIG = "$perfil/.kube/config"
$env:TF_VAR_kubeconfig_path = "$perfil/.kube/config"

if ((ClustersKind) -contains "revenda") {
    if (Test-Path $statePath) {
        $codigo = Invocar "kind" @("export", "kubeconfig", "--name", "revenda")
        if ($codigo -eq 0) {
            $codigo = Invocar "terraform" @("-chdir=$tfDir", "init", "-input=false", "-no-color", "-reconfigure", "-backend-config=path=$statePath")
        }
        if ($codigo -eq 0) {
            $codigo = Invocar "terraform" @("-chdir=$tfDir", "destroy", "-input=false", "-no-color", "-auto-approve")
        }
        if ($codigo -ne 0) { Write-Host "AVISO: terraform destroy falhou (codigo $codigo); seguindo com kind delete cluster." }
    } else {
        Write-Host "Sem state em $statePath; apenas o cluster kind sera apagado."
    }
    if ((Invocar "kind" @("delete", "cluster", "--name", "revenda")) -ne 0) { Falhar "kind delete cluster falhou." }
} else {
    Write-Host "Cluster kind 'revenda' nao existe; nada a destruir no cluster."
}

# Sem cluster, os recursos do state nao existem mais (o state tem segredos em texto claro)
Remove-Item -Path $statePath, "$statePath.backup" -Force -ErrorAction SilentlyContinue
Write-Host "State removido: $statePath"

if ((ClustersKind) -contains "revenda") { Falhar "o cluster 'revenda' ainda existe." }
Write-Host ""
Write-Host "Ambiente destruido. Para recriar: scripts\windows\04-subir-ambiente.ps1 e depois o CD."
Write-Host "As imagens revenda-api:<sha> continuam no Docker local (docker image prune para limpar)."
Write-Host "Log: $log"
Stop-Transcript | Out-Null
exit 0
