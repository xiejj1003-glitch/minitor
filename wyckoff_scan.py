import pandas as pd
import yfinance as yf
import numpy as np
import logging
import time
import os
import random
import traceback
import math
import requests
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime
from scipy.signal import argrelextrema
from scipy.stats import percentileofscore, linregress
import urllib3

# ==========================================
# 0. 🛠️ 用户配置区
# ==========================================
# 邮箱配置 (优先读取环境变量)
MAIL_USER = os.environ.get("MAIL_USER")
MAIL_PASS = os.environ.get("MAIL_PASS")
MAIL_TO   = os.environ.get("MAIL_TO")

# 代理配置 
# 注意：在 GitHub Actions 云端运行时，不要设置这个变量，让它保持为 None
PROXY_PORT = os.environ.get("PROXY_PORT") 

# ------------------------------------------

# 自动配置代理逻辑
if PROXY_PORT:
    PROXY_URL = f"http://127.0.0.1:{PROXY_PORT}"
    os.environ["HTTP_PROXY"] = PROXY_URL
    os.environ["HTTPS_PROXY"] = PROXY_URL
    print(f"🌍 本地代理已开启: {PROXY_PORT}")
else:
    # GitHub Actions 会走进这个分支，直接使用云端高速网络
    print("☁️ 无代理模式 (适合云端/Github Actions)")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("Wyckoff_Mail")

# ==========================================
# 1. 📧 邮件发送模块
# ==========================================
def send_email(results_list):
    if not MAIL_USER or not MAIL_PASS or not MAIL_TO:
        print("❌ 邮箱配置缺失 (Secrets未设置)，跳过发送。")
        return

    print(f"📧 正在向 {MAIL_TO} 发送战报...")
    
    # 构建 HTML 表格
    html_content = f"""
    <h3>🦅 威科夫全市场战报 ({datetime.now().strftime('%Y-%m-%d %H:%M')})</h3>
    <p>共扫描全美股，发现 <b>{len(results_list)}</b> 个高概率结构。</p>
    <table border='1' cellpadding='5' cellspacing='0' style='border-collapse: collapse; width: 100%; font-family: Arial, sans-serif;'>
        <tr style='background-color:#2c3e50; color:white;'>
            <th>Symbol</th>
            <th>Price</th>
            <th>Signal</th>
            <th>Detail (Score/Vol/RS)</th>
            <th>Stop Loss</th>
        </tr>
    """
    
    for row in results_list:
        # 根据信号类型给颜色
        bg_color = "#e8f5e9" if "Spring" in row['Signal'] else "#fff3e0" # Spring绿，SOS橙
        text_color = "#1b5e20" if "Spring" in row['Signal'] else "#e65100"
        
        html_content += f"""
        <tr style='background-color:{bg_color};'>
            <td><b>{row['Symbol']}</b></td>
            <td>${row['Price']}</td>
            <td style='color:{text_color}; font-weight:bold;'>{row['Signal']}</td>
            <td style='font-size:12px;'>{row['Detail']}</td>
            <td style='color:#c62828;'>${row['Stop']}</td>
        </tr>
        """
    
    html_content += "</table><p style='font-size:12px; color:gray;'>* V19.0 Anti-Fragile Engine Output</p>"

    msg = MIMEText(html_content, 'html', 'utf-8')
    msg['From'] = formataddr(["Wyckoff Hunter", MAIL_USER])
    msg['To'] = formataddr(["Commander", MAIL_TO])
    msg['Subject'] = f"🚀 威科夫战报: 发现 {len(results_list)} 个猎物"

    try:
        # 智能判断 SMTP 服务器
        if 'qq.com' in MAIL_USER:
            smtp_server = 'smtp.qq.com'
        elif '163.com' in MAIL_USER:
            smtp_server = 'smtp.163.com'
        elif 'gmail.com' in MAIL_USER:
            smtp_server = 'smtp.gmail.com'
        else:
            smtp_server = 'smtp.qq.com' # 默认尝试QQ
        
        # 使用 SSL 465 端口
        server = smtplib.SMTP_SSL(smtp_server, 465)
        server.login(MAIL_USER, MAIL_PASS)
        server.sendmail(MAIL_USER, [MAIL_TO], msg.as_string())
        server.quit()
        print("✅ 邮件发送成功！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")

# ==========================================
# 2. 强壮网络与统计库
# ==========================================
class RobustDownloader:
    @staticmethod
    def get_custom_session():
        s = requests.Session()
        s.verify = False
        s.trust_env = True
        a = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=3)
        s.mount('http://', a); s.mount('https://', a)
        return s

    @staticmethod
    def download_chunk(tickers, period="1y"):
        s = RobustDownloader.get_custom_session()
        for _ in range(3):
            try:
                time.sleep(random.uniform(0.5, 1.5))
                # 注意：yfinance 新版 auto_adjust 参数
                data = yf.download(tickers, period=period, group_by='ticker', 
                                 threads=True, progress=False, auto_adjust=True, session=s)
                if data is not None and not data.empty: return data
            except: 
                time.sleep(2)
        return None

    @staticmethod
    def normalize_data(raw_data, batch_tickers):
        std = {}
        if raw_data is None or raw_data.empty: return std
        
        # 处理多级索引 (MultiIndex)
        if isinstance(raw_data.columns, pd.MultiIndex):
            for t in raw_data.columns.levels[0]:
                try:
                    df = raw_data[t].copy()
                    if 'Close' in df.columns and 'Volume' in df.columns:
                        if not df['Close'].dropna().empty: std[t] = df
                except: continue
        # 处理单级索引 (DataFrame)
        elif isinstance(raw_data, pd.DataFrame):
            cols = set(raw_data.columns)
            if {'Close', 'Volume'}.issubset(cols):
                if len(batch_tickers) == 1: std[batch_tickers[0]] = raw_data.copy()
        return std

class StatUtils:
    @staticmethod
    def calculate_atr(df, period=14):
        h, l, c_prev = df['High'], df['Low'], df['Close'].shift()
        tr = pd.concat([h-l, (h-c_prev).abs(), (l-c_prev).abs()], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    @staticmethod
    def calculate_rolling_rank(series, window=120):
        return series.rolling(window).rank(pct=True) * 100

    @staticmethod
    def calculate_log_rs_slope(stock_close, bench_close, window=50):
        try:
            # 对齐数据
            bench = bench_close.reindex(stock_close.index).ffill()
            s = stock_close / stock_close.iloc[0]
            b = bench / bench.iloc[0]
            rs = s / b
            
            if len(rs) < window: return 0
            
            log_rs = np.log(rs.replace(0, np.nan).dropna())
            y = log_rs.iloc[-window:].values
            
            if len(y) < 10: return 0
            return linregress(np.arange(len(y)), y)[0] * 1000
        except: return 0

# ==========================================
# 3. 威科夫分析引擎
# ==========================================
class WyckoffAnalyzer:
    def __init__(self):
        self.bench_data = None

    def fetch_benchmark(self):
        try:
            s = RobustDownloader.get_custom_session()
            b = yf.download("QQQ", period="1y", progress=False, session=s)
            
            # 处理 benchmark 数据格式
            if isinstance(b, pd.DataFrame):
                if isinstance(b.columns, pd.MultiIndex): 
                    # 尝试提取 QQQ 的 Close
                    if 'QQQ' in b.columns.get_level_values(1):
                        self.bench_data = b.xs('QQQ', level=1, axis=1)['Close'] 
                    else:
                        self.bench_data = b.iloc[:,0] # 盲取第一列
                else: 
                    self.bench_data = b['Close']
            
            # 再次确认是 Series
            if isinstance(self.bench_data, pd.DataFrame): 
                self.bench_data = self.bench_data.iloc[:,0]
                
            print("✅ 基准数据 (QQQ) 就绪")
        except Exception as e: 
            print(f"⚠️ 基准获取失败 ({e})，将跳过 RS 分析")

    def find_dynamic_zones(self, df):
        sub = df.iloc[-120:-3]
        if len(sub) < 50: return None, None
        
        curr = df['Close'].iloc[-1]
        atr = StatUtils.calculate_atr(sub).iloc[-1]
        atr = curr * 0.05 if pd.isna(atr) else atr
        
        # 95% 分位数 + ATR 钳位
        res = min(sub['High'].quantile(0.95), sub['Close'].median() + 4*atr)
        sup = max(sub['Low'].quantile(0.05), sub['Close'].median() - 4*atr)
        return res, sup

    def analyze(self, t, df):
        try:
            df = df.dropna(subset=['Close','Volume']).sort_index()
            if len(df) < 180: return None
            
            c, v, l = df['Close'], df['Volume'], df['Low']
            curr = c.iloc[-1]
            
            # 过滤: $2-$500, 流动性>50万
            if not (2 <= curr <= 500): return None
            if (c*v).rolling(20).mean().iloc[-1] < 500000: return None
            
            # 指标计算
            atr = StatUtils.calculate_atr(df).iloc[-1]
            vr = StatUtils.calculate_rolling_rank(v, 60)
            rs = StatUtils.calculate_log_rs_slope(c, self.bench_data) if self.bench_data is not None else 0
            
            res, sup = self.find_dynamic_zones(df)
            if not res or (res-sup)/curr < 0.05: return None # 波动太窄
            
            # === Spring 信号识别 ===
            rec_l = l.iloc[-3:].min()
            # 价格刺破支撑但收回
            if rec_l < sup * 1.03 and curr > sup:
                l3 = df.iloc[-3:]
                rng = (l3['High']-l3['Low']).replace(0, 0.01)
                crp = ((l3['Close']-l3['Low'])/rng).clip(0,1)
                w_crp = np.average(crp.values, weights=[1,2,3])
                
                sc = 0
                note = []
                if w_crp > 0.6: sc+=1
                if w_crp > 0.7: sc+=1
                
                cur_vr = vr.iloc[-3:].mean()
                if cur_vr < 30: sc+=1.5; note.append("Dry")
                elif cur_vr > 85 and w_crp > 0.6: sc+=1.5; note.append("Absorb")
                if rs > -0.05: sc+=1
                
                if sc >= 2.5:
                    return {
                        'Symbol':t, 
                        'Signal':'🔥 V19 Spring', 
                        'Price':round(curr,2), 
                        'Detail':f"Sc:{sc} {','.join(note)} CRP:{w_crp:.2f}", 
                        'Stop':round(rec_l*0.98,2)
                    }

            # === SOS 信号识别 ===
            if curr > res:
                if atr < df['Close'].rolling(120).std().iloc[-1]*0.8: # Coil近似
                    if rs > 0 and vr.iloc[-1] > 70:
                        return {
                            'Symbol':t, 
                            'Signal':'🚀 V19 SOS', 
                            'Price':round(curr,2),
                            'Detail':f"Coil Break | RS:{rs:.1f}", 
                            'Stop':round(l.iloc[-1],2)
                        }
        except: pass
        return None

# ==========================================
# 4. 主程序
# ==========================================
def get_tickers():
    print("🌊 拉取 NASDAQ 全量列表...")
    try:
        s = RobustDownloader.get_custom_session()
        r = s.get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25&offset=0&download=true", 
                  headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        
        data_json = r.json()
        if 'data' not in data_json or 'rows' not in data_json['data']:
            raise Exception("API结构改变")
            
        df = pd.DataFrame(data_json['data']['rows'])
        
        # 数据清洗
        df['lastsale'] = pd.to_numeric(df['lastsale'].astype(str).str.replace('$','').str.replace(',',''), errors='coerce')
        df['marketCap'] = pd.to_numeric(df['marketCap'].astype(str).str.replace(',','').str.replace('NA','0'), errors='coerce')
        
        mask = (df['lastsale'] >= 2) & (df['marketCap'] > 50000000)
        ts = [x for x in df[mask]['symbol'].tolist() if str(x).isalpha()]
        
        print(f"✅ 获取 {len(ts)} 只标的")
        return list(set(ts))
    except Exception as e:
        print(f"⚠️ 获取失败 ({e})，使用测试列表")
        return ['AAPL','TSLA','AMD','NVDA','PLTR','SOFI','MARA','DKNG','COIN','AI','UPST','CVNA']

def main():
    engine = WyckoffAnalyzer()
    engine.fetch_benchmark()
    
    tickers = get_tickers()
    BATCH = 100
    total = math.ceil(len(tickers)/BATCH)
    all_results = []
    
    print(f"\n🚀 开始全量扫描 ({len(tickers)}只)...")
    
    for i in range(total):
        batch = tickers[i*BATCH : (i+1)*BATCH]
        print(f"Batch {i+1}/{total}...", end="\r")
        
        raw = RobustDownloader.download_chunk(batch)
        data = RobustDownloader.normalize_data(raw, batch)
        
        for t, df in data.items():
            res = engine.analyze(t, df)
            if res:
                print(f"\n🎯 Found: {t} ({res['Signal']})")
                all_results.append(res)
        
        time.sleep(1) # 保护 API

    print("\n✅ 扫描完成。")
    
    # 发送邮件
    if all_results:
        send_email(all_results)
        # 尝试保存 CSV，虽然在 Actions 里这步不是必须的
        try:
            pd.DataFrame(all_results).to_csv(f"Wyckoff_Result_{datetime.now().strftime('%Y%m%d')}.csv", index=False)
        except: pass
    else:
        print("🛡️ 今日无符合条件的标的，不发送邮件。")

if __name__ == "__main__":
    main()
