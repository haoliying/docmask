#!/usr/bin/env bash
# 在有网络的机器上运行：下载全部依赖并打包成可拷贝到离线机器的目录。
#
# 用法：
#   ./scripts/build_offline_bundle.sh [输出目录]
#
# 默认输出到 dist/offline-bundle，并生成 dist/docmask-offline-bundle.tar.gz。
# 注意：wheels 与当前操作系统、CPU 架构、Python 版本绑定。请在与离线机器
# 相同（或兼容）的环境里执行本脚本，例如同为 Linux x86_64 + Python 3.11。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/dist/offline-bundle}"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "找不到 Python 解释器: $PYTHON" >&2
  exit 1
fi

echo "==> 准备输出目录 $OUT"
rm -rf "$OUT"
mkdir -p "$OUT/wheels" "$OUT/scripts" "$OUT/examples" "$OUT/src"

echo "==> 下载依赖 wheels"
"$PYTHON" -m pip download \
  --requirement "$ROOT/requirements.txt" \
  --dest "$OUT/wheels" \
  --only-binary=:all:

echo "==> 构建 docmask wheel"
if "$PYTHON" -c "import setuptools" >/dev/null 2>&1; then
  "$PYTHON" -m pip wheel "$ROOT" --no-deps --no-build-isolation --wheel-dir "$OUT/wheels"
else
  "$PYTHON" -m pip wheel "$ROOT" --no-deps --wheel-dir "$OUT/wheels"
fi

echo "==> 复制项目文件"
cp -R "$ROOT/docmask" "$OUT/src/docmask"
find "$OUT/src" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$OUT/src" -type f -name "*.pyc" -delete
cp "$ROOT/README.md" "$ROOT/requirements.txt" "$ROOT/pyproject.toml" "$OUT/"
cp -R "$ROOT/examples/." "$OUT/examples/"
cp "$ROOT/scripts/install_offline.sh" "$OUT/scripts/"
chmod +x "$OUT/scripts/install_offline.sh"

cat > "$OUT/安装说明.txt" <<'EOF'
docmask 离线安装包
==================

1. 将整个目录拷贝到离线机器（保持目录结构）。
2. 在离线机器上执行：

     bash scripts/install_offline.sh

   脚本会创建 .venv，并从本目录的 wheels/ 安装依赖与 docmask。
   不访问网络。

3. 启动命令行：

     ./docmask --help

4. 启动本地 Web 界面：

     ./docmask ui

   浏览器访问 http://127.0.0.1:8765/ 。

详细用法见 README.md。
EOF

echo "==> 打包 tar.gz"
ARCHIVE="$ROOT/dist/docmask-offline-bundle.tar.gz"
mkdir -p "$ROOT/dist"
tar -czf "$ARCHIVE" -C "$(dirname "$OUT")" "$(basename "$OUT")"

echo
echo "完成："
echo "  目录  $OUT"
echo "  压缩包 $ARCHIVE"
echo
echo "下一步：把压缩包拷贝到离线机器，解压后执行 scripts/install_offline.sh"
