// src/tabs/TabControls.tsx - Settings tab (Gemini, controls, display, behavior, debug)

import {
    PanelSection,
    PanelSectionRow,
    DropdownItem,
    ToggleField,
    SliderField,
    TextField,
    Field,
    ButtonItem,
    Router
} from "@decky/ui";

import { VFC, useState, useEffect, useCallback } from "react";
import { call } from "@decky/api";
import { useSettings } from "../SettingsContext";
import { InputMode } from "../Input";
import { logger } from "../Logger";

// Input mode options for dropdown
const inputModeOptions = [
    { label: "L3 (Left Stick Click)", data: InputMode.L3_BUTTON },
    { label: "L4", data: InputMode.L4_BUTTON },
    { label: "L5", data: InputMode.L5_BUTTON },
    { label: "R3 (Right Stick Click)", data: InputMode.R3_BUTTON },
    { label: "R4", data: InputMode.R4_BUTTON },
    { label: "R5", data: InputMode.R5_BUTTON },
    { label: "L3 + R3 (Both Sticks Click)", data: InputMode.L3_R3_COMBO },
    { label: "L4 + R4", data: InputMode.L4_R4_COMBO },
    { label: "L5 + R5", data: InputMode.L5_R5_COMBO },
    { label: "Both Touchpads Touch", data: InputMode.TOUCHPAD_COMBO }
];

// Helper to get button labels for current input mode
const getInputModeButtons = (mode: string): string => {
    switch (mode) {
        case 'L3_BUTTON': return 'L3';
        case 'L4_BUTTON': return 'L4';
        case 'L5_BUTTON': return 'L5';
        case 'R3_BUTTON': return 'R3';
        case 'R4_BUTTON': return 'R4';
        case 'R5_BUTTON': return 'R5';
        case 'L3_R3_COMBO': return 'L3 + R3';
        case 'L4_R4_COMBO': return 'L4 + R4';
        case 'L5_R5_COMBO': return 'L5 + R5';
        case 'TOUCHPAD_COMBO': return 'Left Pad + Right Pad';
        default: return mode;
    }
};

// ログ状態の型
interface LogStatus {
    translationCount: number;
    translationSize: number;
    pinCount: number;
    pinSize: number;
}

const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

// Logs セクションコンポーネント
const LogsSection: VFC = () => {
    const { settings, updateSetting } = useSettings();
    const [logStatus, setLogStatus] = useState<LogStatus | null>(null);
    const [deleting, setDeleting] = useState<string | null>(null);

    const loadLogStatus = useCallback(async () => {
        try {
            const mainApp = Router.MainRunningApp;
            const appId = mainApp?.appid ? Number(mainApp.appid) : 0;
            if (!appId) { setLogStatus(null); return; }

            const [transStatus, pinStatus] = await Promise.all([
                call<[number], any>('get_translation_history_status', appId),
                call<[number], any>('get_pin_history_status', appId),
            ]);

            setLogStatus({
                translationCount: transStatus?.count ?? 0,
                translationSize: transStatus?.size_bytes ?? 0,
                pinCount: pinStatus?.count ?? 0,
                pinSize: pinStatus?.total_size_bytes ?? 0,
            });
        } catch (err) {
            logger.error('LogsSection', 'Failed to load log status', err);
        }
    }, []);

    useEffect(() => { loadLogStatus(); }, []);

    const handleDelete = async (type: "translation" | "pin") => {
        const mainApp = Router.MainRunningApp;
        const appId = mainApp?.appid ? Number(mainApp.appid) : 0;
        if (!appId) return;

        setDeleting(type);
        try {
            if (type === "translation") {
                await call<[number], any>('delete_translation_history_for_game', appId);
            } else {
                await call<[number], any>('delete_pin_history_for_game', appId);
            }
            await loadLogStatus();
        } catch (err) {
            logger.error('LogsSection', `Failed to delete ${type} history`, err);
        } finally {
            setDeleting(null);
        }
    };

    return (
        <PanelSection title="Logs">
            <PanelSectionRow>
                <ToggleField
                    label="Save Translation History"
                    description="Automatically save translation results for each game"
                    checked={settings.translationHistoryEnabledDefault ?? true}
                    onChange={(value) => updateSetting('translationHistoryEnabledDefault', value, 'Translation History')}
                />
            </PanelSectionRow>

            <PanelSectionRow>
                <ToggleField
                    label="Save Pin History"
                    description="Automatically save pin records for each game"
                    checked={settings.pinHistoryEnabledDefault ?? true}
                    onChange={(value) => updateSetting('pinHistoryEnabledDefault', value, 'Pin History')}
                />
            </PanelSectionRow>

            {logStatus && (
                <PanelSectionRow>
                    <Field focusable={false} childrenContainerWidth="max">
                        <div style={{ fontSize: "11px", color: "#aaa", padding: "4px 0" }}>
                            <div>Translation: {logStatus.translationCount} entries ({formatSize(logStatus.translationSize)})</div>
                            <div>Pin: {logStatus.pinCount} entries ({formatSize(logStatus.pinSize)})</div>
                        </div>
                    </Field>
                </PanelSectionRow>
            )}

            <PanelSectionRow>
                <ButtonItem
                    layout="below"
                    onClick={loadLogStatus}
                >
                    Refresh Log Status
                </ButtonItem>
            </PanelSectionRow>

            {logStatus && logStatus.translationCount > 0 && (
                <PanelSectionRow>
                    <ButtonItem
                        layout="below"
                        disabled={deleting === "translation"}
                        onClick={() => handleDelete("translation")}
                    >
                        {deleting === "translation" ? "Deleting..." : "Delete Translation Logs"}
                    </ButtonItem>
                </PanelSectionRow>
            )}

            {logStatus && logStatus.pinCount > 0 && (
                <PanelSectionRow>
                    <ButtonItem
                        layout="below"
                        disabled={deleting === "pin"}
                        onClick={() => handleDelete("pin")}
                    >
                        {deleting === "pin" ? "Deleting..." : "Delete Pin Logs"}
                    </ButtonItem>
                </PanelSectionRow>
            )}
        </PanelSection>
    );
};

interface TabControlsProps {
    inputDiagnostics: any;
}

export const TabControls: VFC<TabControlsProps> = ({ inputDiagnostics }) => {
    const { settings, updateSetting } = useSettings();

    return (
        <div style={{ marginLeft: "-8px", marginRight: "-8px", paddingBottom: "40px" }}>
            <PanelSection title="Gemini">
                <PanelSectionRow>
                    <Field label="Model" childrenContainerWidth="max">
                        <TextField
                            value={settings.geminiModel}
                            onChange={(e) => updateSetting('geminiModel', e.target.value, 'Gemini Model')}
                            bShowClearAction={true}
                            description="e.g. gemini-2.5-flash or gemini-2.5-pro"
                        />
                    </Field>
                </PanelSectionRow>

                <PanelSectionRow>
                    <Field label="Fallback Model" childrenContainerWidth="max">
                        <TextField
                            value={settings.geminiFallbackModel}
                            onChange={(e) => updateSetting('geminiFallbackModel', e.target.value, 'Gemini Fallback Model')}
                            bShowClearAction={true}
                            description="Used when primary returns 503. Leave blank to disable. e.g. gemini-2.5-flash-lite"
                        />
                    </Field>
                </PanelSectionRow>

                <PanelSectionRow>
                    <Field label="API Key" childrenContainerWidth="max">
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
                    <Field label="Base URL" childrenContainerWidth="max">
                        <TextField
                            value={settings.geminiBaseUrl}
                            onChange={(e) => updateSetting('geminiBaseUrl', e.target.value, 'Gemini Base URL')}
                            bShowClearAction={true}
                            description="Leave empty to use the official endpoint"
                        />
                    </Field>
                </PanelSectionRow>
            </PanelSection>

            <PanelSection title="Control">
                <PanelSectionRow>
                    <DropdownItem
                        label="Quick Translation Shortcut"
                        description="Select which buttons to hold to start translation"
                        rgOptions={inputModeOptions}
                        selectedOption={settings.inputMode}
                        onChange={(option) => updateSetting('inputMode', option.data, 'Input method')}
                    />
                </PanelSectionRow>

                <PanelSectionRow>
                    <SliderField
                        value={settings.holdTimeTranslate / 1000}
                        max={3}
                        min={0}
                        step={0.1}
                        label="Hold Time to Start"
                        description="Seconds to hold button(s) to translate"
                        showValue={true}
                        valueSuffix="s"
                        onChange={(value) => {
                            const milliseconds = Math.round(value * 1000);
                            updateSetting('holdTimeTranslate', milliseconds, 'Hold time');
                        }}
                    />
                </PanelSectionRow>

                <PanelSectionRow>
                    <SliderField
                        value={settings.holdTimeDismiss / 1000}
                        max={3}
                        min={0}
                        step={0.1}
                        label="Hold Time to Dismiss"
                        description="Seconds to hold button(s) to dismiss overlay"
                        showValue={true}
                        valueSuffix="s"
                        onChange={(value) => {
                            const milliseconds = Math.round(value * 1000);
                            updateSetting('holdTimeDismiss', milliseconds, 'Hold time for dismissal');
                        }}
                    />
                </PanelSectionRow>

                {/* Quick toggle option - only show for combo modes */}
                {(settings.inputMode === InputMode.L4_R4_COMBO ||
                    settings.inputMode === InputMode.L5_R5_COMBO ||
                    settings.inputMode === InputMode.L3_R3_COMBO ||
                    settings.inputMode === InputMode.TOUCHPAD_COMBO) && (
                    <PanelSectionRow>
                        <ToggleField
                            checked={settings.quickToggleEnabled}
                            label="Quick toggle with Right Button"
                            description="If double buttons combination is selected, press right button to toggle overlay visibility"
                            onChange={(value) => {
                                updateSetting('quickToggleEnabled', value, 'Quick toggle');
                            }}
                        />
                    </PanelSectionRow>
                )}
            </PanelSection>

            <PanelSection title="Display">
                <PanelSectionRow>
                    <SliderField
                        value={settings.fontScale}
                        max={3}
                        min={1}
                        step={0.1}
                        label="Font Scaling"
                        description="Increase if translated text is too small. Can be useful for large external monitors"
                        showValue={true}
                        valueSuffix="x"
                        onChange={(value) => {
                            const rounded = Math.round(value * 10) / 10;
                            updateSetting('fontScale', rounded, 'Font scale');
                        }}
                    />
                </PanelSectionRow>

                <PanelSectionRow>
                    <SliderField
                        value={settings.groupingPower}
                        min={0.25}
                        max={1.0}
                        step={0.25}
                        notchCount={4}
                        notchTicksVisible={true}
                        label="Text Blocks Grouping"
                        description={
                            settings.groupingPower <= 0.25 ? "Normal - Keeps text blocks separated" :
                            settings.groupingPower <= 0.5 ? "Increased - Merges text blocks" :
                            settings.groupingPower <= 0.75 ? "Large - Merges distant text blocks" :
                            "Huge - Merges very distant text blocks"
                        }
                        onChange={(value) => {
                            updateSetting('groupingPower', value, 'Text grouping');
                        }}
                    />
                </PanelSectionRow>

                <PanelSectionRow>
                    <ToggleField
                        checked={settings.hideIdenticalTranslations}
                        label="Hide Identical Translations"
                        description="Don't display if translation is the same as original word/sentence"
                        onChange={(value) => {
                            updateSetting('hideIdenticalTranslations', value, 'Hide identical translations');
                        }}
                    />
                </PanelSectionRow>

                <PanelSectionRow>
                    <ToggleField
                        checked={settings.allowLabelGrowth}
                        label="Allow Labels to Expand"
                        description="Let translated labels grow wider if the text doesn't fit the original box"
                        onChange={(value) => {
                            updateSetting('allowLabelGrowth', value, 'Allow label growth');
                        }}
                    />
                </PanelSectionRow>
            </PanelSection>

            <PanelSection title="Behavior">
                <PanelSectionRow>
                    <ToggleField
                        checked={settings.pauseGameOnOverlay}
                        label="Pause Game While Translating"
                        description="Pauses the active game and allows you to read the text more thoughtfully. The game is resumed when overlay is dismissed"
                        onChange={(value) => {
                            updateSetting('pauseGameOnOverlay', value, 'Pause game while translating');
                        }}
                    />
                </PanelSectionRow>
            </PanelSection>

            <PanelSection title="Advanced">
                <PanelSectionRow>
                    <ToggleField
                        label="Advanced Features"
                        description="Show advanced settings: Agent CLI, Pin, Logs, Debug"
                        checked={settings.advancedFeaturesEnabled ?? false}
                        onChange={(value) => updateSetting('advancedFeaturesEnabled', value, 'Advanced Features')}
                    />
                </PanelSectionRow>
            </PanelSection>

            {settings.advancedFeaturesEnabled && (
            <>
            <PanelSection title="Agent CLI">
                <PanelSectionRow>
                    <ToggleField
                        label="Agent CLI"
                        description="Allow external AI/scripts to capture and analyze the screen via SSH"
                        checked={settings.agentEnabled ?? false}
                        onChange={(value) => updateSetting('agentEnabled', value, 'Agent CLI')}
                    />
                </PanelSectionRow>
            </PanelSection>

            <PanelSection title="Pin">
                <PanelSectionRow>
                    <ToggleField
                        label="Enable Pin Feature"
                        description="Save screenshots with Gemini analysis for later reference"
                        checked={settings.pinFeatureEnabled ?? false}
                        onChange={(value) => updateSetting('pinFeatureEnabled', value, 'Pin Feature')}
                    />
                </PanelSectionRow>

                {settings.pinFeatureEnabled && (
                <>
                    <PanelSectionRow>
                        <ToggleField
                            label="Enable Pin Shortcut"
                            description="Use a dedicated button shortcut to pin the current screen"
                            checked={settings.pinShortcutEnabled ?? false}
                            onChange={(value) => {
                                updateSetting('pinShortcutEnabled', value, 'Pin Shortcut');
                                // pinInputMode が未設定なら既定値を保存
                                if (value && settings.pinInputMode == null) {
                                    updateSetting('pinInputMode', InputMode.L4_BUTTON, 'Pin input mode');
                                }
                            }}
                        />
                    </PanelSectionRow>

                    {settings.pinShortcutEnabled && (
                    <>
                        <PanelSectionRow>
                            <DropdownItem
                                label="Pin Shortcut"
                                description="Select which buttons to hold to pin"
                                rgOptions={inputModeOptions}
                                selectedOption={settings.pinInputMode ?? InputMode.L4_BUTTON}
                                onChange={(option) => updateSetting('pinInputMode', option.data, 'Pin input mode')}
                            />
                        </PanelSectionRow>

                        <PanelSectionRow>
                            <SliderField
                                value={(settings.holdTimePin ?? 1000) / 1000}
                                max={3}
                                min={0}
                                step={0.1}
                                label="Hold Time to Pin"
                                description="Seconds to hold button(s) to pin"
                                showValue={true}
                                valueSuffix="s"
                                onChange={(value) => {
                                    const milliseconds = Math.round(value * 1000);
                                    updateSetting('holdTimePin', milliseconds, 'Hold time for pin');
                                }}
                            />
                        </PanelSectionRow>
                    </>
                    )}
                </>
                )}
            </PanelSection>

            <LogsSection />

            <PanelSection title="Debug">
                <PanelSectionRow>
                    <ToggleField
                        label="Debug Mode"
                        description="Enable verbose console logging and diagnostics panel"
                        checked={settings.debugMode}
                        onChange={(value) => updateSetting('debugMode', value, 'Debug mode')}
                    />
                </PanelSectionRow>

                {/* Show diagnostics when debug mode is on */}
                {settings.debugMode && inputDiagnostics && (
                    <PanelSectionRow>
                        <Field
                            focusable={true}
                            childrenContainerWidth="max"
                        >
                            <div style={{
                                backgroundColor: 'rgba(0,0,0,0.4)',
                                padding: '12px',
                                borderRadius: '6px',
                                fontSize: '11px',
                                fontFamily: 'monospace',
                                border: '1px solid rgba(255,255,255,0.1)'
                            }}>
                                <div style={{ display: 'grid', gap: '3px' }}>
                                    <div>
                                        <span style={{ color: '#888' }}>Status:</span>{' '}
                                        {inputDiagnostics.enabled ?
                                            (inputDiagnostics.healthy ? 'Healthy' : 'Unhealthy') :
                                            'Disabled'
                                        }
                                    </div>

                                    <div>
                                        <span style={{ color: '#888' }}>Input mode:</span>{' '}
                                        {getInputModeButtons(inputDiagnostics.inputMode)}
                                    </div>

                                    <div>
                                        <span style={{ color: '#888' }}>Input active:</span>{' '}
                                        {inputDiagnostics.leftTouchpadTouched ? 'Yes' : 'No'}
                                    </div>

                                    <div>
                                        <span style={{ color: '#888' }}>Buttons pressed:</span>{' '}
                                        {inputDiagnostics.currentButtons && inputDiagnostics.currentButtons.length > 0
                                            ? inputDiagnostics.currentButtons.join(', ')
                                            : 'None'}
                                    </div>

                                    <div>
                                        <span style={{ color: '#888' }}>Plugin State:</span>{' '}
                                        {!inputDiagnostics.inCooldown && !inputDiagnostics.waitingForRelease && !inputDiagnostics.overlayVisible ? 'Ready' : ''}
                                        {inputDiagnostics.inCooldown ? 'Cooldown ' : ''}
                                        {inputDiagnostics.waitingForRelease ? 'WaitRelease ' : ''}
                                        {inputDiagnostics.overlayVisible ? 'Overlay ' : ''}
                                    </div>

                                    <div>
                                        <span style={{ color: '#888' }}>Timings:</span>{' '}
                                        Hold:{inputDiagnostics.translateHoldTime}ms{' '}
                                        Dismiss:{inputDiagnostics.dismissHoldTime}ms
                                    </div>
                                </div>

                                {!inputDiagnostics.healthy && inputDiagnostics.enabled && (
                                    <div style={{
                                        color: '#ff6b6b',
                                        fontWeight: 'bold',
                                        marginTop: '8px',
                                        padding: '6px',
                                        backgroundColor: 'rgba(255, 107, 107, 0.1)',
                                        borderRadius: '4px',
                                        fontSize: '11px'
                                    }}>
                                        Input system is unhealthy - try toggling the plugin off/on
                                    </div>
                                )}
                            </div>
                        </Field>
                    </PanelSectionRow>
                )}
            </PanelSection>
            </>
            )}
        </div>
    );
};
