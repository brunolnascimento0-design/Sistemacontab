import streamlit as st
import sqlite3
import pandas as pd
import io
from werkzeug.security import generate_password_hash, check_password_hash

# --- 1. CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="SysContábil SaaS", layout="wide", page_icon="⚖️")
DB_NAME = "syscontabil_v5.db"

# --- 2. FUNÇÕES DE BANCO DE DADOS (DATABASE LAYER) ---
def get_db():
    """Cria uma conexão com o banco de dados SQLite."""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Inicializa as tabelas se não existirem."""
    with get_db() as conn:
        cursor = conn.cursor()
        # Usuários
        cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, nome_completo TEXT)''')
        # Empresas (incluindo campo regime)
        cursor.execute('''CREATE TABLE IF NOT EXISTS empresas 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT, cnpj TEXT, regime TEXT, usuario_id INTEGER, 
            FOREIGN KEY(usuario_id) REFERENCES usuarios(id))''')
        # Plano de Contas
        cursor.execute('''CREATE TABLE IF NOT EXISTS plano_contas 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, cod TEXT, nome TEXT, grupo TEXT, 
            FOREIGN KEY(empresa_id) REFERENCES empresas(id))''')
        # Lançamentos
        cursor.execute('''CREATE TABLE IF NOT EXISTS lancamentos 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, data TEXT, conta_debito TEXT, 
            conta_credito TEXT, valor REAL, historico TEXT, 
            FOREIGN KEY(empresa_id) REFERENCES empresas(id))''')
        # Fechamentos de Período
        cursor.execute('''CREATE TABLE IF NOT EXISTS fechamentos 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, mes_ano TEXT, 
            UNIQUE(empresa_id, mes_ano), FOREIGN KEY(empresa_id) REFERENCES empresas(id))''')
        conn.commit()

def is_periodo_fechado(emp_id, data_str):
    """Verifica se a data pertence a um período trancado."""
    mes_ano = str(data_str)[:7]  # Extrai YYYY-MM
    with get_db() as conn:
        res = conn.execute("SELECT 1 FROM fechamentos WHERE empresa_id=? AND mes_ano=?", (emp_id, mes_ano)).fetchone()
    return True if res else False

def importar_plano_padrao(emp_id):
    """Importa contas contábeis básicas para a empresa."""
    plano = [
        ("1.01.01", "Caixa Geral", "Ativo"), ("1.01.02", "Banco Movimento", "Ativo"),
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
        u = st.text_input("Usuário", key="login_u")
        p = st.text_input("Senha", type="password", key="login_p")
        if st.button("Entrar", use_container_width=True):
            with get_db() as conn:
                user = conn.execute('SELECT * FROM usuarios WHERE username = ?', (u,)).fetchone()
                if user and check_password_hash(user['password'], p):
                    st.session_state.auth, st.session_state.user_id = True, user['id']
                    st.rerun()
                else: st.error("Acesso negado.")
    with t2:
        nu, nome, np = st.text_input("Novo Usuário", key="reg_u"), st.text_input("Nome Completo", key="reg_n"), st.text_input("Senha", type="password", key="reg_p")
        if st.button("Criar Conta", use_container_width=True):
            try:
                with get_db() as conn:
                    conn.execute('INSERT INTO usuarios (username, password, nome_completo) VALUES (?,?,?)', (nu, generate_password_hash(np), nome))
                    conn.commit(); st.success("Registrado! Faça login.")
            except: st.error("Usuário já existe.")
else:
    # --- 4. ÁREA LOGADA ---
    with get_db() as conn:
        empresas = conn.execute('SELECT * FROM empresas WHERE usuario_id = ?', (st.session_state.user_id,)).fetchall()
    
    if not empresas:
        with st.form("nova_emp"):
            st.subheader("Cadastrar Empresa")
            n = st.text_input("Razão Social", key="emp_n")
            c = st.text_input("CNPJ", key="emp_c")
            r = st.selectbox("Regime Tributário", ["Simples Nacional", "Lucro Presumido", "MEI"], key="emp_r")
            if st.form_submit_button("Criar Empresa"):
                with get_db() as conn:
                    conn.execute('INSERT INTO empresas (nome, cnpj, regime, usuario_id) VALUES (?,?,?,?)', (n, c, r, st.session_state.user_id))
                    conn.commit(); st.rerun()
        st.stop()

    # Sidebar: Navegação
    emp_dict = {e['id']: e['nome'] for e in empresas}
    emp_regime = {e['id']: e['regime'] for e in empresas}
    emp_id = st.sidebar.selectbox("Empresa Ativa", options=list(emp_dict.keys()), format_func=lambda x: emp_dict[x])
    regime_ativo = emp_regime[emp_id]
    
    menu = st.sidebar.radio("Módulo", ["📊 Dashboard", "⚖️ Contabilidade", "📄 Relatórios", "⚙️ Gerenciar", "🔒 Fechamento", "🏦 Fiscal"])
    
    if st.sidebar.button("Logout"):
        st.session_state.auth = False; st.rerun()

    # --- 5. LÓGICA DE MÓDULOS ---

    # --- DASHBOARD ---
    if menu == "📊 Dashboard":
        st.header(f"Panorama: {emp_dict[emp_id]}")
        with get_db() as conn:
            rec = conn.execute("SELECT sum(valor) FROM lancamentos WHERE empresa_id=? AND conta_credito LIKE '4%'", (emp_id,)).fetchone()[0] or 0
            des = conn.execute("SELECT sum(valor) FROM lancamentos WHERE empresa_id=? AND conta_debito LIKE '5%'", (emp_id,)).fetchone()[0] or 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Faturamento", f"R$ {rec:,.2f}")
        c2.metric("Despesas", f"R$ {des:,.2f}")
        c3.metric("Resultado", f"R$ {rec - des:,.2f}", delta=float(rec-des))

        st.divider()
        with get_db() as conn:
            df_hist = pd.read_sql_query("SELECT data, valor FROM lancamentos WHERE empresa_id=?", conn, params=(emp_id,))
        if not df_hist.empty:
            df_hist['data'] = pd.to_datetime(df_hist['data'])
            st.subheader("Movimentação Temporal")
            st.line_chart(df_hist.groupby('data')['valor'].sum())

    # --- CONTABILIDADE ---
    elif menu == "⚖️ Contabilidade":
        tp, tl = st.tabs(["Plano de Contas", "Lançamentos"])
        with tp:
            with get_db() as conn:
                res = conn.execute("SELECT count(*) FROM plano_contas WHERE empresa_id=?", (emp_id,)).fetchone()[0]
            if res == 0:
                if st.button("⚡ Importar Plano Padrão"): importar_plano_padrao(emp_id); st.rerun()
            
            with st.form("f_conta"):
                c1, c2, c3 = st.columns(3)
                cod = c1.text_input("Cód", key="pc_cod")
                nm = c2.text_input("Nome", key="pc_nome")
                gr = c3.selectbox("Grupo", ["Ativo", "Passivo", "Patrimônio Líquido", "Receita", "Despesa"], key="pc_grp")
                if st.form_submit_button("Salvar Conta"):
                    with get_db() as conn:
                        conn.execute("INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?,?,?,?)", (emp_id, cod, nm, gr))
                        conn.commit(); st.rerun()
            with get_db() as conn:
                st.dataframe(pd.read_sql_query("SELECT cod, nome, grupo FROM plano_contas WHERE empresa_id=?", conn, params=(emp_id,)), use_container_width=True)

        with tl:
            with get_db() as conn:
                lista_c = [f"{r['cod']} - {r['nome']}" for r in conn.execute("SELECT cod, nome FROM plano_contas WHERE empresa_id=?", (emp_id,)).fetchall()]
            if not lista_c: st.warning("Cadastre o plano de contas.")
            else:
                with st.form("f_lanc"):
                    d, v, h = st.date_input("Data"), st.number_input("Valor R$", min_value=0.01), st.text_input("Histórico", key="l_h")
                    deb, crd = st.selectbox("Conta Débito", lista_c, key="l_d"), st.selectbox("Conta Crédito", lista_c, key="l_c")
                    if st.form_submit_button("Registrar"):
                        if is_periodo_fechado(emp_id, d): st.error("Mês trancado!")
                        elif deb != crd:
                            with get_db() as conn:
                                conn.execute("INSERT INTO lancamentos (empresa_id, data, conta_debito, conta_credito, valor, historico) VALUES (?,?,?,?,?,?)", (emp_id, str(d), deb, crd, v, h))
                                conn.commit(); st.success("Registrado!"); st.rerun()
                        else: st.error("Contas iguais!")

    # --- RELATÓRIOS ---
    elif menu == "📄 Relatórios":
        st.header("Balancete de Verificação")
        with get_db() as conn:
            df_l = pd.read_sql_query("SELECT * FROM lancamentos WHERE empresa_id=?", conn, params=(emp_id,))
            df_p = pd.read_sql_query("SELECT * FROM plano_contas WHERE empresa_id=?", conn, params=(emp_id,))
        
        if not df_l.empty:
            resumo = []
            for _, c in df_p.iterrows():
                label = f"{c['cod']} - {c['nome']}"
                deb = df_l[df_l['conta_debito'] == label]['valor'].sum()
                crd = df_l[df_l['conta_credito'] == label]['valor'].sum()
                res = (deb - crd) if c['grupo'] in ['Ativo', 'Despesa'] else (crd - deb)
                resumo.append({'Cód': c['cod'], 'Conta': c['nome'], 'Grupo': c['grupo'], 'Débito': deb, 'Crédito': crd, 'Saldo': res})
            
            df_b = pd.DataFrame(resumo)
            st.table(df_b)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_b.to_excel(writer, index=False, sheet_name='Balancete')
            st.download_button("📥 Baixar Excel", output.getvalue(), f"balancete_{emp_id}.xlsx")
        else: st.info("Sem dados.")

    # --- GERENCIAR ---
    elif menu == "⚙️ Gerenciar":
        st.header("Gerenciar Lançamentos")
        with get_db() as conn:
            df_g = pd.read_sql_query("SELECT id, data, conta_debito, conta_credito, valor, historico FROM lancamentos WHERE empresa_id=?", conn, params=(emp_id,))
        if not df_g.empty:
            st.dataframe(df_g, use_container_width=True, hide_index=True)
            id_del = st.number_input("ID para excluir", min_value=int(df_g['id'].min()), key="del_id")
            if st.button("❌ Excluir Selecionado"):
                row = df_g[df_g['id'] == id_del]
                if not row.empty and is_periodo_fechado(emp_id, row['data'].values[0]):
                    st.error("Período fechado!")
                else:
                    with get_db() as conn:
                        conn.execute("DELETE FROM lancamentos WHERE id=? AND empresa_id=?", (id_del, emp_id))
                        conn.commit(); st.rerun()

    # --- FECHAMENTO ---
    elif menu == "🔒 Fechamento":
        st.header("Fechamento Contábil")
        c_f1, c_f2 = st.columns(2)
        with c_f1:
            with st.form("f_lock"):
                m = st.selectbox("Mês", [f"{i:02d}" for i in range(1, 13)], key="f_m")
                a = st.selectbox("Ano", ["2025", "2026"], key="f_a")
                if st.form_submit_button("Trancar Período"):
                    try:
                        with get_db() as conn:
                            conn.execute("INSERT INTO fechamentos (empresa_id, mes_ano) VALUES (?,?)", (emp_id, f"{a}-{m}"))
                            conn.commit(); st.rerun()
                    except: st.error("Já fechado.")
        with c_f2:
            with get_db() as conn:
                df_f = pd.read_sql_query("SELECT id, mes_ano FROM fechamentos WHERE empresa_id=?", conn, params=(emp_id,))
            st.write("Meses Trancados:", df_f)
            if not df_f.empty:
                id_abrir = st.number_input("ID para reabrir", min_value=int(df_f['id'].min()), key="f_id_a")
                if st.button("🔓 Abrir Período"):
                    with get_db() as conn:
                        conn.execute("DELETE FROM fechamentos WHERE id=? AND empresa_id=?", (id_abrir, emp_id))
                        conn.commit(); st.rerun()

    # --- FISCAL ---
    elif menu == "🏦 Fiscal":
        st.header(f"Apuração Fiscal - {regime_ativo}")
        col_f1, col_f2 = st.columns(2)
        mes_f = col_f1.selectbox("Mês", [f"{i:02d}" for i in range(1, 13)], key="fi_m")
        ano_f = col_f1.selectbox("Ano", ["2025", "2026"], key="fi_a")
        
        data_ini, data_fim = f"{ano_f}-{mes_f}-01", f"{ano_f}-{mes_f}-31"
        with get_db() as conn:
            fat = conn.execute("SELECT sum(valor) FROM lancamentos WHERE empresa_id=? AND conta_credito LIKE '4%' AND data BETWEEN ? AND ?", (emp_id, data_ini, data_fim)).fetchone()[0] or 0
        
        st.metric("Faturamento do Período", f"R$ {fat:,.2f}")
        imp_total, detalhes = 0, {}

        if regime_ativo == "MEI":
            atv = st.radio("Atividade", ["Comércio (R$ 70,60)", "Serviços (R$ 75,60)"], key="mei_atv")
            imp_total = 70.60 if "Comércio" in atv else 75.60
            detalhes = {"DAS MEI": imp_total}
        elif regime_ativo == "Simples Nacional":
            aliq = st.number_input("Alíquota (%)", value=6.0, key="sn_aliq")
            imp_total = fat * (aliq/100)
            detalhes = {"Simples Nacional": imp_total}
        elif regime_ativo == "Lucro Presumido":
            atv = st.selectbox("Atividade", ["Serviços (32%)", "Comércio (8%)"], key="lp_atv")
            base = 0.32 if "Serviços" in atv else 0.08
            p, c, i, cs = fat*0.0065, fat*0.03, (fat*base)*0.15, (fat*(0.32 if "Serviços" in atv else 0.12))*0.09
            imp_total = p+c+i+cs
            detalhes = {"PIS": p, "COFINS": c, "IRPJ": i, "CSLL": cs}

        st.divider()
        for k, v in detalhes.items(): st.write(f"**{k}:** R$ {v:,.2f}")
        st.subheader(f"Total: R$ {imp_total:,.2f}")

        if st.button("Gerar Provisão Contábil"):
            if is_periodo_fechado(emp_id, data_ini): st.error("Período trancado!")
            elif imp_total > 0:
                with get_db() as conn:
                    for k, v in detalhes.items():
                        conn.execute("INSERT INTO lancamentos (empresa_id, data, conta_debito, conta_credito, valor, historico) VALUES (?,?,?,?,?,?)", 
                                   (emp_id, data_fim, "5.01.04 - Provisão de Impostos", "2.01.03 - Impostos a Recolher", v, f"Provisão {k} {mes_f}/{ano_f}"))
                    conn.commit(); st.success("Provisionado!")