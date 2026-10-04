# keycloak — realm `revenda`

`realm-revenda.json` é importado pelo Keycloak 26.4 na inicialização (`start-dev --import-realm`), a partir do ConfigMap `keycloak-realm-revenda` (Terraform) ou do volume do `docker-compose.yml`.

| Item | Configuração |
|---|---|
| Realm | autocadastro habilitado, login por e-mail, e-mail único, proteção contra força bruta, `sslRequired=none` (só local), idioma padrão `pt-BR`, ação "Delete Account" habilitada (LGPD, docs/07 §5.5) |
| Papéis | `cliente` (dentro de `default-roles-revenda`: todo autocadastrado vira cliente) e `gestor` |
| Perfil de usuário | declarativo (componente `org.keycloak.userprofile.UserProfileProvider`, chave `kc.user.profile.config`): username, e-mail, nome e sobrenome obrigatórios; `cpf` obrigatório (`^\d{11}$`); `telefone` opcional (`^\d{10,11}$`) |
| `revenda-api` | confidencial, sem fluxos: existe só como audiência (`aud`) |
| `revenda-swagger` | público, Authorization Code + PKCE S256, redirect `http://localhost:8080/docs/oauth2-redirect` |
| `revenda-e2e` | público com password grant — **somente ambiente local** (testes e2e); remover em produção |
| Mappers | `oidc-audience-mapper` com `revenda-api` nos dois clients públicos; escopos padrão `basic`, `roles`, `profile`, `email`, `web-origins`, `acr` |
| Usuário seed | `gestor.loja` (gestor@revenda.local, CPF 00000000000), papel `gestor` |

## Senha do `gestor.loja`

O arquivo traz `"value": "${GESTOR_PASSWORD}"`. No import de inicialização o Keycloak substitui `${VAR}` pelo valor da variável de ambiente **no texto do arquivo, antes de ler o JSON** (guia oficial "Importing and exporting realms", seção *Using Environment Variables within the Realm Configuration Files*; no código, `AbstractFileBasedImportProvider` da tag 26.4.16). Placeholders sem variável correspondente ficam como estão — por isso `${username}`, `${email}` etc. do perfil continuam sendo chaves de tradução. A variável vem do Secret `identidade/keycloak-gestor` (chave `GESTOR_PASSWORD`).

Limite: o import é `IGNORE_EXISTING` — o realm só é criado na primeira subida. Para a senha não divergir do Secret (rotação com `terraform apply -replace=random_password.keycloak_gestor`, state recriado com o banco preservado), o Terraform roda o Job `keycloak-gestor-senha`, que com `kcadm.sh` cria o usuário se faltar, redefine a senha a partir do Secret e garante o papel `gestor` (idempotente; reexecutado quando a senha ou o Deployment do Keycloak mudam).

Pelo mesmo motivo, **mudanças neste JSON não chegam a um realm já existente**: recrie o ambiente (`scripts/windows/05-destruir-ambiente.ps1` e `04-subir-ambiente.ps1`) ou aplique a mudança pela Admin API/console. O admin bootstrap (`keycloak-admin`) também só é criado na primeira subida: rotacioná-lo exige recriar o `keycloak-db`.

## Limitações conhecidas

- Unicidade do CPF não é garantida pelo Keycloak (R6); o e-mail é o identificador único.
- O CPF é editável pelo usuário (contrato 14.2), enquanto docs/07 §5.5 diz que alterá-lo "passa pelo administrador": o perfil declarativo não tem permissão "só no cadastro"; restringir a edição ao admin tiraria o campo do formulário de registro.
