import streamlit as st
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import io
import contextlib
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="SysContábil SaaS", layout="wide")
DB_NAME = "syscontabil_v4.db"

# --- BANCO DE DADOS ---
def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@contextlib.contextmanager
def db_cursor():
    conn = get_db()
    try:
        yield conn.cursor()
        conn.commit()
    finally:
        conn.close()

def init_db():
    with db_cursor() as cursor:
        cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            username TEXT UNIQUE, 
            password TEXT,
            nome_completo TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            nome TEXT, cnpj TEXT, regime TEXT, usuario_id INTEGER,
            FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS plano_contas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            empresa_id INTEGER, cod TEXT, nome TEXT, grupo TEXT,
            FOREIGN KEY(empresa_id) REFERENCES empresas(id)
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS lancamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            empresa_id INTEGER, data TEXT, 
            conta_debito_id INTEGER, conta_credito_id INTEGER, 
            valor REAL, historico TEXT,
            FOREIGN KEY(empresa_id) REFERENCES empresas(id)
        )''')

init_db()

# --- FUNÇÃO DE EXPORTAÇÃO PDF ---
def exportar_pdf(titulo, empresa, df):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, 750, f"{titulo}")
    p.setFont("Helvetica", 10)
    p.drawString(50, 735, f"Empresa: {empresa['nome']} | CNPJ: {empresa['cnpj']}")
    p.line(50, 730, 550, 730)
    
    y = 710
    for _, row in df.iterrows():
        linha = f"{row.get('cod','')} - {row.get('nome','')} ({row.get('grupo','')})"
        p.drawString(50, y, linha[:100])
        y -= 20
        if y < 100:
            p.showPage()
            y = 750
            
    p.line(150, 80, 450, 80)
    p.drawCentredString(300, 65, "Assinatura do Responsável")
    p.save()
    buffer.seek(0)
    return buffer

# --- SISTEMA DE LOGIN ---
if 'auth' not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🛡️ SysContábil SaaS")
    t1, t2 = st.tabs(["Login", "Criar Conta"])
    
    with t1:
        u = st.text_input("Usuário")
        p = st.text_input("Senha", type="password")
        if st.button("Entrar"):
            with get_db() as db:
                user = db.execute('SELECT * FROM usuarios WHERE username = ?', (u,)).fetchone()
                if user and check_password_hash(user['password'], p):
                    st.session_state.auth, st.session_state.user_id = True, user['id']
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos.")
    
    with t2:
        nu = st.text_input("Escolha um Usuário")
        nome = st.text_input("Nome Completo")
        np = st.text_input("Escolha uma Senha", type="password")
        if st.button("Finalizar Registro"):
            with get_db() as db:
                try:
                    db.execute('INSERT INTO usuarios (username, password, nome_completo) VALUES (?,?,?)', 
                               (nu, generate_password_hash(np), nome))
                    db.commit()
                    st.success("Conta criada! Agora faça o login na aba ao lado.")
                except sqlite3.IntegrityError:
                    st.error("Este nome de usuário já está sendo usado. Tente outro.")

else:
    # --- INTERFACE PRINCIPAL ---
    db = get_db()
    st.sidebar.success(f"Logado como: {st.session_state.user_id}")
    
    empresas = db.execute('SELECT * FROM empresas WHERE usuario_id = ?', (st.session_state.user_id,)).fetchall()
    if not empresas:
        with st.form("nova_emp"):
            st.subheader("Cadastrar Empresa")
            n = st.text_input("Razão Social")
            c = st.text_input("CNPJ")
            r = st.selectbox("Regime", ["Simples Nacional", "MEI", "Lucro Presumido"])
            if st.form_submit_button("Salvar"):
                db.execute('INSERT INTO empresas (nome, cnpj, regime, usuario_id) VALUES (?,?,?,?)', 
                           (n, c, r, st.session_state.user_id))
                db.commit()
                st.rerun()
        st.stop()

    emp_id = st.sidebar.selectbox("Empresa", [e['id'] for e in empresas], 
                                  format_func=lambda x: next(e['nome'] for e in empresas if e['id'] == x))
    emp_atual = db.execute('SELECT * FROM empresas WHERE id = ?', (emp_id,)).fetchone()
    
    menu = st.sidebar.radio("Módulo", ["📊 Dashboard", "⚖️ Contabilidade", "🏛️ Fiscal", "📥 Importação CSV"])

    if menu == "⚖️ Contabilidade":
        st.header("Relatórios de Balanço e DRE")
        df_contas = pd.read_sql_query("SELECT cod, nome, grupo FROM plano_contas WHERE empresa_id=?", db, params=(emp_id,))
        st.dataframe(df_contas)
        st.download_button("📥 Baixar Relatório (PDF)", exportar_pdf("Relatório Contábil", emp_atual, df_contas), "relatorio.pdf")

    elif menu == "🏛️ Fiscal":
        st.header("Apuração Fiscal (Faturamento 12 Meses)")
        df_fat = pd.DataFrame({'Mês': ['09/25', '10/25', '11/25', '12/25', '01/26', '02/26'], 
                               'Valor': [1000, 1500, 1200, 1800, 2000, 1700]})
        fig = go.Figure([go.Bar(x=df_fat['Mês'], y=df_fat['Valor'])])
        st.plotly_chart(fig, use_container_width=True)
        st.download_button("📥 Baixar Declaração", exportar_pdf("Declaração de Faturamento", emp_atual, df_fat), "faturamento.pdf")

    elif menu == "📥 Importação CSV":
        st.header("Importar via Planilha")
        file = st.file_uploader("Selecione o CSV", type="csv")
        if file and st.button("Importar"):
            df = pd.read_csv(file)
            st.write("Dados detectados:", df.head())
            st.success("Dados prontos para processamento!")

    if st.sidebar.button("Logout"):
        st.session_state.auth = False
        st.rerun()
    db.close()