#!/bin/bash
# Deploy script สำหรับ EC2 (Ubuntu 22.04)
# รันครั้งแรกครั้งเดียวหลัง SSH เข้า EC2

set -e

echo "=== 1. Update system ==="
sudo apt update && sudo apt upgrade -y

echo "=== 2. Install Python ==="
sudo apt install -y python3 python3-pip python3-venv git

echo "=== 3. Clone / copy project ==="
# ถ้าใช้ git:
# git clone https://github.com/yourname/yourrepo.git ~/bot
# cd ~/bot

# ถ้า scp ไฟล์มาเอง ข้ามขั้นตอนนี้
cd ~/bot

echo "=== 4. Setup virtual environment ==="
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo "=== 5. Setup .env ==="
# copy .env.example แล้วใส่ API keys จริง
cp .env.example .env
echo "⚠️  อย่าลืมแก้ไข .env ด้วย API keys จริงก่อน start bot!"
echo "    nano .env"

echo "=== 6. สร้าง systemd service (รัน bot ตลอด + auto-restart) ==="
sudo tee /etc/systemd/system/telegram-bot.service > /dev/null <<EOF
[Unit]
Description=Telegram AI Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/bot
ExecStart=$HOME/bot/venv/bin/python bot.py
Restart=always
RestartSec=10
EnvironmentFile=$HOME/bot/.env

[Install]
WantedBy=multi-user.target
EOF

echo "=== 7. Enable และ start service ==="
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot
sudo systemctl start telegram-bot

echo ""
echo "✅ Done! ใช้คำสั่งเหล่านี้จัดการ bot:"
echo "  sudo systemctl status telegram-bot   # ดู status"
echo "  sudo systemctl restart telegram-bot  # restart"
echo "  sudo journalctl -u telegram-bot -f   # ดู logs แบบ realtime"
