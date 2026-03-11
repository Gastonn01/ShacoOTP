# OTP Shaco — Deploy Guide

## Archivos a colocar en la raíz del proyecto

Copiá estos archivos a `C:\Users\gasto\otp-shaco\`:
- `requirements.txt`
- `Procfile`
- `railway.toml`
- `.gitignore`

Copiá `templates/player.html` a `C:\Users\gasto\otp-shaco\templates\`

---

## Opción A — Railway (recomendado, más simple)

### 1. Instalar Railway CLI (opcional, o usá la web)
https://railway.app

### 2. Crear proyecto en Railway
- New Project → Deploy from GitHub repo
- Conectá tu repo de GitHub con el proyecto

### 3. Variables de entorno en Railway
En tu proyecto → Variables → agregar:

```
DATABASE_URL     = postgresql://...  (tu Supabase connection string)
RIOT_API_KEY     = RGAPI-xxxx-xxxx   (tu dev key o production key)
```

⚠️ Para la DATABASE_URL de Supabase, usá la "Direct connection" (no el pooler)
   para evitar timeout issues con SQLAlchemy. Formato:
   postgresql://postgres:[PASSWORD]@db.[PROJECT].supabase.co:5432/postgres

### 4. Deploy
Railway detecta el `Procfile` automáticamente y usa el comando:
```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

### 5. Dominio
Railway te da un dominio gratis tipo `otp-shaco.up.railway.app`
Podés conectar un dominio custom desde Settings → Domains.

---

## Opción B — Render

### 1. New Web Service → conectá el repo de GitHub

### 2. Configuración:
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Environment:** Python 3

### 3. Variables de entorno: igual que Railway arriba

---

## Notas importantes

### Dev API Key (expira cada 24h)
Si no tenés Production Key todavía, el sitio funciona para mostrar
jugadores ya guardados en DB. Los fetcheos de nuevos jugadores darán 401.

Para aplicar a Production Key:
https://developer.riotgames.com → Products → submit application

### Supabase connection
Si ves errores de conexión en producción, probá cambiar en DATABASE_URL
el puerto de 5432 a 6543 (pooler) o viceversa según el modo.

### Cache en memoria
El cache de stats (`_stats_cache`) se resetea en cada deploy. 
El primer request post-deploy tarda ~2s más. Es normal.

### Seeders
Los seeders (`seed_ladder.py`, etc.) se corren localmente, no en producción.
La DB de Supabase es compartida así que los datos ya estarán ahí.

---

## Checklist antes de deployar

- [ ] `requirements.txt` en la raíz
- [ ] `Procfile` en la raíz  
- [ ] `railway.toml` en la raíz
- [ ] Variables de entorno configuradas en Railway/Render
- [ ] `templates/player.html` actualizado (versión con todo en inglés)
- [ ] Supabase corriendo y accesible desde internet (ya lo está)
