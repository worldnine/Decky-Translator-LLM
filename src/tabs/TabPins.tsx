// src/tabs/TabPins.tsx - Pin history tab

import {
    PanelSection,
    PanelSectionRow,
    ButtonItem,
    Field
} from "@decky/ui";

import { VFC, useState, useEffect } from "react";
import { call } from "@decky/api";
import { Router } from "@decky/ui";
import { useSettings } from "../SettingsContext";
import { logger } from "../Logger";

interface PinRecord {
    pin_id: string;
    created_at: string;
    app_id: number;
    game_name: string;
    trigger: string;
    analysis_status: string;
    recognized_text: string;
    translated_text: string;
    error: string | null;
}

const formatTime = (isoString: string): string => {
    try {
        // "2026-04-07T01:19:56.195768" → "04/07 01:19"
        const d = isoString.replace("T", " ").slice(0, 16);
        const parts = d.split(" ");
        const datePart = parts[0].slice(5); // "04-07"
        const timePart = parts[1]; // "01:19"
        return `${datePart.replace("-", "/")} ${timePart}`;
    } catch {
        return isoString.slice(0, 16);
    }
};

const statusLabel = (status: string): { text: string; color: string } => {
    switch (status) {
        case "complete": return { text: "Analyzed", color: "#4caf50" };
        case "pending": return { text: "Analyzing...", color: "#ff9800" };
        case "failed": return { text: "Analysis failed", color: "#f44336" };
        case "skipped_config_missing": return { text: "Skipped (no config)", color: "#888" };
        default: return { text: status, color: "#888" };
    }
};

const truncate = (text: string, maxLen: number): string => {
    if (!text) return "";
    const oneLine = text.replace(/\n/g, " ").trim();
    return oneLine.length > maxLen ? oneLine.slice(0, maxLen) + "…" : oneLine;
};

export const TabPins: VFC = () => {
    const { settings } = useSettings();
    const [pins, setPins] = useState<PinRecord[]>([]);
    const [loading, setLoading] = useState(false);

    const loadPins = async () => {
        setLoading(true);
        try {
            const mainApp = Router.MainRunningApp;
            const appId = mainApp?.appid ? Number(mainApp.appid) : 0;
            if (!appId) {
                setPins([]);
                return;
            }
            const result = await call<[number, number], PinRecord[]>('list_pin_history', appId, 20);
            setPins(result || []);
        } catch (err) {
            logger.error('TabPins', 'Failed to load pins', err);
            setPins([]);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadPins();
    }, []);

    if (!settings.advancedFeaturesEnabled || !settings.pinFeatureEnabled) {
        return null;
    }

    return (
        <div style={{ marginLeft: "-8px", marginRight: "-8px", paddingBottom: "40px" }}>
            <PanelSection title="Pins">
                <PanelSectionRow>
                    <ButtonItem
                        layout="below"
                        onClick={loadPins}
                        disabled={loading}
                    >
                        {loading ? "Loading..." : "Refresh"}
                    </ButtonItem>
                </PanelSectionRow>

                {pins.length === 0 && !loading && (
                    <PanelSectionRow>
                        <Field focusable={false}>
                            <div style={{ color: "#888", fontSize: "12px", textAlign: "center", padding: "16px 0" }}>
                                No pins yet for this game
                            </div>
                        </Field>
                    </PanelSectionRow>
                )}

                {pins.map((pin) => {
                    const status = statusLabel(pin.analysis_status);
                    const preview = truncate(pin.translated_text || pin.recognized_text, 80);
                    return (
                        <PanelSectionRow key={pin.pin_id}>
                            <Field focusable={true} childrenContainerWidth="max">
                                <div style={{
                                    padding: "8px 0",
                                    borderBottom: "1px solid rgba(255,255,255,0.05)",
                                }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                                        <span style={{ color: "#aaa", fontSize: "11px" }}>
                                            {formatTime(pin.created_at)}
                                        </span>
                                        <span style={{ color: status.color, fontSize: "10px" }}>
                                            {status.text}
                                        </span>
                                    </div>
                                    {preview && (
                                        <div style={{ color: "#dcdedf", fontSize: "12px", lineHeight: "1.4" }}>
                                            {preview}
                                        </div>
                                    )}
                                    {!preview && pin.analysis_status === "complete" && (
                                        <div style={{ color: "#888", fontSize: "11px", fontStyle: "italic" }}>
                                            No text detected
                                        </div>
                                    )}
                                    {pin.error && (
                                        <div style={{ color: "#f44336", fontSize: "10px", marginTop: "2px" }}>
                                            {truncate(pin.error, 60)}
                                        </div>
                                    )}
                                </div>
                            </Field>
                        </PanelSectionRow>
                    );
                })}
            </PanelSection>
        </div>
    );
};
