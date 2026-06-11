import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
from banco import conectar, criar_tabelas
from sqlalchemy.sql import text
import pytz  
import smtplib  
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Configuração visual da página do Streamlit
st.set_page_config(page_title="Controle de Estoque - Obra", layout="wide")
st.title("🏗️ Sistema de Inventário e Estoque de Obra")

# --- 🧠 GERENCIADOR DE CONEXÃO CACHADA (EVITA TRAVAR O BANCO NA NUVEM) ---
@st.cache_resource
def obter_engine():
    return conectar()

# --- 🖼️ CONFIGURAÇÃO DE IMAGEM DE FUNDO (PROTEGIDA CONTRA CORTES) ---
imagem_fundo_url = "https://images.unsplash.com/photo-1541888946425-d81bb19240f5?q=80&w=1920&auto=format&fit=crop"
css_fundo = "<style>[data-testid='stAppViewContainer'] { background-image: linear-gradient(rgba(255, 255, 255, 0.85), rgba(255, 255, 255, 0.85)), url('" + imagem_fundo_url + "'); background-size: cover; background-position: center; background-repeat: no-repeat; background-attachment: fixed; } [data-testid='stSidebar'] { background-color: #f1f3f6 !important; } [data-testid='stMetricValue'] { background-color: rgba(255, 255, 255, 0.6); padding: 5px 10px; border-radius: 5px; }</style>"
st.markdown(css_fundo, unsafe_allow_html=True)

# --- 🔐 CONFIGURAÇÃO DEFINITIVA DOS ALERTAS POR E-MAIL ---
EMAIL_REMETENTE = "isaacmendes2516@gmail.com"  
SENHA_REMETENTE = "dqzmmvpowdoznheb"  
EMAIL_DESTINATARIO = "isaacmendes2516@gmail.com"  

def enviar_email_alerta(nome_material, qtd_atual, qtd_minima, unidade):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_REMETENTE
        msg['To'] = EMAIL_DESTINATARIO
        msg['Subject'] = f"⚠️ ESTOQUE CRÍTICO: {nome_material}"
        corpo = f"Alerta Vez Mais: O material {nome_material} atingiu o nivel crítico. Saldo: {qtd_atual} {unidade}. Mínimo: {qtd_minima}."
        msg.attach(MIMEText(corpo, 'plain'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
        server.sendmail(EMAIL_REMETENTE, EMAIL_DESTINATARIO, msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Erro e-mail: {e}")

# --- SISTEMA DE LOGIN ---
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False
    st.session_state["perfil"] = None
    st.session_state["usuario_logado"] = ""

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
            if st.form_submit_button("Entrar no Sistema"):
                if usuario_input in USUARIOS and USUARIOS[usuario_input]["senha"] == senha_input:
                    st.session_state["autenticado"] = True
                    st.session_state["perfil"] = USUARIOS[usuario_input]["perfil"]
                    st.session_state["usuario_logado"] = usuario_input.capitalize()
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos.")
    st.stop()

# --- MENU LATERAL ---
st.sidebar.markdown(f"👤 **Usuário:** {st.session_state['usuario_logado']}")
if st.session_state["perfil"] == "Admin":
    opcoes_menu = ["Estoque", "Alertas", "Insumos", "Movimentar", "Histórico"]
else:
    opcoes_menu = ["Estoque", "Movimentar"]

menu = st.sidebar.selectbox("Navegação", opcoes_menu)

if st.sidebar.button("🚪 Sair"):
    st.session_state["autenticado"] = False
    st.rerun()

# --- FUNÇÕES INTERNAS OTIMIZADAS ---
def listar_materials():
    engine = obter_engine()
    return pd.read_sql_query(text("SELECT id, nome, unidade, quantidade, estoque_minimo FROM materiais ORDER BY nome"), engine)

def calcular_autonomia(df_estoque):
    engine = obter_engine()
    fuso_br = pytz.timezone('America/Sao_Paulo')
    hoje = datetime.now(fuso_br).date()
    data_limite = (hoje - timedelta(days=7)).strftime('%Y-%m-%d')
    try:
        df_saidas = pd.read_sql_query(text("SELECT material_id, quantidade, DATE(data AT TIME ZONE 'America/Sao_Paulo') AS data_dia FROM movimentacoes WHERE tipo = 'SAÍDA' AND data >= :limite"), engine, params={"limite": data_limite})
        if not df_saidas.empty:
            df_saidas['data_dia'] = pd.to_datetime(df_saidas['data_dia'])
            hoje_dt = pd.to_datetime(hoje)
            df_saidas['dias_atras'] = (hoje_dt - df_saidas['data_dia']).dt.days
            df_saidas['peso'] = (8 - df_saidas['dias_atras']).clip(lower=1, upper=7)
            df_saidas['qtd_ponderada'] = df_saidas['quantidade'] * df_saidas['peso']
            consumo_diario = df_saidas.groupby('material_id')['qtd_ponderada'].sum() / 28.0
        else:
            consumo_diario = pd.Series(dtype='float64')
    except:
        consumo_diario = pd.Series(dtype='float64')
        
    df_estoque['Autonomia Estimada'] = [f"⏳ {qtd/consumo_diario.get(m_id, 0):.1f} dias" if consumo_diario.get(m_id, 0) > 0 else "♾️ Estável" for m_id, qtd in zip(df_estoque['id'], df_estoque['quantidade'])]
    return df_estoque

def registrar_movimento(material_id, tipo, qtd, responsavel):
    engine = obter_engine()
    fuso_br = pytz.timezone('America/Sao_Paulo')
    # 🔥 Força a captura exata do horário local atual e converte em texto puro para o banco não distorcer
    data_br_texto = datetime.now(fuso_br).strftime('%Y-%m-%d %H:%M:%S')
    try:
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO movimentacoes (material_id, tipo, quantidade, responsavel, data) VALUES (:m_id, :tipo, :qtd, :resp, :data)"),
                {"m_id": int(material_id), "tipo": tipo, "qtd": float(qtd), "resp": responsavel, "data": data_br_texto}
            )
            delta = float(qtd) if tipo == "ENTRADA" else -float(qtd)
            conn.execute(text("UPDATE materiais SET quantidade = quantidade + :delta WHERE id = :id"), {"delta": delta, "id": int(material_id)})
            conn.commit()
        st.success(f"Registrado com sucesso!")
        if tipo == "SAÍDA":
            df_atual = listar_materials()
            mat_info = df_atual[df_atual['id'] == int(material_id)].iloc[0]
            if float(mat_info['quantidade']) < float(mat_info['estoque_minimo']):
                enviar_email_alerta(mat_info['nome'], float(mat_info['quantidade']), float(mat_info['estoque_minimo']), mat_info['unidade'])
                st.warning(f"⚠️ Alerta enviado para o e-mail!")
    except Exception as e:
        st.error(f"Erro: {e}")

# --- TELAS ---
if menu == "Estoque":
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

    output_estoque_atual = io.BytesIO()
    with pd.ExcelWriter(output_estoque_atual, engine='xlsxwriter') as writer:
        df_vis.to_excel(writer, index=False, sheet_name='Estoque_Atual')
    st.download_button(label="🟢 Baixar Estoque Atual em Excel (.xlsx)", data=output_estoque_atual.getvalue(), file_name="Estoque_Atual_Vez_Mais.xlsx", mime="application/vnd.ms-excel")
    
    st.markdown("---")

    st.subheader("📜 Últimas 10 Movimentações Gerais")
    engine = obter_engine()
    df_mov = pd.read_sql_query(text("SELECT m.tipo AS \"Operação\", mat.nome AS \"Material\", m.quantidade AS \"Qtd\", mat.unidade AS \"Unidade\", to_char(m.data AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY HH24:MI:SS') AS \"Data/Hora\", m.responsavel AS \"Responsável\" FROM movimentacoes m JOIN materiais mat ON m.material_id = mat.id ORDER BY m.data DESC LIMIT 10"), engine)
    
    if df_mov.empty: 
        st.text("Nenhuma movimentação realizada.")
    else: 
        st.dataframe(df_mov.style.apply(lambda r: [
            'background-color: #d4edda; color: #155724; font-weight: bold;' if i == 0 and r['Operação'] == 'ENTRADA'
            else 'background-color: #f8d7da; color: #721c24; font-weight: bold;' if i == 0 and r['Operação'] == 'SAÍDA'
            else '' for i, _ in enumerate(r)
        ], axis=1), use_container_width=True)

elif menu == "Movimentar":
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
            if tipo == "SAÍDA" and qtd > saldo: st.error("Saldo insuficiente!")
            else: registrar_movimento(id_m, tipo, qtd, resp)

elif menu == "Histórico" and st.session_state["perfil"] == "Admin":
    st.header("📅 Histórico Completo e Relatórios")
    fuso = pytz.timezone('America/Sao_Paulo')
    
    col_d1, col_d2 = st.columns(2)
    with col_d1: d1 = st.date_input("Data Inicial", datetime.now(fuso) - timedelta(days=7))
    with col_d2: d2 = st.date_input("Data Final", datetime.now(fuso))
    
    d1_str, d2_str = f"{d1} 00:00:00-03:00", f"{d2} 23:59:59-03:00"
    engine = obter_engine()
    
    df_hist = pd.read_sql_query(text("SELECT m.tipo AS \"Operação\", mat.nome AS \"Material\", m.quantidade AS \"Qtd\", mat.unidade AS \"Unidade\", to_char(m.data AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY HH24:MI:SS') AS \"Data/Hora\", m.responsavel AS \"Responsável\" FROM movimentacoes m JOIN materiais mat ON m.material_id = mat.id WHERE m.data >= :data_inicio AND m.data <= :data_fim ORDER BY m.data DESC"), engine, params={"data_inicio": d1_str, "data_fim": d2_str})
    
    if df_hist.empty: 
        st.warning("Nenhuma movimentação encontrada para o período selecionado.")
    else:
        st.markdown("### 🔍 Aplicar Filtros ao Relatório")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filtro_op = st.selectbox("Tipo de Operação", ["TODAS", "ENTRADA", "SAÍDA"])
        with col_f2:
            df_todos_insumos = listar_materials()
            lista_materiais = ["TODOS"] + sorted(df_todos_insumos["nome"].unique().tolist())
            filtro_mat = st.selectbox("Insumo Específico", lista_materiais)
        
        if filtro_op != "TODAS":
            df_hist = df_hist[df_hist["Operação"] == filtro_op]
        if filtro_mat != "TODOS":
            df_hist = df_hist[df_hist["Material"] == filtro_mat]
            
        if df_hist.empty:
            st.info("Nenhum registro corresponde aos filtros selecionados acima.")
        else:
            st.subheader(f"📋 Registros encontrados no período: {len(df_hist)}")
            
            st.dataframe(df_hist.style.apply(lambda r: [
                'background-color: #d4edda; color: #155724; font-weight: bold;' if i == 0 and r['Operação'] == 'ENTRADA'
                else 'background-color: #f8d7da; color: #721c24; font-weight: bold;' if i == 0 and r['Operação'] == 'SAÍDA'
                else '' for i, _ in enumerate(r)
            ], axis=1), use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_hist.to_excel(writer, index=False, sheet_name='Histórico')
            
            st.markdown("---")
            st.download_button(label="🟢 Baixar Relatório Filtrado em Excel (.xlsx)", data=output.getvalue(), file_name="Relatorio_Estoque_Filtrado.xlsx", mime="application/vnd.ms-excel")

elif menu == "Insumos" and st.session_state["perfil"] == "Admin":
    st.header("📝 Gerenciamento Completo de Insumos")
    tab_cad, tab_edit, tab_del = st.tabs(["➕ Cadastrar Novo", "✏️ Editar Mínimo", "🗑️ Excluir Material"])
    with tab_cad:
        with st.form("f_cad"):
            n = st.text_input("Nome").upper()
            u = st.selectbox("Unidade", ["Saco", "m³", "Kg", "Unidade", "Barra"])
            m = st.number_input("Estoque Mínimo", value=10.0)
            if st.form_submit_button("Salvar") and n:
                engine = obter_engine()
                try:
                    with engine.connect() as conn:
                        conn.execute(text("INSERT INTO materiais (nome, unidade, quantidade, estoque_minimo) VALUES (:n, :u, 0, :m)"), {"n": n, "u": u, "m": m})
                        conn.commit()
                    st.success("Cadastrado com sucesso!")
                except: st.error("Erro. O material já existe?")
    with tab_edit:
        df_mat = listar_materials()
        if not df_mat.empty:
            mat_sel = st.selectbox("Selecione o Material", df_mat['nome'].tolist())
            min_atual = df_mat[df_mat['nome'] == mat_sel]['estoque_minimo'].values[0]
            novo_min = st.number_input(f"Novo limite (Atual: {min_atual})", min_value=0.0, step=1.0, value=float(min_atual))
            if st.button("Atualizar Limite"):
                engine = obter_engine()
                with engine.connect() as conn:
                    conn.execute(text("UPDATE materiais SET estoque_minimo = :m WHERE nome = :n"), {"m": novo_min, "n": mat_sel})
                    conn.commit()
                st.success("Atualizado!")
    with tab_del:
        df_mat = listar_materials()
        if not df_mat.empty:
            with st.form("f_del"):
                mat_del = st.selectbox("Material para DELETAR", df_mat['nome'].tolist())
                confirmar = st.checkbox("Desejo apagar este material e todo o seu histórico.")
                if st.form_submit_button("🚨 Excluir Permanentemente") and confirmar:
                    engine = obter_engine()
                    id_mat = int(df_mat[df_mat['nome'] == mat_del]['id'].values[0])
                    with engine.connect() as conn:
                        conn.execute(text("DELETE FROM movimentacoes WHERE material_id = :id"), {"id": id_mat})
                        conn.execute(text("DELETE FROM materiais WHERE id = :id"), {"id": id_mat})
                        conn.commit()
                    st.success("Apagado do banco!")

elif menu == "Alertas" and st.session_state["perfil"] == "Admin":
    st.header("⚠️ Itens Críticos")
    df = listar_materials()
    crit = df[df['quantidade'] < df['estoque_minimo']]
    if crit.empty: st.success("Tudo OK!")
    else: st.dataframe(crit, use_container_width=True)
