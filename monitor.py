import requests
import pandas as pd
import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr  # <--- 新增这个工具
from io import StringIO             # <--- 新增这个工具(修警告用)
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
    message = MIMEText(content, 'html', 'utf-8')
    
    # === 关键修改点开始 ===
    # QQ邮箱要求极其严格，必须是 "昵称 <邮箱>" 的格式，且邮箱必须和登录账号一致
    # 比如: "Nano哨兵 <123456@qq.com>"
    message['From'] = formataddr(["Nano-Sniper 哨兵", mail_user])
    message['To'] = formataddr(["指挥官", mail_to])
    # === 关键修改点结束 ===
    
    subject = f"🔥 妖股雷达异动提醒 ({datetime.now().strftime('%H:%M')})"
    message['Subject'] = subject

    try:
        # 3. 连接邮箱服务器
        smtp_obj = smtplib.SMTP_SSL('smtp.qq.com', 465) 
        smtp_obj.login(mail_user, mail_pass)
        smtp_obj.sendmail(mail_user, [mail_to], message.as_string())
        print("✅ 邮件已发送成功！(快去检查收件箱)")
        smtp_obj.quit()
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")

def scan_nano_stocks():
    print(f"📡 雷达启动: {datetime.now()} | 正在扫描美股微盘池...")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(FINVIZ_URL, headers=headers)
        
        # 修复 FutureWarning: 使用 StringIO 包装字符串
        html_data = StringIO(response.text)
        tables = pd.read_html(html_data)
        df = tables[-2]
        
        if df.empty or 'Ticker' not in df.columns:
            print("⚠️ 没扫描到符合条件的股票，或者是休市时间。")
            return

        top_movers = df.head(10)
        
        # 生成 HTML 邮件
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
            
            # 把 Volume 转成更易读的格式 (比如 116185096 -> 116M)
            vol_str = str(volume)
            if volume > 1000000:
                vol_str = f"{volume/1000000:.1f}M"
            
            msg_lines.append(f"<tr><td><b>{ticker}</b></td><td style='color:red;'>{change}</td><td>${price}</td><td>{vol_str}</td></tr>")
            
        msg_lines.append("</table>")
        msg_lines.append("<p><i>⚠️ 风险提示: 必须结合 VWAP 指标判断。</i></p>")
        
        final_msg = "".join(msg_lines)
        
        send_email(final_msg)
        print(top_movers[['Ticker', 'Change', 'Price', 'Volume']])

    except Exception as e:
        print(f"❌ 扫描失败: {e}")

if __name__ == "__main__":
    scan_nano_stocks()
