import streamlit as st
import sqlite3
import pandas as pd
import io
from werkzeug.security import generate_password_hash, check_password_hash

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="SysContábil SaaS", layout="wide", page_icon="⚖️")
DB_NAME = "syscontabil_v5.db"

# --- 2. FUNÇÕES DE BANCO DE DADOS ---
def get_db():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, nome_completo TEXT)')
        cursor.execute('CREATE TABLE IF NOT EXISTS empresas (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, cnpj TEXT, usuario_id INTEGER, FOREIGN KEY(usuario_id) REFERENCES usuarios(id))')
        cursor.execute('CREATE TABLE IF NOT EXISTS plano_contas (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, cod TEXT, nome TEXT, grupo TEXT, FOREIGN KEY(empresa_id) REFERENCES empresas(id))')
        cursor.execute('CREATE TABLE IF NOT EXISTS lancamentos (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, data TEXT, conta_debito TEXT, conta_credito TEXT, valor REAL, historico TEXT, FOREIGN KEY(empresa_id) REFERENCES empresas(id))')
        cursor.execute('CREATE TABLE IF NOT EXISTS fechamentos (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, mes_ano TEXT, UNIQUE(empresa_id, mes_ano), FOREIGN KEY(empresa_id) REFERENCES empresas(id))')
        conn.commit()

def is_periodo_fechado(emp_id, data_str):
    """Verifica se o mês/ano da data está trancado."""
    mes_ano = str(data_str)[:7] # Pega YYYY-MM
    with get_db() as conn:
        res = conn.execute("SELECT 1 FROM fechamentos WHERE empresa_id=? AND mes_ano=?", (emp_id, mes_ano)).fetchone()
    return True if res else False

def importar_plano_padrao(emp_id):
    plano = [
        ("1.01.01", "Caixa Geral", "Ativo"), ("1.01.02", "Banco Movimento", "Ativo"),
        ("2.01.01", "Fornecedores", "Passivo"), ("3.01.01", "Capital Social", "Patrimônio Líquido"),
        ("4.01.01", "Venda de Serviços", "Receita"), ("5.01.01", "Aluguéis", "Despesa")
    ]
    with get_db() as conn:
        conn.executemany("INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?, ?, ?, ?)", [(emp_id, c, n, g) for c, n, g in plano])
        conn.commit()

init_db()

# --- 3. AUTENTICAÇÃO ---
if 'auth' not in st.session_state:
    st.session_state.update({'auth': False, 'user_id': None})

if not st.session_state.auth:
    st.title("🛡️ SysContábil SaaS")
    t1, t2 = st.tabs(["Login", "Criar Conta"])
    with t1:
        # Adicionado keys únicas para evitar DuplicateElementId
        u = st.text_input("Usuário", key="login_user")
        p = st.text_input("Senha", type="password", key="login_pass")
        if st.button("Entrar", use_container_width=True):
            with get_db() as conn:
                user = conn.execute('SELECT * FROM usuarios WHERE username = ?', (u,)).fetchone()
                if user and check_password_hash(user['password'], p):
                    st.session_state.auth, st.session_state.user_id = True, user['id']
                    st.rerun()
                else: st.error("Acesso negado.")
    with t2:
        nu = st.text_input("Novo Usuário", key="reg_user")
        nome = st.text_input("Nome Completo", key="reg_nome")
        np = st.text_input("Senha", type="password", key="reg_pass")
        if st.button("Criar Conta", use_container_width=True):
            try:
                with get_db() as conn:
                    conn.execute('INSERT INTO usuarios (username, password, nome_completo) VALUES (?,?,?)', (nu, generate_password_hash(np), nome))
                    conn.commit(); st.success("Registrado!")
            except: st.error("Usuário já existe.")
else:
    # --- 4. ÁREA LOGADA ---
    with get_db() as conn:
        empresas = conn.execute('SELECT * FROM empresas WHERE usuario_id = ?', (st.session_state.user_id,)).fetchall()
    
    if not empresas:
        with st.form("nova_emp"):
            n = st.text_input("Razão Social", key="emp_nome")
            c = st.text_input("CNPJ", key="emp_cnpj")
            if st.form_submit_button("Criar Empresa"):
                with get_db() as conn:
                    conn.execute('INSERT INTO empresas (nome, cnpj, usuario_id) VALUES (?,?,?)', (n, c, st.session_state.user_id))
                    conn.commit(); st.rerun()
        st.stop()

    emp_dict = {e['id']: e['nome'] for e in empresas}
    emp_id = st.sidebar.selectbox("Empresa Ativa", options=list(emp_dict.keys()), format_func=lambda x: emp_dict[x])
    menu = st.sidebar.radio("Módulo", ["📊 Dashboard", "⚖️ Contabilidade", "📄 Relatórios", "⚙️ Gerenciar", "🔒 Fechamento"])
    
    if st.sidebar.button("Sair"):
        st.session_state.auth = False; st.rerun()

    # --- 5. LÓGICA DE MÓDULOS ---
    if menu == "⚖️ Contabilidade":
        tp, tl = st.tabs(["Plano de Contas", "Lançamentos"])
        with tp:
            with get_db() as conn:
                res = conn.execute("SELECT count(*) FROM plano_contas WHERE empresa_id=?", (emp_id,)).fetchone()[0]
            if res == 0:
                if st.button("⚡ Importar Padrão"): importar_plano_padrao(emp_id); st.rerun()
            
            with st.form("f_conta"):
                c1, c2, c3 = st.columns(3)
                cod = c1.text_input("Cód", key="c_cod")
                nm = c2.text_input("Nome", key="c_nome")
                gr = c3.selectbox("Grupo", ["Ativo", "Passivo", "Patrimônio Líquido", "Receita", "Despesa"], key="c_grp")
                if st.form_submit_button("Salvar"):
                    with get_db() as conn:
                        conn.execute("INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?,?,?,?)", (emp_id, cod, nm, gr))
                        conn.commit(); st.rerun()

        with tl:
            with get_db() as conn:
                lista = [f"{r['cod']} - {r['nome']}" for r in conn.execute("SELECT cod, nome FROM plano_contas WHERE empresa_id=?", (emp_id,)).fetchall()]
            with st.form("f_lanc"):
                d = st.date_input("Data")
                v = st.number_input("Valor", min_value=0.01)
                deb = st.selectbox("Débito", lista, key="l_deb")
                crd = st.selectbox("Crédito", lista, key="l_crd")
                h = st.text_input("Histórico", key="l_hist")
                if st.form_submit_button("Registrar"):
                    if is_periodo_fechado(emp_id, d): st.error("Mês trancado!")
                    elif deb != crd:
                        with get_db() as conn:
                            conn.execute("INSERT INTO lancamentos (empresa_id, data, conta_debito, conta_credito, valor, historico) VALUES (?,?,?,?,?,?)", (emp_id, str(d), deb, crd, v, h))
                            conn.commit(); st.success("Sucesso!"); st.rerun()
                    else: st.error("Contas iguais!")

    elif menu == "🔒 Fechamento":
        st.subheader("Trancar Período")
        m = st.selectbox("Mês", [f"{i:02d}" for i in range(1, 13)], key="f_mes")
        a = st.selectbox("Ano", ["2025", "2026"], key="f_ano")
        if st.button("Fechar Mês"):
            try:
                with get_db() as conn:
                    conn.execute("INSERT INTO fechamentos (empresa_id, mes_ano) VALUES (?,?)", (emp_id, f"{a}-{m}"))
                    conn.commit(); st.rerun()
            except: st.error("Já fechado.")
        
        with get_db() as conn:
            df_f = pd.read_sql_query("SELECT id, mes_ano FROM fechamentos WHERE empresa_id=?", conn)
            st.write("Meses Trancados:", df_f)

    elif menu == "⚙️ Gerenciar":
        with get_db() as conn:
            df_g = pd.read_sql_query("SELECT * FROM lancamentos WHERE empresa_id=?", conn)
        if not df_g.empty:
            st.dataframe(df_g, hide_index=True)
            id_del = st.number_input("ID para excluir", min_value=int(df_g['id'].min()), key="del_id")
            if st.button("Remover"):
                row = df_g[df_g['id'] == id_del]
                if not row.empty and is_periodo_fechado(emp_id, row['data'].values[0]):
                    st.error("Período fechado!")
                else:
                    with get_db() as conn:
                        conn.execute("DELETE FROM lancamentos WHERE id=?", (id_del,))
                        conn.commit(); st.rerun()

    elif menu == "📊 Dashboard":
        st.title("Panorama")
        with get_db() as conn:
            rec = conn.execute("SELECT sum(valor) FROM lancamentos WHERE empresa_id=? AND conta_credito LIKE '4%'", (emp_id,)).fetchone()[0] or 0
            des = conn.execute("SELECT sum(valor) FROM lancamentos WHERE empresa_id=? AND conta_debito LIKE '5%'", (emp_id,)).fetchone()[0] or 0
        st.metric("Resultado", f"R$ {rec - des:,.2f}", delta=float(rec-des))