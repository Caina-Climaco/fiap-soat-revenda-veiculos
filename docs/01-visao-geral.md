# 1. Visão geral

Este documento apresenta o problema de negócio, o objetivo, o escopo, os atores, as premissas e as restrições do projeto **Revenda de Veículos — API**, desenvolvido como Trabalho Substitutivo da Fase 3 do Tech Challenge (FIAP PósTech, Software Architecture). Serve como porta de entrada da documentação: quem lê este arquivo primeiro sabe o que foi construído, para quem e onde encontrar cada detalhe.

## 1.1 Problema de negócio

Uma empresa de revenda de veículos automotores quer vender pela internet. Hoje o estoque é gerido fora de qualquer plataforma e a compra depende de atendimento presencial. A empresa precisa de uma plataforma web em que:

- a loja cadastre e mantenha os veículos anunciados (marca, modelo, ano, cor e preço);
- pessoas previamente cadastradas comprem um veículo pela internet;
- qualquer pessoa consulte os veículos à venda e os já vendidos, ordenados por preço;
- os dados pessoais dos compradores fiquem **totalmente apartados** dos dados transacionais da operação.

A interface (front-end) é responsabilidade de outros times. Este projeto entrega o back-end: a **API** e a infraestrutura que a executa.

## 1.2 Objetivo

Entregar uma API REST funcional, testada e implantada de forma automatizada que suporte o ciclo completo de venda — cadastro do veículo, cadastro do cliente, compra, reserva, efetivação por confirmação de pagamento e cancelamento — com:

1. serviço de identidade separado (Keycloak) guardando os dados pessoais em banco próprio, entregue em repositório próprio ([fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade), [ADR-014](adrs/ADR-014-identidade-em-repositorio-proprio.md));
2. garantia de que um mesmo veículo não seja vendido duas vezes, mesmo sob acesso concorrente;
3. toda mudança de código ou de infraestrutura passando por Pull Request e pipeline de CI/CD;
4. documentação de arquitetura (DDD, C4, ADRs, requisitos, testes) rastreável até o código.

## 1.3 Escopo

### 1.3.1 Dentro do escopo

| Item | Observação |
|---|---|
| API REST `revenda-api` (FastAPI) com módulos **Catálogo** e **Vendas** | Monólito modular, Clean Architecture por módulo |
| Cadastro e edição de veículos pelo gestor | Edição só enquanto o veículo está à venda |
| Listagens públicas de veículos à venda e vendidos, ordenadas por preço ascendente | Paginadas |
| Compra por cliente autenticado, com reserva do veículo e expiração da reserva | TTL padrão de 30 min |
| Efetivação ou recusa da compra por webhook de gateway de pagamento **simulado** | `POST /api/v1/pagamentos/webhook` com segredo compartilhado |
| Cancelamento da compra pelo comprador (desistência) ou pela loja | Somente antes da efetivação |
| Cadastro, login e papéis de usuários no **Keycloak** com PostgreSQL próprio | Realm `revenda`, papéis `cliente` e `gestor`; mantido e implantado pelo repositório de identidade, consumido aqui por contrato (OIDC/JWT) |
| Infraestrutura local: cluster Kubernetes **kind** criado pela CLI `kind`, com a plataforma provisionada por **Terraform** (aqui: namespace `revenda`, banco da API, segredos, metrics-server; o namespace `identidade` vem do repositório de identidade) | Sem nuvem; cluster local compartilhado pelos dois repositórios |
| Observabilidade: logs JSON, probes e métricas Prometheus em `/metrics` | Prometheus, Grafana e APM como evolução ([12-observabilidade.md](12-observabilidade.md)) |
| CI no GitHub Actions (runner hospedado) e CD no runner self-hosted do autor | Deploy automático a cada merge na `main` |
| Testes de unidade, integração e ponta a ponta (e2e) | Cobertura mínima de 80% |
| Documentação, README, vídeo e PDF de entrega | Ver [10-plano-execucao.md](10-plano-execucao.md) |

### 1.3.2 Fora do escopo

| Item | Motivo |
|---|---|
| Front-end (telas da loja e do comprador) | Responsabilidade de outros times; a interação é demonstrada pelo Swagger UI e por `curl` |
| Integração com provedor de pagamento real, estorno e conciliação | Pagamento é simulado por webhook; o resultado chega como chamada HTTP autenticada |
| Financiamento, consórcio, troca, proposta e negociação de preço | Não pedidos no enunciado |
| Emissão de nota fiscal, transferência de documentação (DETRAN), entrega do veículo | Processos pós-venda fora do sistema |
| Fotos, opcionais, quilometragem e busca com filtros avançados | Não pedidos; o modelo admite extensão futura |
| Múltiplas lojas ou filiais | Uma única revenda |
| Notificações (e-mail, SMS, push) | Não pedidas |
| API Gateway (Kong, APIM) e funções Serverless (Lambda, SAM, Cognito) | Sem conta de nuvem e um único backend; justificativa e onde entrariam em [ADR-013](adrs/ADR-013-sem-api-gateway-e-serverless.md) |
| Mensageria (broker) e sagas | Eventos de domínio são apenas registrados em log estruturado ([02-modelagem-ddd.md](02-modelagem-ddd.md)) |
| Nuvem pública, alta disponibilidade multi-nó, backup gerenciado | Restrição de custo; ambiente local |
| Telas próprias de cadastro além das oferecidas pelo Keycloak | O formulário de registro do realm atende ao cadastro |

## 1.4 Atores

| Ator | Descrição | Como interage | Papel / credencial |
|---|---|---|---|
| **Gestor da loja** | Funcionário da revenda que mantém o estoque e acompanha as vendas | Login no Keycloak; chama endpoints de veículos e de gestão de vendas | Papel de realm `gestor` (usuário seed `gestor.loja`) |
| **Cliente / Comprador** | Pessoa cadastrada no serviço de identidade que compra um veículo | Autorregistro e login no Keycloak; inicia, consulta e cancela as próprias compras | Papel de realm `cliente` (atribuído automaticamente no autorregistro) |
| **Visitante anônimo** | Qualquer pessoa sem login | Consulta listagens e detalhes de veículos; pode se cadastrar e virar cliente | Nenhuma |
| **Gateway de pagamento (simulado)** | Sistema externo que informa o resultado do pagamento associado a um código de pagamento | Chama o webhook da API | Segredo compartilhado no cabeçalho `X-Webhook-Secret` |
| **Avaliador / operador** | Professor avaliador ou o próprio autor operando o ambiente | Executa o projeto localmente, assiste ao vídeo, acompanha pipelines, consulta bancos e Swagger | Acesso aos dois repositórios e ao ambiente local |

## 1.5 Premissas

1. O trabalho é **individual**; não há revisor humano além do autor. A proteção da branch `main` exige PR e CI verde, com zero aprovações obrigatórias (documentado como exceção consciente).
2. O pagamento é feito fora da plataforma; a plataforma só conhece o **código de pagamento** e recebe o resultado do gateway.
3. O comprador paga o preço anunciado no momento em que inicia a compra; não há negociação.
4. Um veículo é uma unidade física única: só pode ter uma venda ativa por vez.
5. O avaliador dispõe de máquina com Docker, kind, kubectl e Terraform para reproduzir o ambiente (primeiro o repositório de identidade, depois este), ou assiste ao vídeo da execução.
6. O PC do autor fica ligado nos momentos de deploy; o runner self-hosted não é um serviço de alta disponibilidade.
7. O ambiente é de demonstração: dados de exemplo, senhas geradas pelo Terraform e um client de teste (`revenda-e2e`) habilitado apenas localmente.

## 1.6 Restrições

| Restrição | Consequência |
|---|---|
| Prazo de entrega: **15/10/2026** | Escopo enxuto, monólito modular, sem mensageria |
| Sem nuvem pública (custo zero) | Kubernetes local com kind; imagem carregada no cluster sem registry |
| Separação total entre dados pessoais e transacionais | Keycloak em repositório, pipeline, state do Terraform, namespace e instância PostgreSQL próprios; a API guarda apenas o `sub` do token |
| Toda alteração via CI/CD e Pull Request | `main` protegida; CD só após merge |
| Stack das fases anteriores | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 |
| Entregáveis fixos | PDF com links dos dois repositórios (API e identidade) e do vídeo; README em cada repositório; vídeo com fluxo ponta a ponta |

## 1.7 Mapa da documentação

| # | Documento | Conteúdo |
|---|---|---|
| 01 | [Visão geral](01-visao-geral.md) | Este documento |
| 02 | [Modelagem DDD](02-modelagem-ddd.md) | Domain Storytelling, Event Storming, linguagem ubíqua, contextos, agregados, máquinas de estado e regras de negócio |
| 03 | [Requisitos](03-requisitos.md) | Requisitos funcionais e não funcionais, matriz de rastreabilidade |
| 04 | [Arquitetura](04-arquitetura.md) | Diagramas C4, visão de módulos e camadas, implantação |
| 05 | [API](05-api.md) | Contrato REST, autenticação, erros, paginação, exemplos |
| 06 | [Dados](06-dados.md) | Modelo físico, schemas, índices, migrações |
| 07 | [Segurança e LGPD](07-seguranca-lgpd.md) | Ameaças, controles, tratamento de dados pessoais |
| 08 | [CI/CD e infraestrutura](08-ci-cd-infra.md) | Terraform, kind, manifestos, pipelines, governança do repositório |
| 09 | [Testes](09-testes.md) | Estratégia, níveis, cenários BDD, como executar |
| 10 | [Plano de execução](10-plano-execucao.md) | Backlog, DoR, DoD, cronograma e riscos |
| 11 | [Roteiro do vídeo](11-roteiro-video.md) | Roteiro da demonstração em vídeo, checklist de preparação e comandos |
| 12 | [Observabilidade](12-observabilidade.md) | Logs, métricas Prometheus, golden signals, SLIs/SLOs, alertas e plano de APM |
| 13 | [Design Approval Sheet](13-das.md) | Folha de aprovação do desenho: escopo, decisões, atributos de qualidade, riscos, custos e aprovação |
| — | [ADRs](adrs/README.md) | Registros de decisões de arquitetura |
