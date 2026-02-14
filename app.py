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
    """Cria uma conexão com o banco de dados."""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Inicializa as tabelas do sistema."""
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
    """Insere o plano de contas padrão detalhado."""
    plano = [
        ("1.01.01", "Caixa Geral", "Ativo"), ("1.01.02", "Banco Conta Movimento", "Ativo"),
        ("1.02.01", "Clientes Nacionais", "Ativo"), ("2.01.01", "Fornecedores", "Passivo"),
        ("2.01.02", "Salários a Pagar", "Passivo"), ("2.01.03", "Impostos a Recolher", "Passivo"),
        ("3.01.01", "Capital Social", "Patrimônio Líquido"), ("3.01.02", "Reservas de Lucros", "Patrimônio Líquido"),
        ("4.01.01", "Venda de Serviços/Produtos", "Receita"), ("4.01.02", "Receitas Financeiras", "Receita"),
        ("5.01.01", "Aluguéis e Condomínio", "Despesa"), ("5.01.02", "Energia e Internet", "Despesa"),
        ("5.01.03", "Marketing e Vendas", "Despesa"), ("5.01.04", "Provisão de Impostos", "Despesa")
    ]
    with get_db() as conn:
        conn.executemany("INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?, ?, ?, ?)", 
                       [(emp_id, c, n, g) for c, n, g in plano])
        conn.commit()

init_db()

# --- 3. AUTENTICAÇÃO ---
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
                    st.session_state.auth, st.session_state.user_id = True, user['id']
                    st.rerun()
                else: st.error("Acesso negado.")
    with t2:
        nu, nome, np = st.text_input("Novo Usuário"), st.text_input("Nome Completo"), st.text_input("Senha", type="password")
        if st.button("Cadastrar", use_container_width=True):
            try:
                with get_db() as conn:
                    conn.execute('INSERT INTO usuarios (username, password, nome_completo) VALUES (?,?,?)', (nu, generate_password_hash(np), nome))
                    conn.commit()
                st.success("Conta criada! Faça login.")
            except: st.error("Usuário já existe.")
else:
    # --- 4. ÁREA LOGADA ---
    with get_db() as conn:
        empresas = conn.execute('SELECT * FROM empresas WHERE usuario_id = ?', (st.session_state.user_id,)).fetchall()
    
    if not empresas:
        st.subheader("Cadastre sua primeira empresa")
        with st.form("nova_emp"):
            n, c = st.text_input("Razão Social"), st.text_input("CNPJ")
            if st.form_submit_button("Criar Empresa"):
                with get_db() as conn:
                    conn.execute('INSERT INTO empresas (nome, cnpj, usuario_id) VALUES (?,?,?)', (n, c, st.session_state.user_id))
                    conn.commit()
                st.rerun()
        st.stop()

    # Sidebar
    emp_dict = {e['id']: e['nome'] for e in empresas}
    emp_id = st.sidebar.selectbox("Empresa Ativa", options=list(emp_dict.keys()), format_func=lambda x: emp_dict[x])
    menu = st.sidebar.radio("Módulo", ["📊 Dashboard", "⚖️ Contabilidade", "📄 Relatórios", "⚙️ Gerenciar Dados"])
    
    if st.sidebar.button("Sair"):
        st.session_state.auth = False
        st.rerun()

    # --- 5. MÓDULOS ---
    if menu == "⚖️ Contabilidade":
        t_plano, t_lanc = st.tabs(["Plano de Contas", "Lançamentos"])
        with t_plano:
            with get_db() as conn:
                count = conn.execute("SELECT count(*) as total FROM plano_contas WHERE empresa_id=?", (emp_id,)).fetchone()
            if count['total'] == 0:
                if st.button("⚡ Importar Plano Padrão"):
                    importar_plano_padrao(emp_id); st.rerun()
            
            with st.expander("Adicionar Conta"):
                with st.form("add_c"):
                    c1, c2, c3 = st.columns(3); cod = c1.text_input("Cód"); nome_c = c2.text_input("Nome"); grp = c3.selectbox("Grupo", ["Ativo", "Passivo", "Patrimônio Líquido", "Receita", "Despesa"])
                    if st.form_submit_button("Salvar"):
                        with get_db() as conn:
                            conn.execute("INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?,?,?,?)", (emp_id, cod, nome_c, grp))
                            conn.commit()
                        st.rerun()
            with get_db() as conn:
                st.dataframe(pd.read_sql_query("SELECT cod, nome, grupo FROM plano_contas WHERE empresa_id=?", conn, params=(emp_id,)), use_container_width=True)

        with t_lanc:
            with get_db() as conn:
                contas = [f"{r['cod']} - {r['nome']}" for r in conn.execute("SELECT cod, nome FROM plano_contas WHERE empresa_id=?", (emp_id,)).fetchall()]
            if not contas: st.warning("Cadastre o plano de contas.")
            else:
                with st.form("add_l"):
                    d, v, h = st.date_input("Data"), st.number_input("Valor R$", min_value=0.01), st.text_input("Histórico")
                    deb, crd = st.selectbox("Conta Débito", contas), st.selectbox("Conta Crédito", contas)
                    if st.form_submit_button("Registrar"):
                        if deb != crd:
                            with get_db() as conn:
                                conn.execute("INSERT INTO lancamentos (empresa_id, data, conta_debito, conta_credito, valor, historico) VALUES (?,?,?,?,?,?)", (emp_id, str(d), deb, crd, v, h))
                                conn.commit(); st.success("Lançado!"); st.rerun()
                        else: st.error("Contas iguais!")

    elif menu == "📄 Relatórios":
        st.header("Balancete de Verificação")
        with get_db() as conn:
            lancamentos = pd.read_sql_query("SELECT * FROM lancamentos WHERE empresa_id=?", conn, params=(emp_id,))
            contas_p = pd.read_sql_query("SELECT * FROM plano_contas WHERE empresa_id=?", conn, params=(emp_id,))
        if not lancamentos.empty:
            resumo = []
            for _, c in contas_p.iterrows():
                label = f"{c['cod']} - {c['nome']}"
                deb = lancamentos[lancamentos['conta_debito'] == label]['valor'].sum()
                crd = lancamentos[lancamentos['conta_credito'] == label]['valor'].sum()
                saldo = (deb - crd) if c['grupo'] in ['Ativo', 'Despesa'] else (crd - deb)
                resumo.append({'Cód': c['cod'], 'Conta': c['nome'], 'Grupo': c['grupo'], 'Débito': deb, 'Crédito': crd, 'Saldo': saldo})
            df_b = pd.DataFrame(resumo)
            st.table(df_b)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_b.to_excel(writer, index=False, sheet_name='Balancete')
            st.download_button("📥 Baixar Excel", output.getvalue(), f"balancete_{emp_id}.xlsx")
        else: st.info("Sem dados.")

    elif menu == "📊 Dashboard":
        st.header("Resumo Financeiro")
        with get_db() as conn:
            receitas = conn.execute("SELECT sum(valor) FROM lancamentos WHERE empresa_id=? AND conta_credito LIKE '4%'", (emp_id,)).fetchone()[0] or 0
            despesas = conn.execute("SELECT sum(valor) FROM lancamentos WHERE empresa_id=? AND conta_debito LIKE '5%'", (emp_id,)).fetchone()[0] or 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Receitas", f"R$ {receitas:,.2f}")
        c2.metric("Despesas", f"R$ {despesas:,.2f}")
        c3.metric("Resultado", f"R$ {receitas - despesas:,.2f}", delta=float(receitas - despesas))

        st.divider()
        with get_db() as conn:
            df_l = pd.read_sql_query("SELECT data, valor FROM lancamentos WHERE empresa_id=?", conn)
        if not df_l.empty:
            df_l['data'] = pd.to_datetime(df_l['data'])
            st.subheader("Movimentação Diária")
            st.line_chart(df_l.groupby('data')['valor'].sum())
        else: st.info("Lance dados para ver o gráfico.")

    elif menu == "⚙️ Gerenciar Dados":
        st.header("Histórico e Exclusão")
        with get_db() as conn:
            df_g = pd.read_sql_query("SELECT id, data, conta_debito, conta_credito, valor, historico FROM lancamentos WHERE empresa_id=?", conn)
        if not df_g.empty:
            st.dataframe(df_g, use_container_width=True, hide_index=True)
            id_del = st.number_input("ID para excluir", min_value=int(df_g['id'].min()), max_value=int(df_g['id'].max()))
            if st.button("❌ Excluir Selecionado", type="primary"):
                with get_db() as conn:
                    conn.execute("DELETE FROM lancamentos WHERE id=? AND empresa_id=?", (id_del, emp_id))
                    conn.commit()
                st.success(f"ID {id_del} removido."); st.rerun()
        else: st.info("Nada para gerenciar.")

# --- FIM DO CÓDIGO ---