// src/tabs/TabTranslation.tsx - Language settings and prompt editing

import {
    PanelSection,
    PanelSectionRow,
    DropdownItem,
    Field,
    Focusable,
    Router
} from "@decky/ui";
import { call } from "@decky/api";

import { CSSProperties, VFC, useState, useEffect } from "react";
import { useSettings } from "../SettingsContext";

const languageOptions = [
    { label: "\u{1F310} Auto-detect", data: "auto" },
    { label: "\u{1F1EC}\u{1F1E7} English", data: "en" },
    { label: "\u{1F1EA}\u{1F1F8} Spanish", data: "es" },
    { label: "\u{1F1EB}\u{1F1F7} French", data: "fr" },
    { label: "\u{1F1E9}\u{1F1EA} German", data: "de" },
    { label: "\u{1F1EC}\u{1F1F7} Greek", data: "el" },
    { label: "\u{1F1EE}\u{1F1F9} Italian", data: "it" },
    { label: "\u{1F1F5}\u{1F1F9} Portuguese", data: "pt" },
    { label: "\u{1F1F7}\u{1F1FA} Russian", data: "ru" },
    { label: "\u{1F1EF}\u{1F1F5} Japanese", data: "ja" },
    { label: "\u{1F1F0}\u{1F1F7} Korean", data: "ko" },
    { label: "\u{1F1E8}\u{1F1F3} Chinese (Simplified)", data: "zh-CN" },
    { label: "\u{1F1F9}\u{1F1FC} Chinese (Traditional)", data: "zh-TW" },
    { label: "\u{1F1F8}\u{1F1E6} Arabic", data: "ar" },
    { label: "\u{1F1EB}\u{1F1EE} Finnish", data: "fi" },
    { label: "\u{1F1F3}\u{1F1F1} Dutch", data: "nl" },
    { label: "\u{1F1EE}\u{1F1F3} Hindi", data: "hi" },
    { label: "\u{1F1F5}\u{1F1F1} Polish", data: "pl" },
    { label: "\u{1F1F9}\u{1F1ED} Thai", data: "th" },
    { label: "\u{1F1F9}\u{1F1F7} Turkish", data: "tr" },
    { label: "\u{1F1FA}\u{1F1E6} Ukrainian", data: "uk" },
    { label: "\u{1F1F7}\u{1F1F4} Romanian", data: "ro" },
    { label: "\u{1F1FB}\u{1F1F3} Vietnamese", data: "vi" },
    { label: "\u{1F1E7}\u{1F1EC} Bulgarian", data: "bg" }
];

const selectLanguageOption = { label: "Select language...", data: "" };
const outputLanguageOptions = languageOptions.filter(lang => lang.data !== "auto");

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
        </Field>
    </PanelSectionRow>
);

export const TabTranslation: VFC = () => {
    const { settings, updateSetting } = useSettings();

    // Common prompt state
    const [commonContent, setCommonContent] = useState("");
    const [commonPath, setCommonPath] = useState("");
    const [commonSaved, setCommonSaved] = useState("");

    // Game-specific prompt state
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
            <PanelSection title="Languages">
                <PanelSectionRow>
                    <DropdownItem
                        label="Input Language"
                        description="Source language. Auto-detect is recommended if you are unsure."
                        rgOptions={[...(settings.inputLanguage === '' ? [selectLanguageOption] : []), ...languageOptions]}
                        selectedOption={settings.inputLanguage}
                        onChange={(option) => updateSetting('inputLanguage', option.data, 'Input language')}
                    />
                </PanelSectionRow>

                <PanelSectionRow>
                    <DropdownItem
                        label="Output Language"
                        description="Target language for translation"
                        rgOptions={[...(settings.targetLanguage === '' ? [selectLanguageOption] : []), ...outputLanguageOptions]}
                        selectedOption={settings.targetLanguage}
                        onChange={(option) => updateSetting('targetLanguage', option.data, 'Output language')}
                    />
                </PanelSectionRow>
            </PanelSection>

            <PanelSection title="Common Instructions">
                <PanelSectionRow>
                    <Field focusable={true} childrenContainerWidth="max">
                        <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                            Instructions applied to all games.
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
                        label="Game Instructions"
                        value={gameContent}
                        filePath={gamePath}
                        placeholder="Glossary, tone, and special rules for this game..."
                        onChange={setGameContent}
                        onBlur={saveGame}
                    />
                </PanelSection>
            ) : (
                <PanelSection title="Game-Specific Instructions">
                    <PanelSectionRow>
                        <Field focusable={true} childrenContainerWidth="max">
                            <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                                Launch a game to edit game-specific instructions.
                            </div>
                        </Field>
                    </PanelSectionRow>
                </PanelSection>
            )}
        </div>
    );
};
