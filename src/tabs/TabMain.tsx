// src/tabs/TabMain.tsx - Main tab with enable toggle, translate button, and status summary

import {
    ButtonItem,
    PanelSection,
    PanelSectionRow,
    ToggleField,
    Router
} from "@decky/ui";

import { VFC } from "react";
import { BsTranslate, BsXLg } from "react-icons/bs";
import { useSettings } from "../SettingsContext";
import { GameTranslatorLogic } from "../Translator";
import { logger } from "../Logger";

// Language code to display name
const languageNames: Record<string, string> = {
    "auto": "Auto-detect",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "el": "Greek",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "ar": "Arabic",
    "fi": "Finnish",
    "nl": "Dutch",
    "hi": "Hindi",
    "pl": "Polish",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ro": "Romanian",
    "vi": "Vietnamese",
    "bg": "Bulgarian",
};

interface TabMainProps {
    logic: GameTranslatorLogic;
    overlayVisible: boolean;
}

export const TabMain: VFC<TabMainProps> = ({ logic, overlayVisible }) => {
    const { settings, updateSetting } = useSettings();

    const handleButtonClick = () => {
        if (overlayVisible) {
            logic.imageState.hideImage();
            Router.CloseSideMenus();
        } else {
            Router.CloseSideMenus();
            setTimeout(() => {
                logic.takeScreenshotAndTranslate().catch(err => logger.error('TabMain', 'Screenshot failed', err));
            }, 200);
        }
    };

    const inputLang = settings.inputLanguage
        ? (languageNames[settings.inputLanguage] || settings.inputLanguage)
        : "Not set";
    const outputLang = settings.targetLanguage
        ? (languageNames[settings.targetLanguage] || settings.targetLanguage)
        : "Not set";

    return (
        <div style={{ marginLeft: "-8px", marginRight: "-8px" }}>
            <PanelSection>
                <PanelSectionRow>
                    <ToggleField
                        label={settings.enabled ? "Plugin is enabled" : "Plugin is disabled"}
                        description="Toggle the functionality on or off"
                        checked={settings.enabled}
                        onChange={(value) => updateSetting('enabled', value, 'Decky Translator')}
                    />
                </PanelSectionRow>

                {settings.enabled && (
                    <>
                        <PanelSectionRow>
                            <ButtonItem
                                bottomSeparator="standard"
                                layout="below"
                                onClick={handleButtonClick}>
                                {overlayVisible ?
                                    <span><BsXLg style={{marginRight: "8px"}} /> Close Overlay</span> :
                                    <span><BsTranslate style={{marginRight: "8px"}} /> Translate</span>
                                }
                            </ButtonItem>
                        </PanelSectionRow>

                        <PanelSectionRow>
                            <div style={{ fontSize: '12px', marginTop: '8px' }}>
                                {/* Model name - most prominent */}
                                <div style={{ marginBottom: '6px' }}>
                                    <span style={{ color: '#888', fontSize: '10px' }}>Model</span>
                                    <div style={{
                                        fontSize: '15px',
                                        fontWeight: 'bold',
                                        color: settings.geminiModel ? '#dcdedf' : '#ff6b6b',
                                        marginTop: '2px'
                                    }}>
                                        {settings.geminiModel || 'Model not set'}
                                    </div>
                                </div>

                                {/* Endpoint */}
                                <div style={{ color: '#666', fontSize: '10px', marginBottom: '3px' }}>
                                    Endpoint: {settings.geminiBaseUrl ? 'Custom' : 'Official'}
                                </div>

                                {/* Languages */}
                                <div style={{ color: '#666', fontSize: '10px', marginBottom: '3px' }}>
                                    {inputLang} → {outputLang}
                                </div>

                                {/* API key status */}
                                <div style={{
                                    color: settings.geminiApiKey ? '#666' : '#ff6b6b',
                                    fontSize: '10px'
                                }}>
                                    {settings.geminiApiKey ? 'API key configured' : 'API key not set'}
                                </div>
                            </div>
                        </PanelSectionRow>
                    </>
                )}

            </PanelSection>
        </div>
    );
};
