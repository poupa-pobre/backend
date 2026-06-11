# Setup — Poupa Pobre

Como rodar o projeto do zero num notebook novo. São dois projetos:
`backend/` (Django REST + Postgres) e `mobile/` (React Native + Expo).

## Pré-requisitos

Instalar uma vez:

- **Git**
- **Docker + Docker Compose** — pro banco do backend (jeito mais fácil)
- **Node.js 20+** e **npm**
- **Python 3.12** — só pro backend sem Docker (opcional)
- **App Expo Go** no celular (Play Store / App Store) — roda quase tudo
- **Android Studio / Android SDK + Java 17** — só pro **scanner de cupom**
  (câmera + ML Kit não rodam no Expo Go)

> ⚠️ Os arquivos `.env` **não vão pro git**. Num notebook novo, recrie-os a
> partir dos `.env.example` (passos abaixo).

---

## 1) Backend (Django + Postgres)

```bash
cd backend
cp .env.example .env
```

Edite `backend/.env` e troque a chave secreta (o resto pode manter):

```
DJANGO_SECRET_KEY=qualquer-string-longa-e-aleatoria-aqui
```

Suba tudo com Docker (recomendado) — sobe Postgres + Django, migra e serve em
`http://localhost:8000`:

```bash
docker compose up --build
```

Crie um usuário pra logar (ou use a tela "Criar conta" do app):

```bash
docker compose exec web python manage.py createsuperuser
```

### Alternativa sem Docker (só o banco no Docker)

```bash
docker compose up -d db
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
POSTGRES_HOST=localhost python manage.py migrate
POSTGRES_HOST=localhost python manage.py runserver 0.0.0.0:8000
```

> O `.env` aponta `POSTGRES_HOST=db` (nome do serviço Docker). Rodando fora do
> Docker, use `POSTGRES_HOST=localhost` como acima.

### Testes

```bash
docker compose up -d db
POSTGRES_HOST=localhost python manage.py test --keepdb
```

---

## 2) Mobile (Expo)

```bash
cd mobile
npm install
cp .env.example .env
```

Edite `mobile/.env` apontando pro backend **conforme onde o app vai rodar**:

```
# Emulador Android:         http://10.0.2.2:8000
# Simulador iOS:            http://localhost:8000
# Celular físico (Expo Go): http://SEU_IP_NA_LAN:8000   (ex: http://192.168.1.68:8000)
EXPO_PUBLIC_API_URL=http://10.0.2.2:8000
```

> IP da LAN: `hostname -I` (Linux) / `ipconfig` (Windows). O celular precisa
> estar no **mesmo Wi-Fi** que o notebook.

Rodar:

```bash
npm start
```

Abra o **Expo Go** e escaneie o QR — ou tecle `a` (Android) / `i` (iOS).
Tudo funciona no Expo Go **exceto o scanner de cupom** (ver abaixo).

Checagem de tipos:

```bash
npx tsc --noEmit
```

---

## 3) Scanner de cupom (opcional — exige dev build)

Câmera + ML Kit não rodam no Expo Go. Uma vez só (precisa do Android SDK + Java 17):

```bash
cd mobile
npx expo prebuild --clean --platform android
npx expo run:android        # builda e instala no emulador/celular
```

Depois, `npm start` e abra **no dev build** (não no Expo Go). Mais detalhes em
`mobile/CLAUDE.md` → seção "Dev build".

---

## Dia a dia

```bash
# terminal 1 — backend
cd backend && docker compose up

# terminal 2 — mobile
cd mobile && npm start
```
