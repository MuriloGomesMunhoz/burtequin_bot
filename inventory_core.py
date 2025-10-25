
import pandas as pd
import json, os
from datetime import datetime
from unidecode import unidecode

DATA_DIR = os.environ.get("BURTEQ_DATA_DIR", "data")
PARAMS_FILE = os.path.join(DATA_DIR, "parametros.json")
ING_FILE = os.path.join(DATA_DIR, "ingredientes.csv")
REC_FILE = os.path.join(DATA_DIR, "receitas.csv")
MOV_FILE = os.path.join(DATA_DIR, "movimentos.csv")

def _ensure_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(PARAMS_FILE):
        with open(PARAMS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "imposto_percent": 0.08,
                "taxa_plataforma_percent": 0.23,
                "taxa_cartao_percent": 0.03,
                "desconto_medio_percent": 0.0,
                "margem_liquida_desejada_percent": 0.18,
                "overhead_mensal_est": 4000.0,
                "vendas_previstas_mes": 500,
                "custo_embalagem_padrao": 2.50
            }, f, ensure_ascii=False, indent=2)
    if not os.path.exists(ING_FILE):
        pd.DataFrame(columns=["codigo","ingrediente","un_base","estoque_minimo"]).to_csv(ING_FILE, index=False)
    if not os.path.exists(REC_FILE):
        pd.DataFrame(columns=["produto","variante","codigo_ingrediente","quantidade"]).to_csv(REC_FILE, index=False)
    if not os.path.exists(MOV_FILE):
        pd.DataFrame(columns=["data","tipo","codigo_ingrediente","un","quantidade","valor_total","ref","observacao"]).to_csv(MOV_FILE, index=False)

_ensure_files()

def load_params():
    with open(PARAMS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_params(p):
    with open(PARAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)

def load_csv(path, cols):
    try:
        df = pd.read_csv(path)
        for c in cols:
            if c not in df.columns:
                df[c] = None
        return df
    except:
        return pd.DataFrame(columns=cols)

def save_csv(df, path):
    df.to_csv(path, index=False)

def norm(s):
    return unidecode(str(s).strip().lower())

def unit_to_base(un, qty):
    u = norm(un)
    if u in ["kg","quilo","quilos"]:
        return "g", qty*1000.0
    if u in ["un","unid","unidade","unidades"]:
        return "un", qty
    return "g", qty if u=="g" else qty

def get_tables():
    params = load_params()
    ingredientes = load_csv(ING_FILE, ["codigo","ingrediente","un_base","estoque_minimo"])
    receitas = load_csv(REC_FILE, ["produto","variante","codigo_ingrediente","quantidade"])
    movimentos = load_csv(MOV_FILE, ["data","tipo","codigo_ingrediente","un","quantidade","valor_total","ref","observacao"])
    return params, ingredientes, receitas, movimentos

def set_tables(params=None, ingredientes=None, receitas=None, movimentos=None):
    if params is not None: save_params(params)
    if ingredientes is not None: save_csv(ingredientes, ING_FILE)
    if receitas is not None: save_csv(receitas, REC_FILE)
    if movimentos is not None: save_csv(movimentos, MOV_FILE)

def codigo_por_nome(ingredientes, nome):
    n = norm(nome)
    m = ingredientes[ingredientes["ingrediente"].apply(lambda x: norm(x)==n)]
    if len(m): return m.iloc[0]["codigo"]
    m = ingredientes[ingredientes["ingrediente"].apply(lambda x: n in norm(x))]
    if len(m): return m.iloc[0]["codigo"]
    m = ingredientes[ingredientes["codigo"].apply(lambda x: norm(x)==n)]
    if len(m): return m.iloc[0]["codigo"]
    return None

def receita_do(receitas, produto, variante="Padrao"):
    prod_n = norm(produto)
    df = receitas[receitas["produto"].apply(lambda x: norm(x)==prod_n)]
    if len(df)==0: return pd.DataFrame(columns=receitas.columns)
    dfv = df[df["variante"].fillna("Padrao").apply(norm)==norm(variante)]
    return dfv if len(dfv) else df

def custo_medio_por_codigo(movimentos, cod):
    df_in = movimentos[(movimentos["tipo"]=="Entrada") & (movimentos["codigo_ingrediente"]==cod)]
    if len(df_in)==0: return None
    tot_q = df_in["quantidade"].astype(float).sum()
    tot_v = df_in["valor_total"].astype(float).sum()
    if tot_q<=0: return None
    return tot_v/tot_q

def estoque_atual_por_codigo(movimentos, cod):
    q = 0.0
    for _,r in movimentos[movimentos["codigo_ingrediente"]==cod].iterrows():
        if r["tipo"] in ["Entrada","Ajuste"]:
            q += float(r["quantidade"])
        elif r["tipo"]=="Saida":
            q -= float(r["quantidade"])
    return q

def registrar_mov(movimentos, tipo, codigo, un, quantidade, valor_total=0.0, ref="", obs=""):
    row = {
        "data": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tipo": tipo,
        "codigo_ingrediente": codigo,
        "un": un,
        "quantidade": float(quantidade),
        "valor_total": float(valor_total),
        "ref": ref,
        "observacao": obs
    }
    movimentos = pd.concat([movimentos, pd.DataFrame([row])], ignore_index=True)
    save_csv(movimentos, MOV_FILE)
    return movimentos, row

def abater_por_venda(ingredientes, receitas, movimentos, produto, qtd=1, variante="Padrao", ref="Venda"):
    rc = receita_do(receitas, produto, variante)
    if len(rc)==0:
        return movimentos, 0, []
    linhas = []
    for _, r in rc.iterrows():
        cod = r["codigo_ingrediente"]
        row_ing = ingredientes[ingredientes["codigo"]==cod]
        unb = row_ing.iloc[0]["un_base"] if len(row_ing) else "g"
        quant = float(r["quantidade"]) * float(qtd)
        movimentos, _ = registrar_mov(movimentos, "Saida", cod, unb, quant, 0.0, ref=f"{ref} {produto}", obs=f"{qtd}x {produto}")
        linhas.append((cod, quant, unb))
    return movimentos, qtd, linhas

def preco_sugerido(params, ingredientes, receitas, movimentos, produto, variante="Padrao"):
    rc = receita_do(receitas, produto, variante)
    total = 0.0
    for _, r in rc.iterrows():
        cod = r["codigo_ingrediente"]
        qtd = float(r["quantidade"])
        cm = custo_medio_por_codigo(movimentos, cod) or 0.0
        total += qtd*cm
    embalagem = params.get("custo_embalagem_padrao", 0.0) or 0.0
    overhead = (params.get("overhead_mensal_est",0.0) or 0.0) / max(params.get("vendas_previstas_mes",1),1)
    custo_total = total + embalagem + overhead
    percentuais = sum([params.get(k,0.0) or 0.0 for k in [
        "imposto_percent","taxa_plataforma_percent","taxa_cartao_percent","desconto_medio_percent"
    ]])
    margem = params.get("margem_liquida_desejada_percent", 0.0) or 0.0
    base = 1.0 - (percentuais + margem)
    preco = custo_total / base if base>0 else 0.0
    return round(preco,2), {
        "custo_ingredientes": round(total,2),
        "embalagem": round(embalagem,2),
        "overhead_venda": round(overhead,2),
        "custo_total": round(custo_total,2),
        "percentuais": round(percentuais,2),
        "margem": round(margem,2)
    }
