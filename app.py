import streamlit as st
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import io
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from ofxtools.Parser import OFXTree

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="SysContábil Pro - SaaS Fiscal", layout="wide")
DB_NAME = "syscontabil_master.db"

# --- BANCO DE DADOS ---
def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS empresas (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, cnpj TEXT, regime TEXT, ramo TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS plano_contas (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, cod TEXT, nome TEXT, grupo TEXT, FOREIGN KEY(empresa_id) REFERENCES empresas(id))')
    cursor.execute('CREATE TABLE IF NOT EXISTS lancamentos (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, data TEXT, conta_debito_id INTEGER, conta_credito_id INTEGER, valor REAL, historico TEXT, FOREIGN KEY(empresa_id) REFERENCES empresas(id))')
    conn.commit()
    conn.close()

init_db()

# --- UTILITÁRIOS ---
def format_brl(val):
    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def gerar_pdf_fiscal(empresa_nome, resumo):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, 750, f"Laudo de Recuperação Tributária - {empresa_nome}")
    p.setFont("Helvetica", 12)
    y = 720
    for k, v in resumo.items():
        p.drawString(100, y, f"{k}: {v}")
        y -= 25
    p.save()
    buffer.seek(0)
    return buffer

# --- AUTENTICAÇÃO ---
if 'auth' not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("📊 SysContábil SaaS")
    tab_login, tab_reg = st.tabs(["Acesso", "Novo Usuário"])
    with tab_login:
        user_input = st.text_input("Usuário")
        pass_input = st.text_input("Senha", type="password")
        if st.button("Entrar"):
            db = get_db()
            user = db.execute('SELECT * FROM usuarios WHERE username = ?', (user_input,)).fetchone()
            if user and check_password_hash(user['password'], pass_input):
                st.session_state.auth, st.session_state.user = True, user_input
                st.rerun()
            else: st.error("Acesso negado.")
    with tab_reg:
        new_u, new_p = st.text_input("Definir Usuário"), st.text_input("Definir Senha", type="password")
        if st.button("Registrar"):
            db = get_db()
            try:
                db.execute('INSERT INTO usuarios (username, password) VALUES (?,?)', (new_u, generate_password_hash(new_p)))
                db.commit()
                st.success("Conta criada!")
            except: st.error("Erro no cadastro.")
else:
    # --- APP PRINCIPAL ---
    db = get_db()
    st.sidebar.title(f"👤 {st.session_state.user}")
    
    empresas = db.execute('SELECT * FROM empresas').fetchall()
    if not empresas:
        with st.expander("Cadastrar Empresa", expanded=True):
            n = st.text_input("Nome da Empresa")
            if st.button("Salvar"):
                db.execute('INSERT INTO empresas (nome) VALUES (?)', (n,))
                db.commit()
                st.rerun()
        st.stop()

    emp_id = st.sidebar.selectbox("Empresa Ativa", [e['id'] for e in empresas], format_func=lambda x: next(e['nome'] for e in empresas if e['id'] == x))
    emp_atual = db.execute('SELECT * FROM empresas WHERE id = ?', (emp_id,)).fetchone()
    menu = st.sidebar.radio("Navegação", ["Dashboard", "Conciliação OFX", "Recuperação Fiscal", "Plano de Contas", "Diário"])

    contas_db = db.execute(f'SELECT * FROM plano_contas WHERE empresa_id = {emp_id}').fetchall()
    c_map = {c['id']: f"{c['cod']} - {c['nome']}" for c in contas_db}

    if menu == "Dashboard":
        st.header(f"Gestão - {emp_atual['nome']}")
        rec = db.execute(f"SELECT SUM(valor) FROM lancamentos l JOIN plano_contas p ON l.conta_credito_id = p.id WHERE l.empresa_id={emp_id} AND p.grupo='Receita'").fetchone()[0] or 0
        desp = db.execute(f"SELECT SUM(valor) FROM lancamentos l JOIN plano_contas p ON l.conta_debito_id = p.id WHERE l.empresa_id={emp_id} AND p.grupo='Despesa'").fetchone()[0] or 0
        c1, c2, c3 = st.columns(3)
        c1.metric("Faturamento", format_brl(rec))
        c2.metric("Despesas", format_brl(desp))
        c3.metric("Lucro", format_brl(rec-desp), delta=rec-desp)
        st.plotly_chart(go.Figure(data=[go.Bar(x=['Receitas', 'Despesas'], y=[rec, desp], marker_color=['green', 'red'])]), use_container_width=True)

    elif menu == "Conciliação OFX":
        st.header("Conciliação Bancária")
        up = st.file_uploader("Subir OFX", type=["ofx"])
        if up:
            p = OFXTree()
            p.parse(io.BytesIO(up.read()))
            ofx = p.convert()
            for stmt in ofx.statements:
                for trn in stmt.transactions:
                    with st.expander(f"{trn.memo} | {format_brl(float(trn.trnamt))}"):
                        d_id = st.selectbox("Débito", list(c_map.keys()), format_func=lambda x: c_map[x], key=f"d{trn.fitid}")
                        c_id = st.selectbox("Crédito", list(c_map.keys()), format_func=lambda x: c_map[x], key=f"c{trn.fitid}")
                        if st.button("Confirmar", key=f"b{trn.fitid}"):
                            db.execute('INSERT INTO lancamentos (empresa_id, data, conta_debito_id, conta_credito_id, valor, historico) VALUES (?,?,?,?,?,?)', (emp_id, trn.dtposted.date().isoformat(), d_id, c_id, abs(float(trn.trnamt)), trn.memo))
                            db.commit()
                            st.success("Lançado!")

    elif menu == "Recuperação Fiscal":
        st.header("Teses Tributárias")
        receita = db.execute(f"SELECT SUM(valor) FROM lancamentos l JOIN plano_contas p ON l.conta_credito_id = p.id WHERE l.empresa_id={emp_id} AND p.grupo='Receita'").fetchone()[0] or 0
        aliq_icms = st.number_input("Alíquota ICMS (%)", 18.0) / 100
        pis_cofins_p = receita * 0.0365
        base_t = receita - (receita * aliq_icms)
        pis_cofins_t = base_t * 0.0365
        st.success(f"Crédito Estimado (Exclusão ICMS): {format_brl(pis_cofins_p - pis_cofins_t)}")
        pdf = gerar_pdf_fiscal(emp_atual['nome'], {"Crédito Tese ICMS": format_brl(pis_cofins_p - pis_cofins_t)})
        st.download_button("📥 Baixar PDF", pdf, "fiscal.pdf")

    elif menu == "Plano de Contas":
        st.header("Configurar Contas")
        with st.form("add_c"):
            c1, c2, c3 = st.columns(3)
            cod, nome = c1.text_input("Código"), c2.text_input("Nome")
            grupo = c3.selectbox("Grupo", ["Ativo", "Passivo", "Receita", "Despesa"])
            if st.form_submit_button("Salvar"):
                db.execute('INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?,?,?,?)', (emp_id, cod, nome, grupo))
                db.commit()
                st.rerun()
        st.table(pd.read_sql_query(f"SELECT cod, nome, grupo FROM plano_contas WHERE empresa_id={emp_id}", db))

    elif menu == "Diário":
        st.header("Lançamento Manual")
        with st.form("manual"):
            dt, vl = st.date_input("Data"), st.number_input("Valor", 0.0)
            db_id = st.selectbox("Débito", list(c_map.keys()), format_func=lambda x: c_map[x])
            cr_id = st.selectbox("Crédito", list(c_map.keys()), format_func=lambda x: c_map[x])
            hist = st.text_input("Histórico")
            if st.form_submit_button("Gravar"):
                db.execute('INSERT INTO lancamentos (empresa_id, data, conta_debito_id, conta_credito_id, valor, historico) VALUES (?,?,?,?,?,?)', (emp_id, dt.isoformat(), db_id, cr_id, vl, hist))
                db.commit()
                st.success("Gravado!")

    if st.sidebar.button("🚪 Sair"):
        st.session_state.auth = False
        st.rerun()
    db.close()
