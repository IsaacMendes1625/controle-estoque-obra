import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
from banco import conectar, criar_tabelas
from sqlalchemy.sql import text

# Configuração visual da página do Streamlit
st.set_page_config(page_title="Controle de Estoque - Obra", layout="wide")
st.title("🏗️ Sistema de Inventário e Estoque de Obra")

# Menu Lateral para Navegação
menu = st.sidebar.selectbox("Menu", [
    "Visualizar Estoque", 
    "Materiais em Alerta",
    "Cadastrar Novo Material", 
    "Registrar Movimentação",
    "Histórico Avançado e Relatórios"
])

# --- FUNÇÕES INTERNAS DO SISTEMA ---
def listar_materials():
    engine = conectar()
    df = pd.read_sql_query(text("SELECT id, nome, unidade, quantidade, estoque_minimo FROM materiais ORDER BY nome"), engine)
    return df

def calcular_autonomia(df_estoque):
    """Calcula o consumo médio diário dos últimos 7 dias e estima a autonomia em dias"""
    engine = conectar()
    data_limite = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    try:
        df_saidas = pd.read_sql_query(text(f"""
            SELECT material_id, quantidade 
            FROM movimentacoes 
            WHERE tipo = 'SAÍDA' AND data >= '{data_limite}'
        """), engine)
        
        if not df_saidas.empty:
            consumo_total = df_saidas.groupby('material_id')['quantidade'].sum()
            consumo_diario = consumo_total / 7.0
        else:
            consumo_diario = pd.Series(dtype='float64')
    except:
        consumo_diario = pd.Series(dtype='float64')
        
    autonomias = []
    for _, row in df_estoque.iterrows():
        m_id = row['id']
        qtd_atual = row['quantidade']
        
        media_dia = consumo_diario.get(m_id, 0.0)
        
        if media_dia > 0:
            dias_restantes = qtd_atual / media_dia
            autonomias.append(f"⏳ {dias_restantes:.1f} dias")
        else:
            autonomias.append("♾️ Estável (Sem consumo)")
            
    df_estoque['Autonomia Estimada'] = autonomias
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
    try:
        with engine.connect() as conn:
            # 1. Salva a linha no histórico de movimentações
            conn.execute(
                text("INSERT INTO movimentacoes (material_id, tipo, quantidade, responsavel) VALUES (:material_id, :tipo, :qtd, :responsavel)"),
                {"material_id": int(material_id), "tipo": tipo, "qtd": float(qtd), "responsavel": responsavel}
            )
            # 2. Atualiza o saldo geral na tabela principal de materiais
            if tipo == "ENTRADA":
                conn.execute(text("UPDATE materiais SET quantidade = quantidade + :qtd WHERE id = :id"), {"qtd": float(qtd), "id": int(material_id)})
            elif tipo == "SAÍDA":
                conn.execute(text("UPDATE materiais SET quantidade = quantidade - :qtd WHERE id = :id"), {"qtd": float(qtd), "id": int(material_id)})
            conn.commit()
        st.success(f"Movimentação de {tipo} realizada com sucesso!")
    except Exception as e:
        st.error(f"Erro ao registrar movimentação: {e}")

# --- TELAS DA INTERFACE ---

# 1. TELA: VISUALIZAR ESTOQUE
if menu == "Visualizar Estoque":
    st.header("📊 Painel Geral de Materiais com Autonomia")
    
    try:
        df_estoque = listar_materials()
        
        if df_estoque.empty:
            st.info("Nenhum material cadastrado ainda.")
        else:
            df_estoque = calcular_autonomia(df_estoque)
            
            # --- CÁLCULO DOS INDICADORES ---
            total_cadastrados = len(df_estoque)
            total_itens_estoque = float(df_estoque['quantidade'].sum())
            total_alertas = len(df_estoque[df_estoque['quantidade'] < df_estoque['estoque_minimo']])
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(label="📋 Tipos de Materiais Cadastrados", value=f"{total_cadastrados} itens")
            with col2:
                st.metric(label="📦 Volume Total em Estoque (Geral)", value=f"{total_itens_estoque:,.1f}")
            with col3:
                if total_alertas > 0:
                    st.metric(label="⚠️ Alertas Críticos Ativos", value=f"{total_alertas} pendentes", delta="- Repor Urgente", delta_color="inverse")
                else:
                    st.metric(label="⚠️ Alertas Críticos Ativos", value="0", delta="Estoque OK", delta_color="normal")
            
            st.markdown("---")
            
            # --- TABELA PRINCIPAL FORMATADA ---
            st.subheader("Saldo Atual e Previsão de Esgotamento")
            
            # Mudamos o nome dos títulos direto nas colunas originais para não dar conflito na estilização de cor
            df_visualizar = df_estoque[['id', 'nome', 'unidade', 'quantidade', 'estoque_minimo', 'Autonomia Estimada']].copy()
            df_visualizar.columns = ['ID', 'Material', 'Unidade', 'quantidade', 'estoque_minimo', 'Autonomia Estimada (Últimos 7 dias)']
            
            def destacar_critico(row):
                return ['background-color: #ffcccc' if row['quantidade'] < row['estoque_minimo'] else '' for _ in row]
            
            # Exibe a tabela estilizada e depois dá um tapa visual nas colunas finais
            df_final = df_visualizar.style.apply(destacar_critico, axis=1)
            st.dataframe(df_final, use_container_width=True)
            
            # --- HISTÓRICO ---
            st.subheader("📜 Últimas 10 Movimentações Gerais")
            engine = conectar()
            df_mov = pd.read_sql_query(text("""
                SELECT m.tipo AS "Operação", mat.nome AS "Material", m.quantidade AS "Qtd", 
                       mat.unidade AS "Unidade", m.data AS "Data/Hora", m.responsavel AS "Responsável"
                FROM movimentacoes m
                JOIN materiais mat ON m.material_id = mat.id
                ORDER BY m.data DESC LIMIT 10
            """), engine)
            
            if df_mov.empty:
                st.text("Nenhuma movimentação realizada.")
            else:
                st.dataframe(df_mov, use_container_width=True)
    except Exception as e:
        st.error(f"Erro ao carregar o painel de estoque: {e}")

# 2. TELA: MATERIAIS EM ALERTA
elif menu == "Materiais em Alerta":
    st.header("⚠️ Insumos com Estoque Crítico (Abaixo do Mínimo)")
    
    try:
        df_estoque = listar_materials()
        
        if df_estoque.empty:
            st.info("Nenhum material cadastrado ainda.")
        else:
            df_critico = df_estoque[df_estoque['quantidade'] < df_estoque['estoque_minimo']]
            
            if df_critico.empty:
                st.success("🎉 Excelente! Nenhum material está com estoque crítico no momento.")
            else:
                st.warning(f"Atenção: Existem {len(df_critico)} itens que precisam de reposição urgente!")
                
                df_critico = calcular_autonomia(df_critico)
                df_critico_vis = df_critico[['nome', 'unidade', 'quantidade', 'estoque_minimo', 'Autonomia Estimada']].copy()
                df_critico_vis.columns = ['Material', 'Unidade', 'Qtd Atual', 'Estoque Mínimo', 'Tempo Restante']
                
                def estilo_alerta(row):
                    return ['background-color: #ffcccc' for _ in row]
                
                st.dataframe(df_critico_vis.style.apply(estilo_alerta, axis=1), use_container_width=True)
    except Exception as e:
        st.error(f"Erro ao carregar itens em alerta: {e}")

# 3. TELA: CADASTRAR MATERIAL
elif menu == "Cadastrar Novo Material":
    st.header("📝 Cadastrar Insumo na Obra")
    try:
        criar_tabelas()
    except:
        pass

    with st.form("form_cadastro"):
        nome = st.text_input("Nome do Material (Ex: CIMENTO CP-II, TIJOLO 8 FUROS)")
        unidade = st.selectbox("Unidade de Medida", ["Saco", "Milheiro", "m³", "Kg", "Unidade", "Barra", "Metro"])
        estoque_minimo = st.number_input("Estoque Mínimo de Alerta", min_value=0.0, value=10.0, step=1.0)
        
        botao_cadastrar = st.form_submit_button("Salvar Material")
        if botao_cadastrar and nome:
            cadastrar_material(nome, unidade, estoque_minimo)

# 4. TELA: REGISTRAR MOVIMENTAÇÃO
elif menu == "Registrar Movimentação":
    st.header("🔄 Entrada ou Saída de Material")
    
    try:
        df_mat = listar_materials()
        
        if df_mat.empty:
            st.warning("Cadastre os materiais antes de realizar movimentações.")
        else:
            lista_materiais = {f"{row['nome']} ({row['unidade']})": row['id'] for _, row in df_mat.iterrows()}
            
            with st.form("form_movimentacao"):
                material_selecionado = st.selectbox("Selecione o Material", list(lista_materiais.keys()))
                tipo_mov = st.radio("Tipo de Operação", ["ENTRADA", "SAÍDA"])
                quantidade = st.number_input("Quantidade", min_value=0.1, step=1.0)
                responsavel = st.text_input("Nome do Responsável pelo Recebimento/Retirada")
                
                botao_movimento = st.form_submit_button("Confirmar Movimentação")
                
                if botao_movimento:
                    id_material = lista_materiais[material_selecionado]
                    qtd_atual = df_mat[df_mat['id'] == id_material]['quantidade'].values[0]
                    
                    if tipo_mov == "SAÍDA" and quantidade > qtd_atual:
                        st.error(f"Erro: Saldo insuficiente no almoxarifado! Estoque atual é de apenas {qtd_atual}.")
                    else:
                        registrar_movimento(id_material, tipo_mov, quantidade, responsavel)
    except Exception as e:
        st.warning("Cadastre os materiais antes de realizar movimentações.")

# 5. TELA: HISTÓRICO AVANÇADO E FILTROS
elif menu == "Histórico Avançado e Relatórios":
    st.header("📅 Histórico e Filtro de Fluxo de Materiais")
    
    st.subheader("🔍 Filtros de Pesquisa")
    col_data1, col_data2, col_mat, col_tipo = st.columns(4)
    
    with col_data1:
        data_inicio = st.date_input("Data Inicial", datetime.today() - timedelta(days=7))
    with col_data2:
        data_fim = st.date_input("Data Final", datetime.today())
        
    try:
        engine = conectar()
        df_mat_lista = listar_materials()
        opcoes_materiais = ["TODOS"] + list(df_mat_lista['nome'].unique())
        
        with col_mat:
            material_filtro = st.selectbox("Filtrar por Material", opcoes_materiais)
        with col_tipo:
            tipo_filtro = st.selectbox("Filtrar por Operação", ["TODOS", "ENTRADA", "SAÍDA"])
            
        query_base = """
            SELECT m.tipo AS "Operação", 
                   mat.nome AS "Material", 
                   m.quantidade AS "Qtd", 
                   mat.unidade AS "Unidade", 
                   to_char(m.data, 'DD/MM/YYYY HH24:MI:SS') AS "Data/Hora", 
                   m.responsavel AS "Responsável",
                   m.data::date as data_filtro
            FROM movimentacoes m
            JOIN materiais mat ON m.material_id = mat.id
            WHERE m.data::date BETWEEN :data_ini AND :data_fim
        """
        
        parametros = {"data_ini": data_inicio.strftime('%Y-%m-%d'), "data_fim": data_fim.strftime('%Y-%m-%d')}
        
        if material_filtro != "TODOS":
            query_base += " AND mat.nome = :material"
            parametros["material"] = material_filtro
            
        if tipo_filtro != "TODOS":
            query_base += " AND m.tipo = :tipo"
            parametros["tipo"] = tipo_filtro
            
        query_base += " ORDER BY m.data DESC"
        
        df_filtrado = pd.read_sql_query(text(query_base), engine, params=parametros)
        
        st.markdown("---")
        
        if df_filtrado.empty:
            st.info("Nenhuma movimentação correspondente aos filtros foi encontrada.")
        else:
            st.subheader("📋 Registros Encontrados")
            df_exibir = df_filtrado.drop(columns=['data_filtro'])
            st.dataframe(df_exibir, use_container_width=True)
            
            st.subheader("📊 Consumo Consolidado do Período Selecionado")
            resumo = df_filtrado.groupby(['Material', 'Operação'])['Qtd'].sum().unstack(fill_value=0)
            st.table(resumo)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_exibir.to_excel(writer, sheet_name='Movimentacoes_Filtradas', index=False)
                resumo.to_excel(writer, sheet_name='Resumo_Consolidado')
            
            st.download_button(
                label="📥 Baixar Dados Filtrados em Excel (.xlsx)",
                data=output.getvalue(),
                file_name=f"Relatorio_Customizado_{data_inicio.strftime('%Y%m%d')}_a_{data_fim.strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
    except Exception as e:
        st.error(f"Erro ao processar relatórios: {e}")
