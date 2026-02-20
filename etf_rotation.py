import akshare as ak
import pandas as pd
import numpy as np
import requests
import os
import sys

# =========================
# 参数读取
# =========================
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
ETF_ENV = os.getenv("ETF_POOL")
WINDOW_ENV = os.getenv("MOMENTUM_WINDOW")

if not ETF_ENV:
    print("错误：ETF_POOL 未设置")
    sys.exit(1)

ETF_POOL = [code.strip() for code in ETF_ENV.split(",") if code.strip()]
MOMENTUM_WINDOW = int(WINDOW_ENV.strip()) if WINDOW_ENV else 20

START_DATE = "20160101"
INITIAL_CASH = 1000000

print("ETF池:", ETF_POOL)
print("动量窗口:", MOMENTUM_WINDOW)

# =========================
# 获取数据
# =========================
def get_etf_data(code):
    try:
        df = ak.fund_etf_hist_em(
            symbol=code,
            start_date=START_DATE,
            adjust="qfq"
        )
        df = df[["日期", "收盘"]]
        df.columns = ["date", code]
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
        return df
    except Exception as e:
        print(f"{code} 数据下载失败:", e)
        return None

data_list = []

for code in ETF_POOL:
    print(f"下载 {code}")
    df = get_etf_data(code)
    if df is not None:
        data_list.append(df)

if not data_list:
    print("无可用数据")
    sys.exit(1)

data = pd.concat(data_list, axis=1).dropna()

if len(data) < 250:
    print("数据不足，无法计算200MA")
    sys.exit(1)

# =========================
# 计算指标
# =========================
momentum = data / data.shift(MOMENTUM_WINDOW) - 1
ma200 = data["510300"].rolling(200).mean()

# 每周调仓（周五）
weekly_dates = data.resample("W-FRI").last().index

cash = INITIAL_CASH
position = None
shares = 0
equity_curve = []

# =========================
# 回测主循环
# =========================
for date in data.index:

    price_today = data.loc[date]

    # 是否为调仓日
    if date in weekly_dates and date in momentum.index:

        today_mom = momentum.loc[date].dropna()

        if not today_mom.empty:

            ranking = today_mom.sort_values(ascending=False)
            top = ranking.index[0]
            top_mom = ranking.iloc[0]

            market_bull = price_today["510300"] > ma200.loc[date]

            new_position = None

            # 牛市
            if market_bull:
                if top_mom > 0:
                    new_position = top

            # 熊市
            else:
                if "518880" in today_mom.index and today_mom["518880"] > 0:
                    new_position = "518880"

            # 执行调仓
            if new_position != position:
                if position is not None:
                    cash = shares * price_today[position]
                    shares = 0
                if new_position is not None:
                    shares = cash / price_today[new_position]
                    cash = 0
                position = new_position

    # 记录资产
    if position is None:
        equity = cash
    else:
        equity = shares * price_today[position]

    equity_curve.append(equity)

equity_curve = pd.Series(equity_curve, index=data.index)

# =========================
# 回测统计
# =========================
total_return = equity_curve.iloc[-1] / INITIAL_CASH - 1
max_drawdown = (equity_curve / equity_curve.cummax() - 1).min()
annual_return = (1 + total_return) ** (252 / len(equity_curve)) - 1

# =========================
# 今日信号模块（防崩溃版）
# =========================
latest_date = data.index[-1]

today_signal = "空仓"
ranking = pd.Series(dtype=float)
market_bull = False

if latest_date in momentum.index:

    latest_mom = momentum.loc[latest_date].dropna()

    if not latest_mom.empty:

        ranking = latest_mom.sort_values(ascending=False)

        top = ranking.index[0]
        top_mom = ranking.iloc[0]

        latest_ma200 = ma200.loc[latest_date]
        latest_price_300 = data.loc[latest_date]["510300"]

        market_bull = latest_price_300 > latest_ma200

        if market_bull:
            if top_mom > 0:
                today_signal = top
        else:
            if "518880" in latest_mom.index and latest_mom["518880"] > 0:
                today_signal = "518880"

# =========================
# 输出报告
# =========================
result_text = f"""
📊 周频双动量趋势系统报告

【历史回测】
总收益: {total_return:.2%}
年化收益: {annual_return:.2%}
最大回撤: {max_drawdown:.2%}

【当前市场状态】
沪深300 > 200MA: {market_bull}

【今日动量排名】
"""

if not ranking.empty:
    for i, (etf, value) in enumerate(ranking.items(), 1):
        result_text += f"{i}. {etf} | {value:.2%}\n"
else:
    result_text += "数据不足，无法计算动量\n"

result_text += f"\n👉 今日建议持仓: {today_signal}\n"

print(result_text)

# =========================
# 飞书推送
# =========================
if FEISHU_WEBHOOK:
    payload = {
        "msg_type": "text",
        "content": {"text": result_text}
    }
    try:
        response = requests.post(FEISHU_WEBHOOK, json=payload)
        print("飞书推送状态:", response.status_code)
    except Exception as e:
        print("飞书推送失败:", e)
