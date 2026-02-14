import streamlit as st
import sqlite3
import pandas as pd
import io
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# --- CONFIGURAÇÃO E BANCO DE DADOS ---
st.set_page_config(page_title="SysContábil SaaS", layout="wide", page_icon="🛡️")
DB_NAME = "syscontabil_v4.db"

def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
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
            id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, 
            cod TEXT, nome TEXT, grupo TEXT, 
            FOREIGN KEY(empresa_id) REFERENCES empresas(id))''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS lancamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, 
            data TEXT, conta_debito_id INTEGER, conta_credito_id INTEGER, 
            valor REAL, historico TEXT, 
            FOREIGN KEY(empresa_id) REFERENCES empresas(id))''')
        conn.commit()

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
        text_line = " | ".join([str(x) for x in row.values])
        p.drawString(50, y, text_line[:100])
        y -= 20
        if y < 100: 
            p.showPage()
            y = 750
            
    p.line(150, 80, 450, 80)
    p.drawCentredString(300, 65, "Assinatura do Responsável")
    p.save()
    buffer.seek(0)
    return buffer

# --- SISTEMA DE LOGIN E CADASTRO ---
if 'auth' not in st.session_state:
    st.session_state.auth = False
    st.session_state.user_id = None

if not st.session_state.auth:
    st.title("🛡️ SysContábil SaaS")
    t1, t2 = st.tabs(["Login", "Criar Conta"])
    
    with t1:
        u = st.text_input("Usuário", key="login_user")
        p = st.text_input("Senha", type="password", key="login_pass")
        if st.button("Entrar"):
            db = get_db()
            user = db.execute('SELECT * FROM usuarios WHERE username = ?', (u,)).fetchone()
            db.close()
            if user and check_password_hash(user['password'], p):
                st.session_state.auth = True
                st.session_state.user_id = user['id']
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")

    with t2:
        nu = st.text_input("Escolha um Usuário (E-mail ou ID)", key="reg_user").strip()
        nome = st.text_input("Nome Completo", key="reg_nome").strip()
        np = st.text_input("Escolha uma Senha", type="password", key="reg_pass")
        
        if st.button("Finalizar Registro"):
            if not nu or not np or not nome:
                st.warning("Por favor, preencha todos os campos.")
            elif len(np) < 6:
                st.error("A senha deve ter pelo menos 6 caracteres.")
            else:
                db = get_db()
                try:
                    db.execute('INSERT INTO usuarios (username, password, nome_completo) VALUES (?,?,?)', 
                               (nu, generate_password_hash(np), nome))
                    db.commit()
                    st.success("✅ Conta criada! Agora faça o login na aba ao lado.")
                except sqlite3.IntegrityError:
                    st.error("Este nome de usuário já está sendo usado.")
                finally:
                    db.close()

else:
    # --- INTERFACE PRINCIPAL ---
    db = get_db()
    
    # Sidebar - Informações do Usuário
    st.sidebar.title("Menu")
    st.sidebar.info(f"ID Usuário: {st.session_state.user_id}")
    
    # Gerenciamento de Empresas
    empresas = db.execute('SELECT * FROM empresas WHERE usuario_id = ?', (st.session_state.user_id,)).fetchall()
    
    if not empresas:
        st.warning("Nenhuma empresa cadastrada para este usuário.")
        with st.form("nova_emp"):
            st.subheader("Cadastrar Primeira Empresa")
            n = st.text_input("Razão Social")
            c = st.text_input("CNPJ")
            r = st.selectbox("Regime", ["Simples Nacional", "MEI", "Lucro Presumido"])
            if st.form_submit_button("Salvar Empresa"):
                if n and c:
                    db.execute('INSERT INTO empresas (nome, cnpj, regime, usuario_id) VALUES (?,?,?,?)', 
                               (n, c, r, st.session_state.user_id))
                    db.commit()
                    st.rerun()
                else:
                    st.error("Preencha Nome e CNPJ.")
        st.stop()

    # Seleção de Empresa
    emp_options = {e['id']: f"{e['nome']} ({e['cnpj']})" for e in empresas}
    emp_id = st.sidebar.selectbox("Empresa Ativa", options=list(emp_options.keys()), 
                                  format_func=lambda x: emp_options[x])
    
    emp_atual = db.execute('SELECT * FROM empresas WHERE id = ?', (emp_id,)).fetchone()
    
    menu = st.sidebar.radio("Módulo", ["📊 Dashboard", "⚖️ Contabilidade", "🏛️ Fiscal", "📥 Importação"])

    if menu == "⚖️ Contabilidade":
        st.header(f"Contabilidade: {emp_atual['nome']}")
        # Correção de Segurança: Passando parâmetros via tupla no Pandas
        df_contas = pd.read_sql_query("SELECT cod, nome, grupo FROM plano_contas WHERE empresa_id=?", 
                                      db, params=(emp_id,))
        
        if df_contas.empty:
            st.info("Plano de contas vazio. Importe dados ou cadastre contas.")
        else:
            st.dataframe(df_contas, use_container_width=True)
            st.download_button("📥 Baixar Relatório (PDF)", 
                               exportar_pdf("Relatório Contábil", emp_atual, df_contas), "relatorio.pdf")

    elif menu == "🏛️ Fiscal":
        st.header("Apuração Fiscal")
        df_fat = pd.DataFrame({
            'Mês': ['09/25', '10/25', '11/25', '12/25', '01/26', '02/26'], 
            'Valor': [1000, 1500, 1200, 1800, 2000, 1700]
        })
        st.bar_chart(df_fat.set_index('Mês'))
        st.download_button("📥 Baixar Declaração", 
                           exportar_pdf("Declaração de Faturamento", emp_atual, df_fat), "faturamento.pdf")

    elif menu == "📥 Importação":
        st.header("Importar via Planilha")
        file = st.file_uploader("Selecione o CSV", type="csv")
        if file:
            df = pd.read_csv(file)
            st.write("Prévia dos dados:", df.head())
            if st.button("Confirmar Importação"):
                # Aqui você implementaria o loop de salvamento no banco
                st.success("Dados prontos para processamento!")

    if st.sidebar.button("Sair / Logout"):
        st.session_state.auth = False
        st.session_state.user_id = None
        st.rerun()
        
    db.close()