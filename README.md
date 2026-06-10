# Bot de Finanzas Personales — Telegram + Supabase

## Qué hace
- Mandás "carne 25000" → guarda el gasto automáticamente
- Mandás una foto de ticket → Claude la lee y extrae el monto
- /resumen → te muestra el resumen del mes
- El dashboard en Vercel se actualiza solo

---

## Setup paso a paso

### 1. Crear el bot en Telegram
1. Abrí Telegram y buscá @BotFather
2. Mandá /newbot
3. Elegí un nombre: "Mis Finanzas"
4. Elegí un username: "misfinanzas_bot" (debe terminar en _bot)
5. BotFather te da el TOKEN — guardalo

### 2. Conseguir tu Chat ID
1. Buscá @userinfobot en Telegram
2. Mandá cualquier mensaje
3. Te responde con tu ID — guardalo como MI_CHAT_ID

### 3. Crear la tabla en Supabase
1. Entrá a supabase.com → tu proyecto
2. Ir a SQL Editor → New query
3. Pegar todo el contenido de supabase_tabla.sql
4. Ejecutar (Run)

### 4. Conseguir las credenciales de Supabase
1. En tu proyecto Supabase → Settings → API
2. Copiar "Project URL" → SUPABASE_URL
3. Copiar "anon public" key → SUPABASE_KEY

### 5. Conseguir API key de Anthropic (para leer fotos)
1. Ir a console.anthropic.com
2. API Keys → Create Key
3. Guardar como ANTHROPIC_API_KEY
(Tiene costo mínimo — leer ~100 tickets cuesta menos de $0.10 USD)

### 6. Subir a Railway (hosting gratuito)
1. Crear cuenta en railway.app
2. New Project → Deploy from GitHub repo
   (o usar el CLI: npm install -g @railway/cli → railway init)
3. Agregar las variables de entorno en Railway:
   - TELEGRAM_TOKEN
   - SUPABASE_URL
   - SUPABASE_KEY
   - ANTHROPIC_API_KEY
   - MI_CHAT_ID
4. Deploy — Railway detecta el Procfile solo

---

## Uso del bot

| Mensaje              | Resultado                        |
|----------------------|----------------------------------|
| `carne 25000`        | Gasto: Carne $25.000 · otros     |
| `nafta 18000 combustible` | Gasto: Nafta $18.000 · combustible |
| `netflix 5000 suscripcion` | Gasto: Netflix $5.000 · suscripcion |
| Foto de ticket       | Lee automáticamente monto y local |
| `/resumen`           | Totales del mes por categoría     |
| `/ayuda`             | Lista de comandos                 |

---

## Estructura del proyecto
```
finanzas-bot/
├── bot.py              # lógica principal
├── requirements.txt    # dependencias Python
├── Procfile            # instrucción para Railway
├── .env.example        # plantilla de variables
└── supabase_tabla.sql  # SQL para crear la tabla
```
