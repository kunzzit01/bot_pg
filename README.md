# bot_pg — Telegram 群记账机器人

单文件 Telegram 机器人（`bot.py`），基于 `python-telegram-bot` v21 异步 API。
用途：在群组里记流水 / 下发 / 出账，按「账期」统计 Deposit、Withdraw、Settlement，并支持撤销与撤销恢复。

## 功能一览

| 功能 | 触发方式 |
|---|---|
| 入账 | `+100 备注` |
| 出账 | `-50 备注` |
| 下发 | `下发 2000`、`下发 2000 手续20 备注`、`下发 +2000`（冲正一笔下发） |
| 查看账单 | `账单` 或 `/ledger` |
| 撤销 / 恢复某一笔 | 回复那条记账消息，发 `撤销` / `撤销恢复`；`回撤` = 作废并删除原始消息 |
| 币种 | `设置币种 AUD`、批量改 `修改币种 USD到MYR`（管理员） |
| 时区 | `设定时区 +10`（支持负数和半点，如 `-5`、`5.5`） |
| 费率 | `设置IN费率 5`、`设置OUT费率 3` |
| 校准账期 | `设定日期 2026-09-10` |
| 日切 / 清账 | `结束账单`、`日切`、`清空账单`、`撤销清空账单` |
| 操作员管理 | `/addoperator`、`/removeoperator`、`/listoperators` |

权限两级：`ADMIN_USERNAMES` 里的用户名是管理员（硬编码在 `bot.py` 顶部）；其余用户需被加进操作员名单才能记账。

数字与括号支持全角，例如 `＋１００`、`（` 会被自动转成半角后再解析。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `BOT_TOKEN` | 是 | BotFather 给的 token，**不要写进代码或提交到 git** |
| `BOT_DATA_DIR` | 否 | 数据目录，默认 `/app`；本地跑建议设成 `./data` |

## 本地运行

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # 填上 BOT_TOKEN
export BOT_DATA_DIR=./data      # Windows PowerShell: $env:BOT_DATA_DIR="./data"
export BOT_TOKEN="你的token"

python3 bot.py
```

看到 `记账机器人已启动，正在监听消息...` 即为启动成功。之后私聊或拉进群发 `/start` 查看指令说明。

## Docker 部署

首次部署：

```bash
mkdir -p ~/newbot_pg1 && cd ~/newbot_pg1
git clone https://github.com/kunzzit01/bot_pg.git .
cp .env.example .env && nano .env       # 填入 BOT_TOKEN
bash deploy/update.sh
```

以后更新代码只要一条：

```bash
cd ~/newbot_pg1 && git pull && bash deploy/update.sh
```

`deploy/update.sh` 是幂等的，可以反复执行：`git pull` → `docker build` → 删掉旧容器 → 用同样的参数重新 `docker run`。
数据卷固定挂在仓库目录的 `data/`，重建容器不会丢账本；脚本只操作自己的容器，不会影响机器上其他容器。

容器名与镜像名默认是 `newbot_pg1_container` / `newbot_pg1_image:latest`，需要改时用环境变量覆盖：
`CONTAINER=别的名字 IMAGE=别的镜像:tag bash deploy/update.sh`。

### 换 bot token

token 只在服务器的 `.env` 里，不在 git 里 —— 所以换 token 必须连 `.env` 一起改，单独 `git pull` 是换不掉的：

```bash
cd ~/newbot_pg1 && BOT_TOKEN='BotFather 给的新token' bash deploy/update.sh
```

脚本会把 `.env` 里的 `BOT_TOKEN=` 那一行换成新值（其余行原样保留；没有 `.env` 就先从 `.env.example` 生成一份），
然后照常 `git pull` → 构建镜像 → 重建容器，一次搞定。

验证部署版本：

```bash
docker logs --tail 3 newbot_pg1_container     # 应显示：记账机器人 v1.32 已启动，正在监听消息...
```

> 机器人是纯出站长轮询（`run_polling`），不监听任何端口，所以不需要 `-p` 端口映射。
> 数据卷一定要挂，否则容器重建后账本会丢。

## 数据文件（都在 `BOT_DATA_DIR` 下，JSON 格式）

| 文件 | 存什么 |
|---|---|
| `ledger_settings.json` | 每个群的币种、时区、费率、账期起点/标签 |
| `ledger_entries.json` | 全部流水（入账 / 出账 / 下发）与作废标记 |
| `ledger_carryover.json` | 日切后的结转余额 |
| `ledger_clear_snapshot.json` | 最近一次「清空账单」的快照，供撤销用 |
| `operators.json` | 操作员名单（id 与 username） |

这些文件都已在 `.gitignore` 里，不会被提交。

## 注意

- `bot.py` 顶部的 `ADMIN_USERNAMES` 是唯一的管理员来源，改完需要重启进程。
- 账期由 `结束账单` / `日切` 推进；`period_start` 只在第一次记账时确定一次。
- `bot.py` 顶部的 `BOT_VERSION` 是版本号常量，改动代码时递增，方便用 `docker logs` 核对线上跑的是哪一版。
