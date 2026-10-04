# Destroi a plataforma local: terraform destroy (mesmo state do CD) e, por garantia,
# kind delete cluster. Os dados dos bancos (PVCs no no do kind) sao PERDIDOS.
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File .\scripts\windows\05-destruir-ambiente.ps1 [-Forcar]
#     -Forcar  nao pede confirmacao
#
# Se o terraform destroy falhar (ex.: cluster ja apagado a mao, o que quebra o refresh do
# provider tehcyx/kind), o cluster e apagado com o kind e o state e removido: sem cluster
# nao sobra recurso para o Terraform gerenciar (os segredos serao gerados de novo).
# Log: .setup\relatorio-ambiente-destruir.txt. Arquivo somente ASCII (Windows PowerShell 5.1).
param(
    [switch]$Forcar
)

$ErrorActionPreference = "Continue"
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

$destruido = $false
$temCluster = (ClustersKind) -contains "revenda"
if (Test-Path $statePath) {
    if ($temCluster) {
        $codigo = Invocar "terraform" @("-chdir=$tfDir", "init", "-input=false", "-no-color", "-reconfigure", "-backend-config=path=$statePath")
        if ($codigo -eq 0) {
            $codigo = Invocar "terraform" @("-chdir=$tfDir", "destroy", "-input=false", "-no-color", "-auto-approve")
            $destruido = ($codigo -eq 0)
        }
        if (-not $destruido) { Write-Host "AVISO: terraform destroy falhou (codigo $codigo); seguindo com kind delete cluster." }
    } else {
        Write-Host "Cluster 'revenda' nao existe; o state sera removido sem terraform destroy."
    }
} else {
    Write-Host "Sem state em $statePath; apenas o cluster kind (se existir) sera apagado."
}

# Garantia: o cluster some mesmo que o destroy tenha falhado no meio
if ((ClustersKind) -contains "revenda") {
    if ((Invocar "kind" @("delete", "cluster", "--name", "revenda")) -ne 0) { Falhar "kind delete cluster falhou." }
} else {
    Write-Host "Cluster kind 'revenda' ausente (ok)."
}

if (-not $destruido) {
    # State orfao (contem segredos em texto claro): removido junto com o backup.
    Remove-Item -Path $statePath, "$statePath.backup" -Force -ErrorAction SilentlyContinue
    Write-Host "State removido: $statePath"
}

if ((ClustersKind) -contains "revenda") { Falhar "o cluster 'revenda' ainda existe." }
Write-Host ""
Write-Host "Ambiente destruido. Para recriar: scripts\windows\04-subir-ambiente.ps1 e depois o CD."
Write-Host "As imagens revenda-api:<sha> continuam no Docker local (docker image prune para limpar)."
Write-Host "Log: $log"
Stop-Transcript | Out-Null
exit 0
