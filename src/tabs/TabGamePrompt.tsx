// src/tabs/TabGamePrompt.tsx - ゲーム別プロンプト設定タブ

import {
    PanelSection,
    PanelSectionRow,
    Field,
    Focusable,
    Router
} from "@decky/ui";
import { call } from "@decky/api";

import { VFC, useState, useEffect } from "react";
import { useSettings } from "../SettingsContext";

export const TabGamePrompt: VFC = () => {
    const { settings } = useSettings();
    const [gameInfo, setGameInfo] = useState<{
        appId: number;
        displayName: string;
        filePath: string;
        content: string;
    } | null>(null);
    const [editContent, setEditContent] = useState("");

    useEffect(() => {
        if (settings.translationProvider !== 'llm') return;

        const mainApp = Router.MainRunningApp;
        if (!mainApp?.appid) return;

        const appId = Number(mainApp.appid);
        const displayName = mainApp.display_name || "";

        call<any>('ensure_game_prompt_file', appId, displayName).then(result => {
            if (result && !result.error) {
                setGameInfo({
                    appId: result.app_id,
                    displayName: displayName,
                    filePath: result.file_path,
                    content: result.content,
                });
                setEditContent(result.content);
            }
        });
    }, [settings.translationProvider]);

    const handleBlur = () => {
        if (gameInfo && editContent !== gameInfo.content) {
            call('save_game_prompt', gameInfo.appId, editContent);
            setGameInfo({ ...gameInfo, content: editContent });
        }
    };

    // LLMプロバイダー未選択時
    if (settings.translationProvider !== 'llm') {
        return (
            <div style={{ marginLeft: "-8px", marginRight: "-8px", paddingBottom: "40px" }}>
                <PanelSection title="Game-Specific Prompt">
                    <PanelSectionRow>
                        <Field focusable={true} childrenContainerWidth="max">
                            <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                                <div>Game-specific prompts are only available with the LLM translation provider.</div>
                                <div style={{ marginTop: "4px" }}>Select "LLM (OpenAI-compatible)" in the Translation tab to use this feature.</div>
                            </div>
                        </Field>
                    </PanelSectionRow>
                </PanelSection>
            </div>
        );
    }

    // ゲーム未起動時
    if (!gameInfo) {
        return (
            <div style={{ marginLeft: "-8px", marginRight: "-8px", paddingBottom: "40px" }}>
                <PanelSection title="Game-Specific Prompt">
                    <PanelSectionRow>
                        <Field focusable={true} childrenContainerWidth="max">
                            <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                                <div>No game is currently running.</div>
                                <div style={{ marginTop: "4px" }}>Launch a game to configure game-specific translation prompts.</div>
                            </div>
                        </Field>
                    </PanelSectionRow>
                </PanelSection>
            </div>
        );
    }

    return (
        <div style={{ marginLeft: "-8px", marginRight: "-8px", paddingBottom: "40px" }}>
            <PanelSection title="Game-Specific Prompt">
                <PanelSectionRow>
                    <Field focusable={true} childrenContainerWidth="max">
                        <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                            <div><span style={{ color: "#dcdedf" }}>{gameInfo.displayName}</span> (App ID: {gameInfo.appId})</div>
                            <div style={{ fontSize: "11px", wordBreak: "break-all", marginTop: "2px" }}>{gameInfo.filePath}</div>
                        </div>
                    </Field>
                </PanelSectionRow>
                <PanelSectionRow>
                    <Field label="Prompt" childrenContainerWidth="max">
                        <Focusable onBlur={handleBlur}>
                            <textarea
                                value={editContent}
                                onChange={(e) => setEditContent(e.target.value)}
                                rows={8}
                                style={{
                                    width: "100%",
                                    backgroundColor: "#3d4450",
                                    color: "#dcdedf",
                                    border: "1px solid #4c5564",
                                    borderRadius: "4px",
                                    padding: "8px",
                                    fontSize: "13px",
                                    lineHeight: "1.5",
                                    resize: "vertical",
                                    fontFamily: "inherit",
                                }}
                                placeholder="Glossary, tone, and instructions for this game..."
                            />
                        </Focusable>
                        <div style={{ color: "#8b929a", fontSize: "11px", marginTop: "4px" }}>
                            Also editable via SSH. Saved on focus out.
                        </div>
                    </Field>
                </PanelSectionRow>
            </PanelSection>

            {/* Invisible spacer to help with scroll when focusing last element */}
            <PanelSection>
                <PanelSectionRow>
                    <Focusable
                        style={{ height: "1px", opacity: 0 }}
                        onActivate={() => {}}
                    />
                </PanelSectionRow>
            </PanelSection>
        </div>
    );
};
