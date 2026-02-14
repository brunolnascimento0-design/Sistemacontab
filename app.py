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
    # Usuários
    cursor.execute('CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)')
    # Empresas
    cursor.execute('CREATE TABLE IF NOT EXISTS empresas (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, cnpj TEXT, regime TEXT, ramo TEXT)')
    # Plano de Contas
    cursor.execute('CREATE TABLE IF NOT EXISTS plano_contas (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, cod TEXT, nome TEXT, grupo TEXT, FOREIGN KEY(empresa_id) REFERENCES empresas(id))')
    # Lançamentos
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
    p.drawString(100, 750, f"Relatório de Recuperação Tributária - {empresa_nome}")
    p.setFont("Helvetica", 12)
    y = 720
    for k, v in resumo.items():
        p.drawString(100, y, f"{k}: {v}")
        y -= 25
    p.save()
    buffer.seek(0)
    return buffer

# --- SISTEMA DE AUTENTICAÇÃO ---
if 'auth' not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 SysContábil SaaS")
    tab_login, tab_reg = st.tabs(["Acesso Restrito", "Novo Usuário"])
    
    with tab_login:
        user_input = st.text_input("Usuário")
        pass_input = st.text_input("Senha", type="password")
        if st.button("Entrar"):
            db = get_db()
            user = db.execute('SELECT * FROM usuarios WHERE username = ?', (user_input,)).fetchone()
            if user and check_password_hash(user['password'], pass_input):
                st.session_state.auth = True
                st.session_state.user = user_input
                st.rerun()
            else:
                st.error("Credenciais inválidas.")
    
    with tab_reg:
        new_u = st.text_input("Definir Usuário")
        new_p = st.text_input("Definir Senha", type="password")
        if st.button("Criar Conta"):
            db = get_db()
            try:
                db.execute('INSERT INTO usuarios (username, password) VALUES (?,?)', (new_u, generate_password_hash(new_p)))
                db.commit()
                st.success("Conta criada com sucesso!")
            except:
                st.error("Este nome de usuário já está em uso.")

else:
    # --- INTERFACE DO APLICATIVO ---
    db = get_db()
    st.sidebar.title(f"👤 {st.session_state.user}")
    
    # Gerenciamento de Empresas
    empresas = db.execute('SELECT * FROM empresas').fetchall()
    if not empresas:
        st.warning("Nenhuma empresa cadastrada.")
        with st.expander("Cadastrar sua primeira Empresa", expanded=True):
            n = st.text_input("Razão Social")
            r = st.selectbox("Regime Tributário", ["Lucro Presumido", "Lucro Real", "Simples Nacional", "MEI"])
            if st.button("Salvar Empresa"):
                db.execute('INSERT INTO empresas (nome, regime) VALUES (?,?)', (n, r))
                db.commit()
                st.rerun()
        st.stop()

    emp_id = st.sidebar.selectbox("Empresa Ativa", [e['id'] for e in empresas], format_func=lambda x: next(e['nome'] for e in empresas if e['id'] == x))
    emp_atual = db.execute('SELECT * FROM empresas WHERE id = ?', (emp_id,)).fetchone()
    
    menu = st.sidebar.radio("Navegação", ["📈 Dashboard", "🏦 Conciliação Bancária", "⚖️ Recuperação Fiscal", "🗂️ Plano de Contas", "📝 Lançamentos Manuais"])

    # Dados de Contas para Selectboxes
    contas_list = db.execute(f'SELECT * FROM plano_contas WHERE empresa_id = {emp_id}').fetchall()
    c_map = {c['id']: f"{c['cod']} - {c['nome']}" for c in contas_list}

    if menu == "📈 Dashboard":
        st.header(f"Dashboard Financeiro - {emp_atual['nome']}")
        rec = db.execute(f"SELECT SUM(valor) FROM lancamentos l JOIN plano_contas p ON l.conta_credito_id = p.id WHERE l.empresa_id={emp_id} AND p.grupo='Receita'").fetchone()[0] or 0
        desp = db.execute(f"SELECT SUM(valor) FROM lancamentos l JOIN plano_contas p ON l.conta_debito_id = p.id WHERE l.empresa_id={emp_id} AND p.grupo='Despesa'").fetchone()[0] or 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Receita Bruta", format_brl(rec))
        c2.metric("Despesas Totais", format_brl(desp))
        c3.metric("Resultado Líquido", format_brl(rec-desp), delta=rec-desp)

        fig = go.Figure(data=[go.Bar(x=['Receitas', 'Despesas'], y=[rec, desp], marker_color=['#2ecc71', '#e74c3c'])])
        fig.update_layout(title="Comparativo Mensal")
        st.plotly_chart(fig, use_container_width=True)

    elif menu == "🏦 Conciliação Bancária":
        st.header("Importação de Extratos (OFX)")
        st.info("Importe o arquivo do banco para classificar os lançamentos.")
        upload = st.file_uploader("Upload de arquivo .ofx", type=["ofx"])
        
        if upload:
            parser = OFXTree()
            parser.parse(io.BytesIO(upload.read()))
            ofx = parser.convert()
            for stmt in ofx.statements:
                for trn in stmt.transactions:
                    with st.expander(f"Transação: {trn.memo} | {format_brl(float(trn.trnamt))}"):
                        col1, col2 = st.columns(2)
                        deb_id = col1.selectbox("Conta Débito", list(c_map.keys()), format_func=lambda x: c_map[x], key=f"d{trn.fitid}")
                        cred_id = col2.selectbox("Conta Crédito", list(c_map.keys()), format_func=lambda x: c_map[x], key=f"c{trn.fitid}")
                        if st.button("Confirmar Lançamento", key=f"b{trn.fitid}"):
                            db.execute('INSERT INTO lancamentos (empresa_id, data, conta_debito_id, conta_credito_id, valor, historico) VALUES (?,?,?,?,?,?)',
                                         (emp_id, trn.dtposted.date().isoformat(), deb_id, cred_id, abs(float(trn.trnamt)), trn.memo))
                            db.commit()
                            st.success("Conciliado no Diário!")

    elif menu == "⚖️ Recuperação Fiscal":
        st.header("Cálculo de Teses Tributárias")
        receita_total = db.execute(f"SELECT SUM(valor) FROM lancamentos l JOIN plano_contas p ON l.conta_credito_id = p.id WHERE l.empresa_id={emp_id} AND p.grupo='Receita'").fetchone()[0] or 0
        
        col_1, col_2 = st.columns(2)
        aliq_icms = col_1.number_input("Alíquota ICMS Destacado (%)", 18.0) / 100
        aliq_st = col_2.number_input("Alíquota ICMS-ST Estimada (%)", 10.0) / 100

        # Cálculo de PIS/COFINS (0.65% e 3%)
        p_p, c_p = receita_total * 0.0065, receita_total * 0.03
        
        # Tese ICMS (Século)
        base_tese = receita_total - (receita_total * aliq_icms)
        p_t, c_t = base_tese * 0.0065, base_tese * 0.03
        
        # Tese ICMS-ST
        base_st = receita_total - (receita_total * aliq_st)
        p_st, c_st = base_st * 0.0065, base_st * 0.03

        st.divider()
        res_t1, res_t2, res_t3 = st.tabs(["Cálculo Atual", "Tese do Século (ICMS)", "Exclusão ICMS-ST"])
        
        with res_t1:
            st.write(f"**PIS/COFINS Total Pago:** {format_brl(p_p + c_p)}")
        with res_t2:
            econom_t = (p_p + c_p) - (p_t + c_t)
            st.success(f"**Crédito ICMS Recuperável:** {format_brl(econom_t)}")
            st.caption("Base de cálculo reduzida pelo valor do ICMS destacado.")
        with res_t3:
            econom_st = (p_p + c_p) - (p_st + c_st)
            st.warning(f"**Crédito ST Recuperável:** {format_brl(econom_st)}")
            st.caption("Exclusão da parcela do ICMS-ST da base de cálculo federal.")

        dados_pdf = {"Receita Bruta": format_brl(receita_total), "Crédito Tese ICMS": format_brl(econom_t), "Crédito ICMS-ST": format_brl(econom_st)}
        st.download_button("📥 Gerar Laudo de Recuperação (PDF)", gerar_pdf_fiscal(emp_atual['nome'], dados_pdf), "laudo_fiscal.pdf")

    elif menu == "🗂️ Plano de Contas":
        st.header("Configuração do Plano de Contas")
        with st.form("add_conta"):
            ca, cb, cc = st.columns(3)
            c_cod = ca.text_input("Código Estrutural (ex: 1.1.01)")
            c_nome = cb.text_input("Nome da Conta")
            c_grupo = cc.selectbox("Grupo", ["Ativo", "Passivo", "Receita", "Despesa"])
            if st.form_submit_button("Cadastrar Conta"):
                db.execute('INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?,?,?,?)', (emp_id, c_cod, c_nome, c_grupo))
                db.commit()
                st.rerun()
        
        contas_df = pd.read_sql_query(f"SELECT cod, nome, grupo FROM plano_contas WHERE empresa_id={emp_id} ORDER BY cod", db)
        st.table(contas_df)

    elif menu == "📝 Lançamentos Manuais":
        st.header("Lançamentos no Diário")
        with st.form("manual_lan"):
            d_data = st.date_input("Data do Fato")
            d_valor = st.number_input("Valor do Lançamento", 0.0)
            d_deb = st.selectbox("Conta Débito", list(c_map.keys()), format_func=lambda x: c_map[x])
            d_cred = st.selectbox("Conta Crédito", list(c_map.keys()), format_func=lambda x: c_map[x])
            d_hist = st.text_input("Histórico / Descrição")
            if st.form_submit_button("Efetuar Lançamento"):
                db.execute('INSERT INTO lancamentos (empresa_id, data, conta_debito_id, conta_credito_id, valor, historico) VALUES (?,?,?,?,?,?)',
                             (emp_id, d_data.isoformat(), d_deb, d_cred, d_valor, d_hist))
                db.commit()
                st.success("Lançamento arquivado!")

    if st.sidebar.button("🚪 Encerrar Sessão"):
        st.session_state.auth = False
        st.rerun()
    db.close()