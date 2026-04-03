// src/tabs/TabPrompts.tsx - Gemini プロンプト設定タブ

import {
    PanelSection,
    PanelSectionRow,
    Field,
    Focusable,
    Router
} from "@decky/ui";
import { call } from "@decky/api";

import { CSSProperties, VFC, useState, useEffect } from "react";
import { useSettings } from "../SettingsContext";

interface PromptFileResponse {
    content?: string;
    file_path?: string;
    error?: string;
}

const textareaStyle: CSSProperties = {
    width: "100%",
    backgroundColor: "#3d4450",
    color: "#dcdedf",
    border: "1px solid #4c5564",
    borderRadius: "4px",
    padding: "8px",
    fontSize: "13px",
    lineHeight: "1.5",
    resize: "vertical" as const,
    fontFamily: "inherit",
};

const PromptEditor: VFC<{
    label: string;
    value: string;
    filePath?: string;
    placeholder?: string;
    onChange: (value: string) => void;
    onBlur: () => void;
}> = ({ label, value, filePath, placeholder, onChange, onBlur }) => (
    <PanelSectionRow>
        <Field label={label} childrenContainerWidth="max">
            <Focusable onBlur={onBlur}>
                <textarea
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    rows={6}
                    style={textareaStyle}
                    placeholder={placeholder}
                />
            </Focusable>
            {filePath && (
                <div style={{ color: "#8b929a", fontSize: "11px", marginTop: "4px", wordBreak: "break-all" }}>
                    {filePath}
                </div>
            )}
            <div style={{ color: "#8b929a", fontSize: "11px", marginTop: "2px" }}>
                SSH編集可。フォーカスアウトで保存。
            </div>
        </Field>
    </PanelSectionRow>
);

export const TabPrompts: VFC = () => {
    const { settings } = useSettings();
    const [commonContent, setCommonContent] = useState("");
    const [commonPath, setCommonPath] = useState("");
    const [commonSaved, setCommonSaved] = useState("");
    const [gameInfo, setGameInfo] = useState<{
        appId: number;
        displayName: string;
    } | null>(null);
    const [gameContent, setGameContent] = useState("");
    const [gamePath, setGamePath] = useState("");
    const [gameSaved, setGameSaved] = useState("");

    useEffect(() => {
        call<[], PromptFileResponse | null>('get_common_vision_prompt').then(result => {
            if (!result) return;
            setCommonContent(result.content || "");
            setCommonPath(result.file_path || "");
            setCommonSaved(result.content || "");
        });
    }, [settings.geminiModel, settings.geminiBaseUrl]);

    useEffect(() => {
        const mainApp = Router.MainRunningApp;
        if (!mainApp?.appid) {
            setGameInfo(null);
            return;
        }

        const appId = Number(mainApp.appid);
        const displayName = mainApp.display_name || "";
        setGameInfo({ appId, displayName });

        call<[number, string], PromptFileResponse | null>('ensure_game_vision_prompt_file', appId, displayName).then(result => {
            if (!result || result.error) return;
            setGameContent(result.content || "");
            setGamePath(result.file_path || "");
            setGameSaved(result.content || "");
        });
    }, [settings.geminiModel, settings.geminiBaseUrl]);

    const saveCommon = async () => {
        if (commonContent !== commonSaved) {
            const saving = commonContent;
            try {
                const ok = await call<[string], boolean>('save_common_vision_prompt', saving);
                if (ok) {
                    setCommonSaved(saving);
                }
            } catch {}
        }
    };

    const saveGame = async () => {
        if (gameInfo && gameContent !== gameSaved) {
            const saving = gameContent;
            try {
                const ok = await call<[number, string], boolean>('save_game_vision_prompt', gameInfo.appId, saving);
                if (ok) {
                    setGameSaved(saving);
                }
            } catch {}
        }
    };

    return (
        <div style={{ marginLeft: "-8px", marginRight: "-8px", paddingBottom: "40px" }}>
            <PanelSection title="Common Gemini Instructions">
                <PanelSectionRow>
                    <Field focusable={true} childrenContainerWidth="max">
                        <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                            Instructions applied to all games for Gemini Vision translation.
                        </div>
                    </Field>
                </PanelSectionRow>
                <PromptEditor
                    label="Gemini Instructions"
                    value={commonContent}
                    filePath={commonPath}
                    placeholder="Ignore HUD numbers. Focus on dialog. Keep terminology consistent..."
                    onChange={setCommonContent}
                    onBlur={saveCommon}
                />
            </PanelSection>

            {gameInfo ? (
                <PanelSection title={`Game: ${gameInfo.displayName}`}>
                    <PanelSectionRow>
                        <Field focusable={true} childrenContainerWidth="max">
                            <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                                App ID: {gameInfo.appId}
                            </div>
                        </Field>
                    </PanelSectionRow>
                    <PromptEditor
                        label="Game Gemini Instructions"
                        value={gameContent}
                        filePath={gamePath}
                        placeholder="Glossary, tone, and special rules for this game..."
                        onChange={setGameContent}
                        onBlur={saveGame}
                    />
                </PanelSection>
            ) : (
                <PanelSection title="Game-Specific Gemini Instructions">
                    <PanelSectionRow>
                        <Field focusable={true} childrenContainerWidth="max">
                            <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                                Launch a game to edit game-specific Gemini instructions.
                            </div>
                        </Field>
                    </PanelSectionRow>
                </PanelSection>
            )}
        </div>
    );
};
