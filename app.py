import streamlit as st
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import io
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from ofxtools.Parser import OFXTree

# --- CONFIGURAÇÃO E BANCO DE DADOS ---
st.set_page_config(page_title="SysContábil SaaS Profissional", layout="wide")
DB_NAME = "syscontabil_final.db"

def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    # Tabela de Usuários (Cadastro do Usuário)
    cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        username TEXT UNIQUE, 
        password TEXT,
        nome_completo TEXT,
        email TEXT
    )''')
    # Tabela de Empresas (Cadastro Detalhado)
    cursor.execute('''CREATE TABLE IF NOT EXISTS empresas (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        nome TEXT, 
        cnpj TEXT, 
        regime TEXT,
        usuario_id INTEGER,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
    )''')
    cursor.execute('CREATE TABLE IF NOT EXISTS plano_contas (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, cod TEXT, nome TEXT, grupo TEXT, FOREIGN KEY(empresa_id) REFERENCES empresas(id))')
    cursor.execute('CREATE TABLE IF NOT EXISTS lancamentos (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, data TEXT, conta_debito_id INTEGER, conta_credito_id INTEGER, valor REAL, historico TEXT, FOREIGN KEY(empresa_id) REFERENCES empresas(id))')
    conn.commit()
    conn.close()

init_db()

# --- UTILITÁRIOS DE EXPORTAÇÃO ---
def gerar_pdf_com_assinatura(titulo, empresa_info, df_dados):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, 750, f"{titulo}")
    p.setFont("Helvetica", 10)
    p.drawString(50, 735, f"Empresa: {empresa_info['nome']} | CNPJ: {empresa_info['cnpj']}")
    p.drawString(50, 720, f"Regime: {empresa_info['regime']} | Gerado em: {datetime.now().strftime('%d/%m/%Y')}")
    p.line(50, 715, 550, 715)
    
    y = 690
    for index, row in df_dados.iterrows():
        linha = " | ".join([str(val) for val in row.values])
        p.drawString(50, y, linha[:100])
        y -= 20
        if y < 150:
            p.showPage()
            y = 750
            
    # Bloco de Assinatura
    y = 100
    p.line(150, y, 450, y)
    p.drawCentredString(300, y-15, "Assinatura do Responsável")
    p.save()
    buffer.seek(0)
    return buffer

# --- MÓDULO DE ACESSO E CADASTRO ---
if 'auth' not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🛡️ SysContábil Pro: Gestão & Fiscal")
    tab_login, tab_cad = st.tabs(["Acessar Sistema", "Criar Nova Conta"])
    
    with tab_login:
        u_log = st.text_input("Usuário")
        p_log = st.text_input("Senha", type="password")
        if st.button("Entrar"):
            db = get_db()
            user = db.execute('SELECT * FROM usuarios WHERE username = ?', (u_log,)).fetchone()
            if user and check_password_hash(user['password'], p_log):
                st.session_state.auth = True
                st.session_state.user_id = user['id']
                st.session_state.user_nome = user['username']
                st.rerun()
            else: st.error("Credenciais inválidas.")
            
    with tab_cad:
        st.subheader("Cadastro de Novo Usuário")
        new_nome = st.text_input("Nome Completo")
        new_user = st.text_input("Nome de Usuário (Login)")
        new_mail = st.text_input("E-mail")
        new_pass = st.text_input("Senha de Acesso", type="password")
        if st.button("Finalizar Cadastro"):
            db = get_db()
            try:
                db.execute('INSERT INTO usuarios (username, password, nome_completo, email) VALUES (?,?,?,?)', 
                           (new_user, generate_password_hash(new_pass), new_nome, new_mail))
                db.commit()
                st.success("Conta criada com sucesso! Faça login para continuar.")
            except: st.error("Este nome de usuário já existe.")

else:
    # --- INTERFACE LOGADA ---
    db = get_db()
    st.sidebar.title(f"👤 {st.session_state.user_nome}")
    
    # Gerenciamento de Empresas do Usuário
    empresas = db.execute('SELECT * FROM empresas WHERE usuario_id = ?', (st.session_state.user_id,)).fetchall()
    if not empresas:
        st.warning("Você ainda não possui empresas cadastradas.")
        with st.form("cad_emp"):
            st.subheader("Cadastrar Primeira Empresa")
            e_nome = st.text_input("Razão Social")
            e_cnpj = st.text_input("CNPJ")
            e_reg = st.selectbox("Regime Tributário", ["Simples Nacional", "MEI", "Lucro Presumido", "Lucro Real"])
            if st.form_submit_button("Salvar Empresa"):
                db.execute('INSERT INTO empresas (nome, cnpj, regime, usuario_id) VALUES (?,?,?,?)', 
                           (e_nome, e_cnpj, e_reg, st.session_state.user_id))
                db.commit()
                st.rerun()
        st.stop()

    emp_id = st.sidebar.selectbox("Empresa Ativa", [e['id'] for e in empresas], format_func=lambda x: next(e['nome'] for e in empresas if e['id'] == x))
    emp_atual = db.execute('SELECT * FROM empresas WHERE id = ?', (emp_id,)).fetchone()
    
    menu = st.sidebar.radio("Módulos", ["📈 Dashboard", "⚖️ Contabilidade (BP/DRE)", "🏛️ Fiscal & Faturamento", "📥 Importação (CSV/OFX)", "📝 Lançamentos"])

    # --- CONTABILIDADE (BALANÇO E DRE) ---
    if menu == "⚖️ Contabilidade (BP/DRE)":
        st.header("Demonstrações Contábeis")
        t_bp, t_dre = st.tabs(["Balanço Patrimonial", "DRE"])
        
        with t_bp:
            df_bp = pd.read_sql_query(f"""
                SELECT p.cod as Código, p.nome as Conta, p.grupo as Grupo, 
                SUM(CASE WHEN l.conta_debito_id = p.id THEN l.valor ELSE -l.valor END) as Saldo
                FROM plano_contas p 
                LEFT JOIN lancamentos l ON (p.id = l.conta_debito_id OR p.id = l.conta_credito_id)
                WHERE p.empresa_id = {emp_id} AND p.grupo IN ('Ativo', 'Passivo')
                GROUP BY p.id
            """, db)
            st.table(df_bp)
            st.download_button("📥 Exportar BP (PDF)", gerar_pdf_com_assinatura("Balanço Patrimonial", emp_atual, df_bp), "balanco.pdf")

        with t_dre:
            df_dre = pd.read_sql_query(f"""
                SELECT p.nome as Conta, SUM(l.valor) as Valor
                FROM lancamentos l
                JOIN plano_contas p ON (l.conta_debito_id = p.id OR l.conta_credito_id = p.id)
                WHERE p.empresa_id = {emp_id} AND p.grupo IN ('Receita', 'Despesa')
                GROUP BY p.nome
            """, db)
            st.table(df_dre)
            st.download_button("📥 Exportar DRE (PDF)", gerar_pdf_com_assinatura("DRE", emp_atual, df_dre), "dre.pdf")

    # --- FISCAL (12 MESES) ---
    elif menu == "🏛️ Fiscal & Faturamento":
        st.header("Apuração Fiscal e Faturamento")
        data_12m = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        df_fat = pd.read_sql_query(f"""
            SELECT strftime('%m/%Y', data) as Mes, SUM(valor) as Total
            FROM lancamentos l
            JOIN plano_contas p ON l.conta_credito_id = p.id
            WHERE l.empresa_id = {emp_id} AND p.grupo = 'Receita' AND data >= '{data_12m}'
            GROUP BY Mes ORDER BY data DESC
        """, db)
        
        st.subheader("Faturamento Acumulado (Últimos 12 Meses)")
        st.bar_chart(df_fat.set_index('Mes'))
        st.download_button("📥 Baixar Declaração de Faturamento (PDF)", gerar_pdf_com_assinatura("Declaração de Faturamento", emp_atual, df_fat), "faturamento.pdf")

    # --- IMPORTAÇÃO ---
    elif menu == "📥 Importação (CSV/OFX)":
        st.header("Importação de Dados")
        tipo = st.selectbox("Tipo de Arquivo", ["Plano de Contas (CSV)", "Lançamentos (CSV)", "Extrato Bancário (OFX)"])
        file = st.file_uploader("Upload do arquivo", type=["csv", "ofx"])
        
        if file and st.button("Processar Importação"):
            if "CSV" in tipo:
                df = pd.read_csv(file)
                if "Plano" in tipo:
                    for _, r in df.iterrows():
                        db.execute('INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?,?,?,?)', (emp_id, r['cod'], r['nome'], r['grupo']))
                else:
                    for _, r in df.iterrows():
                        db.execute('INSERT INTO lancamentos (empresa_id, data, conta_debito_id, conta_credito_id, valor, historico) VALUES (?,?,?,?,?,?)',
                                     (emp_id, r['data'], r['debito_id'], r['credito_id'], r['valor'], r['historico']))
                db.commit()
                st.success("Importação concluída!")
            elif "OFX" in tipo:
                parser = OFXTree()
                parser.parse(io.BytesIO(file.read()))
                ofx = parser.convert()
                st.info("Arquivo OFX processado. Use a tela de Lançamentos para conciliar.")

    elif menu == "📝 Lançamentos":
        st.header("Lançamento Manual")
        with st.form("manual_lan"):
            col1, col2 = st.columns(2)
            d_l = col1.date_input("Data")
            v_l = col2.number_input("Valor", 0.0)
            contas = db.execute(f'SELECT * FROM plano_contas WHERE empresa_id = {emp_id}').fetchall()
            c_map = {c['id']: f"{c['cod']} - {c['nome']}" for c in contas}
            deb_l = st.selectbox("Débito", list(c_map.keys()), format_func=lambda x: c_map[x])
            cred_l = st.selectbox("Crédito", list(c_map.keys()), format_func=lambda x: c_map[x])
            h_l = st.text_input("Histórico")
            if st.form_submit_button("Confirmar Lançamento"):
                db.execute('INSERT INTO lancamentos (empresa_id, data, conta_debito_id, conta_credito_id, valor, historico) VALUES (?,?,?,?,?,?)',
                             (emp_id, d_l.isoformat(), deb_l, cred_l, v_l, h_l))
                db.commit()
                st.success("Lançamento efetuado!")

    if st.sidebar.button("🚪 Logout"):
        st.session_state.auth = False
        st.rerun()
    db.close()