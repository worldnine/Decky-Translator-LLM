// src/tabs/TabTranslation.tsx - Language and Gemini settings

import {
    PanelSection,
    PanelSectionRow,
    DropdownItem,
    ToggleField,
    TextField,
    Field
} from "@decky/ui";

import { VFC, useState } from "react";
import { useSettings } from "../SettingsContext";

const languageOptions = [
    { label: "🌐 Auto-detect", data: "auto" },
    { label: "🇬🇧 English", data: "en" },
    { label: "🇪🇸 Spanish", data: "es" },
    { label: "🇫🇷 French", data: "fr" },
    { label: "🇩🇪 German", data: "de" },
    { label: "🇬🇷 Greek", data: "el" },
    { label: "🇮🇹 Italian", data: "it" },
    { label: "🇵🇹 Portuguese", data: "pt" },
    { label: "🇷🇺 Russian", data: "ru" },
    { label: "🇯🇵 Japanese", data: "ja" },
    { label: "🇰🇷 Korean", data: "ko" },
    { label: "🇨🇳 Chinese (Simplified)", data: "zh-CN" },
    { label: "🇹🇼 Chinese (Traditional)", data: "zh-TW" },
    { label: "🇸🇦 Arabic", data: "ar" },
    { label: "🇫🇮 Finnish", data: "fi" },
    { label: "🇳🇱 Dutch", data: "nl" },
    { label: "🇮🇳 Hindi", data: "hi" },
    { label: "🇵🇱 Polish", data: "pl" },
    { label: "🇹🇭 Thai", data: "th" },
    { label: "🇹🇷 Turkish", data: "tr" },
    { label: "🇺🇦 Ukrainian", data: "uk" },
    { label: "🇷🇴 Romanian", data: "ro" },
    { label: "🇻🇳 Vietnamese", data: "vi" },
    { label: "🇧🇬 Bulgarian", data: "bg" }
];

const selectLanguageOption = { label: "Select language...", data: "" };
const outputLanguageOptions = languageOptions.filter(lang => lang.data !== "auto");

export const TabTranslation: VFC = () => {
    const { settings, updateSetting } = useSettings();
    const [showAdvanced, setShowAdvanced] = useState<boolean>(false);

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
                        description="Target language for Gemini translation"
                        rgOptions={[...(settings.targetLanguage === '' ? [selectLanguageOption] : []), ...outputLanguageOptions]}
                        selectedOption={settings.targetLanguage}
                        onChange={(option) => updateSetting('targetLanguage', option.data, 'Output language')}
                    />
                </PanelSectionRow>
            </PanelSection>

            <PanelSection title="Gemini">
                <PanelSectionRow>
                    <Field focusable={true} childrenContainerWidth="max">
                        <div style={{ color: "#8b929a", fontSize: "12px", lineHeight: "1.6" }}>
                            <div style={{ marginBottom: "6px", color: "#dcdedf", fontWeight: "bold" }}>
                                Gemini Vision is the only translation pipeline in this fork.
                            </div>
                            <div>- Screenshot is sent directly to Gemini for text detection and translation</div>
                            <div>- OCR and text-translation provider selection have been removed</div>
                            <div>- Leave Base URL empty to use the official Gemini endpoint</div>
                        </div>
                    </Field>
                </PanelSectionRow>

                <PanelSectionRow>
                    <Field label="Gemini API Key" childrenContainerWidth="max">
                        <TextField
                            value={settings.geminiApiKey}
                            onChange={(e) => updateSetting('geminiApiKey', e.target.value, 'Gemini API Key')}
                            bShowClearAction={true}
                            bIsPassword={true}
                            description="Required for the official Gemini API and most proxies"
                        />
                    </Field>
                </PanelSectionRow>

                <PanelSectionRow>
                    <Field label="Gemini Model" childrenContainerWidth="max">
                        <TextField
                            value={settings.geminiModel}
                            onChange={(e) => updateSetting('geminiModel', e.target.value, 'Gemini Model')}
                            bShowClearAction={true}
                            description="e.g. gemini-2.5-flash or gemini-2.5-pro"
                        />
                    </Field>
                </PanelSectionRow>

                <PanelSectionRow>
                    <ToggleField
                        label="Show Advanced Settings"
                        description="Display custom endpoint settings for proxies or gateways"
                        checked={showAdvanced}
                        onChange={(value) => setShowAdvanced(value)}
                    />
                </PanelSectionRow>

                {showAdvanced && (
                    <PanelSectionRow>
                        <Field label="Gemini Base URL" childrenContainerWidth="max">
                            <TextField
                                value={settings.geminiBaseUrl}
                                onChange={(e) => updateSetting('geminiBaseUrl', e.target.value, 'Gemini Base URL')}
                                bShowClearAction={true}
                                description="Optional. Leave empty to use the official Gemini endpoint."
                            />
                        </Field>
                    </PanelSectionRow>
                )}
            </PanelSection>
        </div>
    );
};
