#!/usr/bin/env bash
# 模拟内网环境：封掉公网 HTTP/HTTPS，保留百度千帆 API 内网专线
# 用法: ./toggle_network.sh on|off
#   off - 关闭外网访问（保留百度 API）
#   on  - 恢复外网访问

set -euo pipefail

BAIDU_IPS=("100.64.80.185" "100.64.80.89")

case "${1:-}" in
  off)
    for ip in "${BAIDU_IPS[@]}"; do
      iptables -A OUTPUT -p tcp -d "$ip" --dport 443 -j ACCEPT
    done
    iptables -A OUTPUT -p tcp --dport 443 -j REJECT
    iptables -A OUTPUT -p tcp --dport 80 -j REJECT
    echo "外网已关闭（百度 API 保留）"
    echo "验证: curl -s --connect-timeout 5 https://www.baidu.com -o /dev/null -w '%{http_code}'"
    ;;
  on)
    iptables -D OUTPUT -p tcp --dport 80 -j REJECT 2>/dev/null || true
    iptables -D OUTPUT -p tcp --dport 443 -j REJECT 2>/dev/null || true
    for ip in "${BAIDU_IPS[@]}"; do
      iptables -D OUTPUT -p tcp -d "$ip" --dport 443 -j ACCEPT 2>/dev/null || true
    done
    echo "外网已恢复"
    ;;
  *)
    echo "用法: $0 on|off"
    echo "  off - 关闭外网（保留百度 API）"
    echo "  on  - 恢复外网"
    exit 1
    ;;
esac
