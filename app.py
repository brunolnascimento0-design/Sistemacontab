import streamlit as st
import sqlite3
import pandas as pd
import io
from werkzeug.security import generate_password_hash, check_password_hash

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="SysContábil SaaS", layout="wide", page_icon="⚖️")
DB_NAME = "syscontabil_v5.db"

# --- FUNÇÕES DE BANCO DE DADOS ---
def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, nome_completo TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS empresas (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, cnpj TEXT, regime TEXT, usuario_id INTEGER, FOREIGN KEY(usuario_id) REFERENCES usuarios(id))')
        cursor.execute('CREATE TABLE IF NOT EXISTS plano_contas (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, cod TEXT, nome TEXT, grupo TEXT, FOREIGN KEY(empresa_id) REFERENCES empresas(id))')
        cursor.execute('CREATE TABLE IF NOT EXISTS lancamentos (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, data TEXT, conta_debito TEXT, conta_credito TEXT, valor REAL, historico TEXT, FOREIGN KEY(empresa_id) REFERENCES empresas(id))')
        conn.commit()

def importar_plano_padrao(emp_id):
    plano = [
        ("1.01.01", "Caixa Geral", "Ativo"), ("1.01.02", "Bancos Movimento", "Ativo"),
        ("2.01.01", "Fornecedores", "Passivo"), ("2.01.02", "Obrigações Trabalhistas", "Passivo"),
        ("3.01.01", "Capital Social", "Patrimônio Líquido"), ("3.01.02", "Lucros/Prejuízos Acumulados", "Patrimônio Líquido"),
        ("4.01.01", "Receita de Serviços", "Receita"), ("5.01.01", "Despesas Administrativas", "Despesa")
    ]
    with get_db() as db:
        db.executemany("INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?, ?, ?, ?)", 
                       [(emp_id, c, n, g) for c, n, g in plano])
        db.commit()

init_db()

# --- SISTEMA DE AUTENTICAÇÃO ---
if 'auth' not in st.session_state:
    st.session_state.update({'auth': False, 'user_id': None})

if not st.session_state.auth:
    st.title("🛡️ SysContábil SaaS")
    t1, t2 = st.tabs(["Login", "Criar Conta"])
    with t1:
        u = st.text_input("Usuário")
        p = st.text_input("Senha", type="password")
        if st.button("Entrar", use_container_width=True):
            db = get_db()
            user = db.execute('SELECT * FROM usuarios WHERE username = ?', (u,)).fetchone()
            if user and check_password_hash(user['password'], p):
                st.session_state.auth, st.session_state.user_id = True, user['id']
                st.rerun()
            else: st.error("Acesso negado.")
    with t2:
        nu, nome, np = st.text_input("Novo Usuário"), st.text_input("Nome Completo"), st.text_input("Senha", type="password")
        if st.button("Criar Conta", use_container_width=True):
            try:
                db = get_db()
                db.execute('INSERT INTO usuarios (username, password, nome_completo) VALUES (?,?,?)', (nu, generate_password_hash(np), nome))
                db.commit(); st.success("Registrado! Faça login.")
            except: st.error("Usuário já existe.")
else:
    # --- ÁREA DO CLIENTE ---
    db = get_db()
    empresas = db.execute('SELECT * FROM empresas WHERE usuario_id = ?', (st.session_state.user_id,)).fetchall()
    
    if not empresas:
        with st.form("nova_emp"):
            st.subheader("Cadastrar Empresa")
            n, c = st.text_input("Razão Social"), st.text_input("CNPJ")
            if st.form_submit_button("Criar Empresa"):
                db.execute('INSERT INTO empresas (nome, cnpj, usuario_id) VALUES (?,?,?)', (n, c, st.session_state.user_id))
                db.commit(); st.rerun()
        st.stop()

    # Sidebar
    emp_id = st.sidebar.selectbox("Empresa Ativa", [e['id'] for e in empresas], format_func=lambda x: next(e['nome'] for e in empresas if e['id'] == x))
    menu = st.sidebar.radio("Módulo", ["📊 Dashboard", "⚖️ Contabilidade", "📄 Relatórios"])
    
    if menu == "⚖️ Contabilidade":
        t_plano, t_lanc = st.tabs(["Plano de Contas", "Lançamentos"])
        
        with t_plano:
            contas_count = db.execute("SELECT count(*) as total FROM plano_contas WHERE empresa_id=?", (emp_id,)).fetchone()
            if contas_count['total'] == 0:
                if st.button("⚡ Importar Plano de Contas Padrão"):
                    importar_plano_padrao(emp_id); st.rerun()
            
            with st.expander("Nova Conta Manual"):
                with st.form("add_c"):
                    c1, c2, c3 = st.columns(3); cod = c1.text_input("Cód"); nome_c = c2.text_input("Nome"); grp = c3.selectbox("Grupo", ["Ativo", "Passivo", "Patrimônio Líquido", "Receita", "Despesa"])
                    if st.form_submit_button("Salvar"):
                        db.execute("INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?,?,?,?)", (emp_id, cod, nome_c, grp))
                        db.commit(); st.rerun()
            
            df_c = pd.read_sql_query("SELECT cod as Código, nome as Nome, grupo as Grupo FROM plano_contas WHERE empresa_id=?", db, params=(emp_id,))
            st.dataframe(df_c, use_container_width=True)

        with t_lanc:
            contas = [f"{r['cod']} - {r['nome']}" for r in db.execute("SELECT cod, nome FROM plano_contas WHERE empresa_id=?", (emp_id,)).fetchall()]
            if not contas: st.warning("Cadastre o plano de contas primeiro.")
            else:
                with st.form("add_l"):
                    d, v, h = st.date_input("Data"), st.number_input("Valor R$", min_value=0.0), st.text_input("Histórico")
                    deb, crd = st.selectbox("Conta Débito", contas), st.selectbox("Conta Crédito", contas)
                    if st.form_submit_button("Registrar Lançamento"):
                        if deb != crd and v > 0:
                            db.execute("INSERT INTO lancamentos (empresa_id, data, conta_debito, conta_credito, valor, historico) VALUES (?,?,?,?,?,?)", (emp_id, str(d), deb, crd, v, h))
                            db.commit(); st.success("Lançado!"); st.rerun()
                        else: st.error("Verifique os dados.")

    elif menu == "📄 Relatórios":
        st.header("Relatórios Financeiros")
        lancamentos = pd.read_sql_query("SELECT conta_debito, conta_credito, valor FROM lancamentos WHERE empresa_id=?", db, params=(emp_id,))
        contas_plano = pd.read_sql_query("SELECT cod, nome, grupo FROM plano_contas WHERE empresa_id=?", db, params=(emp_id,))
        
        if not lancamentos.empty:
            saldos = []
            for _, c in contas_plano.iterrows():
                id_full = f"{c['cod']} - {c['nome']}"
                deb = lancamentos[lancamentos['conta_debito'] == id_full]['valor'].sum()
                crd = lancamentos[lancamentos['conta_credito'] == id_full]['valor'].sum()
                res = (deb - crd) if c['grupo'] in ['Ativo', 'Despesa'] else (crd - deb)
                saldos.append({'Código': c['cod'], 'Conta': c['nome'], 'Grupo': c['grupo'], 'Débitos': deb, 'Créditos': crd, 'Saldo': res})
            
            df_balancete = pd.DataFrame(saldos)
            st.subheader("Balancete de Verificação")
            st.dataframe(df_balancete, use_container_width=True)
            
            # --- EXPORTAÇÃO EXCEL ---
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_balancete.to_excel(writer, index=False, sheet_name='Balancete')
            
            st.download_button(
                label="📥 Exportar Balancete (Excel)",
                data=output.getvalue(),
                file_name=f"balancete_{emp_id}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info("Realize lançamentos para gerar relatórios.")

    if st.sidebar.button("Logout"):
        st.session_state.auth = False; st.rerun()
    db.close()