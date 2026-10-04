# 文件落库与生命周期

## 数据链路

```text
前端上传
  -> POST /api/files
  -> MinIO 写入对象
  -> stored_files 写入元数据
  -> 返回短期 download_url
```

文件元数据包含：用户、对象键、原始文件名、MIME 类型、文件大小、SHA-256、资源类型、业务资源 ID、生命周期状态和清理错误。

## 接口

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/files` | 上传文件并同时写入 MinIO 与 `stored_files` |
| GET | `/api/files` | 查询当前用户文件；管理员可查看全部 |
| GET | `/api/files/{file_id}` | 查询单个文件并生成短期下载地址 |
| POST | `/api/files/{file_id}/archive` | 归档文件，保留对象和元数据 |
| POST | `/api/files/{file_id}/restore` | 将归档文件恢复为使用中 |
| DELETE | `/api/files/{file_id}` | 标记删除并尝试删除 MinIO 对象 |

上传表单字段：

```text
file          文件内容
resource_type image/video/dataset/model/document/generic
resource_id   可选的业务资源 ID
```

## 生命周期状态

```text
active
  -> archived
  -> active
  -> deleted

active / archived
  -> cleanup_pending   MinIO 删除失败，需要人工或定时任务重试
```

`deleted` 采用软删除方式保留数据库台账；`cleanup_pending` 用于记录数据库状态已更新但对象存储清理失败的情况。接口不会把 MinIO 访问密钥返回给前端，只返回短期预签名下载地址。

## 页面

前端页面：`frontend/src/views/FilesPage.vue`

访问路径：`/files`

页面显示：

- 当前文件数；
- 使用中文件数；
- 已归档文件数；
- 待清理文件数；
- 原始文件名、大小、资源类型和对象键；
- 创建时间和生命周期状态；
- 下载、归档、恢复和删除操作。

## 验收重点

1. 上传成功时，MinIO 对象和数据库记录同时存在。
2. 数据库提交失败时，服务尝试回删已经上传的对象。
3. 普通用户只能访问自己的文件。
4. 删除失败时记录 `cleanup_pending` 和错误原因。
5. 归档文件不能被误删，恢复后可以继续生成下载地址。
6. 数据库迁移必须执行 `alembic upgrade head`，禁止手工建表。
