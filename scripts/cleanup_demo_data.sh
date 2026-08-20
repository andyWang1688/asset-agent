#!/usr/bin/env bash
# 清理演示/联调遗留数据（确认闸门测试产物、mock Wiki 页、Raw 副本、Vaultwarden 测试条目）。
# 用法：
#   scripts/cleanup_demo_data.sh                          # 预览将执行的操作（只读）
#   scripts/cleanup_demo_data.sh --yes                    # 确认执行
#   scripts/cleanup_demo_data.sh --yes <文件...>          # 额外删除指定文件
#   scripts/cleanup_demo_data.sh --yes --vaultwarden      # 同时清理 Vaultwarden 测试条目
#
# 说明：
#   - --vaultwarden 只删除 note 以“由资产助手自动保存”开头的条目（本应用创建），
#     通过容器内官方 bw CLI 操作；需要 secrets/bw_email + secrets/bw_password（主密码方式），
#     API Key 登录方式请手工清理。
#   - 脚本中的 bw 登录/解锁与运行中的应用共用 bw 配置目录：应用会在下一次调用时自动
#     重新登录，无需重启。
#   - 若 API 不可达，跳过线上清理（待确认提交/索引重建），仅做文件删除。
set -euo pipefail
cd "$(dirname "$0")/.."

API="${ASSET_ASSISTANT_URL:-http://127.0.0.1:8000}"
YES=0
VW=0
FILES=()

for arg in "$@"; do
  case "$arg" in
    --yes) YES=1 ;;
    --vaultwarden) VW=1 ;;
    -*) echo "未知参数 $arg" >&2; exit 1 ;;
    *) FILES+=("$arg") ;;
  esac
done

# 本会话演示产物（mock 模型生成）
FILES+=(
  workspace/wiki/projects/demo-project.md
  workspace/wiki/sources/mock-source.md
)

echo "== 计划 =="
echo "1) 删除文件（存在的才删）："
for f in "${FILES[@]}"; do
  [ -e "$f" ] && echo "   - $f"
done
echo "2) 线上：取消所有 waiting 待确认提交"
echo "3) 线上：重建 Wiki 索引（POST /api/wiki/rebuild）"
if [ "$VW" = 1 ]; then
  echo "4) Vaultwarden：删除 note 以“由资产助手自动保存”开头的条目（dry-run 列表见下）"
else
  echo "4) Vaultwarden：跳过（加 --vaultwarden 清理本应用创建的测试条目）"
fi
[ "$YES" = 1 ] || { echo; echo "确认执行请加 --yes"; exit 0; }

echo; echo "== 执行 =="
for f in "${FILES[@]}"; do
  if [ -e "$f" ]; then rm -f "$f" && echo "已删除 $f"; fi
done

if curl -s --max-time 3 "$API/api/health" > /dev/null 2>&1; then
  for sid in $(curl -s "$API/api/pending/submissions" \
    | python3 -c "import json,sys; print(' '.join(str(r['id']) for r in json.load(sys.stdin) if r['status']=='waiting'))" 2>/dev/null); do
    curl -s -X POST "$API/api/pending/submissions/$sid/cancel" > /dev/null \
      && echo "已取消待确认提交 #$sid"
  done
  curl -s -X POST "$API/api/wiki/rebuild" > /dev/null && echo "Wiki 索引已重建"
else
  echo "API 不可达（$API），跳过线上清理"
fi

if [ "$VW" = 1 ]; then
  if [ ! -f secrets/bw_email ] || [ ! -f secrets/bw_password ]; then
    echo "缺少 secrets/bw_email 与 secrets/bw_password（API Key 登录请手工清理）" >&2
    exit 1
  fi
  BW_EMAIL="$(cat secrets/bw_email)"
  BW_PASSWORD="$(cat secrets/bw_password)"
  export BW_EMAIL BW_PASSWORD

  ITEMS=$(docker compose exec -T -e BW_EMAIL -e BW_PASSWORD web sh -c '
    export BW_SESSION=$(bw unlock --passwordenv BW_PASSWORD --raw 2>/dev/null)
    if [ -z "$BW_SESSION" ]; then
      bw login "$BW_EMAIL" "$BW_PASSWORD" >/dev/null 2>&1 || true
      export BW_SESSION=$(bw unlock --passwordenv BW_PASSWORD --raw 2>/dev/null)
    fi
    bw list items 2>/dev/null
  ' | python3 -c '
import json, sys
try:
    items = json.load(sys.stdin)
except Exception:
    items = []
for it in items:
    if (it.get("notes") or "").startswith("由资产助手自动保存"):
        print(it.get("id"), it.get("name"), sep="\t")
')
  if [ -z "$ITEMS" ]; then
    echo "Vaultwarden：没有匹配条目"
  else
    echo "Vaultwarden 将删除："
    echo "$ITEMS"
    # 单次容器会话内完成全部删除（避免每轮 login 与应用进程竞争 bw 配置目录）
    printf '%s\n' "$ITEMS" | cut -f1 | docker compose exec -T -e BW_EMAIL -e BW_PASSWORD web sh -c '
      export BW_SESSION=$(bw unlock --passwordenv BW_PASSWORD --raw 2>/dev/null)
      if [ -z "$BW_SESSION" ]; then
        bw login "$BW_EMAIL" "$BW_PASSWORD" >/dev/null 2>&1 || true
        export BW_SESSION=$(bw unlock --passwordenv BW_PASSWORD --raw 2>/dev/null)
      fi
      n=0
      while IFS= read -r id; do
        [ -z "$id" ] && continue
        bw delete item "$id" >/dev/null 2>&1 && n=$((n+1))
      done
      echo "已删除 $n 条"
    ' || echo "Vaultwarden 清理失败（请手工处理：http://127.0.0.1:8081）"
  fi
fi

echo "完成。"
