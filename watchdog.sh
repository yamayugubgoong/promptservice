#!/bin/bash
# watchdog.sh — ตรวจสอบว่า bot รันอยู่ไหม ถ้าไม่ → แจ้ง Telegram admin
# ติดตั้ง: เพิ่มเข้า crontab ให้รันทุก 5 นาที
# crontab -e  แล้วเพิ่มบรรทัดนี้:
# */5 * * * * /home/ec2-user/bot/watchdog.sh >> /home/ec2-user/bot/watchdog.log 2>&1

TELEGRAM_TOKEN="$(grep TELEGRAM_TOKEN /home/ec2-user/bot/.env | cut -d= -f2)"
ADMIN_CHAT_ID="$(grep ADMIN_CHAT_ID /home/ec2-user/bot/.env | cut -d= -f2)"
SERVICE_NAME="telegram-bot"

send_alert() {
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
        -d chat_id="${ADMIN_CHAT_ID}" \
        -d text="$1" > /dev/null
}

# เช็คว่า service รันอยู่ไหม
if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "[$(date)] ❌ Service หยุดทำงาน กำลัง restart..."
    send_alert "🚨 Bot หยุดทำงาน! กำลัง restart อัตโนมัติ..."

    systemctl restart "$SERVICE_NAME"
    sleep 5

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo "[$(date)] ✅ Restart สำเร็จ"
        send_alert "✅ Bot restart สำเร็จแล้ว"
    else
        echo "[$(date)] ❌ Restart ล้มเหลว"
        send_alert "❌ Bot restart ล้มเหลว! กรุณาตรวจสอบ EC2 ด่วน"
    fi
else
    echo "[$(date)] ✅ Bot รันปกติ"
fi
