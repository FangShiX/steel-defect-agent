import { useUserStore } from "@/stores/user";

export function createCameraWs(options) {
  let socket;
  let connected = false;
  let closing = false;
  let reconnectTimer;
  let reconnectAttempts = 0;
  const maxReconnectAttempts = 3;

  return {
    get isConnected() {
      return connected;
    },
    connect() {
      if (socket?.readyState === WebSocket.OPEN) return;
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = undefined;
      }
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const configuredBase = import.meta.env.VITE_WS_BASE_URL;
      const defaultBase = import.meta.env.DEV
        ? "ws://127.0.0.1:8000"
        : `${protocol}//${window.location.host}`;
      const wsBase = configuredBase || defaultBase;
      closing = false;
      const currentSocket = new WebSocket(`${wsBase}/api/detection/camera`);
      socket = currentSocket;
      currentSocket.onopen = () => {
        if (closing) {
          currentSocket.close();
          return;
        }
        connected = true;
        reconnectAttempts = 0;
        currentSocket.send(JSON.stringify({ type: "auth", token: useUserStore().token }));
        currentSocket.send(JSON.stringify({
          type: "config",
          mode: options.mode ?? "cpu",
          conf: options.conf ?? 0.25,
          iou: options.iou ?? 0.45,
          model_id: options.modelId,
        }));
      };
      currentSocket.onmessage = (event) => {
        if (closing) return;
        try {
          const data = JSON.parse(event.data);
          if (data.type === "result") options.onResult?.(data);
          else if (data.type === "config_ok") options.onConfigOk?.(data);
          else if (data.type === "frame_skipped") options.onFrameSkipped?.(data);
          else if (data.type === "error") {
            const detail = typeof data.detail === "string" ? data.detail : data.detail?.message;
            options.onError?.({
            code: data.code || "WEBSOCKET_ERROR",
            errorCode: data.error_code || data.code || "WEBSOCKET_ERROR",
            statusCode: data.status_code || 502,
            message: data.message || detail || "WebSocket request failed",
            detail: data.detail || { code: data.error_code || data.code || "WEBSOCKET_ERROR", message: data.message || detail || "WebSocket request failed" },
            requestId: data.request_id || "",
            taskId: data.task_id || null,
            sessionId: data.session_id || null,
            userId: data.user_id || null,
            retryable: Boolean(data.retryable),
            });
          }
        } catch {
          options.onError?.({ code: "INVALID_WEBSOCKET_RESPONSE", errorCode: "INVALID_WEBSOCKET_RESPONSE", statusCode: 502, message: "Invalid WebSocket response", detail: { code: "INVALID_WEBSOCKET_RESPONSE", message: "Invalid WebSocket response" }, requestId: "", retryable: false });
        }
      };
      currentSocket.onerror = () => {
        if (!closing) options.onError?.({ code: "WEBSOCKET_CONNECT_FAILED", errorCode: "WEBSOCKET_CONNECT_FAILED", statusCode: 503, message: "WebSocket connection failed", detail: { code: "WEBSOCKET_CONNECT_FAILED", message: "WebSocket connection failed" }, requestId: "", retryable: true });
      };
      currentSocket.onclose = (event) => {
        connected = false;
        options.onClose?.(event);
        if (!closing && reconnectAttempts < maxReconnectAttempts) {
          reconnectAttempts += 1;
          options.onReconnect?.(reconnectAttempts, maxReconnectAttempts);
          reconnectTimer = window.setTimeout(() => {
            reconnectTimer = undefined;
            if (!closing) this.connect();
          }, 500 * reconnectAttempts);
        } else if (!closing) {
          options.onReconnectFailed?.(event);
        }
      };
    },
    sendFrame(data) {
      if (closing || !connected || socket?.readyState !== WebSocket.OPEN || !data) return false;
      socket.send(JSON.stringify({ type: "frame", data }));
      return true;
    },
    close() {
      closing = true;
      reconnectAttempts = maxReconnectAttempts;
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = undefined;
      }
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "close" }));
        const closingSocket = socket;
        window.setTimeout(() => {
          if (closingSocket.readyState === WebSocket.OPEN) closingSocket.close(1000, "Client stopped");
        }, 100);
      } else if (socket?.readyState === WebSocket.CONNECTING) {
        const pendingSocket = socket;
        pendingSocket.addEventListener("open", () => pendingSocket.close(), { once: true });
      }
      socket = undefined;
      connected = false;
    },
  };
}
