// src/SettingsContext.tsx
import React, { createContext, useContext, useEffect, useReducer } from 'react';
import { call } from '@decky/api';
import { GameTranslatorLogic } from './Translator';
import { InputMode } from './Input';
import { logger } from './Logger';

export interface Settings {
    inputLanguage: string;
    targetLanguage: string;
    inputMode: InputMode;
    enabled: boolean;
    initialized: boolean;
    holdTimeTranslate: number;
    holdTimeDismiss: number;
    pauseGameOnOverlay: boolean;
    quickToggleEnabled: boolean;
    geminiBaseUrl: string;
    geminiApiKey: string;
    geminiModel: string;
    debugMode: boolean;
    agentEnabled: boolean;
    fontScale: number;
    groupingPower: number;
    hideIdenticalTranslations: boolean;
    allowLabelGrowth: boolean;
    advancedFeaturesEnabled: boolean;
    pinFeatureEnabled: boolean;
    pinShortcutEnabled: boolean;
    pinInputMode: InputMode | null;
    holdTimePin: number;
    translationHistoryEnabledDefault: boolean;
    pinHistoryEnabledDefault: boolean;
}

interface BackendSettings {
    input_language: string;
    target_language: string;
    input_mode: InputMode;
    enabled: boolean;
    hold_time_translate: number;
    hold_time_dismiss: number;
    pause_game_on_overlay?: boolean;
    quick_toggle_enabled?: boolean;
    gemini_base_url?: string;
    gemini_api_key?: string;
    gemini_model?: string;
    debug_mode?: boolean;
    agent_enabled?: boolean;
    font_scale?: number;
    grouping_power?: number;
    hide_identical_translations?: boolean;
    allow_label_growth?: boolean;
    advanced_features_enabled?: boolean;
    pin_feature_enabled?: boolean;
    pin_shortcut_enabled?: boolean;
    pin_input_mode?: number | null;
    hold_time_pin?: number;
    translation_history_enabled_default?: boolean;
    pin_history_enabled_default?: boolean;
}

type SettingsAction =
    | { type: 'INITIALIZE_SETTINGS', settings: Partial<Settings> }
    | { type: 'UPDATE_SETTING', key: keyof Settings, value: any }
    | { type: 'SET_INITIALIZED', initialized: boolean };

const initialSettings: Settings = {
    inputLanguage: "",
    targetLanguage: "",
    inputMode: InputMode.L5_BUTTON,
    enabled: true,
    initialized: false,
    holdTimeTranslate: 1000,
    holdTimeDismiss: 500,
    pauseGameOnOverlay: false,
    quickToggleEnabled: false,
    geminiBaseUrl: "",
    geminiApiKey: "",
    geminiModel: "",
    debugMode: false,
    agentEnabled: false,
    fontScale: 1.0,
    groupingPower: 0.25,
    hideIdenticalTranslations: false,
    allowLabelGrowth: false,
    advancedFeaturesEnabled: false,
    pinFeatureEnabled: false,
    pinShortcutEnabled: false,
    pinInputMode: null,
    holdTimePin: 1000,
    translationHistoryEnabledDefault: true,
    pinHistoryEnabledDefault: true,
};

function settingsReducer(state: Settings, action: SettingsAction): Settings {
    switch (action.type) {
        case 'INITIALIZE_SETTINGS':
            return { ...state, ...action.settings };
        case 'UPDATE_SETTING':
            return { ...state, [action.key]: action.value };
        case 'SET_INITIALIZED':
            return { ...state, initialized: action.initialized };
        default:
            return state;
    }
}

interface SettingsContextType {
    settings: Settings;
    updateSetting: (key: keyof Settings, value: any, label?: string) => Promise<boolean>;
    initialized: boolean;
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined);

interface SettingsProviderProps {
    children: React.ReactNode;
    logic: GameTranslatorLogic;
}

export const SettingsProvider: React.FC<SettingsProviderProps> = ({
    children,
    logic
}) => {
    const [settings, dispatch] = useReducer(settingsReducer, initialSettings);

    const loadAllSettings = async () => {
        try {
            const serverSettings = await call<[], BackendSettings | null>('get_all_settings');

            if (!serverSettings) {
                logger.error('SettingsContext', 'Failed to load settings');
                return;
            }

            const mappedSettings: Partial<Settings> = {
                inputLanguage: serverSettings.input_language,
                targetLanguage: serverSettings.target_language,
                inputMode: serverSettings.input_mode,
                enabled: serverSettings.enabled,
                holdTimeTranslate: serverSettings.hold_time_translate,
                holdTimeDismiss: serverSettings.hold_time_dismiss,
                pauseGameOnOverlay: serverSettings.pause_game_on_overlay || false,
                quickToggleEnabled: serverSettings.quick_toggle_enabled || false,
                geminiBaseUrl: serverSettings.gemini_base_url || "",
                geminiApiKey: serverSettings.gemini_api_key || "",
                geminiModel: serverSettings.gemini_model || "",
                debugMode: serverSettings.debug_mode || false,
                agentEnabled: serverSettings.agent_enabled ?? false,
                fontScale: serverSettings.font_scale ?? 1.0,
                groupingPower: serverSettings.grouping_power ?? 0.25,
                hideIdenticalTranslations: serverSettings.hide_identical_translations ?? false,
                allowLabelGrowth: serverSettings.allow_label_growth ?? false,
                advancedFeaturesEnabled: serverSettings.advanced_features_enabled ?? false,
                pinFeatureEnabled: serverSettings.pin_feature_enabled ?? false,
                pinShortcutEnabled: serverSettings.pin_shortcut_enabled ?? false,
                pinInputMode: serverSettings.pin_input_mode ?? null,
                holdTimePin: serverSettings.hold_time_pin ?? 1000,
                translationHistoryEnabledDefault: serverSettings.translation_history_enabled_default ?? true,
                pinHistoryEnabledDefault: serverSettings.pin_history_enabled_default ?? true,
            };

            dispatch({ type: 'INITIALIZE_SETTINGS', settings: mappedSettings });

            logic.setInputLanguage(serverSettings.input_language);
            logic.setTargetLanguage(serverSettings.target_language);
            logic.setInputMode(serverSettings.input_mode);
            logic.setEnabled(serverSettings.enabled);
            logic.setHoldTimeTranslate(serverSettings.hold_time_translate);
            logic.setHoldTimeDismiss(serverSettings.hold_time_dismiss);
            logic.setPauseGameOnOverlay(serverSettings.pause_game_on_overlay || false);
            logic.setQuickToggleEnabled(serverSettings.quick_toggle_enabled || false);
            logic.setGeminiBaseUrl(serverSettings.gemini_base_url || "");
            logic.setGeminiApiKey(serverSettings.gemini_api_key || "");
            logic.setGeminiModel(serverSettings.gemini_model || "");
            logic.setFontScale(serverSettings.font_scale ?? 1.0);
            logic.setGroupingPower(serverSettings.grouping_power ?? 0.25);
            logic.setHideIdenticalTranslations(serverSettings.hide_identical_translations ?? false);
            logic.setAllowLabelGrowth(serverSettings.allow_label_growth ?? false);
            logic.setPinFeatureEnabled(serverSettings.pin_feature_enabled ?? false);
            logic.setPinShortcutEnabled(serverSettings.pin_shortcut_enabled ?? false);
            logic.setPinInputMode(serverSettings.pin_input_mode ?? null);
            logic.setPinHoldTime(serverSettings.hold_time_pin ?? 1000);
            logger.setEnabled(serverSettings.debug_mode || false);

            logger.info('SettingsContext', 'All settings loaded successfully');
            logger.logObject('SettingsContext', 'Settings', mappedSettings);
        } catch (error) {
            logger.error('SettingsContext', 'Error loading settings', error);
        } finally {
            dispatch({ type: 'SET_INITIALIZED', initialized: true });
        }
    };

    const updateSetting = async (key: keyof Settings, value: any, label?: string): Promise<boolean> => {
        try {
            dispatch({ type: 'UPDATE_SETTING', key, value });

            const backendKeyMap: Record<keyof Settings, string> = {
                inputLanguage: 'input_language',
                targetLanguage: 'target_language',
                inputMode: 'input_mode',
                enabled: 'enabled',
                initialized: 'initialized',
                holdTimeTranslate: 'hold_time_translate',
                holdTimeDismiss: 'hold_time_dismiss',
                pauseGameOnOverlay: 'pause_game_on_overlay',
                quickToggleEnabled: 'quick_toggle_enabled',
                geminiBaseUrl: 'gemini_base_url',
                geminiApiKey: 'gemini_api_key',
                geminiModel: 'gemini_model',
                debugMode: 'debug_mode',
                agentEnabled: 'agent_enabled',
                fontScale: 'font_scale',
                groupingPower: 'grouping_power',
                hideIdenticalTranslations: 'hide_identical_translations',
                allowLabelGrowth: 'allow_label_growth',
                advancedFeaturesEnabled: 'advanced_features_enabled',
                pinFeatureEnabled: 'pin_feature_enabled',
                pinShortcutEnabled: 'pin_shortcut_enabled',
                pinInputMode: 'pin_input_mode',
                holdTimePin: 'hold_time_pin',
                translationHistoryEnabledDefault: 'translation_history_enabled_default',
                pinHistoryEnabledDefault: 'pin_history_enabled_default',
            };

            if (key === 'initialized') return true;

            const backendKey = backendKeyMap[key];

            switch (key) {
                case 'inputLanguage':
                    logic.setInputLanguage(value);
                    break;
                case 'targetLanguage':
                    logic.setTargetLanguage(value);
                    break;
                case 'inputMode':
                    logic.setInputMode(value);
                    break;
                case 'enabled':
                    logic.setEnabled(value);
                    break;
                case 'holdTimeTranslate':
                    logic.setHoldTimeTranslate(value);
                    break;
                case 'holdTimeDismiss':
                    logic.setHoldTimeDismiss(value);
                    break;
                case 'pauseGameOnOverlay':
                    logic.setPauseGameOnOverlay(value);
                    break;
                case 'quickToggleEnabled':
                    logic.setQuickToggleEnabled(value);
                    break;
                case 'geminiBaseUrl':
                    logic.setGeminiBaseUrl(value);
                    break;
                case 'geminiApiKey':
                    logic.setGeminiApiKey(value);
                    break;
                case 'geminiModel':
                    logic.setGeminiModel(value);
                    break;
                case 'debugMode':
                    logger.setEnabled(value);
                    break;
                case 'fontScale':
                    logic.setFontScale(value);
                    break;
                case 'groupingPower':
                    logic.setGroupingPower(value);
                    break;
                case 'hideIdenticalTranslations':
                    logic.setHideIdenticalTranslations(value);
                    break;
                case 'allowLabelGrowth':
                    logic.setAllowLabelGrowth(value);
                    break;
                case 'pinFeatureEnabled':
                    logic.setPinFeatureEnabled(value);
                    break;
                case 'pinShortcutEnabled':
                    logic.setPinShortcutEnabled(value);
                    break;
                case 'pinInputMode':
                    logic.setPinInputMode(value);
                    break;
                case 'holdTimePin':
                    logic.setPinHoldTime(value);
                    break;
            }

            const result = await call<[string, any], boolean>('set_setting', backendKey, value);

            if (result) {
                return true;
            }

            logic.notify(`Failed to update ${label || key}`, 2000);
            return false;
        } catch (error) {
            logger.error('SettingsContext', `Failed to update ${key}`, error);
            logic.notify(`Failed to update ${label || key}`, 2000);
            return false;
        }
    };

    useEffect(() => {
        loadAllSettings();
    }, []);

    return (
        <SettingsContext.Provider value={{
            settings,
            updateSetting,
            initialized: settings.initialized
        }}>
            {children}
        </SettingsContext.Provider>
    );
};

export const useSettings = () => {
    const context = useContext(SettingsContext);
    if (!context) {
        throw new Error('useSettings must be used within a SettingsProvider');
    }
    return context;
};
