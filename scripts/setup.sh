#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p secrets workspace data certs

if [ ! -f secrets/local.key ]; then
  # 密钥格式：64 字符 hex（可带末尾换行），或原始 32 字节。
  # 原始 32 字节不会被 trim（首尾空白字节的随机密钥同样有效）。
  head -c 32 /dev/urandom | xxd -p -c 64 | tr -d '\n' > secrets/local.key
  chmod 600 secrets/local.key
  echo "已生成 secrets/local.key（本地 AES-GCM 密钥）"
fi

# 待确认队列独立密钥（可选；缺失时回退 local.key）。Compose 将其挂载为 PENDING_QUEUE_KEY_FILE。
if [ ! -f secrets/queue.key ]; then
  head -c 32 /dev/urandom | xxd -p -c 64 | tr -d '\n' > secrets/queue.key
  chmod 600 secrets/queue.key
  echo "已生成 secrets/queue.key（待确认队列 AES-256-GCM 密钥）"
fi

# 自签 CA + Vaultwarden 服务端证书（bw CLI 要求 HTTPS；CA 经 secrets/ca.crt 注入 web 容器信任）
if [ ! -f certs/server.crt ]; then
  openssl req -x509 -newkey rsa:2048 -keyout certs/ca.key -out certs/ca.crt -days 3650 -nodes \
    -subj "/CN=asset-assistant-ca" 2>/dev/null
  openssl req -newkey rsa:2048 -keyout certs/server.key -out certs/server.csr -nodes \
    -subj "/CN=vaultwarden" 2>/dev/null
  printf 'subjectAltName = DNS:vaultwarden, DNS:localhost, DNS:host.docker.internal, IP:127.0.0.1\n' > certs/san.cnf
  openssl x509 -req -in certs/server.csr -CA certs/ca.crt -CAkey certs/ca.key -CAcreateserial \
    -out certs/server.crt -days 3650 -extfile certs/san.cnf 2>/dev/null
  chmod 600 certs/ca.key certs/server.key
  echo "已生成 certs/（自签 TLS 证书）"
fi
[ -f secrets/ca.crt ] || cp certs/ca.crt secrets/ca.crt

if [ ! -f .env ]; then
  TOKEN=$(head -c 24 /dev/urandom | xxd -p -c 48 | tr -d '\n')
  printf 'ADMIN_TOKEN=%s\n' "$TOKEN" > .env
  echo "已生成 .env（Vaultwarden 管理令牌）"
fi

echo "初始化完成。接下来："
echo "1. docker compose up -d --build"
echo "2. 创建 Vaultwarden 账号（二选一）："
echo "   a. 打开 http://127.0.0.1:8081 网页注册（推荐，密钥派生全部由官方客户端完成）"
echo "   b. python scripts/register_vaultwarden_account.py <邮箱> <主密码> https://127.0.0.1:8081"
echo "3. 将账号写入凭证文件后重启 web："
echo "   printf 'your@email.com' > secrets/bw_email && printf '你的主密码' > secrets/bw_password"
echo "   （或 secrets/bw_clientid + secrets/bw_clientsecret 走 API Key）"
echo "   docker compose restart web"
echo "4. 打开 http://127.0.0.1:8000 ，在「设置」页配置模型"
