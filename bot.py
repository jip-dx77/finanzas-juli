import os
import re
import base64
import json
from datetime import datetime
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client, Client

# ── Clientes ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ["TELEGRAM_TOKEN"]
SUPABASE_URL    = os.environ["SUPABASE_URL"]
SUPABASE_KEY    = os.environ["SUPABASE_KEY"]
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]
MI_CHAT_ID      = int(os.environ["MI_CHAT_ID"])   # tu ID personal de Telegram

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

CATEGORIAS = [
    "super", "comida", "combustible", "servicios", "tarjeta",
    "salud", "ropa", "ocio", "transporte", "suscripcion", "otros"
]

# ── Seguridad: solo vos podés usar el bot ────────────────────────────────────
def solo_yo(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != MI_CHAT_ID:
            await update.message.reply_text("No autorizado.")
            return
        return await func(update, ctx)
    return wrapper

# ── Guardar gasto en Supabase ─────────────────────────────────────────────────
def guardar_gasto(concepto: str, monto: float, categoria: str, fuente: str = "telegram"):
    hoy = datetime.now()
    data = {
        "concepto":  concepto,
        "monto":     monto,
        "categoria": categoria,
        "fecha":     hoy.date().isoformat(),
        "mes":       hoy.month,
        "anio":      hoy.year,
        "fuente":    fuente,
    }
    resultado = supabase.table("gastos").insert(data).execute()
    return resultado.data[0] if resultado.data else None

# ── Parsear texto libre: "carne 25000" / "super 12500 comida" ─────────────────
def parsear_texto(texto: str):
    texto = texto.strip().lower()
    # busca número (con o sin puntos/comas)
    match = re.search(r"([\d\.,]+)", texto)
    if not match:
        return None, None, None
    monto_str = match.group(1).replace(".", "").replace(",", "")
    monto = float(monto_str)
    # resto del texto = concepto
    concepto = re.sub(r"[\d\.,]+", "", texto).strip()
    concepto = re.sub(r"\s+", " ", concepto).strip()
    # intentar detectar categoría
    categoria = "otros"
    for cat in CATEGORIAS:
        if cat in texto:
            categoria = cat
            break
    if not concepto:
        concepto = categoria
    return concepto.title(), monto, categoria

# ── Parsear foto de ticket con Claude Vision ──────────────────────────────────
async def parsear_foto(foto_bytes: bytes) -> dict:
    img_b64 = base64.standard_b64encode(foto_bytes).decode("utf-8")
    prompt = """Analizá este ticket/factura y devolvé SOLO un JSON válido con:
{
  "concepto": "nombre del negocio o descripción breve",
  "monto": número total en pesos (solo el número, sin $ ni puntos),
  "categoria": una de: super, comida, combustible, servicios, tarjeta, salud, ropa, ocio, transporte, suscripcion, otros,
  "items": ["item1", "item2"] (opcional, los principales productos)
}
Si no podés leer el monto, poné 0. No incluyas nada más que el JSON."""
    
    mensaje = claude.messages.create(
        model="claude-opus-4-6",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
                {"type": "text", "text": prompt}
            ]
        }]
    )
    texto = mensaje.content[0].text.strip()
    # limpiar posibles ```json ... ```
    texto = re.sub(r"```json|```", "", texto).strip()
    return json.loads(texto)

# ── /start ────────────────────────────────────────────────────────────────────
@solo_yo
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola! Soy tu bot de finanzas 💰\n\n"
        "Podés:\n"
        "• Escribir: *carne 25000* o *super 12500 comida*\n"
        "• Mandar una *foto de ticket* y lo cargo automático\n"
        "• /resumen — ver resumen del mes\n"
        "• /ayuda — ver todos los comandos",
        parse_mode="Markdown"
    )

# ── /resumen ──────────────────────────────────────────────────────────────────
@solo_yo
async def cmd_resumen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    hoy = datetime.now()
    res = supabase.table("gastos")\
        .select("categoria, monto")\
        .eq("mes", hoy.month)\
        .eq("anio", hoy.year)\
        .execute()
    
    if not res.data:
        await update.message.reply_text("No hay gastos registrados este mes todavía.")
        return
    
    totales = {}
    for g in res.data:
        cat = g["categoria"]
        totales[cat] = totales.get(cat, 0) + g["monto"]
    
    total = sum(totales.values())
    lineas = [f"📊 *Resumen {hoy.strftime('%B %Y')}*\n"]
    for cat, monto in sorted(totales.items(), key=lambda x: -x[1]):
        pct = (monto / total * 100) if total else 0
        lineas.append(f"• {cat.title()}: ${monto:,.0f} ({pct:.0f}%)")
    lineas.append(f"\n💰 *Total: ${total:,.0f}*")
    
    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")

# ── /ayuda ────────────────────────────────────────────────────────────────────
@solo_yo
async def cmd_ayuda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Comandos disponibles:*\n\n"
        "/start — bienvenida\n"
        "/resumen — gastos del mes actual\n"
        "/ayuda — esta ayuda\n\n"
        "*Cargar gasto rápido:*\n"
        "• `carne 25000`\n"
        "• `nafta 18000 combustible`\n"
        "• `netflix 5000 suscripcion`\n\n"
        "*Foto de ticket:*\nMandá la foto y la leo automáticamente.",
        parse_mode="Markdown"
    )

# ── Recibir mensaje de texto ──────────────────────────────────────────────────
@solo_yo
async def recibir_texto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if texto.startswith("/"):
        return
    
    concepto, monto, categoria = parsear_texto(texto)
    
    if not monto or monto <= 0:
        await update.message.reply_text(
            "No pude entender el monto. Probá con:\n*carne 25000* o *super 12500*",
            parse_mode="Markdown"
        )
        return
    
    gasto = guardar_gasto(concepto, monto, categoria, fuente="telegram-texto")
    
    await update.message.reply_text(
        f"✅ *Gasto guardado*\n\n"
        f"📝 {concepto}\n"
        f"💰 ${monto:,.0f}\n"
        f"🏷️ {categoria.title()}\n"
        f"📅 {datetime.now().strftime('%d/%m/%Y')}",
        parse_mode="Markdown"
    )

# ── Recibir foto de ticket ────────────────────────────────────────────────────
@solo_yo
async def recibir_foto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Leyendo el ticket... un segundo ⏳")
    
    foto = update.message.photo[-1]  # la de mayor resolución
    archivo = await foto.get_file()
    foto_bytes = await archivo.download_as_bytearray()
    
    try:
        datos = await parsear_foto(bytes(foto_bytes))
        concepto  = datos.get("concepto", "Gasto ticket")
        monto     = float(datos.get("monto", 0))
        categoria = datos.get("categoria", "otros")
        items     = datos.get("items", [])
        
        if monto <= 0:
            await update.message.reply_text(
                "No pude leer el monto del ticket. "
                "Podés cargarlo manualmente: *nombre monto*",
                parse_mode="Markdown"
            )
            return
        
        guardar_gasto(concepto, monto, categoria, fuente="telegram-foto")
        
        items_txt = "\n".join(f"  · {i}" for i in items[:4]) if items else ""
        msg = (
            f"✅ *Ticket procesado*\n\n"
            f"🏪 {concepto}\n"
            f"💰 ${monto:,.0f}\n"
            f"🏷️ {categoria.title()}\n"
        )
        if items_txt:
            msg += f"📋 Items:\n{items_txt}\n"
        msg += f"📅 {datetime.now().strftime('%d/%m/%Y')}"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
    
    except Exception as e:
        await update.message.reply_text(
            f"No pude procesar la imagen. Error: {str(e)[:80]}\n"
            "Intentá mandar el gasto como texto: *nombre monto*",
            parse_mode="Markdown"
        )

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(CommandHandler("ayuda",   cmd_ayuda))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_texto))
    app.add_handler(MessageHandler(filters.PHOTO, recibir_foto))
    print("Bot corriendo...")
    app.run_polling()

if __name__ == "__main__":
    main()
