
import os, re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from inventory_core import (get_tables, set_tables, norm, unit_to_base, codigo_por_nome, 
                            registrar_mov, abater_por_venda, preco_sugerido, estoque_atual_por_codigo, 
                            custo_medio_por_codigo, receita_do)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise SystemExit("Defina a variável de ambiente TELEGRAM_TOKEN")

HELP_TEXT = (
    "Comandos:\n"
    "- vendi N <produto>\n"
    "- entrada <ingrediente> <qtd><un> <valor_total>\n"
    "- ajuste <ingrediente> <+/-qtd><un>\n"
    "- estoque <ingrediente>\n"
    "- preco <produto>\n"
    "- receita <produto>\n"
    "- alertas\n"
    "- resumo hoje\n"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Oi! Sou o agente do Burtequin 🍔. Diga: 'vendi 2 simpatia'.\n\n" + HELP_TEXT)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    n = norm(text)
    params, ingredientes, receitas, movimentos = get_tables()

    try:
        if n.startswith("vendi "):
            parts = text.split()
            qtd = float(parts[1])
            nome = " ".join(parts[2:])
            movimentos, q, linhas = abater_por_venda(ingredientes, receitas, movimentos, nome, qtd)
            set_tables(movimentos=movimentos)
            if not linhas:
                await update.message.reply_text("Receita não encontrada para este produto.")
            else:
                det = "\n".join([f"- {c}: -{qtd}{un}" for c,qtd,un in linhas])
                await update.message.reply_text(f"Venda registrada ({q}x {nome}).\nBaixas:\n{det}")
            return

        if n.startswith("entrada "):
            parts = text.split()
            nome = " ".join(parts[1:-2])
            qtd_un = parts[-2]
            valor = float(parts[-1].replace("R$","").replace(",","."))
            m = re.match(r"([0-9]*\.?[0-9]+)\s*([a-zA-Z]+)", qtd_un)
            if not m:
                await update.message.reply_text("Formato: entrada <ingrediente> <quantidade><un> <valor_total>")
                return
            q = float(m.group(1)); un = m.group(2)
            base_un, base_q = unit_to_base(un, q)
            cod = codigo_por_nome(ingredientes, nome) or nome
            movimentos, _ = registrar_mov(movimentos, "Entrada", cod, base_un, base_q, valor, ref="Compra", obs="")
            set_tables(movimentos=movimentos)
            await update.message.reply_text(f"Entrada registrada: {cod} {base_q}{base_un} R${valor:.2f}")
            return

        if n.startswith("ajuste "):
            parts = text.split()
            nome = " ".join(parts[1:-1])
            qtd_un = parts[-1]
            m = re.match(r"([\-+]?[0-9]*\.?[0-9]+)\s*([a-zA-Z]+)", qtd_un)
            if not m:
                await update.message.reply_text("Formato: ajuste <ingrediente> <+/-quantidade><un>")
                return
            q = float(m.group(1)); un = m.group(2)
            base_un, base_q = unit_to_base(un, abs(q))
            cod = codigo_por_nome(ingredientes, nome) or nome
            if q >= 0:
                movimentos, _ = registrar_mov(movimentos, "Ajuste", cod, base_un, base_q, 0.0, ref="Ajuste +", obs="")
            else:
                movimentos, _ = registrar_mov(movimentos, "Saida", cod, base_un, abs(base_q), 0.0, ref="Ajuste -", obs="")
            set_tables(movimentos=movimentos)
            await update.message.reply_text(f"Ajuste registrado: {cod} {q}{base_un}")
            return

        if n.startswith("preco "):
            nome = text.split(" ",1)[1]
            preco, info = preco_sugerido(params, ingredientes, receitas, movimentos, nome)
            await update.message.reply_text(
                f"💰 Preço sugerido de {nome}: R${preco:.2f}\n"
                f"(Ingredientes: {info['custo_ingredientes']} | Embalagem: {info['embalagem']} | Overhead: {info['overhead_venda']})\n"
                f"Custo total: {info['custo_total']} | Margem: {info['margem']} | % taxas/impostos: {info['percentuais']}"
            )
            return

        if n.startswith("estoque "):
            nome = text.split(" ",1)[1]
            from inventory_core import estoque_atual_por_codigo, custo_medio_por_codigo
            cod = codigo_por_nome(ingredientes, nome) or nome
            est = estoque_atual_por_codigo(movimentos, cod)
            cm = custo_medio_por_codigo(movimentos, cod)
            await update.message.reply_text(f"{cod}: estoque {est:.2f}; custo médio {('R$ %.2f' % cm) if cm else '—'}")
            return

        if n.startswith("receita "):
            nome = text.split(" ",1)[1]
            rc = receita_do(receitas, nome)
            if rc.empty:
                await update.message.reply_text("Receita não encontrada.")
            else:
                out = "\n".join([f"- {r.codigo_ingrediente}: {r.quantidade}" for r in rc.itertuples()])
                await update.message.reply_text(f"Receita de {nome}:\n{out}")
            return

        if n.startswith("alertas"):
            rows = []
            for _, ing in ingredientes.iterrows():
                cod = ing["codigo"]; minq = float(ing.get("estoque_minimo",0) or 0)
                from inventory_core import estoque_atual_por_codigo
                est = estoque_atual_por_codigo(movimentos, cod)
                if est <= minq:
                    rows.append(f"- {cod}: {est:.2f} (min {minq})")
            msg = "Sem alertas ✅" if not rows else "⚠️ Itens no ponto de compra:\n" + "\n".join(rows)
            await update.message.reply_text(msg)
            return

        if n.startswith("resumo hoje"):
            from datetime import datetime
            hoje = datetime.now().date().isoformat()
            df = movimentos[movimentos["data"].str.startswith(hoje)]
            if df.empty:
                await update.message.reply_text("Sem movimentos hoje.")
            else:
                out = "\n".join([f"{r.tipo} {r.codigo_ingrediente} {r.quantidade}{r.un} R${r.valor_total}" for r in df.itertuples()])
                await update.message.reply_text(out)
            return

    except Exception as e:
        await update.message.reply_text(f"Erro: {e}")

    await update.message.reply_text("Não entendi 🧐. Exemplos:\n" + HELP_TEXT)

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
