#!/usr/bin/env bash
# ============================================================
#  更新并重启 bot 容器（幂等，可反复执行）
#
#  用法：bash deploy/update.sh
#       换 token：BOT_TOKEN=<BotFather 给的新token> bash deploy/update.sh
#
#  它做的事：git pull -> docker build -> 删旧容器 -> 用同样的参数重跑
#  数据卷固定挂在仓库目录的 data/ 下，重建容器不会丢账本。
#  只操作自己的容器，不会碰 VPS 上别的容器。
#
#  带 BOT_TOKEN 调用时，会先把 .env 里那行 BOT_TOKEN 换成新值（.env 不存在
#  就从 .env.example 生成一份），其余行原样保留。token 只进 .env，不进 git。
# ============================================================
set -euo pipefail

# 切到仓库根目录，这样从任何位置调用都成立
cd "$(dirname "${BASH_SOURCE[0]}")/.."

CONTAINER="${CONTAINER:-newbot_pg1_container}"
IMAGE="${IMAGE:-newbot_pg1_image:latest}"
DATA_DIR="$(pwd)/data"

if ! command -v docker >/dev/null 2>&1; then
  echo "!!  找不到 docker 命令，请确认当前用户在 docker 组里" >&2
  exit 1
fi

echo "==> 1/5 拉取最新代码"
git pull --ff-only

# 换 token：BOT_TOKEN=xxx bash deploy/update.sh
# 平时没带参数就只读现有的 .env；带了参数才改那一行，其余行原样保留
if [ ! -f .env ]; then
  if [ -n "${BOT_TOKEN:-}" ]; then
    cp .env.example .env
    echo "==> .env 不存在，已从 .env.example 生成"
  else
    echo "!!  缺少 .env。先执行：" >&2
    echo "     cp .env.example .env && nano .env   # 填入 BOT_TOKEN" >&2
    exit 1
  fi
fi

if [ -n "${BOT_TOKEN:-}" ]; then
  if grep -q '^BOT_TOKEN=' .env; then
    sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=${BOT_TOKEN}|" .env
  else
    printf 'BOT_TOKEN=%s\n' "${BOT_TOKEN}" >> .env
  fi
  chmod 600 .env
  echo "==> .env 的 BOT_TOKEN 已换新（bot id ${BOT_TOKEN%%:*}），旧 token 随之作废"
fi

echo "==> 2/5 准备数据目录 ${DATA_DIR}"
mkdir -p "${DATA_DIR}"

echo "==> 3/5 构建镜像 ${IMAGE}"
docker build -t "${IMAGE}" .

echo "==> 4/5 重建容器 ${CONTAINER}"
if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER}"; then
  docker rm -f "${CONTAINER}" >/dev/null
  echo "    已移除旧容器（数据卷保留在 ${DATA_DIR}）"
fi

docker run -d \
  --name "${CONTAINER}" \
  --restart unless-stopped \
  --env-file .env \
  -e BOT_DATA_DIR=/app/data \
  -v "${DATA_DIR}:/app/data" \
  "${IMAGE}" >/dev/null

echo "==> 5/5 启动日志"
sleep 3
docker logs --tail 20 "${CONTAINER}"

echo
echo "完成。实时日志： docker logs -f ${CONTAINER}"
