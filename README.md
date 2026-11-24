# 深度学习专项课程（Coursera）

特别感谢吴恩达（Andrew Ng）及 Coursera 团队推出这套通俗易懂的深度学习专项课程。
本仓库收录课程提供的编程作业未完成版本、测验和探索性实验。

## 一键安装本地环境

克隆仓库后，在仓库根目录运行以下命令即可，无需预先安装 Python 或 Conda。

Windows 上的课程目录名称较长，克隆时请启用 Git 长路径支持：

```powershell
git clone -c core.longpaths=true https://github.com/Ghpt6/Deep-Learning-Specialization-Coursera.git
```

**Windows（PowerShell）：**

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

**macOS / Linux：**

```bash
bash setup.sh
```

安装脚本会复用已安装的 **uv >= 0.11.24**，不会自动升级。如果尚未安装 uv，则通过 Astral 官方安装程序安装 **uv 0.11.24**。随后，脚本会准备由 uv 管理的 **Python 3.10.20**，自动检查并补齐课程资料，再根据仓库中的 `uv.lock` 文件安装五个独立环境，注册五个 Jupyter 内核，并检查模块导入、代表性计算和内核的实际启动情况。如果下载失败，可重新运行同一命令；资料下载支持断点续传，uv 也会复用依赖下载缓存。

支持的平台：**Windows x64、Linux x86_64（glibc）、macOS Intel 和 Apple Silicon**。这些环境使用 CPU，不包含 CUDA 或 GPU 驱动的安装配置。安装时需要访问 astral.sh/GitHub、PyPI，以及第 5 门课程所需的 download.pytorch.org。请为课程资料、压缩包缓存和五个独立环境预留足够磁盘空间，并为首次下载 TensorFlow/PyTorch 留出足够时间。

| 课程 | 独立环境 | 主要依赖库 |
| --- | --- | --- |
| 1 — 神经网络与深度学习 | `environments/course1/.venv` | NumPy、SciPy、scikit-learn、h5py、Matplotlib、Pillow |
| 2 — 改善深层神经网络 | `environments/course2/.venv` | 第 1 门课程的工具，加上 TensorFlow/Keras、dlai-tools |
| 3 — 机器学习项目的组织与策略 | `environments/course3/.venv` | 数值计算工具和 Jupyter，供自行实验使用；原课程没有编程作业 |
| 4 — 卷积神经网络 | `environments/course4/.venv` | TensorFlow/Keras、imageio、pandas、图像处理工具 |
| 5 — 序列模型 | `environments/course5/.venv` | TensorFlow/Keras、music21、mido、pydub、emoji、Faker/Babel、Transformers、Datasets、CPU 版 PyTorch、Accelerate、seqeval |

五个环境均包含 `ipykernel` 和 `ipywidgets`。公共依赖共享 uv 缓存，但每门课程都有独立的解释器、已安装依赖和锁定文件。较短的环境目录路径可以避免将冗长的课程和周次名称带入 Windows 软件包路径。

### 在 VS Code 中选择内核（Kernel）

1. 使用 VS Code 打开 **`Deep-Learning.code-workspace`**（运行 `code Deep-Learning.code-workspace`）。该工作区包含五个课程文件夹及对应的解释器设置。也可以直接打开仓库文件夹。
2. 如果出现提示，请安装推荐的 **Python**、**Python Environments** 和 **Jupyter** 扩展。
3. 打开课程的 `.ipynb` 文件，点击 **Select Kernel → Select Another Kernel… → Python Environments…**，选择对应的 `dls-course-N` 环境。根据已安装的 Jupyter 扩展版本，注册的 **DLS Course N - …** 内核也可能显示在 **Jupyter Kernels** 下。注册名称末尾的短后缀用于标识当前克隆副本，避免不同副本的内核相互覆盖。
4. 运行一个单元格。Notebook 的工作目录已设置为该 Notebook 所在目录，因此可以正确导入实验目录中的模块，并访问相对路径下的数据。

如果只看到上述内核*来源*菜单，请点击 **Python Environments…** 查看环境列表。如果安装时 VS Code 已经打开，请运行 **Developer: Reload Window**，然后重新选择内核。如果环境列表仍未更新，请运行 **Python Environments: Refresh All Environment Managers**，或通过 **Python: Select Interpreter → Enter interpreter path** 选择以下解释器：

- Windows：`environments/courseN/.venv/Scripts/python.exe`
- macOS/Linux：`environments/courseN/.venv/bin/python`

VS Code 会记住 Notebook 的内核选择；仅切换 Python 解释器，可能不会改变已经选定的 Notebook 内核。更多说明请参阅官方的[内核选择指南](https://code.visualstudio.com/docs/datascience/jupyter-kernel-management)和 [uv 与 Jupyter 集成指南](https://docs.astral.sh/uv/guides/integration/jupyter/)。

### 单独安装某门课程，或检查现有环境

```powershell
.\setup.ps1 -Course 2       # 仅安装、注册并检查第 2 门课程
.\setup.ps1 -Course 1,5     # 安装两门课程的环境
.\setup.ps1 -CheckOnly     # 检查现有的全部五个环境及内核
```

```bash
bash setup.sh --course 2
bash setup.sh --course 1 5
bash setup.sh --check-only
```

也可以通过 VS Code 的 **Terminal → Run Task**，运行 **DLS: Install all course environments** 或 **DLS: Check all course environments** 任务。移动仓库后，需要重新运行安装脚本，因为注册的内核使用解释器的绝对路径；虚拟环境本身也应在移动后重新创建。

### 依赖维护与兼容性

每个 `environments/courseN/` 目录都有独立的 `pyproject.toml`、`.python-version` 和 `uv.lock`。安装脚本使用 **`uv sync --locked`**，如果锁定文件与依赖配置不一致，就会停止安装，避免自动解析出不同的依赖版本。如果需要调整依赖，请编辑对应课程的依赖清单，然后运行：

```bash
uv lock --project environments/course2
uv run --no-project --python 3.10.20 scripts/setup_envs.py --course 2
```

请将依赖清单和更新后的锁定文件一并提交。不要提交 `.venv` 目录或仅适用于本机的 kernelspec 文件。

依赖版本特意与课程使用的旧版 API 保持兼容：**NumPy 1.23.5**、**TensorFlow 2.10.1**（Apple Silicon 上为 2.10.0）、**Keras 2.10.0** 和 **emoji 0.6.0**。课程使用了 `np.int`/`np.bool`、`Adam(lr=..., decay=...)`、SavedModel 加载，以及 `emoji.emojize(use_aliases=True)`；新版依赖已移除或改变这些接口。实验目录中的旧版 `requirements.txt` 仅作为历史记录保留。请使用对应课程环境，不要在其上叠加安装这份面向 Python 3.7 的旧依赖列表。

安装脚本检查的是环境能否正常运行，不验证练习答案。原始 Notebook 中仍有待完成的作业。大型数据集、预训练权重和 tokenizer 由下面的资料包恢复流程提供；Coursera 专用评分服务不在本地环境中提供。仓库包含两处小范围兼容性修复：风格迁移实验使用 Pillow 保存图像，以替代已移除的 `scipy.misc.imsave`；命名实体识别（NER）Notebook 的安装单元格使用 `%pip` 安装锁定版本的 seqeval，确保安装到当前选定的内核环境。音频检查覆盖课程中的 WAV/MIDI 处理；可选的 MP3 转换需要在系统中另行安装 FFmpeg。

### 自动获取课程资料

全部 **2,758 个补充文件**（包括原先由 Git 跟踪的 39 个文件）统一由 [supplements-v1 Release](https://github.com/Ghpt6/Deep-Learning-Specialization-Coursera/releases/tag/supplements-v1) 中的无损 `tar.gz` 资料包提供，不再由 Git 跟踪，未使用 Git LFS。克隆仓库后，运行 setup 即可自动恢复到对应的实验目录。压缩包约 **3.23 GiB**，按顺序分为 **13 卷**，每卷不超过 **256 MiB**，均低于 Release 的 2 GiB 单附件上限。资料展开后约占 **3.84 GiB**，首次安装还需要为压缩包缓存及课程环境预留磁盘空间。

`setup.ps1` / `setup.sh` 会先根据 `supplements/manifest.json` 校验所选课程的文件大小和 SHA-256。完整文件保持不变；全部完整时不会下载资料包。需要补齐时，脚本优先复用 `downloads/supplements/releases/` 中的缓存，否则从固定版本的公开 Release 下载。分卷和完整压缩流通过校验后，脚本自动按原目录还原缺失或损坏的文件，再继续配置环境。原本存在但校验不一致的文件会先备份到该缓存目录的 `backups/` 中。重复运行会跳过有效资料；`-CheckOnly` / `--check-only` 只检查，不下载或修复。

资料包统一包含全部课程；即使只安装一门课程，首次补齐也需要取得整个压缩包，但只还原所选课程的资料。公开 Release 的下载不要求 GitHub 登录。首次环境安装仍需访问依赖软件源。

如只需要恢复资料，可运行：

```bash
uv run --no-project --python 3.10.20 scripts/supplement_assets.py
uv run --no-project --python 3.10.20 scripts/supplement_assets.py --course 4 --check-only
```

维护者可用 `uv run --no-project python scripts/build_supplement_release.py --tag supplements-v2` 从已校验的本地资料生成新版本；输出位于被 Git 忽略的 `downloads/supplements/release/`。发布对应附件后，再提交更新后的清单。清单固定版本、文件路径、大小和校验值，不会自动追随 `latest`。全部补充资料与压缩包缓存均由 `.gitignore` 排除，恢复到本地后也不应再次提交到 Git。

## 如何完成练习

练习使用交互式 Python Notebook（`.ipynb`）。请在 VS Code 中打开文件，并选择对应课程的内核。也可以使用 [Google Colaboratory](https://colab.research.google.com/)、[Deepnote](https://deepnote.com/) 或 [Jupyter Notebook](https://jupyter.org/)。

欢迎 fork 本仓库供个人学习使用。如果发现内容缺失，请创建 GitHub issue 反馈。祝学习愉快！

## 重要说明

各实验 README 中保留了原作者的 Google Drive 来源链接。本仓库已汇总这些补充资料，并通过版本固定的 GitHub Release 资料包由 setup 自动获取，无需逐个访问云盘链接。
