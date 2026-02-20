import akshare as ak
import pandas as pd
import requests
import os
import sys

# =========================
# 读取环境变量
# =========================
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
ETF_ENV = os.getenv("ETF_POOL")
WINDOW_ENV = os.getenv("MOMENTUM_WINDOW")

if not ETF_ENV:
    print("错误：ETF_POOL 未设置")
    sys.exit(1)

ETF_POOL = [code.strip() for code in ETF_ENV.split(",") if code.strip()]
MOMENTUM_WINDOW = int(WINDOW_ENV.strip()) if WINDOW_ENV else 20

START_DATE = "20180101"
INITIAL_CASH = 1000000

print("ETF池:", ETF_POOL)
print("动量窗口:", MOMENTUM_WINDOW)

# =========================
# 获取数据
# =========================
def get_etf_data(code):
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

data_list = []

for code in ETF_POOL:
    print(f"下载 {code} 数据...")
    df = get_etf_data(code)
    data_list.append(df)

data = pd.concat(data_list, axis=1).dropna()

# =========================
# 计算动量
# =========================
momentum = data / data.shift(MOMENTUM_WINDOW) - 1
momentum = momentum.dropna(how="all")

# =========================
# ① 回测模块
# =========================
cash = INITIAL_CASH
position = None
shares = 0
equity_curve = []

for date in momentum.index:

    today_mom = momentum.loc[date].dropna()
    today_price = data.loc[date]

    if today_mom.empty:
        equity_curve.append(cash if position is None else shares * today_price[position])
        continue

    top = today_mom.idxmax()

    if position is None:
        shares = cash / today_price[top]
        position = top
        cash = 0
    else:
        if top != position:
            cash = shares * today_price[position]
            shares = cash / today_price[top]
            position = top
            cash = 0

    equity = shares * today_price[position]
    equity_curve.append(equity)

equity_curve = pd.Series(equity_curve, index=momentum.index)

total_return = equity_curve.iloc[-1] / INITIAL_CASH - 1
max_drawdown = (equity_curve / equity_curve.cummax() - 1).min()
annual_return = (1 + total_return) ** (252 / len(equity_curve)) - 1

# =========================
# ② 今日实盘信号模块
# =========================
latest_date = momentum.index[-1]
latest_mom = momentum.loc[latest_date].dropna()

ranking = latest_mom.sort_values(ascending=False)
today_top = ranking.index[0]

signal_text = ""
signal_text += "📌 今日动量排名:\n"

for i, (etf, value) in enumerate(ranking.items(), 1):
    signal_text += f"{i}. {etf} | 动量: {value:.2%}\n"

signal_text += f"\n👉 今日策略建议持仓: {today_top}\n"

# =========================
# 输出内容
# =========================
result_text = f"""
📊 ETF 动量策略报告

【历史回测】
总收益: {total_return:.2%}
年化收益: {annual_return:.2%}
最大回撤: {max_drawdown:.2%}

【今日信号】
{signal_text}
"""

print(result_text)

# =========================
# 飞书推送
# =========================
if FEISHU_WEBHOOK:
    payload = {
        "msg_type": "text",
        "content": {
            "text": result_text
        }
    }

    response = requests.post(FEISHU_WEBHOOK, json=payload)
    print("飞书推送状态:", response.status_code)
