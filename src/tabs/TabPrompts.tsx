// src/tabs/TabPrompts.tsx - プロンプト設定タブ（共通 + ゲーム別、Text + Vision）

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

// textarea共通スタイル
const textareaStyle = {
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
};

// プロンプト編集ブロック
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

    // 共通プロンプト状態
    const [commonTextContent, setCommonTextContent] = useState("");
    const [commonTextPath, setCommonTextPath] = useState("");
    const [commonTextSaved, setCommonTextSaved] = useState("");
    const [commonVisionContent, setCommonVisionContent] = useState("");
    const [commonVisionPath, setCommonVisionPath] = useState("");
    const [commonVisionSaved, setCommonVisionSaved] = useState("");

    // ゲーム別プロンプト状態
    const [gameInfo, setGameInfo] = useState<{
        appId: number;
        displayName: string;
    } | null>(null);
    const [gameTextContent, setGameTextContent] = useState("");
    const [gameTextPath, setGameTextPath] = useState("");
    const [gameTextSaved, setGameTextSaved] = useState("");
    const [gameVisionContent, setGameVisionContent] = useState("");
    const [gameVisionPath, setGameVisionPath] = useState("");
    const [gameVisionSaved, setGameVisionSaved] = useState("");

    const isTextLlm = settings.translationProvider === 'llm';
    const isVisionActive = settings.visionMode !== 'off';

    // 共通プロンプト読み込み
    useEffect(() => {
        if (isTextLlm) {
            call<any>('get_common_text_prompt').then(result => {
                if (result) {
                    setCommonTextContent(result.content || "");
                    setCommonTextPath(result.file_path || "");
                    setCommonTextSaved(result.content || "");
                }
            });
        }

        if (isVisionActive) {
            call<any>('get_common_vision_prompt').then(result => {
                if (result) {
                    setCommonVisionContent(result.content || "");
                    setCommonVisionPath(result.file_path || "");
                    setCommonVisionSaved(result.content || "");
                }
            });
        }
    }, [settings.translationProvider, settings.visionMode]);

    // ゲーム別プロンプト読み込み
    useEffect(() => {
        if (!isTextLlm && !isVisionActive) return;

        const mainApp = Router.MainRunningApp;
        if (!mainApp?.appid) {
            setGameInfo(null);
            return;
        }

        const appId = Number(mainApp.appid);
        const displayName = mainApp.display_name || "";

        setGameInfo({ appId, displayName });

        if (isTextLlm) {
            call<any>('ensure_game_text_prompt_file', appId, displayName).then(result => {
                if (result && !result.error) {
                    setGameTextContent(result.content || "");
                    setGameTextPath(result.file_path || "");
                    setGameTextSaved(result.content || "");
                }
            });
        }

        if (isVisionActive) {
            call<any>('ensure_game_vision_prompt_file', appId, displayName).then(result => {
                if (result && !result.error) {
                    setGameVisionContent(result.content || "");
                    setGameVisionPath(result.file_path || "");
                    setGameVisionSaved(result.content || "");
                }
            });
        }
    }, [settings.translationProvider, settings.visionMode]);

    // 保存ハンドラ（失敗時は saved state を更新しない。ユーザーの編集中テキストには触らない）
    const saveCommonText = async () => {
        if (commonTextContent !== commonTextSaved) {
            const saving = commonTextContent;
            try {
                const ok = await call<boolean>('save_common_text_prompt', saving);
                if (ok) { setCommonTextSaved(saving); }
            } catch { /* saved state 未更新 = 次回 blur で再試行 */ }
        }
    };
    const saveCommonVision = async () => {
        if (commonVisionContent !== commonVisionSaved) {
            const saving = commonVisionContent;
            try {
                const ok = await call<boolean>('save_common_vision_prompt', saving);
                if (ok) { setCommonVisionSaved(saving); }
            } catch { /* saved state 未更新 = 次回 blur で再試行 */ }
        }
    };
    const saveGameText = async () => {
        if (gameInfo && gameTextContent !== gameTextSaved) {
            const saving = gameTextContent;
            try {
                const ok = await call<boolean>('save_game_text_prompt', gameInfo.appId, saving);
                if (ok) { setGameTextSaved(saving); }
            } catch { /* saved state 未更新 = 次回 blur で再試行 */ }
        }
    };
    const saveGameVision = async () => {
        if (gameInfo && gameVisionContent !== gameVisionSaved) {
            const saving = gameVisionContent;
            try {
                const ok = await call<boolean>('save_game_vision_prompt', gameInfo.appId, saving);
                if (ok) { setGameVisionSaved(saving); }
            } catch { /* saved state 未更新 = 次回 blur で再試行 */ }
        }
    };

    // Text LLMもVisionも未使用の場合
    if (!isTextLlm && !isVisionActive) {
        return (
            <div style={{ marginLeft: "-8px", marginRight: "-8px", paddingBottom: "40px" }}>
                <PanelSection title="Prompts">
                    <PanelSectionRow>
                        <Field focusable={true} childrenContainerWidth="max">
                            <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                                <div>Prompt settings require LLM translation or Vision mode.</div>
                                <div style={{ marginTop: "4px" }}>Select "LLM" in Translation tab, or enable Vision Mode.</div>
                            </div>
                        </Field>
                    </PanelSectionRow>
                </PanelSection>
            </div>
        );
    }

    return (
        <div style={{ marginLeft: "-8px", marginRight: "-8px", paddingBottom: "40px" }}>
            {/* 共通Text指示（Text LLM使用時のみ） */}
            {isTextLlm && (
                <PanelSection title="Common Text Instructions">
                    <PanelSectionRow>
                        <Field focusable={true} childrenContainerWidth="max">
                            <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                                All games, text translation. e.g. abbreviation rules, tone, terminology.
                            </div>
                        </Field>
                    </PanelSectionRow>
                    <PromptEditor
                        label="Text Instructions"
                        value={commonTextContent}
                        filePath={commonTextPath}
                        placeholder="Keep HP, MP, EXP unchanged. Translate UI labels concisely..."
                        onChange={setCommonTextContent}
                        onBlur={saveCommonText}
                    />
                </PanelSection>
            )}

            {/* 共通Vision指示（Vision有効時のみ） */}
            {isVisionActive && (
                <PanelSection title="Common Vision Instructions">
                    <PanelSectionRow>
                        <Field focusable={true} childrenContainerWidth="max">
                            <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                                All games, vision translation. e.g. ignore edge UI, focus on dialog.
                            </div>
                        </Field>
                    </PanelSectionRow>
                    <PromptEditor
                        label="Vision Instructions"
                        value={commonVisionContent}
                        filePath={commonVisionPath}
                        placeholder="Ignore HUD numbers. Focus on dialog text. Ignore screen-edge UI..."
                        onChange={setCommonVisionContent}
                        onBlur={saveCommonVision}
                    />
                </PanelSection>
            )}

            {/* ゲーム別プロンプト */}
            {gameInfo ? (
                <>
                    <PanelSection title={`Game: ${gameInfo.displayName}`}>
                        <PanelSectionRow>
                            <Field focusable={true} childrenContainerWidth="max">
                                <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                                    App ID: {gameInfo.appId}
                                </div>
                            </Field>
                        </PanelSectionRow>
                        {isTextLlm && (
                            <PromptEditor
                                label="Game Text Instructions"
                                value={gameTextContent}
                                filePath={gameTextPath}
                                placeholder="Glossary and tone for this game's text translation..."
                                onChange={setGameTextContent}
                                onBlur={saveGameText}
                            />
                        )}
                        {isVisionActive && (
                            <PromptEditor
                                label="Game Vision Instructions"
                                value={gameVisionContent}
                                filePath={gameVisionPath}
                                placeholder="Vision-specific instructions for this game..."
                                onChange={setGameVisionContent}
                                onBlur={saveGameVision}
                            />
                        )}
                    </PanelSection>
                </>
            ) : (
                <PanelSection title="Game-Specific">
                    <PanelSectionRow>
                        <Field focusable={true} childrenContainerWidth="max">
                            <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                                No game running. Launch a game to configure game-specific prompts.
                            </div>
                        </Field>
                    </PanelSectionRow>
                </PanelSection>
            )}

            {/* スクロール用スペーサー */}
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
