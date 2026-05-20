from sqlalchemy import create_engine
from sqlalchemy.sql import text

# LINK OFICIAL ATUALIZADO DO SEU PROJETO
# ⚠️ IMPORTANTE: Apague o trecho [YOUR-PASSWORD] e digite a sua senha real do Supabase no lugar.
URL_BANCO = "postgresql://postgres.lhriqpdpzryvngogkhoe:SenhaObraA3@aws-1-sa-east-1.pooler.supabase.com:6543/postgres?sslmode=require"

def conectar():
    # Cria a engrenagem de conexão segura usando o link correto do Pooler
    return create_engine(URL_BANCO)

def criar_tabelas():
    engine = conectar()
    with engine.connect() as conn:
        # Criação da tabela de materiais
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS materiais (
            id SERIAL PRIMARY KEY,
            nome VARCHAR(255) NOT NULL UNIQUE,
            unidade VARCHAR(50) NOT NULL,
            quantidade REAL DEFAULT 0,
            estoque_minimo REAL DEFAULT 0
        );
        """))
        # Criação da tabela de histórico de movimentações
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id SERIAL PRIMARY KEY,
            material_id INTEGER REFERENCES materiais(id),
            tipo VARCHAR(20) NOT NULL,
            quantidade REAL NOT NULL,
            data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            responsavel VARCHAR(255)
        );
        """))
        conn.commit()