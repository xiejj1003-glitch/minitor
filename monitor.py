import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime

# ==========================================
# 0. 📧 邮件配置函数
# ==========================================
def send_email(content):
    mail_user = os.environ.get("MAIL_USER")
    mail_pass = os.environ.get("MAIL_PASS")
    mail_to = os.environ.get("MAIL_TO")

    if not mail_user or not mail_pass or not mail_to:
        print("❌ 邮箱配置缺失，无法发送通知。")
        return

    message = MIMEText(content, 'html', 'utf-8')
    message['From'] = formataddr(["Nano猎手", mail_user])
    message['To'] = formataddr(["指挥官", mail_to])
    
    subject = f"🔥 纳米盘双策略战报 ({datetime.now().strftime('%H:%M')})"
    message['Subject'] = subject

    try:
        # 默认使用 QQ 邮箱端口 465 SSL
        smtp_obj = smtplib.SMTP_SSL('smtp.qq.com', 465) 
        smtp_obj.login(mail_user, mail_pass)
        smtp_obj.sendmail(mail_user, [mail_to], message.as_string())
        print("✅ 邮件已发送！")
        smtp_obj.quit()
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")

# ==========================================
# 1. 数据源：NASDAQ 官方
# ==========================================
def get_nasdaq_tickers(min_p=0.2, max_p=5.0): # 放宽到 $5 以防漏掉好票
    print(f"🌊 [Step 1] 从 NASDAQ 拉取 ${min_p}-${max_p} 名单...")
    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25&offset=0&download=true"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Origin': 'https://www.nasdaq.com',
        'Referer': 'https://www.nasdaq.com/'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=20)
        data_json = response.json()
        rows = data_json['data']['rows']
        df = pd.DataFrame(rows)
        
        df['lastsale'] = df['lastsale'].astype(str).str.replace('$', '').str.replace(',', '')
        df['lastsale'] = pd.to_numeric(df['lastsale'], errors='coerce')
        
        mask = (df['lastsale'] >= min_p) & (df['lastsale'] <= max_p)
        nano_df = df[mask]
        
        def clean_symbol(s):
            s = str(s).strip()
            # 只要纯字母，长度<=5，剔除权证
            return s if (s.isalpha() and len(s) <= 5) else None
            
        ticker_list = nano_df['symbol'].apply(clean_symbol).dropna().unique().tolist()
        print(f"✅ 获取到 {len(ticker_list)} 只有效标的")
        return ticker_list
    except Exception as e:
        print(f"❌ NASDAQ 数据获取失败: {e}")
        # 如果接口挂了，用一些经典妖股保底，证明程序还能跑
        return ["MULN", "FFIE", "HOLO", "GROM", "SNDL", "CEI", "KSCP"]

# ==========================================
# 2. 核心分析逻辑 (融合版)
# ==========================================
class NanoAnalyzer:
    def __init__(self):
        self.atr_period = 10
        # 策略 A (埋伏) 参数
        self.box_days = 15
        self.trigger_buffer = 0.5
        self.min_vol_low = 0.02
        self.min_vol_high = 0.03
        # 策略 B (蓄力) 参数
        self.min_rvol = 2.0
        self.max_change = 8.0
        self.min_change = -3.0

    def calculate_atr(self, df):
        high = df['High']
        low = df['Low']
        close = df['Close']
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(self.atr_period).mean()

    def analyze(self, symbol, df):
        df = df.dropna()
        if len(df) < 60: return None # 稍微降低门槛
        
        curr = df.iloc[-1]
        close_p = float(curr['Close'])
        vol = float(curr['Volume'])
        
        atr_series = self.calculate_atr(df)
        atr = atr_series.iloc[-1]
        if np.isnan(atr) or atr <= 0: return None
        
        results = {}

        # --- 🟢 策略 A: 埋伏 (Deep + Quiet) ---
        max_90d_robust = df['High'].iloc[-90:].quantile(0.95)
        is_deep = (close_p / max_90d_robust) < 0.75
        
        vol_baseline = df['Volume'].iloc[-90:].quantile(0.20)
        vol_5d = df['Volume'].iloc[-5:].mean()
        is_quiet = (vol_5d < vol_baseline * 3.0)
        
        volatility = atr / close_p
        req_vol = self.min_vol_low if close_p < 2.0 else self.min_vol_high
        is_elastic = volatility > req_vol

        if is_deep and is_quiet and is_elastic:
            box_high = df['High'].iloc[-self.box_days:].quantile(0.95)
            trigger = round(box_high + self.trigger_buffer * atr, 2)
            if trigger / close_p < 1.30:
                stop = round(df['Low'].iloc[-5:].min() - 0.2 * atr, 2)
                rr_ratio = (trigger - stop) / trigger
                if 0 < rr_ratio < 0.20:
                    results['Ambush'] = {
                        "Trigger": trigger, "Stop": stop, "Risk": f"{rr_ratio*100:.1f}%", "Setup": "Deep+Quiet"
                    }

        # --- 🔴 策略 B: 蓄力 (Volume Squeeze) ---
        avg_vol_20d = df['Volume'].iloc[-21:-1].mean()
        if avg_vol_20d > 30000: 
            r_vol = vol / avg_vol_20d
            open_p = float(curr['Open'])
            if open_p > 0:
                change_pct = (close_p - open_p) / open_p * 100
                if r_vol > self.min_rvol and self.min_change < change_pct < self.max_change:
                    score = r_vol / (abs(change_pct) + 0.5)
                    results['Compression'] = {
                        "RVol": round(r_vol, 1), "Change%": f"{change_pct:.2f}%", "Score": round(score, 2), "Setup": "Vol Squeeze"
                    }

        if not results: return None
        return {symbol: results}

# ==========================================
# 3. 主程序
# ==========================================
if __name__ == "__main__":
    print(f"⚔️ 终极纳米盘扫描器 | {datetime.now().strftime('%H:%M')}")
    
    tickers = get_nasdaq_tickers(min_p=0.2, max_p=5.0)
    analyzer = NanoAnalyzer()
    
    ambush_list = []
    compression_list = []
    
    # 每次处理 50 个，避免内存爆炸
    chunk_size = 50
    for i in range(0, len(tickers), chunk_size):
        batch = tickers[i:i+chunk_size]
        print(f"   进度: {i}/{len(tickers)}...", end="\r")
        
        try:
            data = yf.download(batch, period="3mo", interval="1d", group_by='ticker', threads=True, progress=False)
            if len(batch) == 1: batch_data = {batch[0]: data}
            else: batch_data = {t: data[t] for t in batch if t in data.columns.get_level_values(0)}
            
            for sym, df in batch_data.items():
                try:
                    res = analyzer.analyze(sym, df)
                    if res:
                        res_data = res[sym]
                        close_price = round(df['Close'].iloc[-1], 2)
                        
                        if 'Ambush' in res_data:
                            item = res_data['Ambush']
                            item['Symbol'] = sym
                            item['Close'] = close_price
                            ambush_list.append(item)
                            
                        if 'Compression' in res_data:
                            item = res_data['Compression']
                            item['Symbol'] = sym
                            item['Close'] = close_price
                            compression_list.append(item)
                except: continue
        except: continue

    # ==========================================
    # 4. 生成邮件内容
    # ==========================================
    msg_lines = []
    has_content = False
    
    msg_lines.append(f"<h3>🕒 扫描时间: {datetime.now().strftime('%H:%M')} (UTC)</h3>")
    
    # --- 生成埋伏表格 ---
    if ambush_list:
        has_content = True
        ambush_list.sort(key=lambda x: x['Trigger']/x['Close'])
        msg_lines.append("<h4>🟢 埋伏机会 (建议挂 Trigger 单)</h4>")
        msg_lines.append("<table border='1' cellpadding='4' cellspacing='0' style='border-collapse: collapse; width: 100%;'>")
        msg_lines.append("<tr style='background-color:#e8f5e9;'><th>代码</th><th>现价</th><th>Trigger</th><th>止损</th><th>盈亏比</th></tr>")
        for item in ambush_list:
            msg_lines.append(f"<tr><td><b>{item['Symbol']}</b></td><td>{item['Close']}</td><td><b>{item['Trigger']}</b></td><td>{item['Stop']}</td><td>{item['Risk']}</td></tr>")
        msg_lines.append("</table>")
    
    # --- 生成蓄力表格 ---
    if compression_list:
        has_content = True
        compression_list.sort(key=lambda x: x['Score'], reverse=True)
        msg_lines.append("<h4>🔴 蓄力异动 (主力正在压盘)</h4>")
        msg_lines.append("<table border='1' cellpadding='4' cellspacing='0' style='border-collapse: collapse; width: 100%;'>")
        msg_lines.append("<tr style='background-color:#ffebee;'><th>代码</th><th>现价</th><th>量比(RVol)</th><th>涨幅</th><th>压盘分</th></tr>")
        for item in compression_list[:15]: # 只发前15名，防止邮件太长
            msg_lines.append(f"<tr><td><b>{item['Symbol']}</b></td><td>{item['Close']}</td><td style='color:red'>{item['RVol']}</td><td>{item['Change%']}</td><td><b>{item['Score']}</b></td></tr>")
        msg_lines.append("</table>")

    # --- 发送逻辑 ---
    if has_content:
        final_msg = "".join(msg_lines)
        print("🚀 发现机会，正在发送邮件...")
        send_email(final_msg)
    else:
        print("🛡️ 本次扫描未发现符合 [Deep+Quiet] 或 [Compression] 的标的。")
   
