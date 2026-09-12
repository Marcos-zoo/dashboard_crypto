import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io
import os

st.set_page_config(
    page_title="Dashboard Coinbase Perpetuals",
    page_icon="⚡",
    layout="wide"
)

st.markdown("""
<style>
    div[data-testid="stMetricValue"] {
        font-size: 20px;
        font-weight: 700;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 18px;
        border-radius: 4px;
    }
</style>
""", unsafe_allow_html=True)

TAGS_FILE = "strategy_tags.csv"
UNCLASSIFIED = "Não Classificado"
TOTAL_COL = 'Total (inclusive of fees and/or spread)'


# =========================================================
# CLASSIFICAÇÃO POR ESTRATÉGIA (persistência local)
# =========================================================

def load_tags():
    if os.path.exists(TAGS_FILE):
        try:
            t = pd.read_csv(TAGS_FILE, dtype=str)
            if "ID" in t.columns and "Estrategia" in t.columns:
                return t[["ID", "Estrategia"]]
        except Exception:
            pass
    return pd.DataFrame(columns=["ID", "Estrategia"])


def save_tags(tags_df):
    tags_df.drop_duplicates(subset="ID", keep="last").to_csv(TAGS_FILE, index=False)


# =========================================================
# LEITURA DO CSV DA COINBASE
# =========================================================

def parse_coinbase_file(uploaded_file):
    raw_content = uploaded_file.getvalue().decode('utf-8', errors='ignore')
    lines = raw_content.splitlines()

    header_line = 0
    for idx, line in enumerate(lines):
        if 'ID,Timestamp,Transaction Type' in line or 'Timestamp,Transaction Type,Asset' in line:
            header_line = idx
            break

    df = pd.read_csv(io.StringIO(raw_content), skiprows=header_line)
    df.columns = [c.strip() for c in df.columns]

    def to_float(val):
        if pd.isna(val):
            return 0.0
        s = str(val).replace('R$', '').replace('$', '').replace(' ', '').replace(',', '')
        try:
            return float(s)
        except Exception:
            return 0.0

    num_cols = ['Subtotal', TOTAL_COL, 'Fees and/or Spread', 'Price at Transaction', 'Quantity Transacted']
    for c in num_cols:
        if c in df.columns:
            df[c] = df[c].apply(to_float)

    df['Datetime'] = pd.to_datetime(df['Timestamp'].astype(str).str.replace(' UTC', ''), errors='coerce')
    df['Date'] = df['Datetime'].dt.date
    df = df.sort_values('Datetime').reset_index(drop=True)
    return df


# =========================================================
# CÁLCULO DE MÉTRICAS
#
# Todos os valores monetários usam a coluna TOTAL_COL
# ('Total (inclusive of fees and/or spread)'), não o 'Subtotal'.
# É a própria Coinbase quem documenta essa coluna como o efeito
# de caixa líquido de cada lançamento (Subtotal já ajustado por
# fee/spread). Isso evita ter que adivinhar, a partir do sinal do
# Subtotal, o que é fee e o que é resultado de execução, separação
# que os dados exportados não permitem fazer com segurança.
#
# Também são usados regexes mais abrangentes de Transaction Type
# do que na versão anterior:
#   - 'Settlement' (sem exigir o 's' de plural) para pegar tanto
#     'Settlements Of Unrealized P/L (24 Hours)' quanto a variante
#     singular 'Settlement Of Unrealized P/L', que antes ficava de
#     fora do cálculo.
#   - 'Reward' (em vez de só 'Interest Reward') para pegar também
#     'Reward Income', que antes não entrava em nenhuma métrica.
# =========================================================

def compute_metrics(df_perp):
    pnl_df = df_perp[df_perp['Transaction Type'].str.contains('Settlement', case=False, na=False)].copy()
    funding_df = df_perp[df_perp['Transaction Type'].str.contains('Funding', case=False, na=False)].copy()
    exec_df = df_perp[df_perp['Transaction Type'].str.contains('Perpetual Futures Buy|Perpetual Futures Sell', case=False, na=False)].copy()
    reward_df = df_perp[df_perp['Transaction Type'].str.contains('Reward', case=False, na=False)].copy()
    deposits_df = df_perp[df_perp['Transaction Type'].str.contains('Deposit', case=False, na=False)].copy()

    total_pnl = pnl_df[TOTAL_COL].sum()
    gross_profit = pnl_df[pnl_df[TOTAL_COL] > 0][TOTAL_COL].sum()
    gross_loss = pnl_df[pnl_df[TOTAL_COL] < 0][TOTAL_COL].sum()

    total_funding = funding_df[TOTAL_COL].sum()
    funding_received = funding_df[funding_df[TOTAL_COL] > 0][TOTAL_COL].sum()
    funding_paid = funding_df[funding_df[TOTAL_COL] < 0][TOTAL_COL].sum()

    exec_result = exec_df[TOTAL_COL].sum()
    reported_fees = df_perp['Fees and/or Spread'].sum()
    total_rewards = reward_df[TOTAL_COL].sum()

    # Resultado líquido = soma de tudo que não é aporte de capital (depósito).
    net_result = total_pnl + total_funding + total_rewards + exec_result

    total_deposited = deposits_df[deposits_df['Asset'] == 'USDC'][TOTAL_COL].sum()
    if total_deposited == 0:
        total_deposited = deposits_df[TOTAL_COL].sum()
    roi_pct = (net_result / total_deposited * 100) if total_deposited > 0 else 0.0

    win_items = pnl_df[pnl_df[TOTAL_COL] > 0]
    loss_items = pnl_df[pnl_df[TOTAL_COL] < 0]
    total_settlements = len(pnl_df)
    winning_settlements = len(win_items)
    losing_settlements = len(loss_items)
    win_rate = (winning_settlements / total_settlements * 100) if total_settlements > 0 else 0.0
    profit_factor = (abs(gross_profit) / abs(gross_loss)) if abs(gross_loss) > 0 else 0.0

    avg_win = win_items[TOTAL_COL].mean() if len(win_items) > 0 else 0.0
    avg_loss = abs(loss_items[TOTAL_COL].mean()) if len(loss_items) > 0 else 0.0
    payoff = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    return dict(
        pnl_df=pnl_df, funding_df=funding_df, exec_df=exec_df, reward_df=reward_df, deposits_df=deposits_df,
        total_pnl=total_pnl, gross_profit=gross_profit, gross_loss=gross_loss,
        total_funding=total_funding, funding_received=funding_received, funding_paid=funding_paid,
        exec_result=exec_result, reported_fees=reported_fees, total_rewards=total_rewards,
        net_result=net_result, total_deposited=total_deposited, roi_pct=roi_pct,
        win_rate=win_rate, profit_factor=profit_factor, payoff=payoff,
        avg_win=avg_win, avg_loss=avg_loss,
        total_settlements=total_settlements, winning_settlements=winning_settlements, losing_settlements=losing_settlements,
    )


# =========================================================
# DASHBOARD (replicado para "Todas as Estratégias" e para cada
# estratégia individual, cada chamada com seu próprio key_prefix
# para os widgets não colidirem)
# =========================================================

def render_dashboard(df_perp, key_prefix):
    if len(df_perp) == 0:
        st.info("Nenhuma transação encontrada para esta seleção.")
        return

    m = compute_metrics(df_perp)

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("Resultado Líquido", f"R$ {m['net_result']:,.2f}")
    c2.metric("Retorno Total (ROI)", f"{m['roi_pct']:.2f}%", help="Calculado sobre os depósitos efetuados (asset USDC)")
    c3.metric("P&L de Settlements", f"R$ {m['total_pnl']:,.2f}", help=f"Ganhos: R$ {m['gross_profit']:,.2f} | Perdas: R$ {m['gross_loss']:,.2f}")
    c4.metric("Funding Líquido", f"R$ {m['total_funding']:,.2f}", help=f"Crédito: R$ {m['funding_received']:,.2f} | Débito: R$ {m['funding_paid']:,.2f}")
    c5.metric("Resultado das Execuções", f"R$ {m['exec_result']:,.2f}", help="Soma do campo 'Total' de todas as compras/vendas, já líquido de fee/spread. Pode incluir P&L realizado na própria execução, não apenas custo.")
    c6.metric("Rewards", f"R$ {m['total_rewards']:,.2f}", help="Reward Income + Intx Interest Reward")
    c7.metric("Win Rate (Settlements)", f"{m['win_rate']:.1f}%", help=f"Profit Factor: {m['profit_factor']:.2f} | Payoff: {m['payoff']:.2f}")

    st.caption(
        f"Fees e spreads reportados explicitamente pela Coinbase: R$ {m['reported_fees']:,.2f}. "
        "Esse valor já está embutido em 'Resultado das Execuções' acima, pois usamos a coluna "
        "'Total (inclusive of fees and/or spread)'. O Win Rate é calculado sobre lançamentos de "
        "settlement, que agregam várias operações internas cada um (ex.: \"37 items\"), então é uma "
        "aproximação do resultado por período, não um win rate por trade individual."
    )

    st.markdown("---")

    tab_overview, tab_daily, tab_daily_trade, tab_history = st.tabs([
        "📈 Visão Geral & Curva",
        "📅 Performance por Dia (Win / Lost / Execuções)",
        "🔍 Detalhe por Dia & Trade",
        "📋 Histórico Completo & Exportação"
    ])

    # ---------------- ABA 1: VISÃO GERAL ----------------
    with tab_overview:
        col_g1, col_g2 = st.columns(2)

        daily_cum = df_perp[df_perp['Transaction Type'].str.contains('Settlement|Funding|Reward', case=False, na=False)].groupby('Date')[TOTAL_COL].sum().reset_index()
        daily_cum['Cumulative'] = daily_cum[TOTAL_COL].cumsum()

        fig_equity = go.Figure()
        fig_equity.add_trace(go.Scatter(
            x=daily_cum['Date'], y=daily_cum['Cumulative'],
            mode='lines+markers', line=dict(color='#00c076', width=2),
            fill='tozeroy', fillcolor='rgba(0, 192, 118, 0.1)', name='Acumulado (R$)'
        ))
        fig_equity.update_layout(title="Curva de Patrimônio Acumulado (Equity Curve)", height=380, template="plotly_dark")
        col_g1.plotly_chart(fig_equity, use_container_width=True, key=f"{key_prefix}_equity")

        asset_pnl = m['pnl_df'].groupby('Asset')[TOTAL_COL].sum().sort_values(ascending=True)
        colors_asset = ['#00c076' if val >= 0 else '#ff4d4f' for val in asset_pnl.values]
        fig_asset = go.Figure(go.Bar(y=asset_pnl.index, x=asset_pnl.values, orientation='h', marker_color=colors_asset))
        fig_asset.update_layout(title="P&L de Settlements por Ativo Perpétuo (R$)", height=380, template="plotly_dark")
        col_g2.plotly_chart(fig_asset, use_container_width=True, key=f"{key_prefix}_asset_pnl")

        c_r1, c_r2, c_r3, c_r4 = st.columns(4)
        c_r1.metric("Profit Factor", f"{m['profit_factor']:.2f}")
        c_r2.metric("Payoff Ratio (Ganho/Perda)", f"{m['payoff']:.2f}")
        c_r3.metric("Maior Ganho Único (Settlement)", f"R$ {m['pnl_df'][TOTAL_COL].max():,.2f}" if len(m['pnl_df']) > 0 else "R$ 0,00")
        c_r4.metric("Maior Perda Única (Settlement)", f"R$ {m['pnl_df'][TOTAL_COL].min():,.2f}" if len(m['pnl_df']) > 0 else "R$ 0,00")

    # ---------------- ABA 2: PERFORMANCE POR DIA ----------------
    with tab_daily:
        st.subheader("Balanço Diário: Ganhos, Perdas, Execuções, Funding e Rewards")

        daily_pnl = m['pnl_df'].groupby('Date')[TOTAL_COL].agg(
            Ganhos_Win=lambda s: s[s > 0].sum(),
            Perdas_Lost=lambda s: s[s < 0].sum(),
            Qtd_Win=lambda s: (s > 0).sum(),
            Qtd_Lost=lambda s: (s < 0).sum(),
            PnL_Bruto='sum'
        )
        daily_funding = m['funding_df'].groupby('Date')[TOTAL_COL].agg(Funding_Liquido='sum')
        daily_exec = m['exec_df'].groupby('Date')[TOTAL_COL].agg(Resultado_Execucoes='sum')
        daily_rewards = m['reward_df'].groupby('Date')[TOTAL_COL].agg(Rewards='sum')

        daily_table = pd.concat([daily_pnl, daily_funding, daily_exec, daily_rewards], axis=1).fillna(0)
        daily_table['Resultado_Liquido'] = (
            daily_table['PnL_Bruto'] + daily_table['Funding_Liquido']
            + daily_table['Resultado_Execucoes'] + daily_table['Rewards']
        )
        daily_table['Win_Rate_Pct'] = (daily_table['Qtd_Win'] / (daily_table['Qtd_Win'] + daily_table['Qtd_Lost']) * 100).fillna(0)
        daily_table = daily_table.sort_index(ascending=False)

        fig_bar_daily = go.Figure()
        fig_bar_daily.add_trace(go.Bar(x=daily_table.index, y=daily_table['Ganhos_Win'], name='Ganhos (Win)', marker_color='#00c076'))
        fig_bar_daily.add_trace(go.Bar(x=daily_table.index, y=daily_table['Perdas_Lost'], name='Perdas (Lost)', marker_color='#ff4d4f'))
        fig_bar_daily.add_trace(go.Bar(x=daily_table.index, y=daily_table['Resultado_Execucoes'], name='Execuções', marker_color='#ffa940'))
        fig_bar_daily.add_trace(go.Bar(x=daily_table.index, y=daily_table['Funding_Liquido'], name='Funding', marker_color='#2157f3'))
        fig_bar_daily.update_layout(barmode='relative', title="Distribuição Diária: Win vs Lost vs Execuções vs Funding (R$)", height=400, template="plotly_dark")
        st.plotly_chart(fig_bar_daily, use_container_width=True, key=f"{key_prefix}_daily_bar")

        st.markdown("#### Tabela Consolidada por Dia")
        format_dict = {
            'Ganhos_Win': 'R$ {:,.2f}',
            'Perdas_Lost': 'R$ {:,.2f}',
            'Funding_Liquido': 'R$ {:,.2f}',
            'Resultado_Execucoes': 'R$ {:,.2f}',
            'Rewards': 'R$ {:,.2f}',
            'PnL_Bruto': 'R$ {:,.2f}',
            'Resultado_Liquido': 'R$ {:,.2f}',
            'Win_Rate_Pct': '{:.1f}%'
        }
        st.dataframe(daily_table.style.format(format_dict), use_container_width=True, key=f"{key_prefix}_daily_table")

    # ---------------- ABA 3: POR DIA & TRADE ----------------
    with tab_daily_trade:
        st.subheader("Desdobramento das Posições e Trades por Dia e Ativo")

        local_assets = sorted(df_perp['Asset'].dropna().unique().tolist())
        col_sel_asset, col_sel_type = st.columns(2)
        asset_filter = col_sel_asset.selectbox("Filtrar por Ativo Perpétuo", options=["TODOS"] + local_assets, key=f"{key_prefix}_asset_filter")
        type_filter = col_sel_type.multiselect("Filtrar Tipo de Operação", options=df_perp['Transaction Type'].unique(), default=df_perp['Transaction Type'].unique(), key=f"{key_prefix}_type_filter")

        df_filtered_trade = df_perp[df_perp['Transaction Type'].isin(type_filter)].copy()
        if asset_filter != "TODOS":
            df_filtered_trade = df_filtered_trade[df_filtered_trade['Asset'] == asset_filter]

        trade_matrix = df_filtered_trade.groupby(['Date', 'Asset', 'Transaction Type'])[TOTAL_COL].agg(
            Total_BRL='sum',
            Qtd='count'
        ).reset_index().sort_values(['Date', 'Total_BRL'], ascending=[False, True])

        st.dataframe(
            trade_matrix.style.format({'Total_BRL': 'R$ {:,.2f}'}),
            use_container_width=True,
            height=450,
            key=f"{key_prefix}_trade_matrix"
        )

    # ---------------- ABA 4: HISTÓRICO COMPLETO ----------------
    with tab_history:
        st.subheader("Auditoria Completa de Lançamentos")

        csv_buffer = io.StringIO()
        df_perp.to_csv(csv_buffer, index=False)
        st.download_button(
            label="📥 Baixar Dados Filtrados (CSV)",
            data=csv_buffer.getvalue(),
            file_name=f"dados_coinbase_{key_prefix}.csv",
            mime="text/csv",
            key=f"{key_prefix}_download"
        )

        cols_show = ['Timestamp', 'Transaction Type', 'Asset', 'Quantity Transacted', 'Price at Transaction',
                     'Subtotal', TOTAL_COL, 'Fees and/or Spread', 'Estrategia', 'Notes']
        cols_show = [c for c in cols_show if c in df_perp.columns]
        st.dataframe(
            df_perp[cols_show].sort_values('Timestamp', ascending=False),
            use_container_width=True,
            height=500,
            key=f"{key_prefix}_history_table"
        )


# =========================================================
# APLICAÇÃO PRINCIPAL
# =========================================================

st.title("📊 Dashboard de Trades & Futuros Perpétuos (Coinbase)")

with st.sidebar:
    st.header("📂 Arquivo")
    uploaded_file = st.file_uploader("Upload do CSV Coinbase", type=["csv"])

if uploaded_file is not None:
    df_raw = parse_coinbase_file(uploaded_file)

    # --- Classificação por estratégia ---
    tags_df = load_tags()
    df_raw = df_raw.merge(tags_df, on='ID', how='left')
    df_raw['Estrategia'] = df_raw['Estrategia'].fillna(UNCLASSIFIED)

    with st.expander("🏷️ Classificar operações por estratégia", expanded=False):
        st.caption(
            "Atribua uma estratégia a cada operação abaixo. A marcação é salva localmente em "
            f"`{TAGS_FILE}` (na mesma pasta do app) e é mantida quando você subir um CSV novo, "
            "casada pelo ID da transação. Lançamentos de Settlement e Funding são agregados por "
            "período pela própria Coinbase (ex.: \"37 items\"), então só ficam corretamente "
            "atribuídos a uma estratégia se você não estiver operando duas estratégias no mesmo "
            "ativo ao mesmo tempo."
        )
        existing_strategies = sorted([s for s in df_raw['Estrategia'].unique() if s != UNCLASSIFIED])
        if existing_strategies:
            st.caption("Estratégias já usadas: " + ", ".join(existing_strategies))

        editable_cols = ['ID', 'Timestamp', 'Transaction Type', 'Asset', 'Notes', 'Estrategia']
        edited = st.data_editor(
            df_raw[editable_cols].sort_values('Timestamp', ascending=False),
            column_config={
                "ID": st.column_config.TextColumn(disabled=True),
                "Timestamp": st.column_config.TextColumn(disabled=True),
                "Transaction Type": st.column_config.TextColumn(disabled=True),
                "Asset": st.column_config.TextColumn(disabled=True),
                "Notes": st.column_config.TextColumn(disabled=True),
                "Estrategia": st.column_config.TextColumn(help="Digite o nome da estratégia"),
            },
            hide_index=True,
            use_container_width=True,
            height=350,
            key="strategy_editor"
        )

        new_tags = edited[['ID', 'Estrategia']].copy()
        save_tags(new_tags)
        df_raw = df_raw.drop(columns=['Estrategia']).merge(new_tags, on='ID', how='left')
        df_raw['Estrategia'] = df_raw['Estrategia'].fillna(UNCLASSIFIED)

    # --- Filtros globais ---
    min_date = df_raw['Date'].min()
    max_date = df_raw['Date'].max()

    with st.sidebar:
        st.markdown("---")
        st.header("🔍 Filtros Globais")
        date_range = st.date_input("Filtrar por Período", value=(min_date, max_date), min_value=min_date, max_value=max_date)

        all_assets = sorted([a for a in df_raw['Asset'].dropna().unique() if a not in ['USDC', 'BRL']])
        selected_assets = st.multiselect("Filtrar Ativos Perpétuos", options=all_assets, default=all_assets)

    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_d, end_d = date_range
        df = df_raw[(df_raw['Date'] >= start_d) & (df_raw['Date'] <= end_d)].copy()
    else:
        df = df_raw.copy()

    # Preserva USDC/BRL para depósitos e recompensas mesmo se não selecionados como "ativo perpétuo"
    df_perp_all = df[(df['Asset'].isin(selected_assets)) | (df['Asset'].isin(['USDC', 'BRL']))].copy()

    # --- Abas por estratégia ---
    strategies_present = sorted([s for s in df_perp_all['Estrategia'].unique() if s != UNCLASSIFIED])
    has_unclassified = (df_perp_all['Estrategia'] == UNCLASSIFIED).any()

    tab_labels = ["🗂️ Todas as Estratégias"] + strategies_present + ([UNCLASSIFIED] if has_unclassified else [])
    strategy_tabs = st.tabs(tab_labels)

    with strategy_tabs[0]:
        render_dashboard(df_perp_all, key_prefix="todas")

    idx = 1
    for strat in strategies_present:
        with strategy_tabs[idx]:
            safe_key = "".join(ch if ch.isalnum() else "_" for ch in strat)
            render_dashboard(df_perp_all[df_perp_all['Estrategia'] == strat], key_prefix=safe_key)
        idx += 1

    if has_unclassified:
        with strategy_tabs[idx]:
            render_dashboard(df_perp_all[df_perp_all['Estrategia'] == UNCLASSIFIED], key_prefix="nao_classificado")

else:
    st.info("👈 Faça o upload do arquivo CSV exportado da Coinbase na barra lateral para carregar e visualizar os dados.")
