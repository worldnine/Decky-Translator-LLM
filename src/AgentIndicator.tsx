// AgentIndicator.tsx
// 外部Agentの操作を通知するインジケーター
// mode: "dot"=🔴のみ, "thumbnail"=スクショ, "message"=テキスト

import { VFC, useState, useEffect, useRef } from "react";
import { call } from "@decky/api";
import { Router } from "@decky/ui";

const POLL_INTERVAL = 2000;
const INDICATOR_DURATION = 3000;

interface AgentNotification {
    mode: "dot" | "thumbnail" | "message";
    purpose?: string;
    timestamp: string;
    thumbnail?: string;
}

export const AgentIndicator: VFC = () => {
    const [visible, setVisible] = useState(false);
    const [notification, setNotification] = useState<AgentNotification | null>(null);
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        const poll = async () => {
            try {
                // ゲーム情報をバックエンドに同期（CLI の game サブコマンド用）
                const mainApp = (Router as any).MainRunningApp;
                if (mainApp?.appid) {
                    call("agent_set_running_game", Number(mainApp.appid), mainApp.display_name || "").catch(() => {});
                } else {
                    call("agent_set_running_game", null, null).catch(() => {});
                }

                const notifications = await call<[], AgentNotification[]>("agent_poll_notifications");
                if (notifications && notifications.length > 0) {
                    const latest = notifications[notifications.length - 1];
                    setNotification(latest);
                    setVisible(true);

                    if (timerRef.current) clearTimeout(timerRef.current);
                    timerRef.current = setTimeout(() => setVisible(false), INDICATOR_DURATION);
                }
            } catch {
                // agent RPCが未対応の場合は無視
            }
        };

        const interval = setInterval(poll, POLL_INTERVAL);
        return () => {
            clearInterval(interval);
            if (timerRef.current) clearTimeout(timerRef.current);
        };
    }, []);

    if (!visible || !notification) return null;

    const { mode, purpose, thumbnail } = notification;

    // dot モード: 🔴 のみ
    if (mode === "dot") {
        return (
            <div style={{
                position: "fixed",
                top: 16,
                left: 16,
                zIndex: 99999,
                pointerEvents: "none",
            }}>
                <div style={{
                    width: 12,
                    height: 12,
                    borderRadius: "50%",
                    background: "#e53935",
                    boxShadow: "0 0 8px rgba(229, 57, 53, 0.6)",
                }} />
            </div>
        );
    }

    // thumbnail モード: スクショサムネイルのみ
    if (mode === "thumbnail" && thumbnail) {
        return (
            <div style={{
                position: "fixed",
                top: 12,
                left: 12,
                zIndex: 99999,
                pointerEvents: "none",
            }}>
                <img src={thumbnail} style={{
                    maxWidth: 120,
                    maxHeight: 75,
                    borderRadius: 6,
                    border: "2px solid rgba(255,255,255,0.3)",
                    boxShadow: "0 2px 12px rgba(0,0,0,0.5)",
                }} />
            </div>
        );
    }

    // message モード: テキストのみ
    if (mode === "message" && purpose) {
        return (
            <div style={{
                position: "fixed",
                top: 12,
                left: 12,
                zIndex: 99999,
                pointerEvents: "none",
                background: "rgba(0, 0, 0, 0.85)",
                borderRadius: 8,
                padding: "6px 12px",
                maxWidth: 250,
            }}>
                <span style={{ color: "#ccc", fontSize: 12, lineHeight: "1.3" }}>
                    {purpose}
                </span>
            </div>
        );
    }

    // フォールバック: dot
    return (
        <div style={{
            position: "fixed",
            top: 16,
            right: 16,
            zIndex: 99999,
            pointerEvents: "none",
        }}>
            <div style={{
                width: 12,
                height: 12,
                borderRadius: "50%",
                background: "#e53935",
                boxShadow: "0 0 8px rgba(229, 57, 53, 0.6)",
            }} />
        </div>
    );
};
