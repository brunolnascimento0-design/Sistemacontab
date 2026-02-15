import streamlit as st
import sqlite3
import pandas as pd
import io
from fpdf import FPDF
from werkzeug.security import generate_password_hash, check_password_hash

# --- 1. CONFIGURAÇÃO E FUNÇÕES AUXILIARES ---
st.set_page_config(page_title="SysContábil SaaS", layout="wide", page_icon="⚖️")
DB_NAME = "syscontabil_v5.db"

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
        cursor.execute('CREATE TABLE IF NOT EXISTS fechamentos (id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, mes_ano TEXT, UNIQUE(empresa_id, mes_ano), FOREIGN KEY(empresa_id) REFERENCES empresas(id))')
        conn.commit()

def is_periodo_fechado(emp_id, data_str):
    mes_ano = str(data_str)[:7] # YYYY-MM
    with get_db() as conn:
        res = conn.execute("SELECT 1 FROM fechamentos WHERE empresa_id=? AND mes_ano=?", (emp_id, mes_ano)).fetchone()
    return True if res else False

def importar_plano_padrao(emp_id):
    plano = [
        ("1.01.01", "Caixa Geral", "Ativo"), ("1.01.02", "Banco Movimento", "Ativo"),
        ("1.09.99", "A Classificar (Entradas)", "Ativo"), ("2.09.99", "A Classificar (Saídas)", "Passivo"),
        ("2.01.01", "Fornecedores", "Passivo"), ("3.01.01", "Capital Social", "Patrimônio Líquido"),
        ("4.01.01", "Receitas de Vendas", "Receita"), ("5.01.01", "Despesas Operacionais", "Despesa"),
        ("5.01.04", "Provisão de Impostos", "Despesa"), ("2.01.03", "Impostos a Recolher", "Passivo")
    ]
    with get_db() as conn:
        conn.executemany("INSERT INTO plano_contas (empresa_id, cod, nome, grupo) VALUES (?, ?, ?, ?)", 
                       [(emp_id, c, n, g) for c, n, g in plano])
        conn.commit()

def gerar_pdf(df, titulo):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(190, 10, titulo, ln=True, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 10)
    for col in df.columns:
        pdf.cell(40, 10, str(col), 1)
    pdf.ln()
    pdf.set_font("Arial", '', 10)
    for _, row in df.iterrows():
        for val in row:
            pdf.cell(40, 10, str(val), 1)
        pdf.ln()
    return pdf.output(dest='S').encode('latin-1')

init_db()

# --- 2. AUTENTICAÇÃO ---
if 'auth' not in st.session_state:
    st.session_state.update({'auth': False, 'user_id': None})

if not st.session_state.auth:
    st.title("🛡️ SysContábil SaaS")
    t1, t2 = st.tabs(["Login", "Criar Conta"])
    with t1:
        u = st.text_input("Usuário", key="l_u")
        p = st.text_input("Senha", type="password", key="l_p")
        if st.button("Entrar", use_container_width=True):
            with get_db() as conn:
                user = conn.execute('SELECT * FROM usuarios WHERE username = ?', (u,)).fetchone()
                if user and check_password_hash(user['password'], p):
                    st.session_state.auth, st.session_state.user_id = True, user['id']
                    st.rerun()
                else: st.error("Acesso negado.")
    with t2:
        nu, nome, np = st.text_input("Novo Usuário", key="r_u"), st.text_input("Nome", key="r_n"), st.text_input("Senha", type="password", key="r_p")
        if st.button("Criar Conta"):
            with get_db() as conn:
                conn.execute('INSERT INTO usuarios (username, password, nome_completo) VALUES (?,?,?)', (nu, generate_password_hash(np), nome))
                conn.commit(); st.success("OK!")
else:
    # --- 3. ÁREA LOGADA ---
    with get_db() as conn:
        empresas = conn.execute('SELECT * FROM empresas WHERE usuario_id = ?', (st.session_state.user_id,)).fetchall()
    
    if not empresas:
        with st.form("nova_emp"):
            st.subheader("Cadastrar Empresa")
            n, c = st.text_input("Razão Social", key="en"), st.text_input("CNPJ", key="ec")
            r = st.selectbox("Regime", ["Simples Nacional", "Lucro Presumido", "MEI"], key="er")
            if st.form_submit_button("Criar"):
                with get_db() as conn:
                    conn.execute('INSERT INTO empresas (nome, cnpj, regime, usuario_id) VALUES (?,?,?,?)', (n, c, r, st.session_state.user_id))
                    conn.commit(); st.rerun()
        st.stop()

    emp_dict = {e['id']: e['nome'] for e in empresas}
    emp_regime = {e['id']: e['regime'] for e in empresas}
    emp_id = st.sidebar.selectbox("Empresa Ativa", options=list(emp_dict.keys()), format_func=lambda x: emp_dict[x])
    menu = st.sidebar.radio("Menu", ["📊 Dashboard", "⚖️ Contabilidade", "🏦 Fiscal", "📥 Importar", "📄 Relatórios", "⚙️ Gerenciar", "🔒 Fechamento"])

    if st.sidebar.button("Sair"):
        st.session_state.auth = False; st.rerun()

    # --- MÓDULO CONTABILIDADE ---
    if menu == "⚖️ Contabilidade":
        tp, tl = st.tabs(["Plano de Contas", "Lançamentos Manuais"])
        with tp:
            with get_db() as conn:
                if conn.execute("SELECT count(*) FROM plano_contas WHERE empresa_id=?", (emp_id,)).fetchone()[0] == 0:
                    if st.button("⚡ Importar Plano Padrão"): importar_plano_padrao(emp_id); st.rerun()
            with get_db() as conn:
                df_p = pd.read_sql_query("SELECT cod, nome, grupo FROM plano_contas WHERE empresa_id=?", conn, params=(emp_id,))
                st.dataframe(df_p, use_container_width=True)
        with tl:
            st.subheader("Nova Partida Dobrada")
            with get_db() as conn:
                contas = [f"{r['cod']} - {r['nome']}" for r in conn.execute("SELECT cod, nome FROM plano_contas WHERE empresa_id=?", (emp_id,)).fetchall()]
            if contas:
                with st.form("f_lanc_man"):
                    col1, col2 = st.columns(2)
                    d, v = col1.date_input("Data"), col2.number_input("Valor R$", min_value=0.01)
                    deb, crd = st.selectbox("Conta Débito", contas, key="d_man"), st.selectbox("Conta Crédito", contas, key="c_man")
                    h = st.text_area("Histórico")
                    if st.form_submit_button("Lançar"):
                        if is_periodo_fechado(emp_id, d): st.error("Período Fechado!")
                        elif deb == crd: st.error("Contas iguais!")
                        else:
                            with get_db() as conn:
                                conn.execute("INSERT INTO lancamentos (empresa_id, data, conta_debito, conta_credito, valor, historico) VALUES (?,?,?,?,?,?)", (emp_id, str(d), deb, crd, v, h))
                                conn.commit(); st.success("OK!"); st.rerun()

    # --- MÓDULO RELATÓRIOS ---
    elif menu == "📄 Relatórios":
        st.header("Relatórios Contábeis")
        t_dre, t_bp, t_fat, t_fisc = st.tabs(["DRE", "Balanço Patrimonial", "Faturamento 12m", "Espelho Fiscal"])
        with get_db() as conn:
            df_l = pd.read_sql_query("SELECT * FROM lancamentos WHERE empresa_id=?", conn, params=(emp_id,))
            df_p = pd.read_sql_query("SELECT * FROM plano_contas WHERE empresa_id=?", conn, params=(emp_id,))
        
        if not df_l.empty:
            saldos = []
            for _, c in df_p.iterrows():
                label = f"{c['cod']} - {c['nome']}"
                deb = df_l[df_l['conta_debito'] == label]['valor'].sum()
                crd = df_l[df_l['conta_credito'] == label]['valor'].sum()
                res = (deb - crd) if c['grupo'] in ['Ativo', 'Despesa'] else (crd - deb)
                saldos.append({'Conta': c['nome'], 'Grupo': c['grupo'], 'Saldo': res})
            df_s = pd.DataFrame(saldos)

            with t_dre:
                dre = df_s[df_s['Grupo'].isin(['Receita', 'Despesa'])]
                st.table(dre)
                if st.button("PDF DRE"): st.download_button("Baixar PDF", gerar_pdf(dre, "DRE"), "dre.pdf")
            with t_bp:
                st.write("**Ativo**")
                st.table(df_s[df_s['Grupo'] == 'Ativo'])
                st.write("**Passivo/PL**")
                st.table(df_s[df_s['Grupo'].isin(['Passivo', 'Patrimônio Líquido'])])
            with t_fat:
                df_l['data'] = pd.to_datetime(df_l['data'])
                fat = df_l[df_l['conta_credito'].str.contains("Receita")].groupby(df_l['data'].dt.strftime('%m/%Y'))['valor'].sum()
                st.bar_chart(fat)
        else: st.info("Sem dados.")
        
    # --- DASHBOARD ---
    elif menu == "📊 Dashboard":
        st.title(f"Painel de Controle - {emp_dict[emp_id]}")
        with get_db() as conn:
            # Cálculo de Receitas (Grupo 4) e Despesas (Grupo 5)
            rec = conn.execute("SELECT sum(valor) FROM lancamentos WHERE empresa_id=? AND conta_credito LIKE '4%'", (emp_id,)).fetchone()[0] or 0
            des = conn.execute("SELECT sum(valor) FROM lancamentos WHERE empresa_id=? AND conta_debito LIKE '5%'", (emp_id,)).fetchone()[0] or 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Faturamento Mensal", f"R$ {rec:,.2f}")
        c2.metric("Total de Custos/Despesas", f"R$ {des:,.2f}")
        c3.metric("Lucro Líquido", f"R$ {rec - des:,.2f}", delta=float(rec - des))

        st.divider()
        with get_db() as conn:
            # Correção: Uso de params para evitar DatabaseError
            df_hist = pd.read_sql_query("SELECT data, valor FROM lancamentos WHERE empresa_id=?", conn, params=(emp_id,))
        
        if not df_hist.empty:
            df_hist['data'] = pd.to_datetime(df_hist['data'])
            st.subheader("Evolução Financeira (Lançamentos)")
            st.line_chart(df_hist.groupby('data')['valor'].sum())
        else:
            st.info("Aguardando lançamentos para gerar gráficos.")

    # --- GERENCIAR ---
    elif menu == "⚙️ Gerenciar":
        st.header("Histórico e Manutenção de Dados")
        st.write("Visualize ou remova lançamentos específicos abaixo.")
        
        with get_db() as conn:
            # Seleção protegida por params
            df_g = pd.read_sql_query("SELECT id, data, conta_debito, conta_credito, valor, historico FROM lancamentos WHERE empresa_id=?", conn, params=(emp_id,))
        
        if not df_g.empty:
            st.dataframe(df_g, use_container_width=True, hide_index=True)
            
            st.subheader("Excluir Registro")
            id_del = st.number_input("Informe o ID do lançamento:", min_value=int(df_g['id'].min()), key="input_del_id")
            
            if st.button("❌ Confirmar Exclusão", type="primary", key="btn_del_exec"):
                # Busca a data do lançamento para validar se o período está fechado
                data_lanc = df_g[df_g['id'] == id_del]['data'].values[0]
                
                if is_periodo_fechado(emp_id, data_lanc):
                    st.error("Não é possível excluir: Este período contábil já foi encerrado.")
                else:
                    with get_db() as conn:
                        conn.execute("DELETE FROM lancamentos WHERE id=? AND empresa_id=?", (id_del, emp_id))
                        conn.commit()
                    st.success(f"Lançamento {id_del} removido com sucesso!")
                    st.rerun()
        else:
            st.info("Nenhum dado encontrado para esta empresa.")

    # --- FECHAMENTO ---
    elif menu == "🔒 Fechamento":
        st.header("Encerramento de Período Contábil")
        st.warning("Atenção: Trancar um mês impede novas inserções, edições ou exclusões de dados naquela data.")
        
        col_f1, col_f2 = st.columns(2)
        
        with col_f1:
            with st.form("form_fechamento_contabil"):
                st.subheader("Trancar Novo Mês")
                m_lock = st.selectbox("Mês", [f"{i:02d}" for i in range(1, 13)], key="sel_mes_lock")
                a_lock = st.selectbox("Ano", ["2024", "2025", "2026"], key="sel_ano_lock")
                
                if st.form_submit_button("🔒 Bloquear Período"):
                    try:
                        with get_db() as conn:
                            conn.execute("INSERT INTO fechamentos (empresa_id, mes_ano) VALUES (?,?)", (emp_id, f"{a_lock}-{m_lock}"))
                            conn.commit()
                        st.success(f"Período {m_lock}/{a_lock} trancado!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Este período já consta como fechado no sistema.")

        with col_f2:
            st.subheader("Meses Bloqueados")
            with get_db() as conn:
                df_fechados = pd.read_sql_query("SELECT id, mes_ano FROM fechamentos WHERE empresa_id=?", conn, params=(emp_id,))
            
            if not df_fechados.empty:
                st.table(df_fechados)
                id_abrir = st.number_input("ID para reabertura:", min_value=int(df_fechados['id'].min()), key="id_reabertura")
                if st.button("🔓 Reabrir Período", key="btn_reabrir"):
                    with get_db() as conn:
                        conn.execute("DELETE FROM fechamentos WHERE id=? AND empresa_id=?", (id_abrir, emp_id))
                        conn.commit()
                    st.success("Período reaberto para lançamentos.")
                    st.rerun()
            else:
                st.info("Todos os períodos estão abertos.")

# --- RODAPÉ ---
st.sidebar.markdown("---")
st.sidebar.caption("SaaS Contábil v5.0 | 2026")