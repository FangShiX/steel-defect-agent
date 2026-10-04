import request from "@/utils/request";

function unwrap(payload) {
  return payload?.data ?? payload;
}

export function normalizeStoredFile(file = {}) {
  return {
    id: file.id,
    userId: file.user_id ?? file.userId,
    objectKey: file.object_key ?? file.objectKey ?? "",
    originalFilename: file.original_filename ?? file.originalFilename ?? "",
    contentType: file.content_type ?? file.contentType ?? "",
    fileSize: Number(file.file_size ?? file.fileSize ?? 0),
    checksum: file.checksum ?? "",
    resourceType: file.resource_type ?? file.resourceType ?? "generic",
    resourceId: file.resource_id ?? file.resourceId ?? "",
    status: file.status ?? "active",
    cleanupError: file.cleanup_error ?? file.cleanupError ?? "",
    downloadUrl: file.download_url ?? file.downloadUrl ?? "",
    createdAt: file.created_at ?? file.createdAt ?? "",
    updatedAt: file.updated_at ?? file.updatedAt ?? "",
    archivedAt: file.archived_at ?? file.archivedAt ?? "",
    deletedAt: file.deleted_at ?? file.deletedAt ?? "",
  };
}

export async function getStoredFilesApi(includeDeleted = false) {
  const data = unwrap(await request.get("/files", { params: { include_deleted: includeDeleted } }));
  return (Array.isArray(data) ? data : data?.items || []).map(normalizeStoredFile);
}

export async function uploadStoredFileApi(file, resourceType = "generic", resourceId = "") {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("resource_type", resourceType);
  if (resourceId) formData.append("resource_id", resourceId);
  return normalizeStoredFile(await request.post("/files", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  }));
}

export async function archiveStoredFileApi(id) {
  return normalizeStoredFile(await request.post(`/files/${id}/archive`));
}

export async function restoreStoredFileApi(id) {
  return normalizeStoredFile(await request.post(`/files/${id}/restore`));
}

export async function deleteStoredFileApi(id) {
  return normalizeStoredFile(await request.delete(`/files/${id}`));
}
