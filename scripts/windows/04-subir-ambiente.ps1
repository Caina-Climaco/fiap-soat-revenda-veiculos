# Sobe a plataforma local: cria o cluster kind "revenda" com a CLI kind, se faltar
# (infra/kind/cluster.yaml), e aplica o Terraform com o que fica dentro do cluster:
# namespaces, segredos, bancos, Keycloak e metrics-server (docs/08-ci-cd-infra.md, secao 1).
# A aplicacao (revenda-api) e implantada pelo CD (.github/workflows/cd.yml).
# O cluster NAO e criado pelo Terraform: o provider tehcyx/kind nao tem assinatura de
# codigo e e bloqueado pelo Smart App Control do Windows 11 (ADR-005).
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File .\scripts\windows\04-subir-ambiente.ps1 [-SemBancoExposto] [-Recriar]
#     -SemBancoExposto  nao publica o revenda-db em localhost:15432
#     -Recriar          apaga o cluster e o state antes (ambiente do zero; dados e senhas novos)
#
# State: %USERPROFILE%\.revenda\terraform.tfstate e TF_DATA_DIR em
# %USERPROFILE%\.revenda\terraform-data -- os MESMOS caminhos usados pelo cd.yml, entao o
# script e o CD compartilham o mesmo ambiente. Nunca dentro do repositorio (ADR-011).
# Log: .setup\relatorio-ambiente-subir.txt. Arquivo somente ASCII (Windows PowerShell 5.1).
param(
    [switch]$SemBancoExposto,
    [switch]$Recriar
)

$ErrorActionPreference = "Continue"
# Recarrega o PATH do registro: ferramentas instaladas pelo winget nesta sessao
# (kind, terraform) so aparecem em janelas novas do PowerShell.
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
$raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$tfDir = Join-Path $raiz "infra\terraform"
$log = Join-Path $raiz ".setup\relatorio-ambiente-subir.txt"
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

# Clusters kind existentes (a mensagem "No kind clusters found." vai para stderr)
function ClustersKind {
    $saida = @(& kind get clusters 2>$null)
    if ($LASTEXITCODE -ne 0) { return @() }
    return @($saida | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
}

Write-Host "04-subir-ambiente.ps1 - $(Get-Date -Format s)"
foreach ($f in @("docker", "kind", "kubectl", "terraform")) {
    if (-not (Get-Command $f -ErrorAction SilentlyContinue)) {
        Falhar "'$f' nao encontrado no PATH (rode scripts\windows\01-instalar-ferramentas.ps1)."
    }
}
if ((Invocar "docker" @("version", "--format", "docker {{.Server.Version}}")) -ne 0) {
    Falhar "Docker Desktop nao responde. Inicie o Docker Desktop e tente de novo."
}
$null = Invocar "kind" @("version")
$null = Invocar "terraform" @("version")

# ------------------------------------------------------------------ caminhos (iguais ao cd.yml)
# Barras normais: o cd.yml (Git Bash, cygpath -m) grava "C:/Users/<voce>/.revenda/...".
# Se o caminho do backend mudasse de forma, o terraform init pediria migracao de state.
$perfil = $env:USERPROFILE -replace '\\', '/'
$stateDir = "$perfil/.revenda"
$statePath = "$stateDir/terraform.tfstate"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$env:TF_DATA_DIR = "$stateDir/terraform-data"
$env:TF_IN_AUTOMATION = "1"
$env:TF_INPUT = "0"
$env:KUBECONFIG = "$perfil/.kube/config"
$env:TF_VAR_kubeconfig_path = "$perfil/.kube/config"
$env:TF_VAR_expor_banco_revenda = if ($SemBancoExposto) { "false" } else { "true" }
Write-Host "State: $statePath | TF_DATA_DIR: $env:TF_DATA_DIR | KUBECONFIG: $env:KUBECONFIG"

# ------------------------------------------------------------------ cluster (CLI kind)
$configKind = Join-Path $raiz "infra\kind\cluster.yaml"
if (-not (Test-Path $configKind)) { Falhar "arquivo $configKind nao encontrado." }

if ($Recriar) {
    Write-Host "-Recriar: apagando o cluster e o state (dados dos bancos serao perdidos)"
    if ((ClustersKind) -contains "revenda") {
        if ((Invocar "kind" @("delete", "cluster", "--name", "revenda")) -ne 0) { Falhar "kind delete cluster falhou." }
    }
    Remove-Item -Path $statePath, "$statePath.backup" -Force -ErrorAction SilentlyContinue
}

# Idempotente: so cria se `kind get clusters` nao listar "revenda". Se o cluster foi
# recriado com o state antigo, o Terraform percebe no refresh que os recursos sumiram e
# os cria de novo (mantendo as senhas do state).
if ((ClustersKind) -contains "revenda") {
    Write-Host "Cluster kind 'revenda' ja existe (nada a criar)."
} else {
    $codigo = Invocar "kind" @("create", "cluster", "--config", $configKind, "--wait", "120s")
    if ($codigo -ne 0) { Falhar "kind create cluster falhou (codigo $codigo)." }
}
# Grava/atualiza o contexto kind-revenda no KUBECONFIG usado pelos providers do Terraform
if ((Invocar "kind" @("export", "kubeconfig", "--name", "revenda")) -ne 0) { Falhar "kind export kubeconfig falhou." }

# ------------------------------------------------------------------ terraform
$codigo = Invocar "terraform" @("-chdir=$tfDir", "init", "-input=false", "-no-color", "-reconfigure", "-backend-config=path=$statePath")
if ($codigo -ne 0) { Falhar "terraform init falhou (codigo $codigo)." }

$codigo = Invocar "terraform" @("-chdir=$tfDir", "apply", "-input=false", "-no-color", "-auto-approve")
if ($codigo -ne 0) { Falhar "terraform apply falhou (codigo $codigo). Diagnostico: kubectl get pods -A" }

# ------------------------------------------------------------------ verificacao
$null = Invocar "kubectl" @("config", "current-context")
$null = Invocar "kubectl" @("get", "nodes", "-o", "wide")
$null = Invocar "kubectl" @("get", "pods", "-A", "-o", "wide")
$null = Invocar "terraform" @("-chdir=$tfDir", "output", "-no-color", "urls")

$pronto = $false
for ($i = 1; $i -le 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8180/realms/revenda/.well-known/openid-configuration" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $pronto = $true; break }
    } catch { }
    Start-Sleep -Seconds 5
}
if ($pronto) { Write-Host "Keycloak OK: realm revenda publicado em http://localhost:8180/realms/revenda" }
else { Write-Host "AVISO: o discovery do realm ainda nao respondeu (kubectl -n identidade logs deployment/keycloak)." }

Write-Host ""
Write-Host "==================== ambiente local ===================="
Write-Host "API (apos o CD)      http://localhost:8080   (Swagger: http://localhost:8080/docs)"
Write-Host "Keycloak             http://localhost:8180   (admin: http://localhost:8180/admin/)"
Write-Host "Conta do cliente     http://localhost:8180/realms/revenda/account"
if (-not $SemBancoExposto) { Write-Host "Banco revenda        localhost:15432 (usuario revenda, banco revenda)" }
Write-Host ""
Write-Host "Segredos (PowerShell): ler e decodificar, por exemplo a senha do gestor.loja:"
Write-Host '  $b = kubectl -n identidade get secret keycloak-gestor -o jsonpath="{.data.GESTOR_PASSWORD}"'
Write-Host '  [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b))'
Write-Host "Outros: keycloak-admin (KC_BOOTSTRAP_ADMIN_PASSWORD), revenda/revenda-webhook-secret"
Write-Host "(WEBHOOK_SECRET), revenda/revenda-db-credentials (DB_PASSWORD)."
Write-Host ""
Write-Host "Aplicacao: merge na main ou  gh workflow run cd.yml  (CD no runner kind-local)."
Write-Host "Log: $log"
Stop-Transcript | Out-Null
exit 0
