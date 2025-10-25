
import os, json, re
from flask import Flask, request, jsonify
from inventory_core import (get_tables, set_tables, norm, unit_to_base, codigo_por_nome, 
                            registrar_mov, abater_por_venda, preco_sugerido, estoque_atual_por_codigo, 
                            custo_medio_por_codigo, receita_do)

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "verify_me")
ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN")
PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID")

def send_whatsapp_text(to, body):
    import requests
    url = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    data = {"messaging_product":"whatsapp","to": to,"type":"text","text":{"body": body}}
    r = requests.post(url, headers=headers, json=data, timeout=10)
    return r.status_code

@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "failed", 403

@app.post("/webhook")
def inbound():
    payload = request.get_json()
    try:
        entry = payload["entry"][0]["changes"][0]["value"]
        msgs = entry.get("messages", [])
        for msg in msgs:
            if msg.get("type")=="text":
                from_num = msg["from"]
                text = msg["text"]["body"]
                reply = handle_text(text)
                send_whatsapp_text(from_num, reply)
    except Exception as e:
        print("ERR:", e)
    return jsonify({"status":"ok"})

def handle_text(text: str) -> str:
    n = norm(text)
    params, ingredientes, receitas, movimentos = get_tables()

    try:
        if n.startswith("alertas"):
            rows = []
            for _, ing in ingredientes.iterrows():
                cod = ing["codigo"]; minq = float(ing.get("estoque_minimo",0) or 0)
                est = estoque_atual_por_codigo(movimentos, cod)
                if est <= minq:
                    rows.append(f"- {cod}: {est:.2f} (min {minq})")
            return "Sem alertas ✅" if not rows else "⚠️ Ponto de compra:\n" + "\n".join(rows)

        if n.startswith("receita "):
            nome = text.split(" ",1)[1]
            rc = receita_do(receitas, nome)
            if rc.empty: return "Receita não encontrada."
            out = "\n".join([f"- {r.codigo_ingrediente}: {r.quantidade}" for r in rc.itertuples()])
            return f"Receita de {nome}:\n{out}"

        if n.startswith("preco "):
            nome = text.split(" ",1)[1]
            preco, info = preco_sugerido(params, ingredientes, receitas, movimentos, nome)
            return (f"💰 Preço sugerido de {nome}: R$ {preco:.2f}\n"
                    f"(Ingredientes: {info['custo_ingredientes']} | Embalagem: {info['embalagem']} | Overhead: {info['overhead_venda']})\n"
                    f"Custo total: {info['custo_total']} | Margem: {info['margem']} | % taxas/impostos: {info['percentuais']}")

        if n.startswith("estoque "):
            nome = text.split(" ",1)[1]
            cod = codigo_por_nome(ingredientes, nome) or nome
            est = estoque_atual_por_codigo(movimentos, cod)
            cm = custo_medio_por_codigo(movimentos, cod)
            return f"{cod}: estoque {est:.2f}; custo médio {('R$ %.2f' % cm) if cm else '—'}"

        if n.startswith("entrada "):
            parts = text.split()
            nome = " ".join(parts[1:-2])
            qtd_un = parts[-2]
            valor = float(parts[-1].replace("R$","").replace(",","."))
            m = re.match(r"([0-9]*\.?[0-9]+)\s*([a-zA-Z]+)", qtd_un)
            if not m: return "Formato: entrada <ingrediente> <quantidade><un> <valor_total>"
            q = float(m.group(1)); un = m.group(2)
            base_un, base_q = unit_to_base(un, q)
            cod = codigo_por_nome(ingredientes, nome) or nome
            movimentos, _ = registrar_mov(movimentos, "Entrada", cod, base_un, base_q, valor, ref="Compra", obs="")
            set_tables(movimentos=movimentos)
            return f"Entrada registrada: {cod} {base_q}{base_un} R${valor:.2f}"

        if n.startswith("ajuste "):
            parts = text.split()
            nome = " ".join(parts[1:-1])
            qtd_un = parts[-1]
            m = re.match(r"([\-+]?[0-9]*\.?[0-9]+)\s*([a-zA-Z]+)", qtd_un)
            if not m: return "Formato: ajuste <ingrediente> <+/-quantidade><un>"
            q = float(m.group(1)); un = m.group(2)
            base_un, base_q = unit_to_base(un, abs(q))
            cod = codigo_por_nome(ingredientes, nome) or nome
            if q >= 0:
                movimentos, _ = registrar_mov(movimentos, "Ajuste", cod, base_un, base_q, 0.0, ref="Ajuste +", obs="")
            else:
                movimentos, _ = registrar_mov(movimentos, "Saida", cod, base_un, abs(base_q), 0.0, ref="Ajuste -", obs="")
            set_tables(movimentos=movimentos)
            return f"Ajuste registrado: {cod} {q}{base_un}"

        if n.startswith("vendi "):
            parts = text.split()
            qtd = float(parts[1])
            nome = " ".join(parts[2:])
            movimentos, q, linhas = abater_por_venda(ingredientes, receitas, movimentos, nome, qtd)
            set_tables(movimentos=movimentos)
            if not linhas: return "Receita não encontrada para este produto."
            det = "\n".join([f"- {c}: -{qtd}{un}" for c,qtd,un in linhas])
            return f"Venda registrada ({q}x {nome}). Baixas:\n{det}"

        if n.startswith("resumo hoje"):
            from datetime import datetime
            hoje = datetime.now().date().isoformat()
            df = movimentos[movimentos["data"].str.startswith(hoje)]
            if df.empty: return "Sem movimentos hoje."
            out = "\n".join([f"{r.tipo} {r.codigo_ingrediente} {r.quantidade}{r.un} R${r.valor_total}" for r in df.itertuples()])
            return out

    except Exception as e:
        return f"Erro: {e}"

    return ("Não entendi. Exemplos:\n"
            "- vendi 2 simpatia\n- entrada bacon 2kg 80\n- ajuste cheddar -200g\n- estoque bacon\n- preco simpatia\n- alertas\n- resumo hoje")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
