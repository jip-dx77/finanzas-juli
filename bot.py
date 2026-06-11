import os
import json
import base64
import re
import asyncio
from datetime import datetime, date
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import Conflict
from supabase import create_client, Client
import anthropic

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MI_CHAT_ID = int(os.getenv("MI_CHAT_ID"))

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

CATEGORIAS = ["super", "comida", "combustible", "servicios", "tarjeta", "salud", "ropa", "ocio", "transporte", "suscripcion", "otros"]


def solo_yo(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id != MI_CHAT_ID:
            return
        return await func(update, context)
    return wrapper


def hoy():
    return date.today()


def mes_anio_de_fecha(fecha_str=None):
    if fecha_str:
        d = datetime.strptime(fecha_str, "%Y-%m-%d")
        return d.month, d.year
    h = hoy()
    return h.month, h.year


def formatear_monto(m):
    return f"${int(float(m)):,}".replace(",", ".")


async def parsear_mensaje(texto: str) -> dict:
    hoy_str = hoy().isoformat()
    mes, anio = mes_anio_de_fecha()

    prompt = f"""Sos un asistente financiero personal argentino. Hoy es {hoy_str}, mes {mes}, año {anio}.

El usuario te mandó: "{texto}"

Respondé SOLO con un JSON válido (sin markdown, sin texto extra):

{{
  "intent": "gasto" | "ingreso" | "resumen" | "resumen_ingresos" | "metas" | "cuotas" | "ayuda" | "desconocido",
  "datos": {{
    "concepto": "texto descriptivo",
    "monto": número o null,
    "categoria": una de ["super","comida","combustible","servicios","tarjeta","salud","ropa","ocio","transporte","suscripcion","otros"] o null,
    "tipo": "salario" | "aguinaldo" | "extra" (solo para ingresos),
    "fecha": "YYYY-MM-DD" o null
  }},
  "confirmacion_necesaria": true | false,
  "pregunta": "pregunta al usuario" | null
}}

Reglas de categorización:
- super/supermercado/almacén/mercado/disco/carrefour/dia/coto/walmart → "super"
- comida/delivery/restaurante/café/almuerzo/cena/desayuno/pizza/sushi/pedidos ya/rappi → "comida"
- nafta/gasoil/combustible/shell/ypf/axion/carga combustible → "combustible"
- luz/agua/gas/internet/wifi/servicio/factura/edesur/metrogas → "servicios"
- tarjeta/resumen/visa/mastercard/cuota → "tarjeta"
- farmacia/médico/doctor/salud/medicamento/turno médico → "salud"
- ropa/zapatillas/indumentaria/zara/h&m/calzado → "ropa"
- cine/teatro/streaming/entretenimiento/salida/bar/boliche → "ocio"
- uber/taxi/remis/colectivo/tren/subte/cabify → "transporte"
- netflix/spotify/disney/suscripción/app/plataforma → "suscripcion"

Para ingresos detectar palabras como: cobré, sueldo, salario, ingresé, me pagaron, aguinaldo, plus, bono.

Si falta el monto → confirmacion_necesaria: true, pregunta: "¿Cuánto fue el monto?"
Si el intent es ambiguo entre gasto e ingreso → pedí aclaración.
Siempre inferí la categoría aunque no sea explícita, usando el contexto."""

    response = claude.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


async def registrar_gasto(datos: dict) -> dict:
    fecha = datos.get("fecha") or hoy().isoformat()
    mes, anio = mes_anio_de_fecha(fecha)
    row = {
        "concepto": datos["concepto"],
        "monto": datos["monto"],
        "categoria": datos.get("categoria") or "otros",
        "fecha": fecha,
        "mes": mes,
        "anio": anio,
        "fuente": "bot",
    }
    result = supabase.table("gastos").insert(row).execute()
    return result.data[0] if result.data else row


async def registrar_ingreso(datos: dict) -> dict:
    fecha = datos.get("fecha") or hoy().isoformat()
    mes, anio = mes_anio_de_fecha(fecha)
    row = {
        "concepto": datos.get("concepto") or datos.get("tipo") or "Ingreso",
        "monto": datos["monto"],
        "tipo": datos.get("tipo") or "extra",
        "fecha": fecha,
        "mes": mes,
        "anio": anio,
    }
    result = supabase.table("ingresos").insert(row).execute()
    return result.data[0] if result.data else row


MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
         "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


async def obtener_resumen_gastos() -> str:
    mes, anio = mes_anio_de_fecha()
    result = supabase.table("gastos").select("categoria, monto").eq("mes", mes).eq("anio", anio).execute()

    if not result.data:
        return "No hay gastos registrados este mes."

    totales = {}
    total = 0
    for row in result.data:
        cat = row["categoria"]
        monto = float(row["monto"])
        totales[cat] = totales.get(cat, 0) + monto
        total += monto

    texto = f"📊 *Gastos {MESES[mes]} {anio}*\n\n"
    for cat, monto in sorted(totales.items(), key=lambda x: x[1], reverse=True):
        pct = monto / total * 100
        texto += f"• {cat.capitalize()}: {formatear_monto(monto)} ({pct:.0f}%)\n"
    texto += f"\n💸 *Total: {formatear_monto(total)}*"
    return texto


async def obtener_resumen_ingresos() -> str:
    mes, anio = mes_anio_de_fecha()
    result = supabase.table("ingresos").select("concepto, monto, tipo").eq("mes", mes).eq("anio", anio).execute()

    if not result.data:
        return "No hay ingresos registrados este mes."

    total = sum(float(r["monto"]) for r in result.data)
    texto = f"💰 *Ingresos {MESES[mes]} {anio}*\n\n"
    for r in result.data:
        texto += f"• {r['concepto']}: {formatear_monto(r['monto'])}\n"
    texto += f"\n✅ *Total: {formatear_monto(total)}*"
    return texto


async def obtener_metas() -> str:
    result = supabase.table("metas").select("*").eq("activa", True).execute()

    if not result.data:
        return "No tenés metas activas."

    texto = "🎯 *Metas de ahorro*\n\n"
    for m in result.data:
        actual = float(m["monto_actual"])
        objetivo = float(m["monto_objetivo"])
        pct = (actual / objetivo * 100) if objetivo > 0 else 0
        bloques = int(pct / 10)
        barra = "█" * bloques + "░" * (10 - bloques)
        texto += f"*{m['icono']} {m['nombre']}*\n"
        texto += f"`{barra}` {pct:.0f}%\n"
        texto += f"{formatear_monto(actual)} / {formatear_monto(objetivo)}\n"
        if m.get("fecha_limite"):
            texto += f"📅 Límite: {m['fecha_limite']}\n"
        texto += "\n"
    return texto.strip()


async def obtener_cuotas() -> str:
    result = supabase.table("cuotas").select("*").eq("activa", True).execute()

    if not result.data:
        return "No tenés cuotas activas."

    texto = "💳 *Cuotas activas*\n\n"
    for c in result.data:
        restantes = c["cuotas_totales"] - c["cuotas_pagadas"]
        total_restante = restantes * float(c["monto_cuota"])
        texto += f"• *{c['nombre']}*\n"
        texto += f"  {formatear_monto(c['monto_cuota'])}/mes · {restantes} cuotas restantes\n"
        texto += f"  Pendiente: {formatear_monto(total_restante)}\n"
        if c.get("tarjeta") and c["tarjeta"] != "Sin tarjeta":
            texto += f"  Tarjeta: {c['tarjeta']}\n"
        texto += "\n"
    return texto.strip()


async def analizar_foto(image_data: bytes) -> list:
    b64 = base64.standard_b64encode(image_data).decode("utf-8")

    prompt = f"""Analizá este ticket/factura. Respondé SOLO con un JSON válido:

{{
  "gastos": [
    {{
      "concepto": "descripción clara del gasto",
      "monto": número,
      "categoria": una de {CATEGORIAS}
    }}
  ]
}}

Reglas:
- Si es un ticket de supermercado con muchos items → un solo gasto con concepto "Supermercado [nombre del local]" y categoria "super".
- Si hay servicios o productos claramente distintos → listá cada uno por separado.
- Usá el nombre del local, tipo de productos y contexto para elegir la categoría correcta.
- El monto debe ser el total del ticket o el precio de cada item.
- No incluyas propinas ni items con monto 0."""

    response = claude.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": prompt}
            ]
        }]
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    data = json.loads(raw)
    return data.get("gastos", [])


TEXTO_AYUDA = """👋 *Asistente financiero*

Hablame en lenguaje natural:

💸 *Gastos*
• "gasté 5000 en uber"
• "almorcé afuera, pagué 3200"
• "compré ropa 15000 con visa"
• [foto de un ticket]

💰 *Ingresos*
• "cobré el sueldo, 500000"
• "me pagaron 20000 de extra"

📊 *Consultas*
• "resumen" — gastos del mes
• "ingresos" — ingresos del mes
• "metas" — progreso de tus metas
• "cuotas" — cuotas activas"""


@solo_yo
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TEXTO_AYUDA, parse_mode="Markdown")


@solo_yo
async def manejar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    texto_lower = texto.lower()

    # Shortcuts directos sin llamar a Claude
    if texto_lower in ["resumen", "gastos", "/resumen"]:
        await update.message.reply_text(await obtener_resumen_gastos(), parse_mode="Markdown")
        return
    if texto_lower in ["ingresos", "resumen ingresos", "/ingresos"]:
        await update.message.reply_text(await obtener_resumen_ingresos(), parse_mode="Markdown")
        return
    if texto_lower in ["metas", "meta", "/metas"]:
        await update.message.reply_text(await obtener_metas(), parse_mode="Markdown")
        return
    if texto_lower in ["cuotas", "/cuotas"]:
        await update.message.reply_text(await obtener_cuotas(), parse_mode="Markdown")
        return
    if texto_lower in ["ayuda", "/ayuda", "help"]:
        await update.message.reply_text(TEXTO_AYUDA, parse_mode="Markdown")
        return

    # Flujo de confirmación pendiente (el usuario está respondiendo con el monto)
    if context.user_data.get("pendiente"):
        pendiente = context.user_data.pop("pendiente")
        try:
            monto_str = re.sub(r"[^\d.,]", "", texto).replace(",", ".")
            monto = float(monto_str)
            pendiente["datos"]["monto"] = monto

            if pendiente["intent"] == "gasto":
                await registrar_gasto(pendiente["datos"])
                cat = pendiente["datos"].get("categoria", "otros")
                await update.message.reply_text(
                    f"✅ *Gasto guardado*\n{pendiente['datos']['concepto']} — {formatear_monto(monto)}\nCategoría: {cat}",
                    parse_mode="Markdown"
                )
            elif pendiente["intent"] == "ingreso":
                await registrar_ingreso(pendiente["datos"])
                await update.message.reply_text(
                    f"✅ *Ingreso guardado*\n{pendiente['datos']['concepto']} — {formatear_monto(monto)}",
                    parse_mode="Markdown"
                )
            return
        except (ValueError, KeyError):
            await update.message.reply_text("No entendí el monto. Mandame solo el número, por ejemplo: 5000")
            return

    # Parsear con Claude
    try:
        parsed = await parsear_mensaje(texto)
    except Exception as e:
        await update.message.reply_text(f"Error al procesar: {e}")
        return

    intent = parsed.get("intent")
    datos = parsed.get("datos", {})

    if intent == "gasto":
        if not datos.get("monto"):
            context.user_data["pendiente"] = {"intent": "gasto", "datos": datos}
            await update.message.reply_text(
                f"_{parsed.get('pregunta', '¿Cuánto fue el monto?')}_",
                parse_mode="Markdown"
            )
            return
        await registrar_gasto(datos)
        await update.message.reply_text(
            f"✅ *Gasto guardado*\n{datos['concepto']} — {formatear_monto(datos['monto'])}\nCategoría: {datos.get('categoria', 'otros')}",
            parse_mode="Markdown"
        )

    elif intent == "ingreso":
        if not datos.get("monto"):
            context.user_data["pendiente"] = {"intent": "ingreso", "datos": datos}
            await update.message.reply_text(
                f"_{parsed.get('pregunta', '¿Cuánto fue el monto?')}_",
                parse_mode="Markdown"
            )
            return
        await registrar_ingreso(datos)
        await update.message.reply_text(
            f"✅ *Ingreso guardado*\n{datos.get('concepto', 'Ingreso')} — {formatear_monto(datos['monto'])}",
            parse_mode="Markdown"
        )

    elif intent == "resumen":
        await update.message.reply_text(await obtener_resumen_gastos(), parse_mode="Markdown")

    elif intent == "resumen_ingresos":
        await update.message.reply_text(await obtener_resumen_ingresos(), parse_mode="Markdown")

    elif intent == "metas":
        await update.message.reply_text(await obtener_metas(), parse_mode="Markdown")

    elif intent == "cuotas":
        await update.message.reply_text(await obtener_cuotas(), parse_mode="Markdown")

    elif intent == "ayuda":
        await update.message.reply_text(TEXTO_AYUDA, parse_mode="Markdown")

    else:
        await update.message.reply_text(
            "No entendí bien. Podés decirme cosas como:\n• \"gasté 3000 en nafta\"\n• \"cobré 200000\"\n• \"resumen\" / \"metas\" / \"cuotas\""
        )


@solo_yo
async def manejar_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Analizando el ticket...")

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_data = bytes(await file.download_as_bytearray())

    try:
        gastos = await analizar_foto(image_data)
    except Exception:
        await update.message.reply_text("No pude leer el ticket. Intentá con una foto más nítida.")
        return

    if not gastos:
        await update.message.reply_text("No encontré gastos en la imagen.")
        return

    guardados = []
    for g in gastos:
        try:
            await registrar_gasto(g)
            guardados.append(g)
        except Exception:
            pass

    if not guardados:
        await update.message.reply_text("Encontré gastos pero no pude guardarlos.")
        return

    texto = "✅ *Ticket procesado*\n\n"
    for g in guardados:
        texto += f"• {g['concepto']}: {formatear_monto(g['monto'])} ({g['categoria']})\n"

    await update.message.reply_text(texto, parse_mode="Markdown")


async def manejar_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, Conflict):
        print("Conflict: otra instancia corriendo, esperando...")
        await asyncio.sleep(3)
        return
    print(f"Error: {context.error}")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ayuda", cmd_start))
    app.add_handler(CommandHandler("resumen", manejar_texto))
    app.add_handler(CommandHandler("metas", manejar_texto))
    app.add_handler(CommandHandler("cuotas", manejar_texto))
    app.add_handler(CommandHandler("ingresos", manejar_texto))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto))
    app.add_handler(MessageHandler(filters.PHOTO, manejar_foto))
    app.add_error_handler(manejar_error)
    print("Bot iniciado...")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
