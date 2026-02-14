import streamlit as st
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import io
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from ofxtools.Parser import OFXTree

# --- CONFIGURAÇÃO E BANCO DE DADOS ---
st.set_page_config(page_title="SysContábil Pro", layout="wide")
DB_NAME = "syscontabil_final.db"

def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS empresas (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, cnpj TEXT, regime TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS plano_contas (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, cod TEXT, nome TEXT, grupo TEXT, FOREIGN KEY(empresa_id) REFERENCES empresas(id))')
    cursor.execute('CREATE TABLE IF NOT EXISTS lancamentos (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, data TEXT, conta_debito_id INTEGER, conta_credito_id INTEGER, valor REAL, historico TEXT, FOREIGN KEY(empresa_id) REFERENCES empresas(id))')
    conn.commit()
    conn.close()

init_db()

# --- FUNÇÕES DE EXPORTAÇÃO PDF ---
def gerar_pdf_com_assinatura(titulo, empresa_info, dataframe):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()

    # Cabeçalho
    elements.append(Paragraph(f"<b>{titulo}</b>", styles['Title']))
    elements.append(Paragraph(f"Empresa: {empresa_info['nome']} | CNPJ: {empresa_info['cnpj']}", styles['Normal']))
    elements.append(Paragraph(f"Regime: {empresa_info['regime']}", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Tabela de Dados
    data = [dataframe.columns.to_list()] + dataframe.values.tolist()
    t = Table(data)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(t)
    elements.append(Spacer(1, 48))

    # Campo de Assinatura
    elements.append(Paragraph("<br/><br/>________________________________________________<br/>Assinatura do Responsável", styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer

# --- AUTENTICAÇÃO ---
if 'auth' not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acesso SysContábil")
    u = st.text_input("Usuário")
    p = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        db = get_db()
        user = db.execute('SELECT * FROM usuarios WHERE username = ?', (u,)).fetchone()
        if user and check_password_hash(user['password'], p):
            st.session_state.auth, st.session_state.user = True, u
            st.rerun()
        else: st.error("Falha na autenticação")
else:
    db = get_db()
    st.sidebar.title(f"👤 {st.session_state.user}")
    
    # Cadastro de Empresa
    empresas = db.execute('SELECT * FROM empresas').fetchall()
    if not empresas:
        with st.form("cad_emp"):
            st.subheader("Nova Empresa")
            n = st.text_input("Razão Social")
            c = st.text_input("CNPJ")
            r = st.selectbox("Regime", ["Simples Nacional", "MEI", "Lucro Presumido"])
            if st.form_submit_button("Cadastrar"):
                db.execute('INSERT INTO empresas (nome, cnpj, regime) VALUES (?,?,?)', (n, c, r))
                db.commit()
                st.rerun()
        st.stop()

    emp_id = st.sidebar.selectbox("Empresa Ativa", [e['id'] for e in empresas], format_func=lambda x: next(e['nome'] for e in empresas if e['id'] == x))
    emp_atual = db.execute('SELECT * FROM empresas WHERE id = ?', (emp_id,)).fetchone()

    menu = st.sidebar.radio("Módulos", ["📊 Dashboard", "⚖️ Contabilidade (BP/DRE)", "🏛️ Fiscal", "📥 Importação CSV", "📝 Lançamentos"])

    # --- MÓDULO CONTÁBIL ---
    if menu == "⚖️ Contabilidade (BP/DRE)":
        st.header("Demonstrações Contábeis")
        tab1, tab2 = st.tabs(["Balanço Patrimonial", "DRE"])
        
        with tab1:
            st.subheader("Balanço Patrimonial")
            df_bp = pd.read_sql_query(f"""
                SELECT p.cod, p.nome, p.grupo, 
                SUM(CASE WHEN l.conta_debito_id = p.id THEN l.valor ELSE 0 END) - 
                SUM(CASE WHEN l.conta_credito_id = p.id THEN l.valor ELSE 0 END) as Saldo
                FROM plano_contas p 
                LEFT JOIN lancamentos l ON (p.id = l.conta_debito_id OR p.id = l.conta_credito_id)
                WHERE p.empresa_id = {emp_id} AND p.grupo IN ('Ativo', 'Passivo')
                GROUP BY p.id
            """, db)
            st.dataframe(df_bp, use_container_width=True)
            st.download_button("📥 Baixar BP (PDF)", gerar_pdf_com_assinatura("Balanço Patrimonial", emp_atual, df_bp), "balanco.pdf")

        with tab2:
            st.subheader("DRE")
            df_dre = pd.read_sql_query(f"""
                SELECT p.nome as Conta, SUM(l.valor) as Valor
                FROM lancamentos l
                JOIN plano_contas p ON (l.conta_debito_id = p.id OR l.conta_credito_id = p.id)
                WHERE p.empresa_id = {emp_id} AND p.grupo IN ('Receita', 'Despesa')
                GROUP BY p.nome
            """, db)
            st.dataframe(df_dre, use_container_width=True)
            st.download_button("📥 Baixar DRE (PDF)", gerar_pdf_com_assinatura("DRE", emp_atual, df_dre), "dre.pdf")

    # --- MÓDULO FISCAL ---
    elif menu == "🏛️ Fiscal":
        st.header("Apuração Fiscal e Faturamento")
        data_12m = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        df_fat = pd.read_sql_query(f"""
            SELECT strftime('%m/%Y', data) as Mes, SUM(valor) as Faturamento
            FROM lancamentos l
            JOIN plano_contas p ON l.conta_credito_id = p.id
            WHERE l.empresa_id = {emp_id} AND p.grupo = 'Receita' AND data >= '{data_12m}'
            GROUP BY Mes ORDER BY data DESC
        """, db)
        st.subheader("Faturamento (Últimos 12 meses)")
        st.line_chart(df_fat.set_index('Mes'))
        st.download_button("📥 Baixar Declaração Faturamento (PDF)", gerar_pdf_com_assinatura("Declaração de Faturamento", emp_atual, df_fat), "faturamento.pdf")

    # --- IMPORTAÇÃO CSV ---
    elif menu == "📥 Importação CSV":
        st.header("Importar Dados via CSV")
        tipo = st.selectbox("Tipo de Arquivo", ["Plano de Contas", "Lançamentos"])
        arq = st.file_uploader("Selecione o CSV", type="csv")
        if arq and st.button("Processar"):
            df = pd.read_csv(arq)
            if tipo == "Plano de Contas":
                for _, r in df.iterrows():
                    db.execute('INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?,?,?,?)', (emp_id, r['cod'], r['nome'], r['grupo']))
            else:
                for _, r in df.iterrows():
                    db.execute('INSERT INTO lancamentos (empresa_id, data, conta_debito_id, conta_credito_id, valor, historico) VALUES (?,?,?,?,?,?)',
                                 (emp_id, r['data'], r['debito_id'], r['credito_id'], r['valor'], r['historico']))
            db.commit()
            st.success("Importação concluída!")

    elif menu == "📝 Lançamentos":
        st.header("Novo Lançamento Manual")
        with st.form("manual"):
            d = st.date_input("Data")
            v = st.number_input("Valor", 0.0)
            contas = db.execute(f'SELECT * FROM plano_contas WHERE empresa_id = {emp_id}').fetchall()
            c_map = {c['id']: f"{c['cod']} - {c['nome']}" for c in contas}
            deb = st.selectbox("Débito", list(c_map.keys()), format_func=lambda x: c_map[x])
            cred = st.selectbox("Crédito", list(c_map.keys()), format_func=lambda x: c_map[x])
            h = st.text_input("Histórico")
            if st.form_submit_button("Salvar"):
                db.execute('INSERT INTO lancamentos (empresa_id, data, conta_debito_id, conta_credito_id, valor, historico) VALUES (?,?,?,?,?,?)', (emp_id, d.isoformat(), deb, cred, v, h))
                db.commit()
                st.success("Lançamento salvo!")

    if st.sidebar.button("Sair"):
        st.session_state.auth = False
        st.rerun()
    db.close()