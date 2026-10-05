# Sobe a infraestrutura da API no cluster kind local: cria o cluster "revenda" com a CLI
# kind, se faltar (infra/kind/cluster.yaml, plataforma compartilhada com o servico de
# identidade), e aplica o Terraform DESTE repositorio: namespace revenda, segredos,
# revenda-db e metrics-server (docs/08-ci-cd-infra.md, secao 1). A aplicacao (revenda-api)
# e implantada pelo CD (.github/workflows/cd.yml).
# O servico de identidade (Keycloak) e de OUTRO repositorio (fiap-soat-revenda-identidade,
# ADR-014): suba-o antes, pelo 04-subir-ambiente.ps1 de la (ou pelo CD de la).
# O cluster NAO e criado pelo Terraform: o provider tehcyx/kind nao tem assinatura de
# codigo e e bloqueado pelo Smart App Control do Windows 11 (ADR-005).
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File .\scripts\windows\04-subir-ambiente.ps1 [-SemBancoExposto]
#     -SemBancoExposto  nao publica o revenda-db em localhost:15432
#
# State: %USERPROFILE%\.revenda\revenda-api.tfstate (TF_DATA_DIR em
# %USERPROFILE%\.revenda\terraform-data). O CD usa o MESMO arquivo de state: o runner e um
# container Linux que monta %USERPROFILE%\.revenda em /revenda-state; so o TF_DATA_DIR
# dele e outro (providers Linux). O state da identidade e outro arquivo (identidade.tfstate).
# Nunca dentro do repositorio (ADR-011).
# Log: .setup\relatorio-ambiente-subir.txt. Arquivo somente ASCII (Windows PowerShell 5.1).
param(
    [switch]$SemBancoExposto
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

# ------------------------------------------------------------------ caminhos (state compartilhado com o cd.yml)
# O cd.yml roda no container Linux do runner (infra/runner) e le/grava o mesmo
# revenda-api.tfstate em /revenda-state, bind mount de %USERPROFILE%\.revenda; o
# TF_DATA_DIR dele e proprio (/home/runner/persist/terraform-data). Aqui o caminho usa
# barras normais e fica sempre igual, para o terraform init nao pedir migracao de state.
$perfil = $env:USERPROFILE -replace '\\', '/'
$stateDir = "$perfil/.revenda"
$statePath = "$stateDir/revenda-api.tfstate"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$env:TF_DATA_DIR = "$stateDir/terraform-data"
$env:TF_IN_AUTOMATION = "1"
$env:TF_INPUT = "0"
$env:KUBECONFIG = "$perfil/.kube/config"
$env:TF_VAR_kubeconfig_path = "$perfil/.kube/config"
$env:TF_VAR_expor_banco_revenda = if ($SemBancoExposto) { "false" } else { "true" }
Write-Host "State: $statePath | TF_DATA_DIR: $env:TF_DATA_DIR | KUBECONFIG: $env:KUBECONFIG"
if (Test-Path "$stateDir/terraform.tfstate") {
    Write-Host "AVISO: existe $stateDir/terraform.tfstate (state antigo, de quando a identidade e a API"
    Write-Host "       estavam no mesmo repositorio). Veja 'Migracao para dois repositorios' no README."
}

# ------------------------------------------------------------------ cluster (CLI kind)
$configKind = Join-Path $raiz "infra\kind\cluster.yaml"
if (-not (Test-Path $configKind)) { Falhar "arquivo $configKind nao encontrado." }


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

# ------------------------------------------------------------------ servico de identidade (outro repositorio)
$identidadeOk = $false
for ($i = 1; $i -le 12; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8180/realms/revenda/.well-known/openid-configuration" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $identidadeOk = $true; break }
    } catch { }
    Start-Sleep -Seconds 5
}
if (-not $identidadeOk) {
    Falhar "o realm revenda nao responde em http://localhost:8180. Suba antes o servico de identidade (repositorio fiap-soat-revenda-identidade, scripts\windows\04-subir-ambiente.ps1)."
}
Write-Host "Servico de identidade OK: http://localhost:8180/realms/revenda"

# ------------------------------------------------------------------ terraform
$codigo = Invocar "terraform" @("-chdir=$tfDir", "init", "-input=false", "-no-color", "-reconfigure", "-backend-config=path=$statePath")
if ($codigo -ne 0) { Falhar "terraform init falhou (codigo $codigo)." }

# Antes do API Gateway o Service revenda-api era NodePort 30080; o Kong assume essa porta.
$tipoSvc = (& kubectl -n revenda get service revenda-api -o "jsonpath={.spec.type}" 2>$null)
if ($tipoSvc -eq "NodePort") {
    Write-Host "Service revenda-api ainda e NodePort: convertendo para ClusterIP (libera a 30080 para o Kong)"
    $patch = '[{"op":"replace","path":"/spec/type","value":"ClusterIP"},{"op":"remove","path":"/spec/ports/0/nodePort"}]'
    $arq = Join-Path $env:TEMP "revenda-svc-patch.json"
    [IO.File]::WriteAllText($arq, $patch)
    $null = Invocar "kubectl" @("-n", "revenda", "patch", "service", "revenda-api", "--type=json", "--patch-file=$arq")
}

$codigo = Invocar "terraform" @("-chdir=$tfDir", "apply", "-input=false", "-no-color", "-auto-approve")
if ($codigo -ne 0) { Falhar "terraform apply falhou (codigo $codigo). Diagnostico: kubectl get pods -A" }

# ------------------------------------------------------------------ verificacao
$null = Invocar "kubectl" @("config", "current-context")
$null = Invocar "kubectl" @("get", "nodes", "-o", "wide")
$null = Invocar "kubectl" @("-n", "revenda", "get", "pods,svc", "-o", "wide")
$null = Invocar "terraform" @("-chdir=$tfDir", "output", "-no-color", "urls")

Write-Host ""
Write-Host "==================== infraestrutura da API ===================="
Write-Host "API pelo Kong (CD)   http://localhost:8080   (Swagger: http://localhost:8080/docs)"
Write-Host "Grafana              http://localhost:3000   (painel Revenda de Veiculos; anonimo como Viewer)"
Write-Host "Prometheus           http://localhost:9090   (alvos em /targets, alertas em /alerts)"
Write-Host "Identidade           http://localhost:8180   (outro repositorio: fiap-soat-revenda-identidade)"
if (-not $SemBancoExposto) { Write-Host "Banco revenda        localhost:15432 (usuario revenda, banco revenda)" }
Write-Host ""
Write-Host "Segredos da API (PowerShell): ler e decodificar, por exemplo o segredo do webhook:"
Write-Host '  $b = kubectl -n revenda get secret revenda-webhook-secret -o jsonpath="{.data.WEBHOOK_SECRET}"'
Write-Host '  [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b))'
Write-Host "Senha do admin do Grafana: o mesmo comando com -n observabilidade, secret grafana-admin, chave GF_SECURITY_ADMIN_PASSWORD"
Write-Host ""
Write-Host "Aplicacao: merge na main ou  gh workflow run cd.yml  (CD no runner kind-local)."
Write-Host "Log: $log"
Stop-Transcript | Out-Null
exit 0
