#!/bin/bash
# 清理「习酒花园」脚本的本地缓存 xijiutoken.json
# 适用：青龙容器 / Linux 服务器（用 bash 运行）
#
# 用法：
#   面板：把本脚本放进脚本目录后，点「运行」即可
#   SSH ：bash /ql/data/scripts/<你的目录>/wxapp/clear_xijiu_cache.sh
#
# 说明：习酒脚本的 token 缓存固定写在同目录的 xijiutoken.json，
#       删除后下一个执行周期会自动重新登录（见习酒.py CACHE_FILE）。

echo "===== 清理习酒花园缓存 (xijiutoken.json) ====="

# 1) 通用扫描青龙所有脚本目录
if [ -d /ql/data/scripts ]; then
    echo "[1] 扫描 /ql/data/scripts ..."
    matches=$(find /ql/data/scripts -name "xijiutoken.json" 2>/dev/null)
    if [ -n "$matches" ]; then
        echo "$matches" | while IFS= read -r f; do
            [ -n "$f" ] && rm -f "$f" && echo "    已删除: $f"
        done
    else
        echo "    未找到 xijiutoken.json"
    fi
else
    echo "[1] 未检测到 /ql/data/scripts 目录（非青龙环境？）"
fi

# 2) 当前工作目录兜底（本地调试时也可删）
if [ -f "./xijiutoken.json" ]; then
    rm -f "./xijiutoken.json" && echo "    已删除: ./xijiutoken.json"
fi

echo "[完成] 缓存删除后，习酒脚本下一个执行周期会自动重新登录。"
