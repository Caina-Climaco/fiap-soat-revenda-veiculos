# keycloak — realm `revenda`

`realm-revenda.json` é importado pelo Keycloak 26.7 na inicialização (`start-dev --import-realm`), a partir do ConfigMap `keycloak-realm-revenda` (Terraform) ou do volume do `docker-compose.yml`.

| Item | Configuração |
|---|---|
| Realm | autocadastro habilitado, login por e-mail, e-mail único, proteção contra força bruta, `sslRequired=none` (só local), idioma padrão `pt-BR`, ação "Delete Account" habilitada (LGPD, docs/07 §5.5) |
| Papéis | `cliente` (dentro de `default-roles-revenda`: todo autocadastrado vira cliente) e `gestor` |
| Perfil de usuário | declarativo (componente `org.keycloak.userprofile.UserProfileProvider`, chave `kc.user.profile.config`): username, e-mail, nome e sobrenome obrigatórios; `cpf` obrigatório (`^\d{11}$`); `telefone` opcional (`^\d{10,11}$`) |
| `revenda-api` | confidencial, sem fluxos: existe só como audiência (`aud`) |
| `revenda-swagger` | público, Authorization Code + PKCE S256, redirect `http://localhost:8080/docs/oauth2-redirect` |
| `revenda-e2e` | público com password grant — **somente ambiente local** (testes e2e); remover em produção |
| Mappers e escopos | `oidc-audience-mapper` com `revenda-api` nos dois clients públicos; escopos **padrão** `basic` (claim `sub`), `roles` (`realm_access`), `web-origins`, `acr`; `profile` e `email` são **opcionais** (só entram no token se pedidos em `scope`) |
| Usuário seed | `gestor.loja` (gestor@revenda.local, CPF 00000000000), **somente** o papel `gestor` |

## Minimização de dados no token (LGPD)

Nos clients `revenda-swagger` e `revenda-e2e`, os escopos `profile` e `email` são opcionais: como o Swagger UI e o e2e pedem só `scope=openid`, o access token leva `sub`, papéis, `aud`/`azp` e metadados, sem nome, sobrenome, username ou e-mail. A API usa apenas `sub` (pseudônimo do comprador) e `realm_access.roles`; o e2e cria e apaga usuários pela Admin API e usa o token só para autorizar. Um cliente que precise desses dados (ex.: um front para exibir o nome) pode pedi-los explicitamente (`scope=openid profile email`). O CI (`jq`) barra a volta de `profile`/`email` aos escopos padrão.

## Senha do `gestor.loja`

O arquivo traz `"value": "${GESTOR_PASSWORD}"`. No import de inicialização o Keycloak substitui `${VAR}` pelo valor da variável de ambiente **no texto do arquivo, antes de ler o JSON** (guia oficial "Importing and exporting realms", seção *Using Environment Variables within the Realm Configuration Files*; no código, `AbstractFileBasedImportProvider` da tag 26.7.1, a mesma da imagem `quay.io/keycloak/keycloak:26.7.1`). Placeholders sem variável correspondente ficam como estão — por isso `${username}`, `${email}` etc. do perfil continuam sendo chaves de tradução. A variável vem do Secret `identidade/keycloak-gestor` (chave `GESTOR_PASSWORD`).

Limite: o import é `IGNORE_EXISTING` — o realm só é criado na primeira subida. Para a senha não divergir do Secret (rotação com `terraform apply -replace=random_password.keycloak_gestor`, state recriado com o banco preservado), o Terraform roda o Job `keycloak-gestor-senha`, que com `kcadm.sh` cria o usuário se faltar, redefine a senha a partir do Secret, garante o papel `gestor` e remove `default-roles-revenda` e `cliente` (que a Admin API atribui a todo usuário criado), deixando o gestor só com o papel `gestor`, como no import (idempotente; reexecutado quando a senha ou o Deployment do Keycloak mudam).

Pelo mesmo motivo, **mudanças neste JSON não chegam a um realm já existente**: recrie o ambiente (`scripts/windows/05-destruir-ambiente.ps1` e `04-subir-ambiente.ps1`) ou aplique a mudança pela Admin API/console. Isso vale para a mudança de `profile`/`email` para escopos opcionais: um realm criado antes dela continua emitindo nome e e-mail no token até ser recriado. O admin bootstrap (`keycloak-admin`) também só é criado na primeira subida: rotacioná-lo exige recriar o `keycloak-db`.

## Limitações conhecidas

- Unicidade do CPF não é garantida pelo Keycloak (R6); o e-mail é o identificador único.
- O CPF é editável pelo usuário (contrato 14.2), enquanto docs/07 §5.5 diz que alterá-lo "passa pelo administrador": o perfil declarativo não tem permissão "só no cadastro"; restringir a edição ao admin tiraria o campo do formulário de registro.
