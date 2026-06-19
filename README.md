# Poupa Pobre — Backend

> API REST do **Poupa Pobre**, um sistema de finanças pessoais posicionado como **"a planilha evoluída"**: categorização granular e tratamento realista de cartão de crédito que os apps comuns não entregam. Cada pessoa é dona dos seus dados (privados por padrão) e compartilha lançamentos específicos, item a item, com quem quiser via **vínculo**.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-6.0-092E20?logo=django&logoColor=white)
![DRF](https://img.shields.io/badge/DRF-3.17-A30000?logo=django&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![JWT](https://img.shields.io/badge/Auth-JWT-000000?logo=jsonwebtokens&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/testes-189%20passando-2DD4A7)

API em produção: **`https://api.poupapobre.rudyson.com.br`** · App mobile que a consome: [`../mobile/`](../mobile/) · Especificação do produto: [`../documentacao/`](../documentacao/)

---

## Índice

- [O que é](#o-que-é)
- [Funcionalidades](#funcionalidades)
- [Stack](#stack)
- [Como rodar](#como-rodar)
- [Estrutura](#estrutura)
- [Convenções](#convenções)
- [Testes](#testes)
- [Deploy](#deploy)

---

## O que é

Backend Django REST compartilhado pelas duas fases de entrega: **mobile primeiro** (React Native + Expo) e **web depois** (React + Tailwind). O **mês** é a unidade central — o usuário abre o app e vê o status do mês corrente ("o que já saiu" × "o que ainda vem").

A especificação completa do produto vive em [`../documentacao/`](../documentacao/):

- [`01-produto/visao.md`](../documentacao/01-produto/visao.md) — visão, os 8 módulos, o que o sistema **não** é.
- [`02-requisitos/requisitos.md`](../documentacao/02-requisitos/requisitos.md) — requisitos funcionais (RF), regras de negócio (RN) e não funcionais (RNF).
- [`03-arquitetura/modelo-de-dados.md`](../documentacao/03-arquitetura/modelo-de-dados.md) — modelo de dados completo (traduz direto para os models Django).
- [`04-design/fluxo-de-telas.md`](../documentacao/04-design/fluxo-de-telas.md) — mapa de telas e navegação.

## Funcionalidades

Os 8 módulos do produto, mapeados em apps Django:

| Módulo | App | Destaques |
|---|---|---|
| 💰 **Receitas** | `receitas` | Salário, recorrência, marcar como recebida; cobertura das faturas |
| 🛒 **Gastos do dia a dia** | `gastos` | Variáveis + **scanner de cupom fiscal** (NFC-e/QR + OCR) com compra detalhada item a item |
| 📌 **Gastos fixos** | `gastos_fixos` | Tipo A (valor fixo) e B (estimado); geração mensal automática |
| 💳 **Cartão de crédito** | `cartoes` | Faturas por competência, composição (fixos + parcelas + variáveis), limite global, pagar fatura |
| 🧾 **Dívidas e parcelamentos** | `dividas` | Geração de parcelas, projeção de quitação, parcela no cartão ligada à fatura |
| 🎯 **Metas de economia** | `metas` | Aportes, progresso, ritmo necessário para a data-alvo |
| 📈 **Investimentos** | `investimentos` | Controle de aportes (Fase 1, sem rendimento), consolidado por tipo/mês |
| 🏦 **Patrimônio líquido** | `patrimonio` | Cálculo ao vivo (ativos − passivos) + snapshot mensal para o histórico |

Transversais: **auth JWT** (`usuarios`), **vínculo entre usuários** com compartilhamento item a item (`vinculos`), **categorias/subcategorias/tags** por usuário (`categorias`), **dashboard do mês** (`dashboard`), **relatórios** com export PDF (`relatorios`) e **importação de extrato OFX/CSV + Pix por notificação** (`importacao`).

## Stack

| Camada | Tecnologia |
|---|---|
| API | Django 6 + Django REST Framework |
| Auth | DRF SimpleJWT (email + senha, JWT com blacklist) |
| Banco | PostgreSQL (`psycopg2-binary`) |
| Config | `django-environ` (lê `.env`) |
| CORS | `django-cors-headers` (clientes mobile/web) |
| PDF | `reportlab` (pure-Python, sem dependência de sistema) |
| Serving | `gunicorn` (WSGI) + WhiteNoise (estáticos) |
| Infra | Docker Compose · Oracle Cloud (Always Free) |

## Como rodar

Setup detalhado (pré-requisitos, sem Docker, scanner) em **[`SETUP.md`](./SETUP.md)**. Resumo com Docker:

```bash
cd backend
cp .env.example .env          # troque DJANGO_SECRET_KEY por uma string longa e aleatória
docker compose up --build     # sobe Postgres + Django, migra e serve em http://localhost:8000
```

Criar um usuário para logar (ou use a tela "Criar conta" do app):

```bash
docker compose exec web python manage.py createsuperuser
```

A API responde em `http://localhost:8000/api/` e o admin em `http://localhost:8000/admin/`.

## Estrutura

```
backend/
  core/                 # config do projeto: settings, urls (raiz), wsgi/asgi
  apps/                 # um pacote por módulo (apps.<nome>)
    common/             # modelos base abstratos (TimeStampedModel, OwnedModel)
    usuarios/           # custom user + auth JWT  (/api/auth/)
    vinculos/           # convite/aceite entre usuários  (/api/vinculos/)
    categorias/         # categorias/subcategorias/tags  (/api/categorias|...)
    receitas/ gastos/ gastos_fixos/ cartoes/ dividas/
    metas/ investimentos/ patrimonio/      # os 8 módulos do produto
    dashboard/ relatorios/                 # leitura/agregações (sem model)
    importacao/                            # OFX/CSV + Pix
  manage.py
  Dockerfile · docker-compose.yml · docker-compose.prod.yml
  .env.example · requirements.txt
```

## Convenções

Derivadas do modelo de dados — valem para todos os apps:

- **Tudo escopado por `usuario` (dono).** Dados privados; o único caminho cross-user é o `Vinculo`. Lançamentos compartilhados referenciam o vínculo e aparecem (read-only) pra outra ponta — nunca são duplicados.
- **Dinheiro é `DECIMAL(12,2)`** em todo lugar — nunca float.
- **Enums como `CharField` + `choices`**, não tabelas separadas.
- **`mes_referencia` denormalizado** (1º dia do mês) para deixar os filtros mensais rápidos.
- **Linhas auto-geradas** (`GastoFixoMensal`, `Fatura`, `Parcela`) vêm de rotinas, com `UNIQUE(parent, mes_referencia)`.
- **Valores derivados são calculados em query** (saldo, totais de fatura, patrimônio, progresso de meta) — exceto `PatrimonioSnapshot`, persistido mensalmente.
- **Soft delete** em entidades com histórico (`Categoria`, `Cartao`, `GastoFixo`).
- **Locale pt-BR:** datas `DD/MM/AAAA`, moeda `R$ 1.234,56`.

## Testes

```bash
docker compose up -d db
POSTGRES_HOST=localhost python manage.py test --keepdb
```

> Rodando os testes fora do Docker, use `POSTGRES_HOST=localhost` — o `.env` aponta `db` (nome do serviço, só resolvível dentro da rede do compose).

## Deploy

Produção com `docker-compose.prod.yml` + `.env.production`, atrás de [`nginx-proxy`](https://github.com/nginx-proxy/nginx-proxy) + `acme-companion` (TLS automático). O `entrypoint.sh` roda `collectstatic` + `migrate` e sobe o **gunicorn**. Detalhes e os jobs mensais (`gerar_gastos_fixos`, `marcar_atrasos`, `gerar_snapshot_patrimonio`, agendados via cron do host) em [`SETUP.md`](./SETUP.md).
