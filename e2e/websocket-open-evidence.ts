export type OpenSocketEvidence = {
  opened: number;
  closed: number;
  active: number;
  maximum: number;
};

declare global {
  interface Window {
    __nexolabOpenSocketEvidence: OpenSocketEvidence;
  }
}

/** Browser init script: connecting/closing transports are not live consumers. */
export function installOpenSocketEvidence(): void {
  const NativeWebSocket = window.WebSocket;
  const sockets = new Set<WebSocket>();
  const evidence = { opened: 0, closed: 0, active: 0, maximum: 0 };
  window.__nexolabOpenSocketEvidence = evidence;

  const recount = () => {
    evidence.active = [...sockets].filter((socket) => socket.readyState === NativeWebSocket.OPEN).length;
    evidence.maximum = Math.max(evidence.maximum, evidence.active);
  };

  window.WebSocket = new Proxy(NativeWebSocket, {
    construct(target, args, newTarget) {
      const socket = Reflect.construct(target, args, newTarget) as WebSocket;
      sockets.add(socket);
      socket.addEventListener("open", () => {
        evidence.opened += 1;
        recount();
      });
      socket.addEventListener("close", () => {
        evidence.closed += 1;
        sockets.delete(socket);
        recount();
      });
      const nativeClose = socket.close;
      socket.close = function (...closeArgs: Parameters<WebSocket["close"]>) {
        try {
          return nativeClose.apply(this, closeArgs);
        } finally {
          // close() enters CLOSING synchronously; its close event arrives later.
          recount();
        }
      };
      recount();
      return socket;
    },
  });
}
