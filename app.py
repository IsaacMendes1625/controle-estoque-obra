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

# --- 🔐 CONFIGURAÇÃO DEFINITIVA DOS ALERTAS POR E-MAIL ---
EMAIL_REMETENTE = "isaacmendes2516@gmail.com"  
SENHA_REMETENTE = "dqzmmvpowdoznheb"  
EMAIL_DESTINATARIO = "isaacmendes2516@gmail.com"  

def enviar_email_alerta(nome_material, qtd_atual, qtd_minima, unidade):
    """Função que conecta no Gmail e dispara o alerta silenciosamente"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_REMETENTE
        msg['To'] = EMAIL_DESTINATARIO
        msg['Subject'] = f"⚠️ ALERTA DE ESTOQUE CRÍTICO: {nome_material}"
        
        corpo = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <h2 style="color: #cc0000;">⚠️ Insumo Abaixo do Estoque Mínimo!</h2>
            <p>O sistema de estoque da obra detectou uma retirada crítica:</p>
            <table style="border-collapse: collapse; width: 100%; max-width: 500px;">
                <tr style="background-color: #f2f2f2;"><td style="padding: 8px; border: 1px solid #ddd;"><b>Material:</b></td><td style="padding: 8px; border: 1px solid #ddd;">{nome_material}</td></tr>
                <tr><td style="padding: 8px; border: 1px solid #ddd;"><b>Saldo Atual:</b></td><td style="padding: 8px; border: 1px solid #ddd; color: red; font-weight: bold;">{qtd_atual} {unidade}</td></tr>
                <tr style="background-color: #f2f2f2;"><td style="padding: 8px; border: 1px solid #ddd;"><b>Estoque Mínimo Exigido:</b></td><td style="padding: 8px; border: 1px solid #ddd;">{qtd_minima} {unidade}</td></tr>
            </table>
            <p style="margin-top: 20px;"><i>💡 Recomendação: Entre em contato com o fornecedor para providenciar a reposição o quanto antes.</i></p>
            <br>
            <hr style="border: 0; border-top: 1px solid #eee;">
            <p style="font-size: 11px; color: #888;">E-mail automático enviado pelo Sistema de Estoque Vez Mais.</p>
        </body>
        </html>
        """
        msg.attach(MIMEText(corpo, 'html'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_REMETENTE, SENHA_REMETENTE)
        server.sendmail(EMAIL_REMETENTE, EMAIL_DESTINATARIO, msg.as_string())
        server.quit()
        print("-> E-mail de alerta enviado com sucesso!")
    except Exception as e:
        print(f"Erro ao enviar e-mail de alerta: {e}")

# --- SISTEMA DE LOGIN E CONTROLE DE ACESSO ---
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False
    st.session_state["perfil"] = None
    st.session_state["usuario_logado"] = ""

# Base de usuários do sistema
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
st.sidebar.markdown(f"👤 **Usuário:** {st.session_state['usuario_logado']} ({st.session_state['perfil']})")

if st.session_state["perfil"] == "Admin":
    opcoes_menu = ["Visualizar Estoque", "Materiais em Alerta", "Gerenciar Insumos", "Registrar Movimentação", "Histórico Avançado e Relatórios", "Gerenciar Usuários"]
else:
    opcoes_menu = ["Visualizar Estoque", "Registrar Movimentação"]

menu = st.sidebar.selectbox("Menu de Navegação", opcoes_menu)

if st.sidebar.button("🚪 Logout / Sair"):
    st.session_state["autenticado"] = False
    st.session_state["perfil"] = None
    st.rerun()

# --- FUNÇÕES INTERNAS DO BANCO ---
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
        
        if tipo == "SAÍDA":
            df_atual = listar_materials()
            mat_info = df_atual[df_atual['id'] == int(material_id)].iloc[0]
            saldo_pos_saida = float(mat_info['quantidade'])
            estoque_min = float(mat_info['estoque_minimo'])
            
            if saldo_pos_saida < estoque_min:
                enviar_email_alerta(mat_info['nome'], saldo_pos_saida, estoque_min, mat_info['unidade'])
                st.warning(f"⚠️ Alerta enviado para o e-mail! O estoque de {mat_info['nome']} está crítico.")
                
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

    st.subheader("📜 Últimas 10 Movimentações Gerais")
    engine = conectar()
    
    df_mov = pd.read_sql_query(text("""
        SELECT m.tipo AS "Operação", mat.nome AS "Material", m.quantidade AS "Qtd", mat.unidade AS "Unidade", 
               to_char(m.data AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY HH24:MI:SS') AS "Data/Hora", m.responsavel AS "Responsável"
        FROM movimentacoes m JOIN materiais mat ON m.material_id = mat.id ORDER BY m.data DESC LIMIT 10
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
    st.markdown("Abaixo estão os perfis ativos autorizados a acessar o sistema da obra:")
    
    dados_usuarios = []
    for k, v in USUARIOS.items():
        dados_usuarios.append({
            "Usuário Logável": k,
            "Chave/Senha de Acesso": v["senha"],
            "Nível de Permissão (Perfil)": "🛠️ Administrador (Acesso Total)" if v["perfil"] == "Admin" else "🚜 Campo (Apenas Lança Movimentações)"
        })
    df_users = pd.DataFrame(dados_usuarios)
    st.dataframe(df_users, use_container_width=True)

elif menu == "Histórico Avançado e Relatórios" and st.session_state["perfil"] == "Admin":
    st.header("📅 Histórico Completo e Relatórios de Auditoria")
    
    fuso = pytz.timezone('America/Sao_Paulo')
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        d1 = st.date_input("Data Inicial", datetime.now(fuso) - timedelta(days=7))
    with col_d2:
        d2 = st.date_input("Data Final", datetime.now(fuso))
    
    d1_str = f"{d1} 00:00:00-03:00"
    d2_str = f"{d2} 23:59:59-03:00"
    
    engine = conectar()
    
    df_hist = pd.read_sql_query(text("""
        SELECT m.tipo AS "Operação", 
               mat.nome AS "Material", 
               m.quantidade AS "Qtd", 
               mat.unidade AS "Unidade", 
               to_char(m.data AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY HH24:MI:SS') AS "Data/Hora", 
               m.responsavel AS "Responsável"
        FROM movimentacoes m 
        JOIN materiais mat ON m.material_id = mat.id
        WHERE m.data >= :data_inicio AND m.data <= :data_fim 
        ORDER BY m.data DESC
    """), engine, params={"data_inicio": d1_str, "data_fim": d2_str})
    
    if df_hist.empty:
        st.warning("Nenhuma movimentação encontrada para o período selecionado.")
    else:
        st.subheader(f"📋 Registros encontrados no período: {len(df_hist)}")
        st.dataframe(df_hist, use_container_width=True)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_hist.to_excel(writer, index=False, sheet_name='Histórico_Estoque')
        dados_excel = output.getvalue()
        
        st.markdown("---")
        st.subheader("📥 Exportar Dados para a Empresa")
        st.download_button(
            label="🟢 Baixar Relatório em Excel (.xlsx)",
            data=dados_excel,
            file_name=f"Relatorio_Estoque_{d1}_a_{d2}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# 🔥 TELA: GERENCIAR INSUMOS (ABAS MÚLTIPLAS E CORRIGIDAS)
elif menu == "Gerenciar Insumos" and st.session_state["perfil"] == "Admin":
    st.header("📝 Gerenciamento Completo de Insumos")
    
    tab_cad, tab_edit, tab_del = st.tabs(["➕ Cadastrar Novo", "✏️ Editar Mínimo", "🗑️ Excluir Material"])
    
    # Aba 1: Cadastrar
    with tab_cad:
        st.subheader("Cadastrar Novo Material")
        with st.form("f_cad"):
            n = st.text_input("Nome do Insumo").upper()
            u = st.selectbox("Unidade de Medida", ["Saco", "m³", "Kg", "Unidade", "Barra"])
            m = st.number_input("Avisar quando o estoque ficar abaixo de:", value=10.0)
            if st.form_submit_button("Salvar Cadastro") and n:
                engine = conectar()
                try:
                    with engine.connect() as conn:
                        conn.execute(text("INSERT INTO materiais (nome, unidade, quantidade, estoque_minimo) VALUES (:n, :u, 0, :m)"), {"n": n, "u": u, "m": m})
                        conn.commit()
                    st.success(f"Material {n} cadastrado com sucesso!")
                except Exception as e:
                    st.error("Erro ao cadastrar. O material já existe com esse nome?")
                    
    # Aba 2: Editar 
    with tab_edit:
        st.subheader("Alterar o Alerta de Estoque Mínimo")
        df_mat = listar_materials()
        if not df_mat.empty:
            mat_sel = st.selectbox("Selecione o Material", df_mat['nome'].tolist())
            min_atual = df_mat[df_mat['nome'] == mat_sel]['estoque_minimo'].values[0]
            novo_min = st.number_input(f"Novo limite mínimo (Atual: {min_atual})", min_value=0.0, step=1.0, value=float(min_atual))
            
            if st.button("Atualizar Limite"):
                engine = conectar()
                try:
                    with engine.connect() as conn:
                        conn.execute(text("UPDATE materiais SET estoque_minimo = :m WHERE nome = :n"), {"m": novo_min, "n": mat_sel})
                        conn.commit()
                    st.success(f"Feito! O estoque mínimo de {mat_sel} foi atualizado para {novo_min}.")
                except Exception as e:
                    st.error(f"Erro ao atualizar: {e}")
        else:
            st.info("Nenhum material cadastrado ainda.")

    # Aba 3: Excluir
    with tab_del:
        st.subheader("Remover Material do Sistema")
        df_mat = listar_materials()
        if not df_mat.empty:
            st.warning("⚠️ **ATENÇÃO:** Excluir um material apagará permanentemente todo o histórico de entradas e saídas dele no banco de dados!")
            with st.form("f_del"):
                mat_del = st.selectbox("Selecione o Material para DELETAR", df_mat['nome'].tolist())
                confirmar = st.checkbox("Estou ciente e desejo apagar este material e todo o seu histórico.")
                
                if st.form_submit_button("🚨 Excluir Permanentemente"):
                    if confirmar:
                        engine = conectar()
                        try:
                            id_mat = int(df_mat[df_mat['nome'] == mat_del]['id'].values[0])
                            with engine.connect() as conn:
                                conn.execute(text("DELETE FROM movimentacoes WHERE material_id = :id"), {"id": id_mat})
                                conn.execute(text("DELETE FROM materiais WHERE id = :id"), {"id": id_mat})
                                conn.commit()
                            st.success(f"O material {mat_del} e todo o seu histórico foram apagados com sucesso!")
                        except Exception as e:
                            st.error(f"Erro ao excluir: {e}")
                    else:
                        st.error("Você precisa marcar a caixa de confirmação para poder excluir.")
        else:
            st.info("Nenhum material cadastrado ainda.")

elif menu == "Materiais em Alerta" and st.session_state["perfil"] == "Admin":
    st.header("⚠️ Itens Críticos")
    df = listar_materials()
    crit = df[df['quantidade'] < df['estoque_minimo']]
    if crit.empty: 
        st.success("Tudo OK!")
    else: 
        st.dataframe(crit, use_container_width=True)
