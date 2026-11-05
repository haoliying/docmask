#!/usr/bin/env bash
# 在离线机器上运行：从随包的 wheels/ 安装 docmask，不访问网络。
#
# 用法：
#   bash scripts/install_offline.sh
#
# 可选环境变量：
#   PYTHON=python3.11   指定解释器
#   VENV=/path/to/venv  指定虚拟环境目录（默认 <安装包>/.venv）

set -euo pipefail

BUNDLE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
VENV="${VENV:-$BUNDLE/.venv}"
WHEELS="$BUNDLE/wheels"

if [ ! -d "$WHEELS" ]; then
  echo "缺少 wheels 目录：$WHEELS" >&2
  echo "请在有网络的机器上执行 scripts/build_offline_bundle.sh 重新打包。" >&2
  exit 1
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "找不到 Python 解释器：$PYTHON" >&2
  exit 1
fi

echo "==> 使用解释器 $("$PYTHON" -V 2>&1)"
echo "==> 创建虚拟环境 $VENV"
"$PYTHON" -m venv "$VENV"

echo "==> 离线安装依赖与 docmask"
"$VENV/bin/python" -m pip install \
  --no-index \
  --find-links "$WHEELS" \
  --disable-pip-version-check \
  docmask

cat > "$BUNDLE/docmask" <<'WRAPPER'
#!/usr/bin/env sh
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$DIR/.venv/bin/python" -m docmask "$@"
WRAPPER
chmod +x "$BUNDLE/docmask"

echo
echo "安装完成。"
echo "  CLI:  $BUNDLE/docmask --help"
echo "  Web:  $BUNDLE/docmask ui"
echo "  默认仅监听 127.0.0.1，不会访问网络。"
