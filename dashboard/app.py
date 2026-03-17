# dashboard/app.py - Ultimate Advanced Dashboard: WebSocket live, candlesticks, geo alerts, full UI
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import asyncio
import websockets
import json
import threading

# WebSocket URL - assume your engine broadcasts here (add ws server in engine.py if needed)
WS_URL = "ws://localhost:8765"  # change to your real ws endpoint

st.set_page_config(page_title="HOPEFX Pro", layout="wide", initial_sidebar_state="collapsed")

# Ultra-dark, modern theme
st.markdown("""
    <style> { background-color: #0a0e14; color: #e6e6e6; }
    .stSidebar { background-color: #12161f; border-right: 1px solid #2a2f3a; }
    .metric-box { background: #1e232c; border-radius: 12px; padding: 20px; margin: 12px 0; box-shadow: 0 8px 16px rgba(0,0,0,0.5); }
    .alert-high { background: #3a1a1a; border-left: 5px solid #ff4d4d; padding: 12px; border-radius: 6px; }
    .buy-signal { color: #00ff9d; font-weight: bold; }
    .sell-signal { color: #ff3366; font-weight: bold; }
    .hold-signal { color: #ffd700; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

st.title("HOPEFX Pro Dashboard")
st.caption("Real-Time XAUUSD • AI Brain Decisions • Geo Risk • WebSocket Powered • 2026 Edition")

# Layout: Chart + Sidebar + Status
col_chart, col_side = st.columns([4, 1])

with col_chart:
    st.subheader("Live Candlestick - XAUUSD")
    chart_placeholder = st.empty()

with col_side:
    st.subheader("AI & Risk Status")
    status_placeholder = st.empty()
    alert_placeholder = st.empty()

# Data buffer for candlesticks (OHLCV)
data_buffer = pd.DataFrame(columns=['time', 'open', 'high', 'low', 'close', 'volume'])

async def ws_listener():
    global data_buffer
    try:
        async with websockets.connect(WS_URL) as ws:
            while True:
                msg = await ws.recv()
                tick = json.loads(msg)
                # Expected: {"time": ts, "price": p, "action": "buy", "geo": 68, "conf": 0.92, "drawdown": 0.02}
                # For candlestick - aggregate into 1-min OHLC if needed
                new_row = {
                    'time': datetime.fromisoformat(tick ),
                    'open': tick ,
                    'high': tick['price'] + 2,  # sim; use real if aggregated
                    'low': tick - 2,
                    'close': tick ,
                    'volume': tick.get('volume', 100)
                }
                data_buffer = pd.concat( )], ignore_index=True).tail(200)

                # Update chart
                fig = go.Figure(data=[go.Candlestick(
                    x=data_buffer ,
                    open=data_buffer ,
                    high=data_buffer ,
                    low=data_buffer ,
                    close=data_buffer ,
                    increasing_line_color='#00ff9d', decreasing_line_color='#ff3366'
                )])
                fig.update_layout(
                    template='plotly_dark', height=600, margin=dict(l=0,r=0,t=30,b=0),
                    xaxis_rangeslider_visible=True, title="Live Gold Spot"
                )
                chart_placeholder.plotly_chart(fig, use_container_width=True)

                # Update status
                action = tick color_class = "buy-signal" if action == "buy" else "sell-signal" if action == "sell" else "hold-signal"
                status_placeholder.markdown(f"""
                    <div class="metric-box">
                        <h2 class="{color_class}">{action.upper()}</h2>
                        <p>Confidence: {tick *100:.0f}%</p>
                        <p>Geo Risk: {tick }%</p>
                        <p>Drawdown: {tick *100:.1f}%</p>
                        <p>Updated: {datetime.now().strftime('%H:%M:%S')}</p>
                    </div>
                """, unsafe_allow_html=True)

                # Alert if high geo
                if tick > 70:
                    alert_placeholder.error("⚠️ HIGH GEO RISK - HOLD MODE ACTIVE")
                else:
                    alert_placeholder.empty()

    except Exception as e:
        st.error(f"WebSocket disconnected: {e}. Retrying...")

# Run listener in thread
threading.Thread(target=asyncio.run, args=(ws_listener(),), daemon=True).start()

st.sidebar.header("Dashboard Controls")
if st.sidebar.button("Reset View"):
    data_buffer = pd.DataFrame(columns=['time', 'open', 'high', 'low', 'close', 'volume'])
st.sidebar.info("Data streams live via WebSocket. Add engine broadcast for true push.")