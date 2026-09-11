import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

st.set_page_config(
    page_title="Dashboard Coinbase Perpetuals",
    page_icon="📈",
    layout="wide"
)

st.markdown("""
<style>
    .metric-card {
        background-color: #1a1e29;
        border: 1px solid #2d3343;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 10px;
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
    st.header("Entrada de Dados")
    uploaded_file = st.file_uploader("Selecione o arquivo CSV da Coinbase", type=["csv"])

if uploaded_file is not None:
    df = parse_coinbase_file(uploaded_file)
    
    # Cálculos
    pnl_df = df[df['Transaction Type'].str.contains('Settlements Of Unrealized P/L', case=False, na=False)].copy()
    funding_df = df[df['Transaction Type'].str.contains('Funding', case=False, na=False)].copy()
    exec_df = df[df['Transaction Type'].str.contains('Perpetual Futures Buy|Perpetual Futures Sell', case=False, na=False)].copy()
    reward_df = df[df['Transaction Type'].str.contains('Interest Reward', case=False, na=False)].copy()

    total_pnl = pnl_df['Subtotal'].sum()
    gross_profit = pnl_df[pnl_df['Subtotal'] > 0]['Subtotal'].sum()
    gross_loss = pnl_df[pnl_df['Subtotal'] < 0]['Subtotal'].sum()
    
    total_funding = funding_df['Subtotal'].sum()
    funding_received = funding_df[funding_df['Subtotal'] > 0]['Subtotal'].sum()
    funding_paid = funding_df[funding_df['Subtotal'] < 0]['Subtotal'].sum()

    trading_fees = exec_df[exec_df['Subtotal'] < 0]['Subtotal'].abs().sum() + df['Fees and/or Spread'].sum()
    total_rewards = reward_df['Subtotal'].sum()
    net_result = total_pnl + total_funding + total_rewards - trading_fees

    total_settlements = len(pnl_df)
    winning_settlements = len(pnl_df[pnl_df['Subtotal'] > 0])
    losing_settlements = len(pnl_df[pnl_df['Subtotal'] < 0])
    win_rate = (winning_settlements / total_settlements * 100) if total_settlements > 0 else 0.0

    # KPIs Cards
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Resultado Líquido", f"R$ {net_result:,.2f}", delta=f"{net_result:,.2f}")
    c2.metric("P&L Realizado", f"R$ {total_pnl:,.2f}", help=f"Ganhos: R$ {gross_profit:,.2f} | Perdas: R$ {gross_loss:,.2f}")
    c3.metric("Funding Líquido", f"R$ {total_funding:,.2f}", help=f"Crédito: R$ {funding_received:,.2f} | Débito: R$ {funding_paid:,.2f}")
    c4.metric("Fees Operacionais", f"R$ {trading_fees:,.2f}")
    c5.metric("Juros / Intx", f"R$ {total_rewards:,.2f}")
    c6.metric("Win Rate Settlements", f"{win_rate:.1f}%", help=f"{winning_settlements} W / {losing_settlements} L")

    # Gráficos
    st.markdown("---")
    col_g1, col_g2 = st.columns(2)

    # 1. Equity Curve
    daily = df[df['Transaction Type'].str.contains('Settlements|Funding|Interest Reward', case=False, na=False)].groupby('Date')['Subtotal'].sum().reset_index()
    daily['Cumulative'] = daily['Subtotal'].cumsum()

    fig_equity = go.Figure()
    fig_equity.add_trace(go.Scatter(
        x=daily['Date'], y=daily['Cumulative'],
        mode='lines+markers', line=dict(color='#00c076', width=2),
        fill='tozeroy', fillcolor='rgba(0, 192, 118, 0.1)', name='Acumulado (R$)'
    ))
    fig_equity.update_layout(title="Curva de Patrimônio Acumulado (Equity Curve)", height=380, template="plotly_dark")
    col_g1.plotly_chart(fig_equity, use_container_width=True)

    # 2. P&L Diário
    colors_daily = ['#00c076' if val >= 0 else '#ff4d4f' for val in daily['Subtotal']]
    fig_daily = go.Figure()
    fig_daily.add_trace(go.Bar(x=daily['Date'], y=daily['Subtotal'], marker_color=colors_daily, name='P&L Diário'))
    fig_daily.update_layout(title="Resultado Líquido por Dia (R$)", height=380, template="plotly_dark")
    col_g2.plotly_chart(fig_daily, use_container_width=True)

    col_g3, col_g4 = st.columns(2)

    # 3. P&L por Ativo
    asset_pnl = pnl_df.groupby('Asset')['Subtotal'].sum().sort_values(ascending=True)
    colors_asset = ['#00c076' if val >= 0 else '#ff4d4f' for val in asset_pnl.values]
    fig_asset = go.Figure(go.Bar(y=asset_pnl.index, x=asset_pnl.values, orientation='h', marker_color=colors_asset))
    fig_asset.update_layout(title="P&L por Ativo Perpétuo (R$)", height=380, template="plotly_dark")
    col_g3.plotly_chart(fig_asset, use_container_width=True)

    # 4. Funding por Ativo
    asset_fund = funding_df.groupby('Asset')['Subtotal'].sum().sort_values(ascending=True)
    colors_fund = ['#2962ff' if val >= 0 else '#e91e63' for val in asset_fund.values]
    fig_fund = go.Figure(go.Bar(y=asset_fund.index, x=asset_fund.values, orientation='h', marker_color=colors_fund))
    fig_fund.update_layout(title="Funding Recebido/Pago por Ativo (R$)", height=380, template="plotly_dark")
    col_g4.plotly_chart(fig_fund, use_container_width=True)

    # Tabela com busca nativa
    st.markdown("---")
    st.subheader("Histórico Detalhado de Lançamentos")
    cols_show = ['Timestamp', 'Transaction Type', 'Asset', 'Quantity Transacted', 'Price at Transaction', 'Subtotal', 'Notes']
    st.dataframe(df[cols_show].iloc[::-1], use_container_width=True, height=400)

else:
    st.info("👈 Faça o upload do arquivo CSV exportado da Coinbase na barra lateral para carregar os dados.")
