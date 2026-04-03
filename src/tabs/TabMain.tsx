// src/tabs/TabMain.tsx - Main tab with enable toggle and translate button

import {
    ButtonItem,
    PanelSection,
    PanelSectionRow,
    ToggleField,
    Router,
    Navigation,
    DialogButton,
    Focusable
} from "@decky/ui";

import { VFC } from "react";
import { BsTranslate, BsXLg } from "react-icons/bs";
import { SiKofi } from "react-icons/si";
import { HiQrCode } from "react-icons/hi2";
import showQrModal from "../showQrModal";
import { useSettings } from "../SettingsContext";
import { GameTranslatorLogic } from "../Translator";
import { logger } from "../Logger";

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
                                <div style={{ display: 'flex', alignItems: 'center', marginBottom: '2px' }}>
                                    <BsTranslate style={{ marginRight: '8px', color: '#aaa' }} />
                                    <span style={{ color: '#888' }}>Pipeline:</span>
                                    <span style={{ marginLeft: '6px', fontWeight: 'bold' }}>Gemini Vision</span>
                                </div>
                                <div style={{ marginLeft: '22px', marginBottom: '6px' }}>
                                    <div style={{ color: settings.geminiApiKey ? '#666' : '#ff6b6b', fontSize: '10px' }}>
                                        {settings.geminiApiKey ? 'API key configured' : 'API key required'}
                                    </div>
                                    <div style={{ color: settings.geminiModel ? '#666' : '#ff6b6b', fontSize: '10px' }}>
                                        {settings.geminiModel ? `Model: ${settings.geminiModel}` : 'Model required'}
                                    </div>
                                    <div style={{ color: '#666', fontSize: '10px' }}>
                                        {settings.geminiBaseUrl
                                            ? `Custom endpoint: ${settings.geminiBaseUrl}`
                                            : 'Official Gemini endpoint'}
                                    </div>
                                </div>
                            </div>
                        </PanelSectionRow>
                    </>
                )}

                <PanelSectionRow>
                    <div
                        style={{
                            display: 'flex',
                            justifyContent: 'center',
                            marginTop: '12px',
                        }}
                    >
                        <Focusable>
                            <DialogButton
                                onClick={() => {
                                    Navigation.CloseSideMenus();
                                    Navigation.NavigateToExternalWeb('https://ko-fi.com/alexanderdev');
                                }}
                                onSecondaryButton={() => showQrModal('https://ko-fi.com/alexanderdev')}
                                onSecondaryActionDescription="Show QR Code"
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px',
                                    padding: '6px 12px',
                                    fontSize: '11px',
                                    minWidth: 'auto',
                                }}
                            >
                                <SiKofi style={{ fontSize: '13px' }} />
                                <span>Support on Ko-fi</span>
                                <HiQrCode style={{ fontSize: '13px', opacity: 0.6 }} />
                            </DialogButton>
                        </Focusable>
                    </div>
                </PanelSectionRow>
            </PanelSection>
        </div>
    );
};
