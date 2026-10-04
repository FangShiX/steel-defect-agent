# SSDD: Steel Defect Agent

钢铁表面缺陷检测智能体平台。SSDD = **Steel Surface Defect Detection**。

Vue 3 + FastAPI，结合 YOLO 图像/视频检测、模型训练、LangGraph 多智能体、RAG 知识库、用户权限和文件生命周期管理。

这是供可信项目团队评估的 **v0.1.0 初始源码发行版**。代码公开不等于已有完整开源授权；来源与依赖许可见 [NOTICE.md](NOTICE.md)。模型权重、训练数据和真实 API 密钥单独配置，不随源码发布。另一个 GUI/HCI 项目不在此仓库内。

## 快速启动

需要 Python 3.10+（生成配置）、Docker Engine/Desktop 和 Docker Compose v2。

```bash
git clone https://github.com/FangShiX/steel-defect-agent.git
cd steel-defect-agent
python scripts/configure.py
docker compose --env-file .env -f docker-compose.yml up -d --build --wait --wait-timeout 300
```

首次构建会下载 CPU 版 PyTorch 等依赖。访问 <http://localhost:8080>；管理员用户名为 `admin`，密码在本机生成的 `.env` 的 `BOOTSTRAP_ADMIN_PASSWORD` 中。配置文件不会被覆盖，密码不会打印到构建或启动日志。开发端口只绑定本机。

Windows 也可使用：

```powershell
python scripts/configure.py
powershell -NoProfile -File scripts/start.ps1 -Build
powershell -NoProfile -File scripts/start.ps1 -Logs
powershell -NoProfile -File scripts/stop.ps1
```

PostgreSQL/pgvector、Redis、MinIO、后端和前端会依次启动。迁移和初始角色/场景由后端启动命令执行。普通 `docker compose down` 保留数据卷；不要对需要保留数据的环境使用 `down -v`。

## 模型与供应商配置

- **检测**：使用有权部署、可信来源的钢铁缺陷 `.pt` 权重，在管理员的模型管理页面上传并设为场景默认模型。空安装没有假模型或假检测结果。`.pt` 可执行代码，上传权限限制为可信模型管理员。
- **训练**：先上传具有有效标签和独立训练/验证图片的数据集。默认容器使用 CPU；GPU 需要额外配置兼容的 CUDA/PyTorch 镜像和 NVIDIA Container Toolkit。
- **智能体**：在私有 `.env` 中设置 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `OPENAI_MODEL`，然后重建后端容器。未配置时相关接口返回明确的不可用错误。
- **RAG**：设置 `EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`。嵌入模型输出必须为 **768 维**；系统会校验维度。上传内容将发送至你配置的供应商。

## 生产配置

```bash
python scripts/configure.py --production --origin https://your-domain.example
# 在 .env.production 中配置供应商、邮件、管理员邮箱等真实值。
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build --wait --wait-timeout 300
```

生产 Compose 是完整独立配置，不与开发 Compose 合并。仅应用端口对外暴露，后端及数据库/缓存/对象存储没有宿主机发布端口。以 HTTPS 反向代理提供公网访问，并限制应用端口直接访问。生产模式拒绝示例密钥和通配符/localhost CORS。运行数据写入专用 volumes。

## 验证与源码包

```bash
cd backend
python -m venv .venv
# 激活该环境后：先安装 CPU 版 torch/torchvision，版本见 Dockerfile。
pip install -r requirements-dev.txt
pytest -q
cd ../frontend
npm ci
npm run test:run
npm run build
cd ..
python scripts/package-release.py
```

GitHub CI 执行回归测试、真实 PostgreSQL/pgvector 迁移、依赖与凭据扫描，以及完整容器栈的登录、数据库/对象存储文件生命周期和 CPU 推理引擎冒烟检查。源码 ZIP 及 SHA-256 不包含秘密配置、历史教学材料、权重、数据集或运行记录。

维护说明见 [发布验收](docs/RELEASE.md)、[安全说明](SECURITY.md)、[文件生命周期](docs/file-lifecycle.md)、[数据集导入](docs/training_dataset_import.md) 和 [变更记录](CHANGELOG.md)。

## 验证边界

发行验证覆盖可安装性、API 合约、权限隔离、数据库迁移、文件生命周期和最小运行流程。模型准确率、真实业务训练效果、GPU/长视频/并发容量、外部 LLM/RAG 质量以及云端生产部署，须由具体模型、账户、数据和硬件另行验收。不要将示例或冒烟推理视为钢铁缺陷检测质量指标。
