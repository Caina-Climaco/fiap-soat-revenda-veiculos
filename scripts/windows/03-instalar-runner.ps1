# Instala e registra o runner self-hosted do GitHub Actions (CD local, ADR-006).
#
# Uso (PowerShell normal, SEM administrador, logado como o usuario que usa o Docker Desktop):
#   powershell -ExecutionPolicy Bypass -File .\scripts\windows\03-instalar-runner.ps1 [-Reconfigurar]
#
# O que faz:
#   1. confere gh (autenticado), git/Git Bash, docker, kind, kubectl e terraform;
#   2. baixa a versao mais recente do runner (win-x64) de github.com/actions/runner/releases
#      e confere o SHA-256 publicado nas notas do release (e o digest do asset, se houver);
#   3. registra o runner no repositorio com as labels self-hosted, Windows, X64 e kind-local,
#      nome <computador>-kind, diretorio de trabalho _work (token de registro via gh api);
#   4. cria uma Tarefa Agendada no logon do usuario atual que executa run.cmd, por um wrapper
#      que poe o Git Bash no inicio do PATH (sem servico e
#      sem admin: o runner roda como o usuario logado e enxerga o Docker Desktop e
#      %USERPROFILE%\.kube\config) e a inicia imediatamente;
#   5. espera o runner aparecer "online" no GitHub.
# Sem -Reconfigurar, um runner ja configurado no diretorio e mantido (ele se atualiza
# sozinho); so a tarefa agendada e recriada e iniciada.
# Diretorio do runner: C:\Projetos\fiap\runner-revenda (FORA do repositorio).
# Log: .setup\relatorio-runner.txt (pasta ignorada pelo git).
# Arquivo somente ASCII (compatibilidade com Windows PowerShell 5.1).
param(
    [string]$Repositorio = "Caina-Climaco/fiap-soat-revenda-veiculos",
    [string]$Diretorio = "C:\Projetos\fiap\runner-revenda",
    [string]$Labels = "kind-local",
    [string]$NomeTarefa = "GitHub Actions Runner - revenda",
    [switch]$Reconfigurar
)

$ErrorActionPreference = "Continue"
# Recarrega o PATH do registro: ferramentas instaladas pelo winget nesta sessao
# (kind, terraform) so aparecem em janelas novas do PowerShell.
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$log = Join-Path $raiz ".setup\relatorio-runner.txt"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
Start-Transcript -Path $log -Force | Out-Null

# Executa um comando nativo mostrando stdout e stderr (inclusive no transcript, que no
# PowerShell 5.1 so registra o que passa pelo pipeline) e devolve o codigo de saida.
# -Mascarar: valores que nunca devem aparecer no log (ex.: token de registro).
function Invocar {
    param([string]$Exe, [string[]]$Argumentos, [string[]]$Mascarar = @())
    $texto = "$Exe $($Argumentos -join ' ')"
    foreach ($m in $Mascarar) { if ($m) { $texto = $texto.Replace($m, "***") } }
    Write-Host ">> $texto"
    $global:LASTEXITCODE = 0
    & $Exe @Argumentos 2>&1 | ForEach-Object {
        $linha = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" }
        foreach ($m in $Mascarar) { if ($m) { $linha = $linha.Replace($m, "***") } }
        $linha
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

Write-Host "03-instalar-runner.ps1 - $(Get-Date -Format s)"
Write-Host "Repositorio: $Repositorio | Diretorio: $Diretorio | Labels: $Labels"

# ------------------------------------------------------------------ pre-requisitos
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($admin) {
    Write-Host "AVISO: sessao com privilegio de administrador. Prefira um PowerShell comum: a tarefa"
    Write-Host "       agendada roda com privilegio limitado de qualquer forma (docs/08, secao 5)."
}
foreach ($f in @("gh", "git", "docker", "kind", "kubectl", "terraform")) {
    if (-not (Get-Command $f -ErrorAction SilentlyContinue)) {
        Falhar "'$f' nao encontrado no PATH (rode scripts\windows\01-instalar-ferramentas.ps1)."
    }
}
if ((Invocar "gh" @("auth", "status")) -ne 0) { Falhar "gh nao autenticado (gh auth login)." }
if ((Invocar "docker" @("version", "--format", "docker {{.Server.Version}}")) -ne 0) {
    Falhar "Docker Desktop nao responde para este usuario. Inicie o Docker Desktop e tente de novo."
}

# Git Bash: os passos do cd.yml usam `shell: bash`. No Windows o runner resolve `bash` pelo
# PATH do processo; o instalador do Git so poe Git\cmd no PATH, e o bash.exe do WSL
# (C:\Windows\System32) viria antes. Por isso a tarefa inicia o runner por um wrapper
# (iniciar-runner.cmd) que coloca Git\bin no inicio do PATH.
$gitExec = (& git --exec-path 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $gitExec) { Falhar "git --exec-path falhou." }
$gitRaiz = $gitExec -replace '/', '\'
$gitRaiz = $gitRaiz -replace '\\(mingw64|clangarm64|mingw32)\\libexec\\git-core\\?$', ''
$gitBin = Join-Path $gitRaiz "bin"
if (-not (Test-Path (Join-Path $gitBin "bash.exe"))) {
    Falhar "Git Bash nao encontrado em $gitBin (instale o Git for Windows)."
}
Write-Host "Git Bash: $gitBin\bash.exe"

# ------------------------------------------------------------------ runner ja configurado?
$configurado = Test-Path (Join-Path $Diretorio ".runner")

# Para a tarefa e qualquer processo do runner deste diretorio (antes de reconfigurar/atualizar)
$tarefa = Get-ScheduledTask -TaskName $NomeTarefa -ErrorAction SilentlyContinue
if ($tarefa) {
    Write-Host "Parando a tarefa agendada existente '$NomeTarefa'"
    Stop-ScheduledTask -TaskName $NomeTarefa -ErrorAction SilentlyContinue
}
Get-Process -Name "Runner.Listener", "Runner.Worker" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($Diretorio, [StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object { Write-Host "Encerrando $($_.ProcessName) (PID $($_.Id))"; Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

if ($configurado -and $Reconfigurar) {
    Write-Host "Removendo a configuracao atual do runner (-Reconfigurar)"
    $tokenRemocao = (& gh api -X POST "repos/$Repositorio/actions/runners/remove-token" --jq .token)
    if ($LASTEXITCODE -ne 0 -or -not $tokenRemocao) { Falhar "nao foi possivel obter o token de remocao (gh api)." }
    Push-Location $Diretorio
    $codigo = Invocar (Join-Path $Diretorio "config.cmd") @("remove", "--token", $tokenRemocao) -Mascarar @($tokenRemocao)
    Pop-Location
    if ($codigo -ne 0) { Falhar "config.cmd remove falhou (codigo $codigo)." }
    $configurado = $false
}

if (-not $configurado) {
    # -------------------------------------------------------------- download verificado
    Write-Host "Consultando o release mais recente de actions/runner"
    $json = (& gh api "repos/actions/runner/releases/latest") -join "`n"
    if ($LASTEXITCODE -ne 0 -or -not $json) { Falhar "gh api repos/actions/runner/releases/latest falhou." }
    $release = $json | ConvertFrom-Json
    $versao = $release.tag_name.TrimStart("v")
    $arquivo = "actions-runner-win-x64-$versao.zip"
    $asset = $release.assets | Where-Object { $_.name -eq $arquivo } | Select-Object -First 1
    if (-not $asset) { Falhar "asset $arquivo nao encontrado no release $($release.tag_name)." }

    $m = [regex]::Match([string]$release.body, '<!-- BEGIN SHA win-x64 -->\s*([0-9a-fA-F]{64})\s*<!-- END SHA win-x64 -->')
    if (-not $m.Success) { Falhar "SHA-256 do pacote win-x64 nao encontrado nas notas do release $($release.tag_name)." }
    $shaPublicado = $m.Groups[1].Value.ToLowerInvariant()
    if ($asset.digest -and $asset.digest -like "sha256:*") {
        $shaAsset = $asset.digest.Substring(7).ToLowerInvariant()
        if ($shaAsset -ne $shaPublicado) { Falhar "SHA-256 das notas ($shaPublicado) difere do digest do asset ($shaAsset)." }
    }
    Write-Host "Versao: $versao | SHA-256 publicado: $shaPublicado"

    New-Item -ItemType Directory -Force -Path $Diretorio | Out-Null
    $zip = Join-Path $env:TEMP $arquivo
    Write-Host "Baixando $($asset.browser_download_url)"
    try {
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
    } catch {
        Falhar "download falhou: $($_.Exception.Message)"
    }
    $shaLocal = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($shaLocal -ne $shaPublicado) {
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        Falhar "SHA-256 do arquivo baixado ($shaLocal) NAO confere com o publicado ($shaPublicado)."
    }
    Write-Host "SHA-256 conferido."
    try {
        Expand-Archive -Path $zip -DestinationPath $Diretorio -Force
    } catch {
        Falhar "falha ao extrair ${zip}: $($_.Exception.Message)"
    }
    Remove-Item $zip -Force -ErrorAction SilentlyContinue

    # -------------------------------------------------------------- registro no repositorio
    $token = (& gh api -X POST "repos/$Repositorio/actions/runners/registration-token" --jq .token)
    if ($LASTEXITCODE -ne 0 -or -not $token) { Falhar "nao foi possivel obter o token de registro (escopo repo do gh?)." }
    $nome = "$($env:COMPUTERNAME.ToLowerInvariant())-kind"
    Push-Location $Diretorio
    $codigo = Invocar (Join-Path $Diretorio "config.cmd") @(
        "--unattended",
        "--url", "https://github.com/$Repositorio",
        "--token", $token,
        "--labels", $Labels,
        "--name", $nome,
        "--work", "_work",
        "--replace"
    ) -Mascarar @($token)
    Pop-Location
    if ($codigo -ne 0) { Falhar "config.cmd falhou (codigo $codigo)." }
} else {
    Write-Host "Runner ja configurado em $Diretorio (use -Reconfigurar para registrar de novo)."
}

# ------------------------------------------------------------------ wrapper de inicio
# Git\bin primeiro no PATH (bash do Git Bash, nao o do WSL) e entao o run.cmd oficial.
$wrapper = Join-Path $Diretorio "iniciar-runner.cmd"
$conteudo = @(
    "@echo off",
    "rem Gerado por scripts\windows\03-instalar-runner.ps1",
    "set ""PATH=$gitBin;%PATH%""",
    "cd /d ""%~dp0""",
    "call ""%~dp0run.cmd"""
)
Set-Content -Path $wrapper -Value $conteudo -Encoding ascii
Write-Host "Wrapper: $wrapper (PATH comeca por $gitBin)"

# ------------------------------------------------------------------ tarefa agendada
$usuario = "$env:USERDOMAIN\$env:USERNAME"
if (-not (Test-Path (Join-Path $Diretorio "run.cmd"))) { Falhar "run.cmd nao encontrado em $Diretorio." }
try {
    $acao = New-ScheduledTaskAction -Execute $wrapper -WorkingDirectory $Diretorio
    $gatilho = New-ScheduledTaskTrigger -AtLogOn -User $usuario
    $principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited
    $config = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $NomeTarefa -Action $acao -Trigger $gatilho -Principal $principal `
        -Settings $config -Description "Runner self-hosted (label kind-local) do repositorio $Repositorio. Criado por scripts\windows\03-instalar-runner.ps1." `
        -Force -ErrorAction Stop | Out-Null
    Write-Host "Tarefa agendada '$NomeTarefa' registrada (logon de $usuario, privilegio limitado)."
    Start-ScheduledTask -TaskName $NomeTarefa -ErrorAction Stop
    Write-Host "Tarefa iniciada: uma janela de console do runner fica aberta (nao feche)."
} catch {
    Falhar "falha ao registrar/iniciar a tarefa agendada: $($_.Exception.Message)"
}

# ------------------------------------------------------------------ confirmacao
$nomeRunner = "$($env:COMPUTERNAME.ToLowerInvariant())-kind"
$status = ""
for ($i = 1; $i -le 24; $i++) {
    Start-Sleep -Seconds 5
    $json = (& gh api "repos/$Repositorio/actions/runners") -join "`n"
    if ($LASTEXITCODE -ne 0 -or -not $json) { continue }
    $r = ($json | ConvertFrom-Json).runners | Where-Object { $_.name -eq $nomeRunner } | Select-Object -First 1
    if ($r) {
        $status = "$($r.status) [$((@($r.labels | ForEach-Object { $_.name })) -join ', ')]"
        if ($r.status -eq "online") { break }
    }
}
if ($status -like "online*") {
    Write-Host "Runner '$nomeRunner' ONLINE: $status"
} else {
    Write-Host "AVISO: runner '$nomeRunner' ainda nao aparece online (status: '$status')."
    Write-Host "       Veja a janela do runner e $Diretorio\_diag. Settings > Actions > Runners no GitHub."
}
Write-Host ""
Write-Host "Proximos passos: scripts\windows\04-subir-ambiente.ps1 (opcional; o CD tambem aplica o"
Write-Host "Terraform) e um merge na main ou: gh workflow run cd.yml -R $Repositorio"
Write-Host "Log: $log"
Stop-Transcript | Out-Null
exit 0
