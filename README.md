# docmask · 本地离线文档脱敏工具

docmask 是一个**完全在本机运行、不需要网络**的文件脱敏工具。它只做一件事：批量识别文档中的敏感信息并遮盖，输出可交付的文件、审计报告，以及（可选的）可还原映射。

- 文件不上传，不调用云端 API，无遥测，无外部 CDN。
- 命令行负责批处理，本地 Web 界面负责可视化预览与下载。
- Web 服务默认只监听 `127.0.0.1`，并校验 Host / Origin。

## 功能概览

| 能力 | 说明 |
| --- | --- |
| 支持格式 | DOCX、XLSX、PPTX、PDF、TXT、Markdown、CSV/TSV、JSON/JSONL，以及 YAML/XML/HTML/SQL 等文本格式 |
| 识别类型 | 手机号、固定电话、身份证号、护照、姓名、地址、机构、邮箱、银行卡、账号、车牌、统一社会信用代码、IP、API Key、密码、URL、自定义词与自定义正则 |
| 脱敏策略 | 全掩码、部分保留、占位符（可还原）、HMAC 哈希 |
| 批处理 | 递归目录、dry-run 演练、逐文件错误隔离、JSON/CSV 审计报告 |
| 还原 | 使用 `mapping.csv` 把占位符还原为原文（PDF 除外） |
| 元数据清理 | 清理文档作者、标题、备注等核心属性（可关闭） |
| 本地界面 | 上传、策略选择、预览、批量脱敏、ZIP 下载 |

## 系统要求

- Python 3.9 或更高版本（建议 3.10+）。
- 依赖：`python-docx`、`openpyxl`、`python-pptx`、`PyMuPDF`。
- 处理 PDF 时需要 PyMuPDF；其余格式可以在缺少某个依赖时继续处理其他文件。

## 快速开始（联网开发机）

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m docmask --help
```

也可以直接从源码运行，不安装：

```bash
./scripts/start.sh --help
```

## Windows EXE

无需安装 Python，直接使用发布页的 `docmask-windows-x64.zip`：

1. 解压 ZIP；
2. 双击 `docmask.exe`，会自动启动本地 Web 界面并打开浏览器；
3. 关闭控制台窗口即可停止服务。

命令行用法：

```bat
docmask.exe --help
docmask.exe run .\文档目录 -o .\out --strategy replace
docmask.exe preview .\合同.docx
docmask.exe ui --port 8765 --no-browser
```

说明：

- 支持 Windows 10/11 x64；EXE 未做代码签名，首次运行可能出现 SmartScreen 提示，选择“更多信息 → 仍要运行”即可。
- EXE 运行时仍然完全离线，只监听 `127.0.0.1`。
- 本地构建：在 Windows 仓库根目录执行 `powershell -ExecutionPolicy Bypass -File scripts/build_windows_exe.ps1`。
- 自动发布：推送 `v*` 标签后，GitHub Actions 会运行测试、构建 EXE，并把 ZIP 与 `SHA256SUMS.txt` 上传到 Release。

## 离线部署

### 1. 在联网机器上打包

请在与离线机器**相同或兼容**的操作系统、CPU 架构和 Python 版本上执行：

```bash
./scripts/build_offline_bundle.sh
```

脚本会：

1. 下载全部依赖 wheel 到 `dist/offline-bundle/wheels/`；
2. 构建 docmask wheel；
3. 复制源码、示例与安装脚本；
4. 生成 `dist/docmask-offline-bundle.tar.gz`。

### 2. 拷贝到离线机器并安装

```bash
tar -xzf docmask-offline-bundle.tar.gz
cd offline-bundle
bash scripts/install_offline.sh
```

安装脚本只使用本目录的 `wheels/`，全程 `--no-index`，不会访问网络。安装完成后：

```bash
./docmask --help
./docmask ui
```

Windows 离线安装（等价命令）：

```bat
py -m venv .venv
.venv\Scripts\python -m pip install --no-index --find-links wheels docmask
.venv\Scripts\python -m docmask ui
```

> wheels 与平台绑定。如果离线机器是 Windows 而打包机是 Linux，请在 Windows 上重新执行打包，或分别准备对应平台的 wheels。

## 命令行用法

### 预览，不写文件

```bash
python -m docmask preview ./文档目录
python -m docmask preview ./合同.docx --json
```

预览只显示**掩码后的上下文**、类型和命中数量，不会打印原文。

### 批量脱敏

```bash
# 默认全掩码，输出到 ./redacted_output
python -m docmask run ./文档目录

# 只演练，不写任何文件
python -m docmask run ./文档目录 --dry-run

# 使用占位符，生成可还原映射
python -m docmask run ./文档目录 -o ./out --strategy replace

# 指定报告路径（.json 或 .csv）
python -m docmask run ./文档目录 -o ./out --report ./审计报告.csv

# 只处理手机号、邮箱和姓名
python -m docmask run ./文档目录 --enable CN_MOBILE EMAIL PERSON

# 关闭某些类型
python -m docmask run ./文档目录 --disable URL IPV4

# 部分保留（如 138****8000）
python -m docmask run ./文档目录 --strategy partial

# 使用自定义词表与规则
python -m docmask run ./文档目录 \
  --custom-words ./examples/custom_words.txt \
  --rules ./examples/custom_rules.json
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `-o, --output` | 输出目录，默认 `./redacted_output` |
| `--mapping FILE` | 映射文件路径；`replace` 策略默认写入输出目录 `mapping.csv` |
| `--report FILE` | 审计报告路径，支持 `.json` / `.csv` |
| `--dry-run` | 只分析并统计，不写入文件 |
| `--non-recursive` | 不递归子目录 |
| `--strategy` | `mask` / `partial` / `replace` / `hash` |
| `--mask-char` | 掩码字符，默认 `*` |
| `--keep-length` | 全掩码时保留原文字符数 |
| `--keep-metadata` | 保留文档核心元数据（默认清理） |
| `--pdf-mode` | `text` 写入掩码文本 / `box` 只覆盖色块 |
| `--salt` | `hash` 策略的盐，也可用环境变量 `DOCMASK_SALT` |
| `--json` | 以 JSON 输出运行结果 |

退出码：`0` 成功；`2` 有文件失败或没有可处理文件；`1` 参数/运行错误。

### 还原占位符

```bash
python -m docmask run ./文档目录 -o ./out --strategy replace
python -m docmask restore ./out -o ./restored --mapping ./out/mapping.csv
```

- 仅支持可写回文本的格式；PDF 不能还原。
- 还原不会处理 `mapping.csv`、`redaction_report.json` 自身。

### 规则文件与词表

```bash
python -m docmask rules init -o ./docmask_rules.json
python -m docmask entities
```

示例规则见 [`examples/custom_rules.json`](examples/custom_rules.json)，词表见 [`examples/custom_words.txt`](examples/custom_words.txt)。

词表支持两种写法：

```text
姓名:张三
公司：某某科技有限公司
CUSTOM:项目代号-朱雀
纯词默认按 CUSTOM 处理
```

规则文件中的 `custom_patterns` 使用 Python 正则语法，可配置 `type`、`group`、`priority`、`validator`（`luhn` / `cn_id` / `uscc` / `ipv4`）和 `ignore_case`。

## Web 界面

```bash
python -m docmask ui
# 或指定端口
python -m docmask ui --port 8765 --no-browser
```

浏览器打开 `http://127.0.0.1:8765/`。界面支持：

1. 拖拽或选择多个文件；
2. 选择策略、掩码字符与实体类型；
3. 填写自定义词、规则 JSON；
4. 先预览命中数量和掩码片段；
5. 执行脱敏并下载 ZIP（包含输出文件、`mapping.csv`、`redaction_report.json`、`脱敏说明.txt`）。

数据目录默认 `~/.docmask`，可用环境变量 `DOCMASK_DATA_DIR` 修改。上传的原始文件在处理完成后立即删除，任务目录默认保留 24 小时。

## 脱敏策略

| 策略 | 示例（手机号 13800138000） | 说明 |
| --- | --- | --- |
| `mask` | `***` 或 `***********` | 默认；`--keep-length` 时保留字符数 |
| `partial` | `138****8000` | 按类型保留前后若干字符，邮箱保留域名 |
| `replace` | `[MOBILE_001]` | 同值同占位符，可跨文件保持一致，可还原 |
| `hash` | `[H_1a2b3c4d5e]` | HMAC-SHA256 + 本次运行盐，不可逆，适合统计分析 |

默认启用的实体类型：

`PERSON`、`CN_ID`、`PASSPORT`、`CN_MOBILE`、`CN_LANDLINE`、`EMAIL`、`ADDRESS`、`BANK_CARD`、`ACCOUNT`、`ORG`、`PATTERN_ADDRESS`、`CN_LICENSE_PLATE`、`IPV4`、`API_KEY`、`PASSWORD`、`CUSTOM`。

默认关闭：`SOCIAL_CREDIT_CODE`、`URL`。可用 `--enable` / `--disable` 调整。

## 安全说明

- **`mapping.csv` 包含敏感原文**。写出时在 POSIX 系统上权限为 `0600`，但仍请把它与脱敏文件分开保管，交付时不要带上。
- 审计报告只包含类型统计、文件名、状态、警告和错误，不包含原文。
- 默认清理文档核心元数据（作者、标题、备注等）。如业务需要保留，使用 `--keep-metadata`。
- 原始文件永不被覆盖：输出到源目录时，同名文件会变为 `文件名_redacted.ext`。
- Web 服务仅监听回环地址，并校验 `Host` / `Origin`，设置 CSP 与 `no-store`。

## 已知限制

- **不处理扫描件 OCR**：PDF 扫描件、图片中的文字不会被识别；工具会给出警告。
- 图片、嵌入对象、SmartArt、图表、批注等非正文内容可能只警告、不自动脱敏。
- 旧格式 `.doc` / `.xls` / `.ppt` 不支持，请先另存为新格式。
- 加密 PDF 仅尝试空密码；失败会报错。
- 中文姓名、地址、机构依赖标签、格式特征或自定义词表；表格中裸姓名建议加入词表。
- 文档被 Word 拆分到多个 run 时会尽量合并检测并回写，但复杂排版仍建议人工复核。
- PDF 的脱敏文本已从内容流移除，但版面可能因替换文本长度不同而轻微变化；`box` 模式适合只追求遮盖的场景。
- JSON 会被重新序列化（缩进风格尽量保持）；JSON 键名不脱敏。

## 开发与测试

```bash
# 运行全部单元测试（标准库 unittest）
python3 -m unittest discover -s tests -t . -v
```

测试覆盖：号码校验、检测冲突、四种策略、映射与还原、DOCX 跨 run、XLSX 批注/公式、PPTX 表格/备注、PDF 真实 redaction、CSV/JSON/编码、批处理与报告、Web 策略与文件名净化。

## 目录结构

```text
docmask/
  cli.py               命令行入口
  config.py            规则文件、词表、策略组装
  detectors.py         敏感信息检测与冲突消解
  entities.py          实体类型注册表
  masking.py           掩码渲染、映射、还原
  models.py            数据模型
  validators.py        身份证/银行卡/统一社会信用代码/IP 校验
  pipeline.py          批处理、预览、报告、还原
  handlers/            各文件格式处理器
  web/                 本地 HTTP 服务与静态界面
scripts/
  build_offline_bundle.sh   联网机器打包
  install_offline.sh        离线安装
  start.sh / start.bat      源码启动
examples/                示例规则与词表
tests/                   单元测试
```
