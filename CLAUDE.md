# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Django REST backend for **"Poupar Pobre"**, a personal finance system positioned as "the evolved spreadsheet" — built for granular categorization and realistic credit-card handling that off-the-shelf apps don't offer. Each person is an **independent user** who owns their own data (private by default); there is **no shared family account**. Two users can connect through a **`Vinculo`** (invite + accept) and then share individual entries with a free split. The **month** is the core unit: the user opens the app and sees the current month's status ("what already went out" vs. "what's still coming").

This backend is shared across both delivery phases: **mobile first** (React Native + Expo), **web later** (React + Tailwind + shadcn/ui).

The full product spec lives in `../documentacao/` — read it for any non-obvious behavior rather than inferring from code:

- `../documentacao/01-produto/visao.md` — product vision, the 8 modules, what the system is **not**.
- `../documentacao/02-requisitos/requisitos.md` — numbered functional requirements (RF), business rules (RN), non-functional (RNF). The backend's source of truth.
- `../documentacao/03-arquitetura/modelo-de-dados.md` — full data model: entities, typed fields, constraints, relationships. Translates directly to Django models.
- `../documentacao/04-design/fluxo-de-telas.md` — screen flow and navigation map.

When the spec and the code disagree, the spec describes the target; the code is behind it (see Project state).

## Project state

**Fases 0 a 4 concluídas** — ver `roadmap.md`. A base está fiada e validada via Docker (`migrate` aplica auth/sessions/token_blacklist no Postgres; `/admin/` responde 302):

- `core/settings.py` lê o `.env` via `django-environ`, usa **PostgreSQL**, registra DRF + SimpleJWT (+ `token_blacklist`) + corsheaders, define a config base do DRF (JWT, `IsAuthenticated`, paginação 20) e o locale **pt-BR** (`America/Sao_Paulo`, `DD/MM/AAAA`).
- `apps/common` traz os modelos base abstratos: `TimeStampedModel` (`created_at`/`updated_at`) e `OwnedModel` (FK `usuario` + `OwnedManager.do_usuario()` para o scoping por dono).
- `apps/usuarios` tem o **custom user model** `Usuario` (login por email, `AUTH_USER_MODEL` setado) + auth JWT em `/api/auth/` (registro, login, refresh, logout c/ blacklist, `me`, recuperação de senha por email).
- `apps/vinculos` tem o `Vinculo` (convite → aceite/recusa, par único + check anti-auto-vínculo) em `/api/vinculos/` (criar convite por email, listar minhas pontas, `aceitar`/`recusar` pelo destinatário, desfazer via DELETE).
- `apps/categorias` tem `Categoria`/`Subcategoria`/`Tag` em `/api/categorias|subcategorias|tags/`. Seed das 12 predefinidas por novo usuário (signal `post_save` em `CategoriasConfig.ready`; backfill via `manage.py seed_categorias`), teto de 10 customizadas, soft delete (`ativa`) + `restaurar`. Excluir customizada com lançamentos exige `reatribuir_para` no DELETE (RF-021; reatribui os `Gasto`). **Fase 1 completa.**
- `apps/cartoes` (Fase 2/3) tem `Cartao` (soft delete via `status=inativo` + `reativar`) e `Fatura` (estrutura, `UNIQUE(cartao, mes_referencia)`, ação `pagar` RN-042) em `/api/cartoes|faturas/`. A função `competencia(data, dia_fechamento)` e `Cartao.competencia_de()`/`fatura_do_mes()` implementam RN-040. **Composição da fatura (Fase 3, RF-041..043)** em `composicao.py` (`compor_fatura`, imports locais p/ evitar ciclo): agrega fixos no cartão + parcelas + gastos variáveis do mês, com subtotais, total e limite usado × disponível — valores **cheios** (extrato; rateio do compartilhado é acertado fora). `Fatura.composicao()` chama a função; `Fatura.recompor()` persiste o cache `total`. Ações: `GET /faturas/{id}/composicao/` e `pagar` (recompoe antes p/ usar o total como padrão). **`FaturaSerializer.total` é derivado ao vivo** (`SerializerMethodField` → `composicao()["total"]`), **não** o campo cache `Fatura.total`: o cache só é atualizado em `composicao`/`pagar`, então ficava defasado após criar gasto/parcela/fixo no cartão (a lista `/faturas/` mostrava limite intacto até abrir o detalhe). Mesma estratégia do `dashboard`.
- `apps/gastos` (Fase 2) tem `Gasto` + `GastoTag` (N:M com `Tag`) em `/api/gastos/`. `mes_referencia` derivado em `Gasto.save()` (competência do cartão no crédito via `competencia_de`, senão 1º dia do mês) e a fatura do mês é garantida via `fatura_do_mes()`. Serializer valida scoping (categoria/subcategoria/cartão/vínculo/tags do dono), RN-020 (cartão obrigatório só no crédito) e RN-021 (compartilhado exige vínculo aceito + `valor_dono+valor_vinculado=valor`; não-compartilhado zera o rateio). FKs: categoria/cartão `PROTECT` (soft delete), subcategoria/vínculo `SET_NULL` (RN-002). Filtros de listagem por `mes_referencia`/`categoria`/`cartao`/`forma_pagamento`.
- `apps/receitas` (Fase 2) tem `Receita` em `/api/receitas/`. `mes_referencia` derivado em `Receita.save()` (1º dia do mês da `data_prevista`); `status` é **property** derivada de `data_real` (RF-011: `recebida`/`prevista`). RN-011: criar receita `recorrente` pré-cria a do mês seguinte como `prevista` via `criar_recorrencia()` (idempotente, a cópia não cascateia) — chamado no `serializer.create` e na ação `receber`. Ação `POST /receitas/{id}/receber/` marca `data_real` (padrão hoje) e, **para salário**, devolve `cobertura` (RN-010/RN-041: `cobertura_do_mes()` em `views.py` compara o saldo disponível — receitas recebidas − gastos não-crédito, pela porção do dono — com o **total das faturas abertas do mês** via composição plena `Fatura.composicao()`). Serializer reusa o padrão de `gastos`: scoping de `vinculo`, RN-021 (`compartilhada` exige vínculo aceito + `valor_dono+valor_vinculado=valor`; senão zera o rateio), FK `Vinculo` `SET_NULL`. Filtros por `mes_referencia`/`tipo`/`status`. **Fase 2 completa.**
- `apps/gastos_fixos` (Fase 3) tem `GastoFixo` (template tipo **A** fixo / **B** estimado; soft delete via `ativo` + `reativar`) e `GastoFixoMensal` (instância, `UNIQUE(gasto_fixo, mes_referencia)`) em `/api/gastos-fixos|gastos-fixos-mensais/`. `valor_efetivo` = `valor_real` (check do B) senão `valor_base` do template. Serializer valida tipo A exige `valor`, cartão obrigatório só na forma `cartao`, e o rateio (§1). Jobs: `manage.py gerar_gastos_fixos [--mes]` (RN-030, pré-cria mensais `pendente` dos ativos, idempotente) e `manage.py marcar_atrasos` (RN-032, pendente vencido → `atrasado`). Ação `POST /gastos-fixos-mensais/{id}/pagar/` dá o check (RN-031; tipo B exige `valor_real`). Categoria/cartão `PROTECT`, vínculo `SET_NULL`.
- `apps/dividas` (Fase 3) tem `Divida` + `Parcela` (`UNIQUE(divida, numero)`) em `/api/dividas|parcelas/`. `Divida.gerar_parcelas()` (RN-050, no `serializer.create`) cria as parcelas de `parcela_inicial` até `numero_parcelas`, uma por mês desde `data_primeira_parcela`, ligando à `Fatura` do cartão (`fatura` FK `SET_NULL`) no parcelamento de cartão. Projeção de quitação (RN-051) derivada no serializer: `valor_pago`/`valor_restante`/`mes_quitacao`. Serializer valida cartão obrigatório só no `parcelamento_cartao`, `parcela_inicial ≤ numero_parcelas` e o rateio (§1). Ação `POST /parcelas/{id}/pagar/`.
- `apps/metas` (Fase 4) tem `Meta` + `AporteMeta` em `/api/metas|aportes-meta/`. O `valor_atual` é **stored** e incrementado por cada aporte (RF-061, via `perform_create`/`perform_destroy` com `F()`); não editado à mão. `Meta.progresso()` (RN-060) deriva percentual concluído, valor restante, e — havendo `data_alvo` — `meses_restantes`, `aporte_mensal_necessario` e `no_ritmo` (ritmo = `contribuicao_mensal_planejada` se houver, senão a média mensal dos aportes). Serializer expõe o progresso via `SerializerMethodField` (cache por instância).
- `apps/investimentos` (Fase 4) tem `Investimento` (só aportes — Fase 1 do produto, sem rendimento) em `/api/investimentos/`. Filtro por `tipo`. Ação `GET /investimentos/consolidado/` (RF-071): `total_geral`, `por_tipo` (`values('tipo').annotate(Sum)`) e `por_mes` (`TruncMonth`).
- `apps/patrimonio` (Fase 4) tem `Bem` (ativo manual) + `PatrimonioSnapshot` (`UNIQUE(usuario, mes_referencia)`) em `/api/bens|patrimonio-snapshots/`. O cálculo ao vivo (RF-080) vive em `calculo.calcular_patrimonio`: **ativos** = saldo disponível do mês (receitas recebidas − gastos pagos fora do crédito, porção do dono) + total investido + bens; **passivos** = faturas abertas (composição plena) + parcelas pendentes **sem fatura** (parcelas de cartão já entram via fatura — não duplicar). Ação `GET /patrimonio-snapshots/atual/?mes=` devolve o cálculo ao vivo; a lista é o histórico (RF-081). Job `manage.py gerar_snapshot_patrimonio [--mes]` persiste o snapshot mensal de cada usuário (idempotente, `update_or_create`).
- `apps/dashboard` (Fase 4, sem model) expõe `GET /api/dashboard/?mes=AAAA-MM-01` (`services.montar_dashboard`): a **visão do mês** (`fluxo-de-telas.md` §3) com cards (receitas previsto×recebido, fixos X/Y, faturas abertas, saldo disponível, economia) e seções (fixos pendentes, faturas por cartão, últimos 5 lançamentos). Receitas/variáveis pela porção do dono; fixos/faturas pelo valor cheio. `status_mes`: mês passado = `fechado`, corrente/futuro = `aberto`.
- `Dockerfile` + `docker-compose.yml` revisado: `db` (postgres:16, creds do `.env`, healthcheck) e `web` (roda `migrate` antes do `runserver`, `depends_on: db healthy`). **Testes locais fora do Docker:** `docker compose up -d db` e rodar com `POSTGRES_HOST=localhost` (o `.env` aponta `db`, só resolvível dentro da rede do compose). **Fase 4 completa. Total: 189 testes passando.**
- `apps/relatorios` (Fase 5, sem model — padrão do `dashboard`) expõe `GET /api/relatorios/gastos-por-categoria/?mes=AAAA-MM-01` (`services.montar_relatorio`): agrega **gastos variáveis (porção do dono) + gastos fixos pagos (valor efetivo)** por categoria, devolvendo `total`, `total_mes_anterior` e `categorias` (id/nome/cor/total, ordenado desc). Base do card "Para onde foi meu dinheiro?" do mobile (RF-100). **Export PDF (RF-101/102) ainda pendente.**
- `core/urls.py` roteia `admin/` + `api/` dos apps `usuarios`, `vinculos`, `categorias`, `cartoes`, `gastos`, `receitas`, `gastos_fixos`, `dividas`, `metas`, `investimentos`, `patrimonio`, `dashboard`, `relatorios`.

Próximo na **Fase 5** (periféricos): `apps/notificacoes` (`ConfigNotificacao`, envio por email + tentativa de Google Calendar RF-090/091), `apps/importacao` (upload OFX/CSV, sugestão de categoria, detecção de duplicata RF-111/RN-110), **export PDF dos relatórios** (RF-101/102) e o **scanner de cupom** em `gastos` (`CompraDetalhada`+`ItemCompra`, NFC-e/OCR RF-022..025 — aguarda validação do MVP mobile).

## Stack

| Layer | Technology |
|---|---|
| API | Django 6 + Django REST Framework |
| Auth | DRF SimpleJWT (email + password, JWT) |
| DB | PostgreSQL (`psycopg2-binary`) |
| Config | `django-environ` (reads `.env`) |
| CORS | `django-cors-headers` (mobile/web clients) |
| Serving | `gunicorn` (WSGI) |
| Mobile (phase 1) | React Native + Expo + TypeScript *(separate repo)* |
| Web (phase 2) | React + TS + Tailwind + shadcn/ui *(separate repo)* |
| External | SEFAZ / Nuvem Fiscal (NFC-e), Google Vision (OCR) |
| Infra | Oracle Cloud (Always Free) |

## App structure by module

Apps live under `apps/` and register as `apps.<name>`. The 8 product modules map to apps as follows (planned — none created yet). Entity names below are the Portuguese domain terms from the data model; see `modelo-de-dados.md` for fields and constraints.

| App | Module(s) | Key entities |
|---|---|---|
| `usuarios` | Users + auth (custom user, JWT) | `Usuario` |
| `vinculos` | Sharing connection between users | `Vinculo` |
| `categorias` | Categorization (per user) | `Categoria`, `Subcategoria`, `Tag` |
| `receitas` | 1 · Income | `Receita` |
| `gastos` | 2 · Daily spending + coupon scanner | `Gasto`, `CompraDetalhada`, `ItemCompra`, `GastoTag` |
| `gastos_fixos` | 3 · Fixed expenses (type A/B) | `GastoFixo`, `GastoFixoMensal` |
| `cartoes` | 4 · Credit cards | `Cartao`, `Fatura` |
| `dividas` | 5 · Debts & installments | `Divida`, `Parcela` |
| `metas` | 6 · Savings goals | `Meta`, `AporteMeta` |
| `investimentos` | 7 · Investments (contributions only, phase 1) | `Investimento` |
| `patrimonio` | 8 · Net worth | `Bem`, `PatrimonioSnapshot` |
| `notificacoes` | Alerts (email; Calendar attempt) | `ConfigNotificacao` |
| `importacao` | OFX/CSV import | `Importacao` |
| `relatorios` | Reports (PDF export) | none — read-side aggregations |

## Conventions

Derived from `modelo-de-dados.md` — apply these across all models and apps:

- **Scoped by `usuario` (owner).** Almost every entity has a `usuario` FK and is filtered by it — data is private to its owner. The only cross-user path is `Vinculo`: shared entries reference the vínculo and surface (read-only) to the other party; they are never duplicated.
- **Money is `DECIMAL(12,2)`** everywhere (Django `DecimalField(max_digits=12, decimal_places=2)`). Never floats.
- **Enums as `CharField` + `choices`**, not separate tables (e.g. `forma_pagamento`, `status`, `tipo`).
- **`mes_referencia` is denormalized on purpose** — a `DateField` set to the 1st of the month, present on many tables to keep the monthly filters (the heart of the system) fast. Derived from the entry's date; for cards, from the closing day (`dia_fechamento`) cycle.
- **Auto-generated rows:** `GastoFixoMensal`, `Fatura`, and `Parcela` are created by routines (monthly job / on template or debt creation), not entered by hand. Use `UNIQUE(parent, mes_referencia)` to avoid duplicates per month.
- **Derived values are computed at query time, not stored** — saldo, fatura totals, net worth, goal progress. The one exception is `PatrimonioSnapshot`, persisted monthly for the evolution chart.
- **Soft delete** on entities with linked history (`Categoria`, `Cartao`, `GastoFixo`) so old entries don't break.
- **Shared-entry split is an application rule:** when `compartilhado`/`compartilhada` is true, a `vinculo` is required and `valor_dono + valor_vinculado` must equal `valor` — validated in the app/serializer, not in the DB. Shareable entries: `Receita`, `Gasto`, `GastoFixo`, `Divida`.
- **Locale:** pt-BR interface, dates `DD/MM/AAAA`, currency `R$ 1.234,56`. Keep `TIME_ZONE`/`LANGUAGE_CODE` consistent with this.

## Commands

The virtualenv lives at `./venv` (Python 3.12). Activate it or call binaries directly via `./venv/bin/...`.

```bash
pip install -r requirements.txt           # install deps
python manage.py migrate                  # apply migrations
python manage.py runserver                # dev server at :8000
python manage.py createsuperuser          # admin user
python manage.py makemigrations           # generate migrations after model changes
python manage.py test                     # run the full test suite
python manage.py test apps.<app>.tests.<Class>.<method>   # run a single test
python manage.py startapp <name> apps/<name>              # create a new app under apps/
gunicorn core.wsgi:application            # production-style WSGI serve
```

## Layout

- `core/` — project config: `settings.py`, `urls.py` (root URLconf), `wsgi.py` / `asgi.py`.
- `apps/` — application code, one package per module (see table above).
- `.env` / `.env.example` — environment config. `.env.example` is the committed template; keep it in sync when adding new settings keys.
- `../documentacao/` — living product spec (vision, requirements, data model, screen flow).
