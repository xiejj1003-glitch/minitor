import requests
import pandas as pd
import os
from datetime import datetime

# ===========================
# 配置区域
# ===========================
# 筛选条件说明 (对应 Finviz 的参数):
# v=111: 查看概览
# f=cap_micro: 微盘股 (包含 Nano) - 市值通常 < 3亿美金
# sh_relvol_o2: 相对成交量 > 2 (量是平时的2倍，说明主力进场)
# ta_change_u5: 涨幅 > 5% (正在启动)
# o=-change: 按涨幅从高到低排序
FINVIZ_URL = "https://finviz.com/screener.ashx?v=111&f=cap_micro,sh_relvol_o2,ta_change_u5&ft=4&o=-change"

def send_pushplus(content):
    """发送微信通知"""
    token = os.environ.get("PUSHPLUS_TOKEN")
    if not token:
        print("❌ 未配置 Pushplus Token")
        return
    
    url = 'http://www.pushplus.plus/send'
    data = {
        "token": token,
        "title": "🔥 纳米妖股异动雷达",
        "content": content,
        "template": "html"
    }
    try:
        requests.post(url, json=data)
        print("✅ 通知已发送")
    except Exception as e:
        print(f"❌ 发送失败: {e}")

def scan_nano_stocks():
    print(f"📡 雷达启动: {datetime.now()} | 正在扫描美股微盘池...")
    
    # 伪装成浏览器 (Finviz 反爬虫很严，必须加这个)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(FINVIZ_URL, headers=headers)
        
        # 使用 Pandas 解析网页中的表格
        # read_html 会返回一个列表，Finviz 的数据通常在倒数第2个表里
        tables = pd.read_html(response.text)
        df = tables[-2]
        
        # 检查是否抓到了数据
        if df.empty or 'Ticker' not in df.columns:
            print("⚠️ 没扫描到符合条件的股票，或者是休市时间。")
            return

        # 只取前 10 名最猛的
        top_movers = df.head(10)
        
        # 生成通知内容 (HTML 格式)
        msg_lines = []
        msg_lines.append(f"<b>🕒 扫描时间: {datetime.now().strftime('%H:%M')} (美东)</b>")
        msg_lines.append("--------------------------------")
        msg_lines.append("筛选条件: 微盘 + 量比>2 + 涨幅>5%")
        msg_lines.append("--------------------------------<br>")
        
        for index, row in top_movers.iterrows():
            # 提取核心字段
            ticker = row['Ticker']
            price = row['Price']
            change = row['Change']
            volume = row['Volume']
            
            # 组装单行信息
            # 格式: GME | +15% | $25.0 | Vol: 10M
            line = f"🚀 <b>{ticker}</b> | <font color='red'>{change}</font> | ${price} | Vol: {volume}"
            msg_lines.append(line)
            
        msg_lines.append("<br><i>⚠️ 风险提示: 纳米盘波动剧烈，请结合 VWAP 决策。</i>")
        
        # 发送
        final_msg = "<br>".join(msg_lines)
        send_pushplus(final_msg)
        
        # 在日志里也打印一下
        print(top_movers[['Ticker', 'Change', 'Price', 'Volume']])

    except Exception as e:
        print(f"❌ 扫描失败 (可能是 Finviz 屏蔽了 IP): {e}")

if __name__ == "__main__":
    scan_nano_stocks()
