// src/SettingsContext.tsx
import React, { createContext, useContext, useEffect, useReducer } from 'react';
import { call } from '@decky/api';
import { GameTranslatorLogic } from './Translator';
import { InputMode } from './Input';
import { logger } from './Logger';

// Define the settings interface
export interface Settings {
    inputLanguage: string;
    targetLanguage: string;
    inputMode: InputMode;
    enabled: boolean;
    initialized: boolean;
    holdTimeTranslate: number;
    holdTimeDismiss: number;
    confidenceThreshold: number;
    rapidocrConfidence: number;
    rapidocrBoxThresh: number;
    rapidocrUnclipRatio: number;
    pauseGameOnOverlay: boolean;
    quickToggleEnabled: boolean;
    useFreeProviders: boolean;
    ocrProvider: 'rapidocr' | 'ocrspace' | 'googlecloud';
    translationProvider: 'freegoogle' | 'googlecloud' | 'llm';
    googleApiKey: string;
    // LLM翻訳設定（テキスト翻訳用）
    llmBaseUrl: string;
    llmApiKey: string;
    llmModel: string;
    llmSystemPrompt: string;
    llmDisableThinking: boolean;
    // Vision設定（OCR/Translationとは独立）
    visionMode: 'off' | 'assist' | 'direct';
    visionParallel: boolean;
    visionAssistSendAll: boolean;
    visionAssistConfidenceThreshold: number;
    // 表示設定
    debugMode: boolean;
    fontScale: number;
    groupingPower: number;
    hideIdenticalTranslations: boolean;
    allowLabelGrowth: boolean;
    customRecognitionSettings: boolean;
}

// Define action types
type SettingsAction =
    | { type: 'INITIALIZE_SETTINGS', settings: Partial<Settings> }
    | { type: 'UPDATE_SETTING', key: keyof Settings, value: any }
    | { type: 'SET_INITIALIZED', initialized: boolean };

// Define the initial state
const initialSettings: Settings = {
    inputLanguage: "",
    targetLanguage: "",
    inputMode: InputMode.L5_BUTTON,
    enabled: true,
    initialized: false,
    holdTimeTranslate: 1000,
    holdTimeDismiss: 500,
    confidenceThreshold: 0.6,
    rapidocrConfidence: 0.5,
    rapidocrBoxThresh: 0.5,
    rapidocrUnclipRatio: 1.6,
    pauseGameOnOverlay: false,
    quickToggleEnabled: false,
    useFreeProviders: true,
    ocrProvider: "rapidocr",
    translationProvider: "freegoogle",
    googleApiKey: "",
    llmBaseUrl: "",
    llmApiKey: "",
    llmModel: "",
    llmSystemPrompt: "",
    llmDisableThinking: true,
    visionMode: "off",
    visionParallel: true,
    visionAssistSendAll: false,
    visionAssistConfidenceThreshold: 0.95,
    debugMode: false,
    fontScale: 1.0,
    groupingPower: 0.25,
    hideIdenticalTranslations: false,
    allowLabelGrowth: false,
    customRecognitionSettings: false
};

// Create the reducer
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

// Create the context
interface SettingsContextType {
    settings: Settings;
    updateSetting: (key: keyof Settings, value: any, label?: string) => Promise<boolean>;
    initialized: boolean;
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined);

// Create the provider component
interface SettingsProviderProps {
    children: React.ReactNode;
    logic: GameTranslatorLogic;
}

export const SettingsProvider: React.FC<SettingsProviderProps> = ({
                                                                      children,
                                                                      logic
                                                                  }) => {
    const [settings, dispatch] = useReducer(settingsReducer, initialSettings);

    // Load all settings at once
    const loadAllSettings = async () => {
        try {
            const serverSettings = await call<any>('get_all_settings');

            if (serverSettings) {

                // Map backend settings to frontend settings
                const mappedSettings: Partial<Settings> = {
                    inputLanguage: serverSettings.input_language,
                    targetLanguage: serverSettings.target_language,
                    inputMode: serverSettings.input_mode,
                    enabled: serverSettings.enabled,
                    holdTimeTranslate: serverSettings.hold_time_translate,
                    holdTimeDismiss: serverSettings.hold_time_dismiss,
                    confidenceThreshold: serverSettings.confidence_threshold || 0.6,
                    rapidocrConfidence: serverSettings.rapidocr_confidence ?? 0.5,
                    rapidocrBoxThresh: serverSettings.rapidocr_box_thresh ?? 0.5,
                    rapidocrUnclipRatio: serverSettings.rapidocr_unclip_ratio ?? 1.6,
                    pauseGameOnOverlay: serverSettings.pause_game_on_overlay || false,
                    quickToggleEnabled: serverSettings.quick_toggle_enabled || false,
                    useFreeProviders: serverSettings.use_free_providers !== false,
                    ocrProvider: serverSettings.ocr_provider || "rapidocr",
                    translationProvider: serverSettings.translation_provider || "freegoogle",
                    googleApiKey: serverSettings.google_api_key || "",
                    llmBaseUrl: serverSettings.llm_base_url || "",
                    llmApiKey: serverSettings.llm_api_key || "",
                    llmModel: serverSettings.llm_model || "",
                    llmSystemPrompt: serverSettings.llm_system_prompt || "",
                    llmDisableThinking: serverSettings.llm_disable_thinking ?? true,
                    visionMode: serverSettings.vision_mode ?? "off",
                    visionParallel: serverSettings.vision_parallel ?? true,
                    visionAssistSendAll: serverSettings.vision_assist_send_all ?? false,
                    visionAssistConfidenceThreshold: serverSettings.vision_assist_confidence_threshold ?? 0.95,
                    debugMode: serverSettings.debug_mode || false,
                    fontScale: serverSettings.font_scale ?? 1.0,
                    groupingPower: serverSettings.grouping_power ?? 0.25,
                    hideIdenticalTranslations: serverSettings.hide_identical_translations ?? false,
                    allowLabelGrowth: serverSettings.allow_label_growth ?? false,
                    customRecognitionSettings: serverSettings.custom_recognition_settings ?? false
                };

                // Update settings in context
                dispatch({ type: 'INITIALIZE_SETTINGS', settings: mappedSettings });

                // Update logic instance with settings
                logic.setInputLanguage(serverSettings.input_language);
                logic.setTargetLanguage(serverSettings.target_language);
                logic.setInputMode(serverSettings.input_mode);
                logic.setEnabled(serverSettings.enabled);
                logic.setHoldTimeTranslate(serverSettings.hold_time_translate);
                logic.setHoldTimeDismiss(serverSettings.hold_time_dismiss);
                logic.setConfidenceThreshold(serverSettings.confidence_threshold || 0.6);
                logic.setPauseGameOnOverlay(serverSettings.pause_game_on_overlay || false);
                logic.setQuickToggleEnabled(serverSettings.quick_toggle_enabled || false);
                logger.setEnabled(serverSettings.debug_mode || false);

                // Set provider settings for upfront API key validation
                logic.setOcrProvider(serverSettings.ocr_provider || "rapidocr");
                logic.setTranslationProvider(serverSettings.translation_provider || "freegoogle");
                logic.setHasGoogleApiKey(!!serverSettings.google_api_key);

                logic.setFontScale(serverSettings.font_scale ?? 1.0);
                logic.setGroupingPower(serverSettings.grouping_power ?? 0.25);
                logic.setHideIdenticalTranslations(serverSettings.hide_identical_translations ?? false);
                logic.setAllowLabelGrowth(serverSettings.allow_label_growth ?? false);
                logic.setVisionMode(serverSettings.vision_mode ?? "off");

                logger.info('SettingsContext', 'All settings loaded successfully');
                logger.logObject('SettingsContext', 'Settings', mappedSettings);
            } else {
                logger.error('SettingsContext', 'Failed to load settings');
            }
        } catch (error) {
            logger.error('SettingsContext', 'Error loading settings', error);
        } finally {
            dispatch({ type: 'SET_INITIALIZED', initialized: true });
        }
    };

    // Update a single setting
    const updateSetting = async (key: keyof Settings, value: any, label?: string): Promise<boolean> => {
        try {
            // Update local state
            dispatch({ type: 'UPDATE_SETTING', key, value });

            // Map frontend setting key to backend setting key
            const backendKeyMap: Record<keyof Settings, string> = {
                inputLanguage: 'input_language',
                targetLanguage: 'target_language',
                inputMode: 'input_mode',
                enabled: 'enabled',
                initialized: 'initialized',
                holdTimeTranslate: 'hold_time_translate',
                holdTimeDismiss: 'hold_time_dismiss',
                confidenceThreshold: 'confidence_threshold',
                rapidocrConfidence: 'rapidocr_confidence',
                rapidocrBoxThresh: 'rapidocr_box_thresh',
                rapidocrUnclipRatio: 'rapidocr_unclip_ratio',
                pauseGameOnOverlay: 'pause_game_on_overlay',
                quickToggleEnabled: 'quick_toggle_enabled',
                useFreeProviders: 'use_free_providers',
                ocrProvider: 'ocr_provider',
                translationProvider: 'translation_provider',
                googleApiKey: 'google_api_key',
                llmBaseUrl: 'llm_base_url',
                llmApiKey: 'llm_api_key',
                llmModel: 'llm_model',
                llmSystemPrompt: 'llm_system_prompt',
                llmDisableThinking: 'llm_disable_thinking',
                visionMode: 'vision_mode',
                visionParallel: 'vision_parallel',
                visionAssistSendAll: 'vision_assist_send_all',
                visionAssistConfidenceThreshold: 'vision_assist_confidence_threshold',
                debugMode: 'debug_mode',
                fontScale: 'font_scale',
                groupingPower: 'grouping_power',
                hideIdenticalTranslations: 'hide_identical_translations',
                allowLabelGrowth: 'allow_label_growth',
                customRecognitionSettings: 'custom_recognition_settings'
            };

            // Skip settings that don't need to be saved to backend
            if (key === 'initialized') return true;

            const backendKey = backendKeyMap[key];

            // Update logic based on setting type
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
                case 'confidenceThreshold':
                    logic.setConfidenceThreshold(value);
                    break;
                case 'pauseGameOnOverlay':
                    logic.setPauseGameOnOverlay(value);
                    break;
                case 'quickToggleEnabled':
                    logic.setQuickToggleEnabled(value);
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
                case 'ocrProvider':
                    logic.setOcrProvider(value);
                    break;
                case 'translationProvider':
                    logic.setTranslationProvider(value);
                    break;
                case 'googleApiKey':
                    logic.setHasGoogleApiKey(!!value);
                    break;
                case 'visionMode':
                    logic.setVisionMode(value);
                    break;
            }

            // Save to backend
            const result = await call<boolean>('set_setting', backendKey, value);

            if (result) {
                return true;
            } else {
                logic.notify(`Failed to update ${label || key}`, 2000);
                return false;
            }
        } catch (error) {
            logger.error('SettingsContext', `Failed to update ${key}`, error);
            logic.notify(`Failed to update ${label || key}`, 2000);
            return false;
        }
    };

    // Initialize settings on mount
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

// Create a hook for using the settings
export const useSettings = () => {
    const context = useContext(SettingsContext);
    if (!context) {
        throw new Error('useSettings must be used within a SettingsProvider');
    }
    return context;
};
