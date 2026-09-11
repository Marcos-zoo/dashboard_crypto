import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

st.set_page_config(
    page_title="Dashboard Coinbase Perpetuals",
    page_icon="⚡",
    layout="wide"
)

# Estilização CSS customizada
st.markdown("""
<style>
    div[data-testid="stMetricValue"] {
        font-size: 22px;
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
        except:
            return 0.0

    num_cols = ['Subtotal', 'Total (inclusive of fees and/or spread)', 'Fees and/or Spread', 'Price at Transaction', 'Quantity Transacted']
    for c in num_cols:
        if c in df.columns:
            df[c] = df[c].apply(to_float)

    df['Datetime'] = pd.to_datetime(df['Timestamp'].astype(str).str.replace(' UTC', ''), errors='coerce')
    df['Date'] = df['Datetime'].dt.date
    df = df.sort_values('Datetime').reset_index(drop=True)
    return df

st.title("📊 Dashboard de Trades & Futuros Perpétuos (Coinbase)")

with st.sidebar:
    st.header("📂 Arquivo")
    uploaded_file = st.file_uploader("Upload do CSV Coinbase", type=["csv"])

if uploaded_file is not None:
    df_raw = parse_coinbase_file(uploaded_file)
    
    # Filtros na Sidebar
    min_date = df_raw['Date'].min()
    max_date = df_raw['Date'].max()
    
    with st.sidebar:
        st.markdown("---")
        st.header("🔍 Filtros Globais")
        date_range = st.date_input("Filtrar por Período", value=(min_date, max_date), min_value=min_date, max_value=max_date)
        
        all_assets = sorted([a for a in df_raw['Asset'].dropna().unique() if a not in ['USDC', 'BRL']])
        selected_assets = st.multiselect("Filtrar Ativos Perpétuos", options=all_assets, default=all_assets)

    # Aplicação dos filtros
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_d, end_d = date_range
        df = df_raw[(df_raw['Date'] >= start_d) & (df_raw['Date'] <= end_d)].copy()
    else:
        df = df_raw.copy()

    # Filtro de ativos (mantendo USDC/BRL para depósitos/juros)
    df_perp = df[(df['Asset'].isin(selected_assets)) | (df['Asset'].isin(['USDC', 'BRL']))].copy()

    # Cálculos contábeis
    pnl_df = df_perp[df_perp['Transaction Type'].str.contains('Settlements Of Unrealized P/L', case=False, na=False)].copy()
    funding_df = df_perp[df_perp['Transaction Type'].str.contains('Funding', case=False, na=False)].copy()
    exec_df = df_perp[df_perp['Transaction Type'].str.contains('Perpetual Futures Buy|Perpetual Futures Sell', case=False, na=False)].copy()
    reward_df = df_perp[df_perp['Transaction Type'].str.contains('Interest Reward', case=False, na=False)].copy()
    deposits_df = df_perp[df_perp['Transaction Type'].str.contains('Deposit', case=False, na=False)].copy()

    total_pnl = pnl_df['Subtotal'].sum()
    gross_profit = pnl_df[pnl_df['Subtotal'] > 0]['Subtotal'].sum()
    gross_loss = pnl_df[pnl_df['Subtotal'] < 0]['Subtotal'].sum()
    
    total_funding = funding_df['Subtotal'].sum()
    funding_received = funding_df[funding_df['Subtotal'] > 0]['Subtotal'].sum()
    funding_paid = funding_df[funding_df['Subtotal'] < 0]['Subtotal'].sum()

    trading_fees = exec_df[exec_df['Subtotal'] < 0]['Subtotal'].abs().sum() + df_perp['Fees and/or Spread'].sum()
    total_rewards = reward_df['Subtotal'].sum()
    net_result = total_pnl + total_funding + total_rewards - trading_fees

    # Cálculo de Retorno % sobre o Capital Depositado
    total_deposited = deposits_df[deposits_df['Asset'] == 'USDC']['Subtotal'].sum()
    if total_deposited == 0:
        total_deposited = deposits_df['Subtotal'].sum()
    roi_pct = (net_result / total_deposited * 100) if total_deposited > 0 else 0.0

    # Win Rate & Payoff
    win_items = pnl_df[pnl_df['Subtotal'] > 0]
    loss_items = pnl_df[pnl_df['Subtotal'] < 0]
    total_settlements = len(pnl_df)
    winning_settlements = len(win_items)
    losing_settlements = len(loss_items)
    win_rate = (winning_settlements / total_settlements * 100) if total_settlements > 0 else 0.0
    profit_factor = (abs(gross_profit) / abs(gross_loss)) if abs(gross_loss) > 0 else 0.0
    
    avg_win = win_items['Subtotal'].mean() if len(win_items) > 0 else 0.0
    avg_loss = abs(loss_items['Subtotal'].mean()) if len(loss_items) > 0 else 0.0
    payoff = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    # Linha 1: Métricas Principais
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Resultado Líquido", f"R$ {net_result:,.2f}", delta=f"{net_result:,.2f}")
    c2.metric("Retorno Total (ROI)", f"{roi_pct:.2f}%", delta=f"{roi_pct:.2f}%", help="Calculado sobre os depósitos efetuados")
    c3.metric("P&L Realizado", f"R$ {total_pnl:,.2f}", help=f"Ganhos: R$ {gross_profit:,.2f} | Perdas: R$ {gross_loss:,.2f}")
    c4.metric("Funding Líquido", f"R$ {total_funding:,.2f}", help=f"Crédito: R$ {funding_received:,.2f} | Débito: R$ {funding_paid:,.2f}")
    c5.metric("Fees Totais (Corretagem)", f"R$ {trading_fees:,.2f}")
    c6.metric("Win Rate", f"{win_rate:.1f}%", help=f"Profit Factor: {profit_factor:.2f} | Payoff: {payoff:.2f}")

    st.markdown("---")

    # Sistema de Abas
    tab_overview, tab_daily, tab_daily_trade, tab_history = st.tabs([
        "📈 Visão Geral & Curva",
        "📅 Performance por Dia (Win / Lost / Fees)",
        "🔍 Detalhe por Dia & Trade",
        "📋 Histórico Completo & Exportação"
    ])

    # ================= ABA 1: VISÃO GERAL =================
    with tab_overview:
        col_g1, col_g2 = st.columns(2)

        # Equity Curve
        daily_cum = df_perp[df_perp['Transaction Type'].str.contains('Settlements|Funding|Interest Reward', case=False, na=False)].groupby('Date')['Subtotal'].sum().reset_index()
        daily_cum['Cumulative'] = daily_cum['Subtotal'].cumsum()

        fig_equity = go.Figure()
        fig_equity.add_trace(go.Scatter(
            x=daily_cum['Date'], y=daily_cum['Cumulative'],
            mode='lines+markers', line=dict(color='#00c076', width=2),
            fill='tozeroy', fillcolor='rgba(0, 192, 118, 0.1)', name='Acumulado (R$)'
        ))
        fig_equity.update_layout(title="Curva de Patrimônio Acumulado (Equity Curve)", height=380, template="plotly_dark")
        col_g1.plotly_chart(fig_equity, use_container_width=True)

        # Gráfico de P&L por Ativo
        asset_pnl = pnl_df.groupby('Asset')['Subtotal'].sum().sort_values(ascending=True)
        colors_asset = ['#00c076' if val >= 0 else '#ff4d4f' for val in asset_pnl.values]
        fig_asset = go.Figure(go.Bar(y=asset_pnl.index, x=asset_pnl.values, orientation='h', marker_color=colors_asset))
        fig_asset.update_layout(title="P&L Consolidado por Ativo Perpétuo (R$)", height=380, template="plotly_dark")
        col_g2.plotly_chart(fig_asset, use_container_width=True)

        # Métricas de Risco Adicionais
        c_r1, c_r2, c_r3, c_r4 = st.columns(4)
        c_r1.metric("Profit Factor", f"{profit_factor:.2f}")
        c_r2.metric("Payoff Ratio (Ganho/Perda)", f"{payoff:.2f}")
        c_r3.metric("Maior Ganho Único", f"R$ {pnl_df['Subtotal'].max():,.2f}" if len(pnl_df) > 0 else "R$ 0,00")
        c_r4.metric("Maior Perda Única", f"R$ {pnl_df['Subtotal'].min():,.2f}" if len(pnl_df) > 0 else "R$ 0,00")

    # ================= ABA 2: PERFORMANCE POR DIA =================
    with tab_daily:
        st.subheader("Balanço Diário: Ganhos, Perdas, Taxas de Funding e Corretagem")

        # Agrupamento Diário
        daily_pnl = pnl_df.groupby('Date')['Subtotal'].agg(
            Ganhos_Win = lambda s: s[s > 0].sum(),
            Perdas_Lost = lambda s: s[s < 0].sum(),
            Qtd_Win = lambda s: (s > 0).sum(),
            Qtd_Lost = lambda s: (s < 0).sum(),
            PnL_Bruto = 'sum'
        )

        daily_funding = funding_df.groupby('Date')['Subtotal'].agg(Funding_Liquido='sum')
        daily_fees = exec_df.groupby('Date')['Subtotal'].agg(Trading_Fees = lambda s: s[s < 0].abs().sum())

        daily_table = pd.concat([daily_pnl, daily_funding, daily_fees], axis=1).fillna(0)
        daily_table['Resultado_Liquido'] = daily_table['PnL_Bruto'] + daily_table['Funding_Liquido'] - daily_table['Trading_Fees']
        daily_table['Win_Rate_%'] = (daily_table['Qtd_Win'] / (daily_table['Qtd_Win'] + daily_table['Qtd_Lost']) * 100).fillna(0)
        daily_table = daily_table.sort_index(ascending=False)

        # Gráfico diário comparativo
        fig_bar_daily = go.Figure()
        fig_bar_daily.add_trace(go.Bar(x=daily_table.index, y=daily_table['Ganhos_Win'], name='Ganhos (Win)', marker_color='#00c076'))
        fig_bar_daily.add_trace(go.Bar(x=daily_table.index, y=daily_table['Perdas_Lost'], name='Perdas (Lost)', marker_color='#ff4d4f'))
        fig_bar_daily.add_trace(go.Bar(x=daily_table.index, y=-daily_table['Trading_Fees'], name='Fees Cobrados', marker_color='#ffa940'))
        fig_bar_daily.update_layout(barmode='relative', title="Distribuição Diária: Win vs Lost vs Fees (R$)", height=400, template="plotly_dark")
        st.plotly_chart(fig_bar_daily, use_container_width=True)

        # Tabela formatada
        st.markdown("#### Tabela Consolidada por Dia")
        format_dict = {
            'Ganhos_Win': 'R$ {:,.2f}',
            'Perdas_Lost': 'R$ {:,.2f}',
            'Funding_Liquido': 'R$ {:,.2f}',
            'Trading_Fees': 'R$ {:,.2f}',
            'PnL_Bruto': 'R$ {:,.2f}',
            'Resultado_Liquido': 'R$ {:,.2f}',
            'Win_Rate_%': '{:.1f}%'
        }
        st.dataframe(daily_table.style.format(format_dict), use_container_width=True)

    # ================= ABA 3: POR DIA & TRADE =================
    with tab_daily_trade:
        st.subheader("Desdobramento das Posições e Trades por Dia e Ativo")

        # Filtro de Ativo específico nesta aba
        col_sel_asset, col_sel_type = st.columns(2)
        asset_filter = col_sel_asset.selectbox("Filtrar por Ativo Perpétuo", options=["TODOS"] + all_assets)
        type_filter = col_sel_type.multiselect("Filtrar Tipo de Operação", options=df_perp['Transaction Type'].unique(), default=df_perp['Transaction Type'].unique())

        df_filtered_trade = df_perp[df_perp['Transaction Type'].isin(type_filter)].copy()
        if asset_filter != "TODOS":
            df_filtered_trade = df_filtered_trade[df_filtered_trade['Asset'] == asset_filter]

        # Resumo Matricial por Dia x Ativo
        trade_matrix = df_filtered_trade.groupby(['Date', 'Asset', 'Transaction Type'])['Subtotal'].agg(
            Total_R$ = 'sum',
            Qtd = 'count'
        ).reset_index().sort_values(['Date', 'Total_R$'], ascending=[False, True])

        st.dataframe(
            trade_matrix.style.format({'Total_R$': 'R$ {:,.2f}'}),
            use_container_width=True,
            height=450
        )

    # ================= ABA 4: HISTÓRICO COMPLETO & DOWNLOAD =================
    with tab_history:
        st.subheader("Auditoria Completa de Lançamentos")
        
        # Botão de download do CSV tratado
        csv_buffer = io.StringIO()
        df_perp.to_csv(csv_buffer, index=False)
        st.download_button(
            label="📥 Baixar Dados Filtrados (CSV)",
            data=csv_buffer.getvalue(),
            file_name="dados_coinbase_filtrados.csv",
            mime="text/csv"
        )

        cols_show = ['Timestamp', 'Transaction Type', 'Asset', 'Quantity Transacted', 'Price at Transaction', 'Subtotal', 'Fees and/or Spread', 'Notes']
        st.dataframe(df_perp[cols_show].sort_values('Timestamp', ascending=False), use_container_width=True, height=500)

else:
    st.info("👈 Faça o upload do arquivo CSV exportado da Coinbase na barra lateral para carregar e visualizar os dados.")
