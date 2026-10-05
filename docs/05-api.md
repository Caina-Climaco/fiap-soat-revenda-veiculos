# 05 — Contrato da API

Este documento é o contrato HTTP da `revenda-api`: convenções gerais, autenticação e autorização, formato de erros e paginação e, para cada endpoint, papel exigido, parâmetros, exemplos de requisição e resposta e códigos de erro. Ele é a referência para o time de front-end e para os testes de API e e2e ([09-testes.md](09-testes.md)). A especificação OpenAPI gerada pela aplicação, disponível em `http://localhost:8080/docs` (Swagger UI) e `http://localhost:8080/openapi.json`, deve permanecer coerente com este documento. As regras de negócio por trás dos códigos de erro estão em [02-modelagem-ddd.md](02-modelagem-ddd.md).

## 1. Convenções

| Item | Convenção |
|---|---|
| Base URL (local) | `http://localhost:8080` |
| Prefixo de versão | `/api/v1` para todos os recursos de negócio. Os endpoints de saúde (`/health/*`) ficam fora do prefixo |
| Formato | `application/json; charset=utf-8` em requisições e respostas de sucesso; `application/problem+json` em erros |
| Nomes de campos | `snake_case`, em português sem acento, alinhados à linguagem ubíqua (`preco_venda`, `codigo_pagamento`) |
| Identificadores | UUID v4 em texto (`"6f1c2a9e-4b7d-4e0a-9c55-2d8f3b1a7e40"`) |
| Datas e horas | ISO-8601 em **UTC** com sufixo `Z` e precisão de segundos: `"2026-10-03T14:05:00Z"` |
| Valores monetários | **String decimal** com duas casas e ponto como separador: `"89900.00"`. Nunca número de ponto flutuante. Moeda implícita: BRL |
| Enums | Texto em maiúsculas: `A_VENDA`, `RESERVADO`, `VENDIDO`, `AGUARDANDO_PAGAMENTO`, `EFETIVADA`, `CANCELADA` |
| Campos nulos | Campos opcionais sem valor são retornados como `null` (não são omitidos) |
| Criação | `201 Created` com header `Location` apontando para o recurso criado |
| Correlação | Header opcional `X-Request-ID`; se ausente, a API gera um UUID e o devolve na resposta e nos logs |

### 1.1 Paginação

As listagens aceitam `limite` (padrão 20, mínimo 1, máximo 100) e `deslocamento` (padrão 0, mínimo 0, **máximo 1.000.000**). Valores fora da faixa resultam em `422`. O teto do deslocamento evita consultas com `OFFSET` gigantesco, que forçariam o banco a percorrer e descartar milhões de linhas, uma forma barata de negação de serviço.

```json
{
  "itens": [],
  "total": 0,
  "limite": 20,
  "deslocamento": 0
}
```

`total` é a quantidade de itens que satisfazem o filtro, independentemente da página.

### 1.2 Erros (RFC 9457, `application/problem+json`)

Todos os erros seguem a RFC 9457 (Problem Details for HTTP APIs) com os membros `type`, `title`, `status`, `detail` e `instance`. O `type` é um URN estável por tipo de problema; a API acrescenta o membro de extensão `request_id` e, em erros de validação, `erros`.

```http
HTTP/1.1 409 Conflict
Content-Type: application/problem+json

{
  "type": "urn:revenda:problema:veiculo-indisponivel",
  "title": "Veículo indisponível para compra",
  "status": 409,
  "detail": "O veículo 6f1c2a9e-4b7d-4e0a-9c55-2d8f3b1a7e40 não está à venda (status atual: RESERVADO).",
  "instance": "/api/v1/vendas",
  "request_id": "0b8e1f52-1d3a-4c8e-9f0e-7a2b6c4d9e11"
}
```

Erro de validação (`422`). As mensagens de `erros` são em português, tanto as das regras de domínio quanto as de tipo e formato geradas na validação da entrada:

```json
{
  "type": "urn:revenda:problema:validacao",
  "title": "Dados inválidos",
  "status": 422,
  "detail": "Um ou mais campos são inválidos.",
  "instance": "/api/v1/veiculos",
  "request_id": "5d0c7a3e-2f41-4b9a-8e6d-1c3b5a7f9e20",
  "erros": [
    { "campo": "ano", "mensagem": "deve estar entre 1950 e 2027" },
    { "campo": "preco", "mensagem": "deve ser maior que zero" }
  ]
}
```

Catálogo de tipos de problema:

| `type` (sufixo após `urn:revenda:problema:`) | Status | Quando ocorre |
|---|---|---|
| `requisicao-malformada` | 400 | JSON inválido ou corpo ilegível |
| `nao-autenticado` | 401 | Token ausente, expirado, com assinatura inválida, `iss`/`aud`/`azp` incorretos |
| `webhook-nao-autorizado` | 401 | `X-Webhook-Secret` ausente ou incorreto |
| `acesso-negado` | 403 | Token válido, mas sem o papel exigido |
| `veiculo-nao-encontrado` | 404 | Veículo inexistente |
| `venda-nao-encontrada` | 404 | Venda inexistente, ou existente mas pertencente a outro comprador |
| `pagamento-nao-encontrado` | 404 | `codigo_pagamento` desconhecido no webhook |
| `veiculo-nao-editavel` | 409 | Edição de veículo que não está `A_VENDA` |
| `veiculo-indisponivel` | 409 | Compra de veículo `RESERVADO` (reserva vigente) ou `VENDIDO` |
| `transicao-invalida` | 409 | Transição de estado não permitida (ex.: cancelar venda `EFETIVADA`) |
| `reserva-expirada` | 409 | Webhook `APROVADO` para venda cuja reserva venceu (a venda é cancelada) |
| `conflito-concorrencia` | 409 | Atualização concorrente detectada pela `versao` do veículo |
| `validacao` | 422 | Campos fora das regras (tipos, faixas, tamanhos, caracteres de controle, parâmetros de consulta) |
| `erro-interno` | 500 | Falha inesperada; o `detail` nunca expõe stack trace nem SQL |
| `indisponivel` | 503 | Banco indisponível (apenas em `/health/ready`) |

## 2. Autenticação e autorização

### 2.1 Fluxos

| Consumidor | Fluxo OAuth 2.0 / OIDC | Client no Keycloak |
|---|---|---|
| Swagger UI (`/docs`) e front-end | Authorization Code + PKCE (S256) | `revenda-swagger` (público) |
| Testes e2e (somente ambiente local) | Resource Owner Password Credentials | `revenda-e2e` (público, `directAccessGrantsEnabled`) |
| Gateway de pagamento | Não usa OAuth; segredo compartilhado no header `X-Webhook-Secret` | — |

Endpoints do Keycloak (realm `revenda`, implantado pelo repositório [fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade)), a partir do host:

- Discovery: `http://localhost:8180/realms/revenda/.well-known/openid-configuration`
- Autorização: `http://localhost:8180/realms/revenda/protocol/openid-connect/auth`
- Token: `http://localhost:8180/realms/revenda/protocol/openid-connect/token`
- Cadastro (tela do realm): link "Register" na página de login
- Conta do titular: `http://localhost:8180/realms/revenda/account`

### 2.2 Validação do token na API

O access token é um JWT assinado com **RS256**. A API rejeita com `401` qualquer token que não cumpra **todas** as verificações:

| Claim / verificação | Regra |
|---|---|
| Assinatura | RS256 com a chave do JWKS cujo `kid` coincide com o header do token. JWKS obtido do endereço interno do Keycloak e mantido em cache (TTL de 10 min; recarga imediata ao encontrar `kid` desconhecido, com limite de uma recarga por minuto). Algoritmos diferentes de RS256 (incluindo `none` e HS256) são recusados |
| `iss` | Igual a `http://localhost:8180/realms/revenda` (configurável por `OIDC_ISSUER`) |
| `exp` | No futuro, com tolerância de 30 s para diferença de relógio; `nbf`/`iat` respeitados quando presentes |
| `aud` | Contém `revenda-api` (adicionado por *audience mapper* nos clients) |
| `azp` | Pertence à lista de clients autorizados (`revenda-swagger`, `revenda-e2e`) |
| `sub` | Presente; é usado como `comprador_id` |
| `realm_access.roles` | Usado para o RBAC (`cliente`, `gestor`) |

### 2.3 Papéis

| Papel | Quem | Atribuição |
|---|---|---|
| `cliente` | Pessoa que se autocadastrou | Papel padrão do realm (default roles), concedido no registro |
| `gestor` | Funcionário da loja | Atribuído pelo administrador do realm; usuário seed `gestor.loja` |
| público | Qualquer pessoa, sem token | — |

O usuário `gestor.loja` **não** recebe o papel `cliente` (por isso o passo 4 do roteiro, "gestor tenta comprar", resulta em `403`). Mesmo um token que tenha os dois papéis é recusado com `403` em `POST /api/v1/vendas`: gestor não compra (RN-05, segregação de funções).

## 3. Recursos

### 3.1 Representação de Veículo

```json
{
  "id": "6f1c2a9e-4b7d-4e0a-9c55-2d8f3b1a7e40",
  "marca": "Toyota",
  "modelo": "Corolla XEi 2.0",
  "ano": 2022,
  "cor": "Prata",
  "preco": "124900.00",
  "status": "A_VENDA",
  "versao": 1,
  "criado_em": "2026-10-03T13:10:00Z",
  "atualizado_em": "2026-10-03T13:10:00Z"
}
```

| Campo | Tipo | Regras |
|---|---|---|
| `marca` | string | 1 a 60 caracteres, espaços nas pontas removidos; sem caracteres de controle |
| `modelo` | string | 1 a 60 caracteres; sem caracteres de controle |
| `ano` | inteiro (estrito) | 1950 até o ano corrente + 1. Tipo estrito: só número inteiro JSON; texto (`"2023"`), número com casas decimais ou booleano resultam em 422 |
| `cor` | string | 1 a 30 caracteres; sem caracteres de controle |
| `preco` | string decimal | > 0, no máximo 10 dígitos inteiros e 2 decimais (`NUMERIC(12,2)`) |
| `status` | enum | `A_VENDA`, `RESERVADO`, `VENDIDO` (somente leitura) |
| `versao` | inteiro | Incrementado a cada alteração efetiva (somente leitura) |

**Caracteres de controle.** `marca`, `modelo` e `cor` recusam caracteres de controle com `422`: a faixa C0 (`\u0000` a `\u001f`, que inclui quebra de linha e tabulação) e o DEL (`\u007f`). O PostgreSQL nem aceitaria o NUL num campo de texto. Esses campos aparecem em listagens, no *snapshot* da venda e nos logs; aceitar controles abriria espaço para injeção em logs e para textos que quebram a exibição no front-end.

### 3.2 Representação de Venda

```json
{
  "id": "c3a7d1e2-58b4-4f6a-a1d9-0e2f4b6c8a10",
  "veiculo_id": "6f1c2a9e-4b7d-4e0a-9c55-2d8f3b1a7e40",
  "veiculo": { "marca": "Toyota", "modelo": "Corolla XEi 2.0", "ano": 2022, "cor": "Prata" },
  "preco_venda": "124900.00",
  "status": "AGUARDANDO_PAGAMENTO",
  "codigo_pagamento": "PAG-3f9a1c0b7e21",
  "expira_em": "2026-10-03T14:35:00Z",
  "criada_em": "2026-10-03T14:05:00Z",
  "efetivada_em": null,
  "cancelada_em": null,
  "motivo_cancelamento": null
}
```

`veiculo` é o *snapshot* gravado no momento da compra, e `preco_venda` é o preço congelado; ambos não mudam se o veículo for editado depois (o que, pelas regras de Catálogo, só ocorreria após a venda ser cancelada). Para o papel `gestor`, a resposta inclui também `"comprador_id": "8d2f6b1c-3e4a-4f5b-9c7d-1a2b3c4d5e6f"` (o `sub` do comprador). Para o próprio cliente e para o gateway, o campo não é retornado.

## 4. Endpoints

Resumo:

| Método | Rota | Papel | Sucesso |
|---|---|---|---|
| GET | `/health/live` | público | 200 |
| GET | `/health/ready` | público | 200 / 503 |
| GET | `/metrics` | público no ambiente local (ver 4.14) | 200 |
| POST | `/api/v1/veiculos` | gestor | 201 |
| PATCH | `/api/v1/veiculos/{id}` | gestor | 200 |
| GET | `/api/v1/veiculos/{id}` | público | 200 |
| GET | `/api/v1/veiculos/a-venda` | público | 200 |
| GET | `/api/v1/veiculos/vendidos` | público | 200 |
| POST | `/api/v1/vendas` | cliente | 201 |
| GET | `/api/v1/vendas/minhas` | cliente | 200 |
| GET | `/api/v1/vendas/{id}` | dono (cliente) ou gestor | 200 |
| GET | `/api/v1/vendas` | gestor | 200 |
| POST | `/api/v1/vendas/{id}/cancelar` | dono (cliente) ou gestor | 200 |
| POST | `/api/v1/pagamentos/webhook` | gateway (`X-Webhook-Secret`) | 200 |

### 4.1 `GET /health/live`

Indica que o processo está de pé (liveness). Não acessa o banco.

```http
GET /health/live HTTP/1.1
Host: localhost:8080
```

```json
{ "status": "ok" }
```

Erros: nenhum previsto (falha = processo não responde, e o kubelet reinicia o container).

### 4.2 `GET /health/ready`

Indica que a instância pode receber tráfego (readiness): executa `SELECT 1` no banco com timeout de 2 s.

```json
{ "status": "ok", "verificacoes": { "banco": "ok" } }
```

| Código | Quando |
|---|---|
| 503 | Banco inacessível; corpo `problem+json` com `type` `urn:revenda:problema:indisponivel` e `verificacoes.banco = "falha"` |

### 4.3 `POST /api/v1/veiculos` — cadastrar veículo

Papel: **gestor**. Cria um veículo com status `A_VENDA` e `versao = 1`. Evento: `VeiculoCadastrado`.

```http
POST /api/v1/veiculos HTTP/1.1
Host: localhost:8080
Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6Ii4uLiJ9...
Content-Type: application/json

{
  "marca": "Volkswagen",
  "modelo": "Gol 1.0 MPI",
  "ano": 2021,
  "cor": "Branco",
  "preco": "54900.00"
}
```

```http
HTTP/1.1 201 Created
Location: /api/v1/veiculos/1e9b7c3d-2a4f-4d6e-8b1a-5c7d9e0f2a34
Content-Type: application/json

{
  "id": "1e9b7c3d-2a4f-4d6e-8b1a-5c7d9e0f2a34",
  "marca": "Volkswagen",
  "modelo": "Gol 1.0 MPI",
  "ano": 2021,
  "cor": "Branco",
  "preco": "54900.00",
  "status": "A_VENDA",
  "versao": 1,
  "criado_em": "2026-10-03T13:12:41Z",
  "atualizado_em": "2026-10-03T13:12:41Z"
}
```

| Código | Quando |
|---|---|
| 400 | JSON malformado |
| 401 | Sem token ou token inválido |
| 403 | Token sem papel `gestor` |
| 422 | Campo ausente ou fora das regras (ex.: `ano` 1949 ou `"2023"` como texto, `preco` `"0.00"`, `preco` como número com mais de 2 casas, `marca` com quebra de linha) |

### 4.4 `PATCH /api/v1/veiculos/{id}` — editar veículo

Papel: **gestor**. Atualização parcial de `marca`, `modelo`, `ano`, `cor` e/ou `preco` (ao menos um campo). Só é permitida com o veículo em `A_VENDA`. `status`, `versao` e datas não são editáveis (campos desconhecidos ou somente leitura resultam em 422). Corpo `application/json` com semântica de *merge* (campos ausentes não mudam). Evento: `VeiculoEditado`.

**Idempotência.** Um `PATCH` que não muda nenhum valor (por exemplo, o mesmo preço já gravado) responde `200` com o veículo como está: `versao` e `atualizado_em` não mudam e nenhum evento é registrado. Repetir a mesma edição, portanto, não gera versões novas.

Parâmetros: `id` (path, UUID).

```http
PATCH /api/v1/veiculos/1e9b7c3d-2a4f-4d6e-8b1a-5c7d9e0f2a34 HTTP/1.1
Authorization: Bearer eyJ...
Content-Type: application/json

{ "preco": "52900.00" }
```

```json
{
  "id": "1e9b7c3d-2a4f-4d6e-8b1a-5c7d9e0f2a34",
  "marca": "Volkswagen",
  "modelo": "Gol 1.0 MPI",
  "ano": 2021,
  "cor": "Branco",
  "preco": "52900.00",
  "status": "A_VENDA",
  "versao": 2,
  "criado_em": "2026-10-03T13:12:41Z",
  "atualizado_em": "2026-10-03T13:20:05Z"
}
```

| Código | Quando |
|---|---|
| 401 / 403 | Sem token / sem papel `gestor` |
| 404 | Veículo inexistente |
| 409 `veiculo-nao-editavel` | Veículo `RESERVADO` ou `VENDIDO` |
| 409 `conflito-concorrencia` | O veículo mudou entre a leitura e a gravação (ex.: foi reservado no mesmo instante) |
| 422 | Corpo vazio, campo inválido ou campo não editável |

### 4.5 `GET /api/v1/veiculos/{id}` — consultar veículo

Papel: **público**. Retorna o veículo em qualquer status. Se o veículo estiver `RESERVADO` por uma venda já vencida, a expiração preguiçosa é aplicada antes da leitura e a resposta mostra o veículo `A_VENDA` ([ADR-009](adrs/ADR-009-expiracao-preguicosa.md)).

```http
GET /api/v1/veiculos/1e9b7c3d-2a4f-4d6e-8b1a-5c7d9e0f2a34 HTTP/1.1
```

Resposta `200`: representação de Veículo (seção 3.1).

| Código | Quando |
|---|---|
| 404 | Veículo inexistente |
| 422 | `id` não é UUID |

### 4.6 `GET /api/v1/veiculos/a-venda` — listar veículos à venda

Papel: **público**. Lista os veículos com status `A_VENDA`, ordenados por `preco` ascendente; desempate por `criado_em` ascendente e, por fim, `id`. Antes da consulta, executa a varredura preguiçosa de reservas expiradas ([ADR-009](adrs/ADR-009-expiracao-preguicosa.md)).

Parâmetros de consulta: `limite`, `deslocamento`.

```http
GET /api/v1/veiculos/a-venda?limite=3&deslocamento=0 HTTP/1.1
```

```json
{
  "itens": [
    {
      "id": "1e9b7c3d-2a4f-4d6e-8b1a-5c7d9e0f2a34",
      "marca": "Volkswagen", "modelo": "Gol 1.0 MPI", "ano": 2021, "cor": "Branco",
      "preco": "52900.00", "status": "A_VENDA", "versao": 2,
      "criado_em": "2026-10-03T13:12:41Z", "atualizado_em": "2026-10-03T13:20:05Z"
    },
    {
      "id": "9a4c2e1f-7b3d-4c5a-8e6f-0d1b2c3a4e56",
      "marca": "Fiat", "modelo": "Argo Drive 1.3", "ano": 2023, "cor": "Vermelho",
      "preco": "79900.00", "status": "A_VENDA", "versao": 1,
      "criado_em": "2026-10-03T13:13:02Z", "atualizado_em": "2026-10-03T13:13:02Z"
    },
    {
      "id": "6f1c2a9e-4b7d-4e0a-9c55-2d8f3b1a7e40",
      "marca": "Toyota", "modelo": "Corolla XEi 2.0", "ano": 2022, "cor": "Prata",
      "preco": "124900.00", "status": "A_VENDA", "versao": 1,
      "criado_em": "2026-10-03T13:10:00Z", "atualizado_em": "2026-10-03T13:10:00Z"
    }
  ],
  "total": 3,
  "limite": 3,
  "deslocamento": 0
}
```

| Código | Quando |
|---|---|
| 422 | `limite` fora de 1..100 ou `deslocamento` fora de 0..1.000.000 |

### 4.7 `GET /api/v1/veiculos/vendidos` — listar veículos vendidos

Papel: **público**. Lista os veículos com status `VENDIDO`, ordenados por `preco` ascendente (desempate `criado_em` e `id`). O preço exibido é o do veículo, que, por estar congelado desde a reserva, coincide com o `preco_venda` da venda efetivada.

Parâmetros e formato de resposta iguais aos de 4.6.

```json
{
  "itens": [
    {
      "id": "9a4c2e1f-7b3d-4c5a-8e6f-0d1b2c3a4e56",
      "marca": "Fiat", "modelo": "Argo Drive 1.3", "ano": 2023, "cor": "Vermelho",
      "preco": "79900.00", "status": "VENDIDO", "versao": 3,
      "criado_em": "2026-10-03T13:13:02Z", "atualizado_em": "2026-10-03T14:07:30Z"
    }
  ],
  "total": 1,
  "limite": 20,
  "deslocamento": 0
}
```

| Código | Quando |
|---|---|
| 422 | Parâmetros de paginação inválidos |

### 4.8 `POST /api/v1/vendas` — iniciar compra

Papel: **cliente**. Reserva o veículo e cria a venda em `AGUARDANDO_PAGAMENTO`, com `codigo_pagamento` único (`PAG-` + 12 hexadecimais) e `expira_em` = agora + TTL (padrão 30 min). O `comprador_id` é o `sub` do token; o corpo **não** aceita dados do comprador. Eventos: `CompraIniciada`, `VeiculoReservado`.

```http
POST /api/v1/vendas HTTP/1.1
Authorization: Bearer eyJ...
Content-Type: application/json

{ "veiculo_id": "9a4c2e1f-7b3d-4c5a-8e6f-0d1b2c3a4e56" }
```

```http
HTTP/1.1 201 Created
Location: /api/v1/vendas/c3a7d1e2-58b4-4f6a-a1d9-0e2f4b6c8a10
Content-Type: application/json

{
  "id": "c3a7d1e2-58b4-4f6a-a1d9-0e2f4b6c8a10",
  "veiculo_id": "9a4c2e1f-7b3d-4c5a-8e6f-0d1b2c3a4e56",
  "veiculo": { "marca": "Fiat", "modelo": "Argo Drive 1.3", "ano": 2023, "cor": "Vermelho" },
  "preco_venda": "79900.00",
  "status": "AGUARDANDO_PAGAMENTO",
  "codigo_pagamento": "PAG-3f9a1c0b7e21",
  "expira_em": "2026-10-03T14:35:00Z",
  "criada_em": "2026-10-03T14:05:00Z",
  "efetivada_em": null,
  "cancelada_em": null,
  "motivo_cancelamento": null
}
```

| Código | Quando |
|---|---|
| 401 | Sem token ou token inválido |
| 403 | Token sem papel `cliente`, ou com papel `gestor` mesmo que também tenha `cliente` (RN-05) |
| 404 `veiculo-nao-encontrado` | `veiculo_id` inexistente |
| 409 `veiculo-indisponivel` | Veículo `VENDIDO` ou `RESERVADO` com reserva vigente (inclui o perdedor de uma disputa concorrente) |
| 422 | `veiculo_id` ausente ou não UUID |

### 4.9 `GET /api/v1/vendas/minhas` — minhas compras

Papel: **cliente**. Lista as vendas cujo `comprador_id` é o `sub` do token, em todos os status, ordenadas por `criada_em` descendente. Parâmetros: `limite`, `deslocamento`. Reservas vencidas são expiradas antes da consulta, para que nenhuma apareça como `AGUARDANDO_PAGAMENTO`.

```json
{
  "itens": [
    {
      "id": "c3a7d1e2-58b4-4f6a-a1d9-0e2f4b6c8a10",
      "veiculo_id": "9a4c2e1f-7b3d-4c5a-8e6f-0d1b2c3a4e56",
      "veiculo": { "marca": "Fiat", "modelo": "Argo Drive 1.3", "ano": 2023, "cor": "Vermelho" },
      "preco_venda": "79900.00",
      "status": "EFETIVADA",
      "codigo_pagamento": "PAG-3f9a1c0b7e21",
      "expira_em": "2026-10-03T14:35:00Z",
      "criada_em": "2026-10-03T14:05:00Z",
      "efetivada_em": "2026-10-03T14:07:30Z",
      "cancelada_em": null,
      "motivo_cancelamento": null
    }
  ],
  "total": 1,
  "limite": 20,
  "deslocamento": 0
}
```

| Código | Quando |
|---|---|
| 401 | Sem token ou token inválido |
| 403 | Token sem papel `cliente` |
| 422 | Paginação inválida |

### 4.10 `GET /api/v1/vendas/{id}` — consultar venda

Papel: **dono** (cliente cujo `sub` = `comprador_id`) ou **gestor**. Para um cliente que não é o dono, a API responde `404` (e não `403`), para não revelar a existência da venda (proteção contra BOLA/IDOR). Se a venda está `AGUARDANDO_PAGAMENTO` com a reserva vencida, ela é cancelada com `RESERVA_EXPIRADA` (e o veículo liberado) antes da resposta.

```http
GET /api/v1/vendas/c3a7d1e2-58b4-4f6a-a1d9-0e2f4b6c8a10 HTTP/1.1
Authorization: Bearer eyJ...   (gestor)
```

```json
{
  "id": "c3a7d1e2-58b4-4f6a-a1d9-0e2f4b6c8a10",
  "veiculo_id": "9a4c2e1f-7b3d-4c5a-8e6f-0d1b2c3a4e56",
  "veiculo": { "marca": "Fiat", "modelo": "Argo Drive 1.3", "ano": 2023, "cor": "Vermelho" },
  "preco_venda": "79900.00",
  "status": "EFETIVADA",
  "codigo_pagamento": "PAG-3f9a1c0b7e21",
  "expira_em": "2026-10-03T14:35:00Z",
  "criada_em": "2026-10-03T14:05:00Z",
  "efetivada_em": "2026-10-03T14:07:30Z",
  "cancelada_em": null,
  "motivo_cancelamento": null,
  "comprador_id": "8d2f6b1c-3e4a-4f5b-9c7d-1a2b3c4d5e6f"
}
```

| Código | Quando |
|---|---|
| 401 | Sem token ou token inválido |
| 403 | Token sem papel `cliente` nem `gestor` |
| 404 | Venda inexistente, ou cliente que não é o dono |

### 4.11 `GET /api/v1/vendas` — listar vendas (gestão)

Papel: **gestor**. Lista todas as vendas, ordenadas por `criada_em` descendente, com `comprador_id`. Como em 4.9, reservas vencidas são expiradas antes da consulta (o filtro `status=AGUARDANDO_PAGAMENTO` nunca devolve reserva vencida).

Parâmetros de consulta: `status` (opcional; `AGUARDANDO_PAGAMENTO`, `EFETIVADA` ou `CANCELADA`), `limite`, `deslocamento`.

```http
GET /api/v1/vendas?status=CANCELADA&limite=20 HTTP/1.1
Authorization: Bearer eyJ...   (gestor)
```

```json
{
  "itens": [
    {
      "id": "e5b1c9d3-6a2f-4e8b-b7c1-3d5f7a9b1c22",
      "veiculo_id": "1e9b7c3d-2a4f-4d6e-8b1a-5c7d9e0f2a34",
      "veiculo": { "marca": "Volkswagen", "modelo": "Gol 1.0 MPI", "ano": 2021, "cor": "Branco" },
      "preco_venda": "52900.00",
      "status": "CANCELADA",
      "codigo_pagamento": "PAG-8b2e44d1a9c0",
      "expira_em": "2026-10-03T14:42:10Z",
      "criada_em": "2026-10-03T14:12:10Z",
      "efetivada_em": null,
      "cancelada_em": "2026-10-03T14:13:55Z",
      "motivo_cancelamento": "PAGAMENTO_RECUSADO",
      "comprador_id": "2b7e9f4a-1c3d-4e5f-8a6b-7c8d9e0f1a2b"
    }
  ],
  "total": 1,
  "limite": 20,
  "deslocamento": 0
}
```

| Código | Quando |
|---|---|
| 401 | Sem token ou token inválido |
| 403 | Token sem papel `gestor` |
| 422 | `status` inválido ou paginação inválida |

### 4.12 `POST /api/v1/vendas/{id}/cancelar` — cancelar venda

Papel: **dono** ou **gestor**. Cancela uma venda `AGUARDANDO_PAGAMENTO` e libera o veículo (`RESERVADO` → `A_VENDA`). O motivo é derivado de quem cancela: `DESISTENCIA_COMPRADOR` (dono) ou `CANCELADA_PELA_LOJA` (gestor). Sem corpo. Eventos: `CompraCanceladaPeloComprador` ou `VendaCancelada`, e `VeiculoLiberado`.

```http
POST /api/v1/vendas/c3a7d1e2-58b4-4f6a-a1d9-0e2f4b6c8a10/cancelar HTTP/1.1
Authorization: Bearer eyJ...   (cliente dono)
```

```json
{
  "id": "c3a7d1e2-58b4-4f6a-a1d9-0e2f4b6c8a10",
  "veiculo_id": "9a4c2e1f-7b3d-4c5a-8e6f-0d1b2c3a4e56",
  "veiculo": { "marca": "Fiat", "modelo": "Argo Drive 1.3", "ano": 2023, "cor": "Vermelho" },
  "preco_venda": "79900.00",
  "status": "CANCELADA",
  "codigo_pagamento": "PAG-3f9a1c0b7e21",
  "expira_em": "2026-10-03T14:35:00Z",
  "criada_em": "2026-10-03T14:05:00Z",
  "efetivada_em": null,
  "cancelada_em": "2026-10-03T14:09:12Z",
  "motivo_cancelamento": "DESISTENCIA_COMPRADOR"
}
```

Se a reserva já estiver vencida no momento do cancelamento, a venda é cancelada com motivo `RESERVA_EXPIRADA` e a resposta é `200` com esse motivo.

| Código | Quando |
|---|---|
| 401 | Sem token ou token inválido |
| 403 | Token sem papel `cliente` nem `gestor` |
| 404 | Venda inexistente, ou cliente que não é o dono |
| 409 `transicao-invalida` | Venda `EFETIVADA` ou `CANCELADA` |

### 4.13 `POST /api/v1/pagamentos/webhook` — notificação do gateway

Chamador: **gateway de pagamento** (simulado por Swagger UI ou curl). Não usa JWT; a autenticação é o segredo compartilhado no header `X-Webhook-Secret`, comparado em tempo constante com o valor do Secret `revenda-webhook-secret`. O endpoint é a camada anticorrupção de Vendas: traduz o payload do gateway em `ProcessarPagamento(codigo, aprovado)`.

Headers:

| Header | Obrigatório | Valor |
|---|---|---|
| `X-Webhook-Secret` | sim | Segredo gerado pelo Terraform (48 caracteres). A API exige `WEBHOOK_SECRET` com no mínimo 16 caracteres e não inicia sem ele |
| `Content-Type` | sim | `application/json` |

Payload:

| Campo | Tipo | Regras |
|---|---|---|
| `codigo_pagamento` | string | Formato `^PAG-[0-9a-f]{12}$` |
| `status` | string | `APROVADO` ou `RECUSADO` |

Exemplo (aprovação):

```bash
curl -X POST http://localhost:8080/api/v1/pagamentos/webhook \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  -d '{"codigo_pagamento": "PAG-3f9a1c0b7e21", "status": "APROVADO"}'
```

```json
{
  "id": "c3a7d1e2-58b4-4f6a-a1d9-0e2f4b6c8a10",
  "veiculo_id": "9a4c2e1f-7b3d-4c5a-8e6f-0d1b2c3a4e56",
  "veiculo": { "marca": "Fiat", "modelo": "Argo Drive 1.3", "ano": 2023, "cor": "Vermelho" },
  "preco_venda": "79900.00",
  "status": "EFETIVADA",
  "codigo_pagamento": "PAG-3f9a1c0b7e21",
  "expira_em": "2026-10-03T14:35:00Z",
  "criada_em": "2026-10-03T14:05:00Z",
  "efetivada_em": "2026-10-03T14:07:30Z",
  "cancelada_em": null,
  "motivo_cancelamento": null
}
```

Comportamento por estado da venda:

| Estado atual | `APROVADO` | `RECUSADO` |
|---|---|---|
| `AGUARDANDO_PAGAMENTO`, não expirada | 200, venda `EFETIVADA`, veículo `VENDIDO` | 200, venda `CANCELADA` (`PAGAMENTO_RECUSADO`), veículo `A_VENDA` |
| `AGUARDANDO_PAGAMENTO`, expirada | 409 `reserva-expirada`; a venda é cancelada (`RESERVA_EXPIRADA`) e o veículo liberado | 200, venda `CANCELADA` (`RESERVA_EXPIRADA`), veículo liberado |
| `EFETIVADA` | 200 idempotente, sem efeito | 409 `transicao-invalida` |
| `CANCELADA` (qualquer motivo) | 409 `transicao-invalida` | 200 idempotente, sem efeito |

| Código | Quando |
|---|---|
| 401 `webhook-nao-autorizado` | Header ausente ou segredo incorreto |
| 404 `pagamento-nao-encontrado` | `codigo_pagamento` desconhecido |
| 409 | Conforme a tabela acima |
| 422 | Payload fora do formato |

Em uma integração real, o gateway reenviaria notificações sem resposta 2xx; por isso a idempotência é parte do contrato. O gateway deve tratar 409 como estado final (não reenviar).

### 4.14 `GET /metrics`: métricas Prometheus

Papel: **público** no ambiente local (como `/health/*`, fica fora do prefixo `/api/v1` e não aparece no OpenAPI). Responde no formato de exposição de texto do Prometheus (`text/plain; version=0.0.4`). Não contém dados pessoais nem identificadores: só contagens e latências agregadas. Em produção, o acesso deve ficar restrito à rede interna do cluster.

| Métrica | Tipo | Rótulos | Significado |
|---|---|---|---|
| `revenda_http_requisicoes_total` | contador | `metodo`, `rota`, `status` | Requisições atendidas |
| `revenda_http_requisicao_duracao_segundos` | histograma (faixas de 5 ms a 5 s) | `metodo`, `rota`, `status` | Latência das requisições |
| `revenda_vendas_iniciadas_total` | contador | — | Compras iniciadas (`CompraIniciada`) |
| `revenda_vendas_efetivadas_total` | contador | — | Vendas efetivadas pelo webhook |
| `revenda_vendas_canceladas_total` | contador | `motivo` | Vendas canceladas, por motivo (`PAGAMENTO_RECUSADO`, `DESISTENCIA_COMPRADOR`, `CANCELADA_PELA_LOJA`, `RESERVA_EXPIRADA`) |
| `revenda_veiculos_cadastrados_total` | contador | — | Veículos cadastrados |

O rótulo `rota` é o **template** da rota (ex.: `/api/v1/vendas/{venda_id}`), nunca o caminho com o identificador, para manter a cardinalidade baixa; caminhos inexistentes (404) usam `nao_mapeada`. A resposta inclui também as métricas padrão do processo Python (`process_*`, `python_*`). Exemplo de trecho da resposta:

```text
revenda_http_requisicoes_total{metodo="GET",rota="/api/v1/veiculos/a-venda",status="200"} 42.0
revenda_vendas_canceladas_total{motivo="PAGAMENTO_RECUSADO"} 1.0
```

Os contadores são por processo (cada réplica tem os seus); a soma entre réplicas é feita pelo Prometheus. Uso, golden signals, SLOs e alertas propostos estão em [12-observabilidade.md](12-observabilidade.md).
