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
    """Cria uma conexão com o banco de dados SQLite."""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Inicializa as tabelas se não existirem."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, nome_completo TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS empresas 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, cnpj TEXT, usuario_id INTEGER, 
            FOREIGN KEY(usuario_id) REFERENCES usuarios(id))''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS plano_contas 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, cod TEXT, nome TEXT, grupo TEXT, 
            FOREIGN KEY(empresa_id) REFERENCES empresas(id))''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS lancamentos 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, data TEXT, conta_debito TEXT, 
            conta_credito TEXT, valor REAL, historico TEXT, 
            FOREIGN KEY(empresa_id) REFERENCES empresas(id))''')
        conn.commit()

def importar_plano_padrao(emp_id):
    """Insere contas contábeis básicas para uma nova empresa."""
    plano = [
        ("1.01.01", "Caixa Geral", "Ativo"), ("1.01.02", "Bancos Movimento", "Ativo"),
        ("2.01.01", "Fornecedores", "Passivo"), ("2.01.02", "Obrigações Trabalhistas", "Passivo"),
        ("3.01.01", "Capital Social", "Patrimônio Líquido"), ("3.01.02", "Lucros/Prejuízos Acumulados", "Patrimônio Líquido"),
        ("4.01.01", "Receita de Serviços", "Receita"), ("5.01.01", "Despesas Administrativas", "Despesa")
    ]
    with get_db() as conn:
        conn.executemany("INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?, ?, ?, ?)", 
                       [(emp_id, c, n, g) for c, n, g in plano])
        conn.commit()

# Inicializa o banco ao rodar o app
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
            with get_db() as conn:
                user = conn.execute('SELECT * FROM usuarios WHERE username = ?', (u,)).fetchone()
                if user and check_password_hash(user['password'], p):
                    st.session_state.auth = True
                    st.session_state.user_id = user['id']
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos.")

    with t2:
        nu = st.text_input("Novo Usuário (E-mail)")
        nome = st.text_input("Nome Completo")
        np = st.text_input("Senha de Cadastro", type="password")
        if st.button("Criar Conta", use_container_width=True):
            if nu and np and nome:
                try:
                    with get_db() as conn:
                        conn.execute('INSERT INTO usuarios (username, password, nome_completo) VALUES (?,?,?)', 
                                   (nu, generate_password_hash(np), nome))
                        conn.commit()
                    st.success("Conta criada com sucesso! Vá para a aba Login.")
                except sqlite3.IntegrityError:
                    st.error("Este usuário já está cadastrado.")
            else:
                st.warning("Preencha todos os campos.")
else:
    # --- ÁREA LOGADA ---
    with get_db() as conn:
        empresas = conn.execute('SELECT * FROM empresas WHERE usuario_id = ?', (st.session_state.user_id,)).fetchall()
    
    # Se não tiver empresa cadastrada, força o cadastro
    if not empresas:
        st.subheader("Bem-vindo! Vamos cadastrar sua primeira empresa.")
        with st.form("nova_emp"):
            n = st.text_input("Razão Social")
            c = st.text_input("CNPJ")
            if st.form_submit_button("Cadastrar Empresa"):
                if n and c:
                    with get_db() as conn:
                        conn.execute('INSERT INTO empresas (nome, cnpj, usuario_id) VALUES (?,?,?)', 
                                   (n, c, st.session_state.user_id))
                        conn.commit()
                    st.rerun()
                else:
                    st.warning("Preencha os dados da empresa.")
        st.stop()

    # Sidebar: Seleção de Empresa e Logout
    emp_dict = {e['id']: e['nome'] for e in empresas}
    emp_id = st.sidebar.selectbox("Empresa Ativa", options=list(emp_dict.keys()), format_func=lambda x: emp_dict[x])
    
    menu = st.sidebar.radio("Módulo", ["📊 Dashboard", "⚖️ Contabilidade", "📄 Relatórios"])
    if st.sidebar.button("Sair / Logout"):
        st.session_state.auth = False
        st.rerun()

    # --- MÓDULO CONTABILIDADE ---
    if menu == "⚖️ Contabilidade":
        t_plano, t_lanc = st.tabs(["Plano de Contas", "Lançamentos"])
        
        with t_plano:
            with get_db() as conn:
                contas_count = conn.execute("SELECT count(*) as total FROM plano_contas WHERE empresa_id=?", (emp_id,)).fetchone()
            
            if contas_count['total'] == 0:
                st.info("Seu plano de contas está vazio.")
                if st.button("⚡ Importar Plano Padrão"):
                    importar_plano_padrao(emp_id)
                    st.rerun()
            
            with st.expander("➕ Adicionar Conta Manualmente"):
                with st.form("add_c"):
                    c1, c2, c3 = st.columns(3)
                    cod = c1.text_input("Código (Ex: 1.01)")
                    nome_c = c2.text_input("Nome da Conta")
                    grp = c3.selectbox("Grupo", ["Ativo", "Passivo", "Patrimônio Líquido", "Receita", "Despesa"])
                    if st.form_submit_button("Salvar Conta"):
                        with get_db() as conn:
                            conn.execute("INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?,?,?,?)", 
                                       (emp_id, cod, nome_c, grp))
                            conn.commit()
                        st.rerun()
            
            with get_db() as conn:
                df_c = pd.read_sql_query("SELECT cod as Código, nome as Nome, grupo as Grupo FROM plano_contas WHERE empresa_id=?", conn, params=(emp_id,))
            st.dataframe(df_c, use_container_width=True)

        with t_lanc:
            with get_db() as conn:
                contas_query = conn.execute("SELECT cod, nome FROM plano_contas WHERE empresa_id=?", (emp_id,)).fetchall()
            contas = [f"{r['cod']} - {r['nome']}" for r in contas_query]
            
            if not contas:
                st.warning("Configure o Plano de Contas antes de fazer lançamentos.")
            else:
                with st.form("add_l"):
                    col1, col2 = st.columns(2)
                    d = col1.date_input("Data do Fato")
                    v = col2.number_input("Valor (R$)", min_value=0.01, step=0.01)
                    deb = st.selectbox("Conta Débito (Onde entra o recurso)", contas)
                    crd = st.selectbox("Conta Crédito (De onde sai o recurso)", contas)
                    h = st.text_input("Histórico / Descrição")
                    if st.form_submit_button("Registrar Lançamento"):
                        if deb != crd:
                            with get_db() as conn:
                                conn.execute("INSERT INTO lancamentos (empresa_id, data, conta_debito, conta_credito, valor, historico) VALUES (?,?,?,?,?,?)", 
                                           (emp_id, str(d), deb, crd, v, h))
                                conn.commit()
                            st.success("Lançamento realizado!")
                            st.rerun()
                        else:
                            st.error("A conta de débito e crédito não podem ser iguais.")

    # --- MÓDULO RELATÓRIOS ---
    elif menu == "📄 Relatórios":
        st.header("Relatórios Financeiros")
        with get_db() as conn:
            lancamentos = pd.read_sql_query("SELECT conta_debito, conta_credito, valor FROM lancamentos WHERE empresa_id=?", conn, params=(emp_id,))
            contas_plano = pd.read_sql_query("SELECT cod, nome, grupo FROM plano_contas WHERE empresa_id=?", conn, params=(emp_id,))
        
        if not lancamentos.empty:
            saldos = []
            for _, c in contas_plano.iterrows():
                id_full = f"{c['cod']} - {c['nome']}"
                deb = lancamentos[lancamentos['conta_debito'] == id_full]['valor'].sum()
                crd = lancamentos[lancamentos['conta_credito'] == id_full]['valor'].sum()
                # Lógica Contábil: Ativo/Despesa aumenta no Débito. Passivo/Receita/PL no Crédito.
                res = (deb - crd) if c['grupo'] in ['Ativo', 'Despesa'] else (crd - deb)
                saldos.append({'Código': c['cod'], 'Conta': c['nome'], 'Grupo': c['grupo'], 'Débitos': deb, 'Créditos': crd, 'Saldo': res})
            
            df_balancete = pd.DataFrame(saldos)
            st.subheader("Balancete de Verificação")
            st.dataframe(df_balancete, use_container_width=True)
            
            # Exportação
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_balancete.to_excel(writer, index=False, sheet_name='Balancete')
            
            st.download_button(label="📥 Baixar Excel", data=output.getvalue(), file_name=f"balancete_{emp_id}.xlsx")
        else:
            st.info("Nenhum lançamento encontrado para gerar o balancete.")