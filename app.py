import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
from banco import conectar, criar_tabelas
from sqlalchemy.sql import text
import pytz  # Biblioteca para fuso horário do Brasil

# Configuração visual da página do Streamlit
st.set_page_config(page_title="Controle de Estoque - Obra", layout="wide")
st.title("🏗️ Sistema de Inventário e Estoque de Obra")

# --- SISTEMA DE LOGIN E CONTROLE DE ACESSO ---
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False
    st.session_state["perfil"] = None
    st.session_state["usuario_logado"] = ""

# Dicionário de usuários, senhas e perfis
USUARIOS = {
    "isaac": {"senha": "adminobra", "perfil": "Admin"},
    "equipe": {"senha": "obravezmais", "perfil": "Campo"}
}

if not st.session_state["autenticado"]:
    st.subheader("🔒 Acesso Restrito - Identifique-se")
    col_login, _ = st.columns([1, 2])
    
    with col_login:
        with st.form("form_login"):
            usuario_input = st.text_input("Usuário").strip().lower()
            senha_input = st.text_input("Senha", type="password")
            botao_entrar = st.form_submit_button("Entrar no Sistema")
            
            if botao_entrar:
                if usuario_input in USUARIOS and USUARIOS[usuario_input]["senha"] == senha_input:
                    st.session_state["autenticado"] = True
                    st.session_state["perfil"] = USUARIOS[usuario_input]["perfil"]
                    st.session_state["usuario_logado"] = usuario_input.capitalize()
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos.")
    st.stop()

# --- MENU LATERAL ---
st.sidebar.markdown(f"👤 **Usuário:** {st.session_state['usuario_logado']} ({st.session_state['perfil']})")

if st.session_state["perfil"] == "Admin":
    opcoes_menu = [
        "Visualizar Estoque", 
        "Materiais em Alerta",
        "Cadastrar Novo Material", 
        "Registrar Movimentação",
        "Histórico Avançado e Relatórios",
        "Gerenciar Usuários"
    ]
else:
    opcoes_menu = [
        "Visualizar Estoque", 
        "Registrar Movimentação"
    ]

menu = st.sidebar.selectbox("Menu de Navegação", opcoes_menu)

if st.sidebar.button("🚪 Logout / Sair"):
    st.session_state["autenticado"] = False
    st.session_state["perfil"] = None
    st.rerun()

# --- FUNÇÕES INTERNAS ---
def listar_materials():
    engine = conectar()
    return pd.read_sql_query(text("SELECT id, nome, unidade, quantidade, estoque_minimo FROM materiais ORDER BY nome"), engine)

def calcular_autonomia(df_estoque):
    engine = conectar()
    fuso_br = pytz.timezone('America/Sao_Paulo')
    data_limite = (datetime.now(fuso_br) - timedelta(days=7)).strftime('%Y-%m-%d')
    try:
        df_saidas = pd.read_sql_query(text(f"SELECT material_id, quantidade FROM movimentacoes WHERE tipo = 'SAÍDA' AND data >= '{data_limite}'"), engine)
        consumo_diario = (df_saidas.groupby('material_id')['quantidade'].sum() / 7.0) if not df_saidas.empty else pd.Series(dtype='float64')
    except:
        consumo_diario = pd.Series(dtype='float64')
        
    df_estoque['Autonomia Estimada'] = [f"⏳ {qtd/consumo_diario.get(m_id, 0):.1f} dias" if consumo_diario.get(m_id, 0) > 0 else "♾️ Estável" for m_id, qtd in zip(df_estoque['id'], df_estoque['quantidade'])]
    return df_estoque

def cadastrar_material(nome, unidade, estoque_minimo):
    engine = conectar()
    try:
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO materiais (nome, unidade, quantidade, estoque_minimo) VALUES (:nome, :unidade, 0, :estoque_minimo)"),
                {"nome": nome.upper(), "unidade": unidade, "estoque_minimo": estoque_minimo}
            )
            conn.commit()
        st.success(f"Material '{nome.upper()}' cadastrado com sucesso!")
    except Exception as e:
        st.error(f"Erro ao cadastrar no banco: {e}")

def registrar_movimento(material_id, tipo, qtd, responsavel):
    engine = conectar()
    fuso_br = pytz.timezone('America/Sao_Paulo')
    data_br = datetime.now(fuso_br)
    try:
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO movimentacoes (material_id, tipo, quantidade, responsavel, data) VALUES (:m_id, :tipo, :qtd, :resp, :data)"),
                         {"m_id": int(material_id), "tipo": tipo, "qtd": float(qtd), "resp": responsavel, "data": data_br})
            delta = float(qtd) if tipo == "ENTRADA" else -float(qtd)
            conn.execute(text("UPDATE materiais SET quantidade = quantidade + :delta WHERE id = :id"), {"delta": delta, "id": int(material_id)})
            conn.commit()
        st.success(f"Registrado com sucesso!")
    except Exception as e:
        st.error(f"Erro: {e}")

# --- TELAS ---

if menu == "Visualizar Estoque":
    st.header("📊 Painel Geral de Materiais")
    df = calcular_autonomia(listar_materials())
    
    col1, col2, col3 = st.columns(3)
    col1.metric("📋 Itens Cadastrados", f"{len(df)} itens")
    col2.metric("📦 Volume Total", f"{df['quantidade'].sum():,.1f}")
    alertas = len(df[df['quantidade'] < df['estoque_minimo']])
    col3.metric("⚠️ Críticos", alertas, delta="- Repor Urgente" if alertas > 0 else "OK", delta_color="inverse" if alertas > 0 else "normal")
    
    st.subheader("Saldo Atual")
    df_vis = df[['id', 'nome', 'unidade', 'quantidade', 'estoque_minimo', 'Autonomia Estimada']].copy()
    df_vis.columns = ['ID', 'Material', 'Unidade', 'quantidade', 'estoque_minimo', 'Autonomia (7 dias)']
    st.dataframe(df_vis.style.apply(lambda r: ['background-color: #ffcccc' if r['quantidade'] < r['estoque_minimo'] else '' for _ in r], axis=1), use_container_width=True)

    # --- HISTÓRICO CORRIGIDO (AQUI ESTÁ A CORREÇÃO DA CONSULTA VAZIA) ---
    st.subheader("📜 Últimas 10 Movimentações Gerais")
    engine = conectar()
    df_mov = pd.read_sql_query(text("""
        SELECT m.tipo AS "Operação", 
               mat.nome AS "Material", 
               m.quantidade AS "Qtd", 
               mat.unidade AS "Unidade", 
               to_char(m.data, 'DD/MM/YYYY HH24:MI:SS') AS "Data/Hora", 
               m.responsavel AS "Responsável"
        FROM movimentacoes m
        JOIN materiais mat ON m.material_id = mat.id
        ORDER BY m.data DESC 
        LIMIT 10
    """), engine)
    
    if df_mov.empty:
        st.text("Nenhuma movimentação realizada.")
    else:
        st.dataframe(df_mov, use_container_width=True)

elif menu == "Registrar Movimentação":
    st.header("🔄 Registrar Entrada ou Saída")
    df_mat = listar_materials()
    lista = {f"{r['nome']} ({r['unidade']})": r['id'] for _, r in df_mat.iterrows()}
    
    with st.form("form_mov"):
        mat = st.selectbox("Selecione o Material", list(lista.keys()))
        tipo = st.radio("Tipo", ["ENTRADA", "SAÍDA"])
        qtd = st.number_input("Quantidade", min_value=0.1, step=1.0)
        resp = st.text_input("Responsável", value=st.session_state["usuario_logado"], disabled=(st.session_state["perfil"] != "Admin"))
        
        if st.form_submit_button("Confirmar"):
            id_m = lista[mat]
            saldo = df_mat[df_mat['id'] == id_m]['quantidade'].values[0]
            if tipo == "SAÍDA" and qtd > saldo:
                st.error(f"Saldo insuficiente! Atual: {saldo}")
            else:
                registrar_movimento(id_m, tipo, qtd, resp)

elif menu == "Gerenciar Usuários" and st.session_state["perfil"] == "Admin":
    st.header("👥 Gerenciamento de Usuários e Permissões")
    
    st.subheader("Usuários Ativos no Sistema")
    df_users = pd.DataFrame([{"Usuário": k, "Perfil": v["perfil"]} for k, v in USUARIOS.items()])
    st.table(df_users)
    
    st.markdown("---")
    st.subheader("🛠️ O que cada perfil pode fazer?")
    
    col_adm, col_cam = st.columns(2)
    with col_adm:
        st.info("### 👑 Perfil: Admin")
        st.markdown("""
        - **Visualizar Estoque:** Sim (com Autonomia)
        - **Cadastrar Materiais:** Sim
        - **Ver Alertas Críticos:** Sim
        - **Registrar Movimentação:** Sim (pode alterar o nome do responsável)
        - **Histórico e Relatórios:** Sim (Filtros e Excel)
        - **Gerenciar Usuários:** Sim
        """)
    with col_cam:
        st.warning("### 👷 Perfil: Campo")
        st.markdown("""
        - **Visualizar Estoque:** Sim
        - **Cadastrar Materiais:** Não
        - **Ver Alertas Críticos:** Não
        - **Registrar Movimentação:** Sim (nome do responsável fica travado)
        - **Histórico e Relatórios:** Não
        - **Gerenciar Usuários:** Não
        """)

elif menu == "Cadastrar Novo Material" and st.session_state["perfil"] == "Admin":
    st.header("📝 Cadastrar Insumo")
    with st.form("f_cad"):
        n = st.text_input("Nome").upper()
        u = st.selectbox("Unidade", ["Saco", "m³", "Kg", "Unidade", "Barra"])
        m = st.number_input("Estoque Mínimo", value=10.0)
        if st.form_submit_button("Salvar") and n:
            cadastrar_material(n, u, m)

elif menu == "Histórico Avançado e Relatórios" and st.session_state["perfil"] == "Admin":
    st.header("📅 Histórico Completo")
    fuso = pytz.timezone('America/Sao_Paulo')
    d1 = st.date_input("Início", datetime.now(fuso) - timedelta(days=7))
    d2 = st.date_input("Fim", datetime.now(fuso))
    
    engine = conectar()
    query = text("""
        SELECT m.tipo AS "Operação", mat.nome AS "Material", m.quantidade AS "Qtd", mat.unidade AS "Unidade", 
        to_char(m.data, 'DD/MM/YYYY HH24:MI:SS') AS "Data/Hora", 
        m.responsavel AS "Responsável"
        FROM movimentacoes m JOIN materiais mat ON m.material_id = mat.id
        WHERE m.data::date BETWEEN :d1 AND :d2
        ORDER BY m.data DESC
    """)
    df_hist = pd.read_sql_query(query, engine, params={"d1": d1, "d2": d2})
    st.dataframe(df_hist, use_container_width=True)
    
    if not df_hist.empty:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_hist.to_excel(writer, index=False)
        st.download_button("📥 Baixar Excel", output.getvalue(), "relatorio_obra.xlsx")

elif menu == "Materiais em Alerta" and st.session_state["perfil"] == "Admin":
    st.header("⚠️ Itens Críticos")
    df = listar_materials()
    crit = df[df['quantidade'] < df['estoque_minimo']]
    if crit.empty: st.success("Tudo OK!")
    else: st.dataframe(crit, use_container_width=True)
