#!/usr/bin/env bash
# ============================================================
#  更新并重启 bot 容器（幂等，可反复执行）
#
#  用法：bash deploy/update.sh
#
#  它做的事：git pull -> docker build -> 删旧容器 -> 用同样的参数重跑
#  数据卷固定挂在仓库目录的 data/ 下，重建容器不会丢账本。
#  只操作自己的容器，不会碰 VPS 上别的容器。
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

if [ ! -f .env ]; then
  echo "!!  缺少 .env。先执行：" >&2
  echo "     cp .env.example .env && nano .env   # 填入 BOT_TOKEN" >&2
  exit 1
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
