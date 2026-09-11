import sys
import os
import re
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

def parse_coinbase_csv(filepath):
    # Detect header row dynamically
    header_line = None
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for idx, line in enumerate(f):
            if 'ID,Timestamp,Transaction Type' in line or 'Timestamp,Transaction Type,Asset' in line:
                header_line = idx
                break
    if header_line is None:
        header_line = 0

    df = pd.read_csv(filepath, skiprows=header_line)
    
    # Standardize column names
    df.columns = [c.strip() for c in df.columns]
    
    # Parse numbers
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

    # Clean Timestamp
    df['Datetime'] = pd.to_datetime(df['Timestamp'].astype(str).str.replace(' UTC', ''), errors='coerce')
    df['Date'] = df['Datetime'].dt.date
    df = df.sort_values('Datetime').reset_index(drop=True)

    # Categorize cash flows & trades
    # In Coinbase Perp statement:
    # 'Settlements Of Unrealized P/L (24 Hours)': PnL Realized
    # 'Funding Fees (24 Hours)' / 'Funding Fee': Funding Fee
    # 'Perpetual Futures Buy' / 'Perpetual Futures Sell': Executions (Subtotal is fee/debit in BRL)
    # 'Intx Interest Reward': Staking/Yield reward
    # 'Perpetual Futures Deposit' / 'Deposit' / 'Receive': Deposits
    # 'Perpetual Futures Withdrawal': Withdrawals

    return df

def generate_dashboard(df, output_html='dashboard_trades.html'):
    # Calculations
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
    win_rate = (winning_settlements / total_settlements * 100) if total_settlements > 0 else 0
    profit_factor = (abs(gross_profit) / abs(gross_loss)) if abs(gross_loss) > 0 else np.nan

    # Daily performance aggregation
    daily = df[df['Transaction Type'].str.contains('Settlements|Funding|Interest Reward', case=False, na=False)].groupby('Date')['Subtotal'].sum().reset_index()
    daily['Cumulative'] = daily['Subtotal'].cumsum()

    # Asset performance
    asset_pnl = pnl_df.groupby('Asset')['Subtotal'].sum().sort_values(ascending=True)
    asset_funding = funding_df.groupby('Asset')['Subtotal'].sum().sort_values(ascending=True)

    # Figures using Plotly
    # 1. Equity Curve
    fig_equity = go.Figure()
    fig_equity.add_trace(go.Scatter(
        x=daily['Date'], y=daily['Cumulative'],
        mode='lines+markers',
        line=dict(color='#00c076', width=2.5),
        fill='tozeroy',
        fillcolor='rgba(0, 192, 118, 0.08)',
        name='Resultado Acumulado (R$)',
        hovertemplate='Data: %{x}<br>Acumulado: R$ %{y:.2f}<extra></extra>'
    ))
    fig_equity.update_layout(
        title='<b>Curva de Equity Acumulada (P&L + Funding + Rewards)</b>',
        paper_bgcolor='#131722', plot_bgcolor='#1e222d',
        font=dict(color='#d1d4dc', family='Segoe UI, sans-serif'),
        xaxis=dict(gridcolor='#2a2e39', title='Data'),
        yaxis=dict(gridcolor='#2a2e39', title='Saldo (R$)'),
        margin=dict(l=40, r=30, t=50, b=40)
    )

    # 2. Daily P&L Bars
    colors = ['#00c076' if val >= 0 else '#ff4d4f' for val in daily['Subtotal']]
    fig_daily = go.Figure()
    fig_daily.add_trace(go.Bar(
        x=daily['Date'], y=daily['Subtotal'],
        marker_color=colors,
        name='P&L Diário (R$)',
        hovertemplate='Data: %{x}<br>Resultado: R$ %{y:.2f}<extra></extra>'
    ))
    fig_daily.update_layout(
        title='<b>Resultado Líquido por Dia (R$)</b>',
        paper_bgcolor='#131722', plot_bgcolor='#1e222d',
        font=dict(color='#d1d4dc', family='Segoe UI, sans-serif'),
        xaxis=dict(gridcolor='#2a2e39'),
        yaxis=dict(gridcolor='#2a2e39', title='R$'),
        margin=dict(l=40, r=30, t=50, b=40)
    )

    # 3. P&L by Asset
    fig_asset = go.Figure()
    bar_colors = ['#00c076' if val >= 0 else '#ff4d4f' for val in asset_pnl.values]
    fig_asset.add_trace(go.Bar(
        y=asset_pnl.index, x=asset_pnl.values,
        orientation='h',
        marker_color=bar_colors,
        hovertemplate='Ativo: %{y}<br>P&L: R$ %{x:.2f}<extra></extra>'
    ))
    fig_asset.update_layout(
        title='<b>P&L Líquido por Ativo Perpétuo (R$)</b>',
        paper_bgcolor='#131722', plot_bgcolor='#1e222d',
        font=dict(color='#d1d4dc', family='Segoe UI, sans-serif'),
        xaxis=dict(gridcolor='#2a2e39', title='P&L (R$)'),
        yaxis=dict(gridcolor='#2a2e39'),
        margin=dict(l=80, r=30, t=50, b=40)
    )

    # 4. Funding by Asset
    fig_fund = go.Figure()
    fund_colors = ['#2962ff' if val >= 0 else '#e91e63' for val in asset_funding.values]
    fig_fund.add_trace(go.Bar(
        y=asset_funding.index, x=asset_funding.values,
        orientation='h',
        marker_color=fund_colors,
        hovertemplate='Ativo: %{y}<br>Funding: R$ %{x:.2f}<extra></extra>'
    ))
    fig_fund.update_layout(
        title='<b>Taxas de Financiamento (Funding) por Ativo (R$)</b>',
        paper_bgcolor='#131722', plot_bgcolor='#1e222d',
        font=dict(color='#d1d4dc', family='Segoe UI, sans-serif'),
        xaxis=dict(gridcolor='#2a2e39', title='Funding (R$)'),
        yaxis=dict(gridcolor='#2a2e39'),
        margin=dict(l=80, r=30, t=50, b=40)
    )

    # Build Table rows
    table_rows = ""
    # Latest 100 transactions
    for _, row in df.tail(150).iloc[::-1].iterrows():
        val = row['Subtotal']
        val_color = '#00c076' if val > 0 else ('#ff4d4f' if val < 0 else '#868993')
        ts_str = str(row['Timestamp']).replace(' UTC', '')
        note_str = str(row['Notes']) if pd.notna(row['Notes']) else '-'
        table_rows += f"""
        <tr>
            <td>{ts_str}</td>
            <td><span class="badge">{row['Transaction Type']}</span></td>
            <td><strong>{row['Asset']}</strong></td>
            <td style="color:{val_color}; font-weight:600;">R$ {val:,.2f}</td>
            <td class="notes-col">{note_str}</td>
        </tr>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard de Trades & Futuros Perpétuos</title>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        :root {{
            --bg-main: #0c0d14;
            --bg-card: #141722;
            --border: #232738;
            --text: #e1e4ea;
            --text-muted: #848e9c;
            --green: #00c076;
            --red: #ff4d4f;
            --blue: #2962ff;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background-color: var(--bg-main);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            padding: 24px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 24px;
        }}
        .header h1 {{ font-size: 22px; font-weight: 700; color: #fff; }}
        .header p {{ font-size: 13px; color: var(--text-muted); margin-top: 4px; }}
        .grid-kpis {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .kpi-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px 20px;
        }}
        .kpi-title {{ font-size: 12px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.5px; }}
        .kpi-value {{ font-size: 22px; font-weight: 700; margin-top: 8px; }}
        .kpi-sub {{ font-size: 11px; color: var(--text-muted); margin-top: 4px; }}
        .text-green {{ color: var(--green); }}
        .text-red {{ color: var(--red); }}
        .text-blue {{ color: var(--blue); }}
        
        .grid-charts {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 20px;
            margin-bottom: 24px;
        }}
        .chart-box {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            min-height: 400px;
        }}
        .table-section {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 20px;
        }}
        .table-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }}
        .search-box {{
            background: #1e2230;
            border: 1px solid var(--border);
            color: #fff;
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 13px;
            outline: none;
            width: 260px;
        }}
        .table-wrapper {{
            overflow-x: auto;
            max-height: 480px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            text-align: left;
        }}
        th {{
            background: #181b28;
            color: var(--text-muted);
            padding: 12px 14px;
            font-weight: 600;
            position: sticky;
            top: 0;
            border-bottom: 1px solid var(--border);
        }}
        td {{
            padding: 10px 14px;
            border-bottom: 1px solid #1a1e2c;
        }}
        tr:hover td {{ background: rgba(255,255,255,0.02); }}
        .badge {{
            background: #202638;
            color: #90a0b7;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 500;
        }}
        .notes-col {{
            max-width: 380px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            color: var(--text-muted);
        }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>Dashboard de Operações & Perpétuos</h1>
            <p>Análise de Performance, Financiamento e Histórico de Ordens</p>
        </div>
        <div>
            <span class="badge" style="font-size: 12px; padding: 6px 12px;">Total de Lançamentos: {len(df)}</span>
        </div>
    </div>

    <!-- KPIs -->
    <div class="grid-kpis">
        <div class="kpi-card">
            <div class="kpi-title">Resultado Líquido Geral</div>
            <div class="kpi-value {'text-green' if net_result >= 0 else 'text-red'}">R$ {net_result:,.2f}</div>
            <div class="kpi-sub">P&L + Funding + Rendimentos - Taxas</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">P&L Realizado (Settlements)</div>
            <div class="kpi-value {'text-green' if total_pnl >= 0 else 'text-red'}">R$ {total_pnl:,.2f}</div>
            <div class="kpi-sub">Ganhos: R$ {gross_profit:,.2f} | Perdas: R$ {gross_loss:,.2f}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Taxas de Funding Líquidas</div>
            <div class="kpi-value {'text-green' if total_funding >= 0 else 'text-red'}">R$ {total_funding:,.2f}</div>
            <div class="kpi-sub">Crédito: R$ {funding_received:,.2f} | Débito: R$ {funding_paid:,.2f}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Taxas Operacionais (Fees)</div>
            <div class="kpi-value text-red">R$ {trading_fees:,.2f}</div>
            <div class="kpi-sub">Corretagens & Spreads de Execução</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Juros & Rendimentos (Intx)</div>
            <div class="kpi-value text-blue">R$ {total_rewards:,.2f}</div>
            <div class="kpi-sub">Recompensas de Saldo USDC</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Win Rate (Settlements Diários)</div>
            <div class="kpi-value">{win_rate:.1f}%</div>
            <div class="kpi-sub">{winning_settlements} Positivos / {losing_settlements} Negativos</div>
        </div>
    </div>

    <!-- Gráficos -->
    <div class="grid-charts">
        <div class="chart-box" id="equity-chart"></div>
        <div class="chart-box" id="daily-chart"></div>
        <div class="chart-box" id="asset-chart"></div>
        <div class="chart-box" id="fund-chart"></div>
    </div>

    <!-- Tabela -->
    <div class="table-section">
        <div class="table-header">
            <h3>Histórico Recente de Transações</h3>
            <input type="text" id="searchInput" class="search-box" placeholder="Buscar ativo, tipo ou data..." onkeyup="filterTable()">
        </div>
        <div class="table-wrapper">
            <table id="transactionsTable">
                <thead>
                    <tr>
                        <th>Data / Hora</th>
                        <th>Tipo</th>
                        <th>Ativo</th>
                        <th>Valor (Subtotal)</th>
                        <th>Detalhes / Notas</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        // Render Plotly charts
        Plotly.newPlot('equity-chart', {fig_equity.to_json()}['data'], {fig_equity.to_json()}['layout'], {{responsive: true}});
        Plotly.newPlot('daily-chart', {fig_daily.to_json()}['data'], {fig_daily.to_json()}['layout'], {{responsive: true}});
        Plotly.newPlot('asset-chart', {fig_asset.to_json()}['data'], {fig_asset.to_json()}['layout'], {{responsive: true}});
        Plotly.newPlot('fund-chart', {fig_fund.to_json()}['data'], {fig_fund.to_json()}['layout'], {{responsive: true}});

        // Filter Table Script
        function filterTable() {{
            const input = document.getElementById("searchInput").value.toLowerCase();
            const rows = document.querySelectorAll("#transactionsTable tbody tr");
            rows.forEach(row => {{
                const text = row.innerText.toLowerCase();
                row.style.display = text.includes(input) ? "" : "none";
            }});
        }}
    </script>
</body>
</html>
"""
    with open(output_html, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"Sucesso! Gerado {output_html}")

if __name__ == '__main__':
    csv_file = sys.argv[1] if len(sys.argv) > 1 else '97aa8213-fa9c-50d2-be01-808296b8933c_2026_57a3e4bc-fcc4-5862-a68d-f10c78df08c4__csv.csv'
    out = sys.argv[2] if len(sys.argv) > 2 else 'dashboard_trades.html'
    df = parse_coinbase_csv(csv_file)
    generate_dashboard(df, out)
