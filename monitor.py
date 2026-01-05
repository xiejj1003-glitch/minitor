import requests
import pandas as pd
import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime

# ===========================
# 配置区域
# ===========================
# 筛选条件: 微盘 + 量比>2 + 涨幅>5%
FINVIZ_URL = "https://finviz.com/screener.ashx?v=111&f=cap_micro,sh_relvol_o2,ta_change_u5&ft=4&o=-change"

def send_email(content):
    """发送邮件通知"""
    # 1. 从 GitHub Secrets 获取账号密码
    mail_user = os.environ.get("MAIL_USER")
    mail_pass = os.environ.get("MAIL_PASS")
    mail_to = os.environ.get("MAIL_TO")

    if not mail_user or not mail_pass or not mail_to:
        print("❌ 邮箱配置缺失，请检查 GitHub Secrets！")
        return

    # 2. 邮件内容设置
    message = MIMEText(content, 'html', 'utf-8') # 支持 HTML 格式
    message['From'] = Header("Nano-Sniper 哨兵", 'utf-8')
    message['To'] = Header("指挥官", 'utf-8')
    subject = f"🔥 妖股雷达异动提醒 ({datetime.now().strftime('%H:%M')})"
    message['Subject'] = Header(subject, 'utf-8')

    try:
        # 3. 连接邮箱服务器 (这里以 QQ 邮箱为例)
        # 如果是 163 邮箱，改成 smtp.163.com
        # 如果是 Gmail，改成 smtp.gmail.com
        smtp_obj = smtplib.SMTP_SSL('smtp.qq.com', 465) 
        
        smtp_obj.login(mail_user, mail_pass)
        smtp_obj.sendmail(mail_user, [mail_to], message.as_string())
        print("✅ 邮件已发送成功")
        smtp_obj.quit()
    except smtplib.SMTPException as e:
        print(f"❌ 邮件发送失败: {e}")

def scan_nano_stocks():
    print(f"📡 雷达启动: {datetime.now()} | 正在扫描美股微盘池...")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(FINVIZ_URL, headers=headers)
        tables = pd.read_html(response.text)
        df = tables[-2]
        
        if df.empty or 'Ticker' not in df.columns:
            print("⚠️ 没扫描到符合条件的股票，或者是休市时间。")
            return

        top_movers = df.head(10)
        
        # 生成 HTML 表格格式的邮件内容
        msg_lines = []
        msg_lines.append(f"<h3>🕒 扫描时间: {datetime.now().strftime('%H:%M')} (美东)</h3>")
        msg_lines.append("<p>筛选策略: <b>Micro Cap + RelVol > 2 + Change > 5%</b></p>")
        msg_lines.append("<table border='1' cellpadding='5' cellspacing='0' style='border-collapse: collapse;'>")
        msg_lines.append("<tr style='background-color:#f2f2f2;'><th>代码</th><th>涨幅</th><th>现价</th><th>成交量</th></tr>")
        
        for index, row in top_movers.iterrows():
            ticker = row['Ticker']
            price = row['Price']
            change = row['Change']
            volume = row['Volume']
            
            # 颜色标记：涨幅标红
            msg_lines.append(f"<tr><td><b>{ticker}</b></td><td style='color:red;'>{change}</td><td>${price}</td><td>{volume}</td></tr>")
            
        msg_lines.append("</table>")
        msg_lines.append("<p><i>⚠️ 风险提示: 请务必结合 VWAP 指标判断，切勿无脑追高。</i></p>")
        
        final_msg = "".join(msg_lines)
        
        # 发送邮件
        send_email(final_msg)
        print(top_movers[['Ticker', 'Change', 'Price', 'Volume']])

    except Exception as e:
        print(f"❌ 扫描失败: {e}")

if __name__ == "__main__":
    scan_nano_stocks()
