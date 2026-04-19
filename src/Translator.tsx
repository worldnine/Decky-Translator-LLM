// Translator.tsx - Handles translator logic and API interactions

import { call, toaster } from "@decky/api";
import { Router } from "@decky/ui";
import { NetworkError, ApiKeyError, RateLimitError } from "./TextRecognizer";
import { TextTranslator, TranslatedRegion } from "./TextTranslator";
import { Input, InputMode, ActionType, ProgressInfo } from "./Input";
import { ImageState } from "./Overlay";
import { logger } from "./Logger";

// Screenshot response interface
export interface ScreenshotResponse {
    path: string;
    base64: string;
}

// Main app logic
export class GameTranslatorLogic {
    // translate / pin の共有ロック（同時実行を禁止する）
    private activeOperation: "translate" | "pin" | null = null;
    public imageState: ImageState;
    private textTranslator: TextTranslator;
    private shortcutInput: Input; // Added shortcut input handler
    private progressListeners: Array<(progressInfo: ProgressInfo) => void> = [];
    private enabled: boolean = true; // Add enabled state
    private confidenceThreshold: number = 0.6; // Default confidence threshold
    private pauseGameOnOverlay: boolean = false;
    private hideIdenticalTranslations: boolean = false;
    private geminiBaseUrl: string = "";
    private geminiApiKey: string = "";
    private geminiModel: string = "";

    isOverlayVisible(): boolean {
        return this.imageState.isVisible();
    }

    // Add public access to shortcutInput for diagnostics
    public get shortcutInputHandler(): Input {
        return this.shortcutInput;
    }

    constructor(imageState: ImageState) {
        this.imageState = imageState;
        this.textTranslator = new TextTranslator();

        // Initialize for hidraw-based button detection
        this.shortcutInput = new Input();

        // Set up listener for translate, dismiss, and toggle actions
        this.shortcutInput.onShortcutPressed((actionType: ActionType) => {
            // Only process inputs if the plugin is enabled
            if (!this.enabled) return;

            if (actionType === ActionType.PIN) {
                // ピンアクション — ショートカット経由
                this.pinCurrentScreen("shortcut").catch(err => logger.error('Translator', 'Pin shortcut failed', err));
            } else if (actionType === ActionType.DISMISS) {
                // Dismiss overlay action
                if (this.imageState.isVisible()) {
                    this.imageState.hideImage();
                    // Update visibility state in Input handler
                    this.shortcutInput.setOverlayVisible(false);
                }
            } else if (actionType === ActionType.TOGGLE_TRANSLATIONS) {
                // Toggle translations action
                if (this.imageState.isVisible()) {
                    logger.debug('Translator', 'Toggling translation visibility');
                    this.imageState.toggleTranslationsVisibility();
                }
            } else {
                // Translate action
                if (!this.imageState.isVisible()) {
                    this.takeScreenshotAndTranslate().catch(err => logger.error('Translator', 'Screenshot failed', err));
                }
            }
        });

        // Set up listener for overlay state changes to track visibility
        imageState.onStateChanged((visible, _, __, ___, ____, _____, ______, _______) => {
            this.shortcutInput.setOverlayVisible(visible);

            // Don't process game pause/resume if plugin is disabled
            if (!this.enabled) return;

            // Handle game pausing/resuming when overlay visibility changes
            if (this.pauseGameOnOverlay) {
                if (visible) {
                    // Overlay is showing, pause the game
                    this.pauseCurrentGame();
                } else {
                    // Overlay is hidden, resume the game
                    this.resumeCurrentGame();
                }
            }
        });

        // Set up progress listener
        this.shortcutInput.onProgress((progressInfo: ProgressInfo) => {
            this.notifyProgressListeners(progressInfo);
        });

        // Load enabled state from server
        this.loadInitialState();
    }

    // Load initial state from server
    private async loadInitialState() {
        try {
            const result = await call<[], boolean>('get_enabled_state');
            this.enabled = !!result;
            logger.info('Translator', `Loaded initial enabled state: ${this.enabled}`);

            if (this.shortcutInput) {
                this.shortcutInput.setEnabled(this.enabled);
            }

            // If plugin starts disabled, stop the hidraw monitor that was auto-started
            if (!this.enabled) {
                logger.info('Translator', 'Plugin is disabled on startup, stopping hidraw monitor');
                call('stop_hidraw_monitor').catch(error => {
                    logger.error('Translator', 'Failed to stop hidraw monitor on startup', error);
                });
            }
        } catch (error) {
            logger.error('Translator', 'Failed to load initial state', error);
        }
    }

    // Add method to enable/disable the plugin
    setEnabled(enabled: boolean): void {
        this.enabled = enabled;

        if (this.shortcutInput) {
            this.shortcutInput.setEnabled(enabled);
        }

        // Save to server settings file
        call('set_setting', 'enabled', enabled).catch(error => {
            logger.error('Translator', 'Failed to save enabled state to server', error);
        });

        // If we're disabling the plugin and the overlay is visible, hide it
        if (!enabled && this.imageState.isVisible()) {
            this.imageState.hideImage();
            this.shortcutInput.setOverlayVisible(false);
        }

        // Stop or start the backend hidraw monitor based on enabled state
        if (enabled) {
            // Re-start hidraw monitor when re-enabling
            call('start_hidraw_monitor').then(result => {
                logger.info('Translator', `Hidraw monitor start result: ${JSON.stringify(result)}`);
            }).catch(error => {
                logger.error('Translator', 'Failed to start hidraw monitor', error);
            });
        } else {
            // Stop hidraw monitor when disabling to save resources
            call('stop_hidraw_monitor').then(result => {
                logger.info('Translator', `Hidraw monitor stop result: ${JSON.stringify(result)}`);
            }).catch(error => {
                logger.error('Translator', 'Failed to stop hidraw monitor', error);
            });
        }
    }

    // Add method to get enabled state
    isEnabled(): boolean {
        return this.enabled;
    }

    // Method to get full diagnostic information
    getInputDiagnostics(): object | null {
        if (!this.shortcutInput) return null;
        return this.shortcutInput.getDiagnostics();
    }

    // New methods for confidence threshold
    setConfidenceThreshold(threshold: number): void {
        logger.debug('Translator', `Setting confidence threshold to: ${threshold}`);
        this.confidenceThreshold = threshold;
    }

    getConfidenceThreshold(): number {
        return this.confidenceThreshold;
    }

    setGroupingPower = (power: number): void => {
        logger.debug('Translator', `Grouping power set to ${power} (unused in Gemini direct mode)`);
    }

    setHideIdenticalTranslations = (enabled: boolean): void => {
        this.hideIdenticalTranslations = enabled;
    }

    setPauseGameOnOverlay = (enabled: boolean): void => {
        logger.debug('Translator', `Setting pauseGameOnOverlay to: ${enabled}`);
        this.pauseGameOnOverlay = enabled;

        // If overlay is currently visible and we're enabling this setting, pause the game
        if (enabled && this.imageState.isVisible()) {
            this.pauseCurrentGame();
        }
    }

    // Method to get pause game on overlay state
    getPauseGameOnOverlay = (): boolean => {
        return this.pauseGameOnOverlay;
    }

    // Method to pause the current game
    async pauseCurrentGame(): Promise<void> {
        try {
            // Get the current running app ID
            const mainApp = Router.MainRunningApp;
            if (!mainApp || !mainApp.appid) {
                logger.debug('Translator', 'No game running to pause');
                return;
            }

            // Use the pid_from_appid function to get the process ID
            const pid = await call<[number], number>('pid_from_appid', Number(mainApp.appid));

            if (pid) {
                logger.info('Translator', `Pausing game with appid ${mainApp.appid}, pid ${pid}`);

                // Call the pause function in the backend
                const pauseResult = await call<[number], boolean>('pause', pid);
                if (pauseResult) {
                    logger.info('Translator', 'Game paused successfully');
                } else {
                    logger.error('Translator', 'Failed to pause game');
                }
            } else {
                logger.error('Translator', 'Failed to get PID for game');
            }
        } catch (error) {
            logger.error('Translator', 'Error pausing game', error);
        }
    }

    // Method to resume the current game
    async resumeCurrentGame(): Promise<void> {
        try {
            // Get the current running app ID
            const mainApp = Router.MainRunningApp;
            if (!mainApp || !mainApp.appid) {
                logger.debug('Translator', 'No game running to resume');
                return;
            }

            // Use the pid_from_appid function to get the process ID
            const pid = await call<[number], number>('pid_from_appid', Number(mainApp.appid));

            if (pid) {
                logger.info('Translator', `Resuming game with appid ${mainApp.appid}, pid ${pid}`);

                // Call the resume function in the backend
                const resumeResult = await call<[number], boolean>('resume', pid);
                if (resumeResult) {
                    logger.info('Translator', 'Game resumed successfully');
                } else {
                    logger.error('Translator', 'Failed to resume game');
                }
            } else {
                logger.error('Translator', 'Failed to get PID for game');
            }
        } catch (error) {
            logger.error('Translator', 'Error resuming game', error);
        }
    }

    // Methods for progress indicator
    onProgress(callback: (progressInfo: ProgressInfo) => void): void {
        this.progressListeners.push(callback);
    }

    offProgress(callback: (progressInfo: ProgressInfo) => void): void {
        const index = this.progressListeners.indexOf(callback);
        if (index !== -1) {
            this.progressListeners.splice(index, 1);
        }
    }

    private notifyProgressListeners(progressInfo: ProgressInfo): void {
        for (const callback of this.progressListeners) {
            callback(progressInfo);
        }
    }

    // Clean up resources when plugin is unmounted
    cleanup(): void {
        if (this.shortcutInput) {
            this.shortcutInput.unregister();
        }

        // Stop backend hidraw monitor
        call('stop_hidraw_monitor').catch(error => {
            logger.error('Translator', 'Failed to stop hidraw monitor', error);
        });
    }

    notify = async (message: string, duration: number = 1000, body?: string): Promise<void> => {
        toaster.toast({
            title: message,
            body: body || message,
            duration: duration,
            critical: true
        });
    }

    pinCurrentScreen = async (trigger: string = "button"): Promise<void> => {
        // 共有ロック: 翻訳中・ピン進行中は発火しない
        if (this.activeOperation !== null) {
            logger.warn('Translator', `Pin skipped: ${this.activeOperation} in progress`);
            if (this.activeOperation === "translate") {
                this.imageState.showPinError("Pin skipped: busy");
            }
            return;
        }

        const mainApp = Router.MainRunningApp;
        const appId = mainApp?.appid ? Number(mainApp.appid) : 0;
        const appName = mainApp?.display_name || "";

        this.activeOperation = "pin";
        // サスペンド等で resetPinState が走ったとき、遅延完了で UI を再点灯させないための世代トークン
        const pinGen = this.imageState.getPinGeneration();
        // トースター通知は使わず、左下スピナー（Overlay のピンレーン）で通知する
        this.imageState.startPinLoading("Pinning");
        try {
            const result = await call<[number, string, string | null, string], any>(
                'pin_capture', appId, appName, null, trigger
            );

            // 進行中に resetPinState が呼ばれたら UI 更新を破棄
            if (this.imageState.getPinGeneration() !== pinGen) {
                logger.debug('Translator', 'Pin result discarded: state was reset mid-flight');
                return;
            }

            if (result?.ok && result?.pin_id) {
                this.imageState.showPinSuccess("Pinned");
                logger.info('Translator', `Pin saved: ${result.pin_id}`);
            } else {
                const reason = result?.error || (result?.ok ? "missing pin_id" : "Unknown error");
                this.imageState.showPinError(`Pin failed: ${reason}`);
                logger.error('Translator', `Pin failed: ${reason}`);
            }
        } catch (err) {
            if (this.imageState.getPinGeneration() !== pinGen) {
                logger.debug('Translator', 'Pin error discarded: state was reset mid-flight');
                return;
            }
            const msg = err instanceof Error ? err.message : String(err);
            this.imageState.showPinError(`Pin failed: ${msg}`);
            logger.error('Translator', 'Pin failed', err);
        } finally {
            this.activeOperation = null;
        }
    }

    takeScreenshotAndTranslate = async (): Promise<void> => {
        // 共有ロック: 翻訳・ピンが進行中なら発火しない
        if (this.activeOperation !== null || !this.enabled) {
            logger.debug('Translator', `Translate skipped: ${this.activeOperation ?? 'plugin disabled'}`);
            return;
        }

        // Check if languages are configured
        const inputLang = this.getInputLanguage();
        const targetLang = this.getTargetLanguage();
        if (!inputLang && targetLang) {
            logger.warn('Translator', 'Cannot start translation: languages not configured');
            this.notify("Input language is not set", 3000, "Please select it in the plugin settings");
            return;
        }
        if (!targetLang && inputLang) {
            logger.warn('Translator', 'Cannot start translation: languages not configured');
            this.notify("Output language is not set", 3000, "Please select it in the plugin settings");
            return;
        }
        if (!inputLang && !targetLang) {
            logger.warn('Translator', 'Cannot start translation: languages not configured');
            this.notify("Output and Input languages are not set", 3000, "Please select them in the plugin settings");
            return;
        }

        // Check if input and output languages are the same (auto-detect is fine)
        if (inputLang !== 'auto' && inputLang === targetLang) {
            logger.warn('Translator', `Cannot start translation: input and output language are both ${inputLang}`);
            this.notify("Input and output languages can not be the same", 3000, "Select change them in plugin settings");
            return;
        }

        const geminiConfigCheck = this.validateGeminiConfiguration();
        if (!geminiConfigCheck.ok) {
            logger.warn('Translator', `Cannot start translation: ${geminiConfigCheck.message}`);
            this.notify(geminiConfigCheck.message, 3000, geminiConfigCheck.detail);
            return;
        }

        try {
            this.activeOperation = "translate";

            const mainApp = Router.MainRunningApp;
            if (mainApp?.appid) {
                try {
                    await call('ensure_game_vision_prompt_file', Number(mainApp.appid), mainApp.display_name || "");
                    // Agent用: ゲーム情報をバックエンドにキャッシュ
                    await call('agent_set_running_game', Number(mainApp.appid), mainApp.display_name || "");
                } catch (e) {
                    logger.warn('Translator', 'Failed to apply Gemini prompt', e);
                }
            } else {
                // ゲーム未起動時はキャッシュをクリアして古い情報が残らないようにする
                try {
                    await call('agent_set_running_game', null, null);
                } catch (e) {
                    // 無視: agent RPCが未対応の環境でも翻訳フローは継続
                }
            }

            // Take screenshot FIRST while screen is clean (no overlay visible)
            const appName = mainApp?.display_name || "";
            logger.info('Translator', `Taking new screenshot for: ${appName}`);
            const result = await call<[string], ScreenshotResponse | null>('take_screenshot', appName);

            // NOW show the overlay - after screenshot is captured
            this.imageState.hideImage();
            this.imageState.startLoading("Processing");

            if (result) {
                logger.debug('Translator', `Screenshot captured, path: ${result.path}`);

                if (result.base64) {
                    // Log image data length for debugging
                    logger.debug('Translator', `Received base64 image data, length: ${result.base64.length}`);

                    // Immediately show the new screenshot on the overlay
                    this.imageState.showImage(result.base64);

                    const primaryModel = this.geminiModel || "Gemini";
                    this.imageState.updateProcessingStep(`Translating with ${primaryModel}`);

                    // リトライ/フォールバック状態を 500ms ごとに polling し処理ステップを更新する
                    type TranslationStatus = {
                        event: "translating" | "retry" | "fallback";
                        model: string;
                        attempt?: number;
                        max?: number;
                        delay?: number;
                        status?: string;
                    };
                    const retryPollInterval = setInterval(async () => {
                        try {
                            const status = await call<[], TranslationStatus | null>('get_translation_status');
                            if (!status) return;
                            if (status.event === "retry") {
                                this.imageState.updateProcessingStep(
                                    `Retrying ${status.model} (${status.attempt}/${status.max})`
                                );
                            } else if (status.event === "fallback") {
                                this.imageState.updateProcessingStep(
                                    `Switching to ${status.model}...`
                                );
                            } else {
                                this.imageState.updateProcessingStep(
                                    `Translating with ${status.model}`
                                );
                            }
                        } catch (err) {
                            logger.debug('Translator', 'get_translation_status failed', err);
                        }
                    }, 500);

                    let visionResult: TranslatedRegion[] | null;
                    try {
                        visionResult = await this.textTranslator.visionTranslate(result.base64);
                    } finally {
                        clearInterval(retryPollInterval);
                    }

                    if (result.path) {
                        call('delete_screenshot', result.path).catch(() => {});
                    }

                    if (visionResult !== null) {
                        if (visionResult.length > 0) {
                            logger.info('Translator', `Gemini translation complete: ${visionResult.length} regions`);
                            let translatedRegions = visionResult;

                            if (this.hideIdenticalTranslations) {
                                const before = translatedRegions.length;
                                translatedRegions = translatedRegions.filter(r =>
                                    r.translatedText.trim().toLowerCase() !== r.text.trim().toLowerCase()
                                );
                                if (translatedRegions.length < before) {
                                    logger.info('Translator', `Filtered ${before - translatedRegions.length} identical translations`);
                                }
                            }

                            this.imageState.showTranslatedImage(result.base64, translatedRegions);
                        } else {
                            logger.info('Translator', 'Gemini translation: no text found');
                            this.imageState.updateProcessingStep("No text found");
                            setTimeout(() => {
                                this.imageState.hideImage();
                            }, 2000);
                        }
                    } else {
                        logger.warn('Translator', 'Gemini translation returned null');
                        this.imageState.updateProcessingStep("Translation failed");
                        setTimeout(() => {
                            this.imageState.hideImage();
                        }, 2500);
                    }
                } else {
                    logger.warn('Translator', 'No base64 data in screenshot response');
                    this.imageState.hideImage();
                }
            } else {
                logger.warn('Translator', 'Screenshot capture failed');
                this.imageState.hideImage();
            }
        } catch (error) {
            logger.error('Translator', 'Screenshot and translation error', error);

            // Check if this is a network error
            if (error instanceof NetworkError) {
                this.imageState.updateProcessingStep("No internet connection");
                // Hide overlay after showing the error message
                setTimeout(() => {
                    this.imageState.hideImage();
                }, 2500); // 2.5 seconds delay for network error
            } else if (error instanceof ApiKeyError) {
                this.imageState.updateProcessingStep("Invalid API key");
                // Hide overlay after showing the error message
                setTimeout(() => {
                    this.imageState.hideImage();
                }, 2500); // 2.5 seconds delay for API key error
            } else if (error instanceof RateLimitError) {
                this.imageState.updateProcessingStep(error.message);
                // Hide overlay after showing the error message
                setTimeout(() => {
                    this.imageState.hideImage();
                }, 3000); // 3 seconds delay for rate limit error
            } else {
                this.imageState.hideImage();
            }
        }
        finally {
            this.activeOperation = null;
        }
    }

    setInputLanguage = (language: string): void => {
        this.textTranslator.setInputLanguage(language);
    }

    getInputLanguage = (): string => {
        return this.textTranslator.getInputLanguage();
    }

    setTargetLanguage = (language: string): void => {
        this.textTranslator.setTargetLanguage(language);
    }

    getTargetLanguage = (): string => {
        return this.textTranslator.getTargetLanguage();
    }

    // Method to set input mode
    setInputMode = (mode: InputMode): void => {
        this.shortcutInput.setInputMode(mode);
    }

    // Method to get current input mode
    getInputMode = (): InputMode => {
        return this.shortcutInput.getInputMode();
    }

    // Method to set translation hold time
    setHoldTimeTranslate = (ms: number): void => {
        if (this.shortcutInput) {
            this.shortcutInput.setTranslateHoldTime(ms);
        }
    }

    // Method to get translation hold time
    getHoldTimeTranslate = (): number => {
        return this.shortcutInput ? this.shortcutInput.getTranslateHoldTime() : 1000;
    }

    // Method to set dismiss hold time
    setHoldTimeDismiss = (ms: number): void => {
        if (this.shortcutInput) {
            this.shortcutInput.setDismissHoldTime(ms);
        }
    }

    // Method to get dismiss hold time
    getHoldTimeDismiss = (): number => {
        return this.shortcutInput ? this.shortcutInput.getDismissHoldTime() : 500;
    }

    // Method to set quick toggle enabled
    setQuickToggleEnabled = (enabled: boolean): void => {
        if (this.shortcutInput) {
            this.shortcutInput.setQuickToggleEnabled(enabled);
        }
    }

    // Method to get quick toggle enabled state
    getQuickToggleEnabled = (): boolean => {
        return this.shortcutInput ? this.shortcutInput.getQuickToggleEnabled() : false;
    }

    setFontScale = (scale: number): void => {
        this.imageState.setFontScale(scale);
    }

    setAllowLabelGrowth = (allow: boolean): void => {
        this.imageState.setAllowLabelGrowth(allow);
    }

    setPinFeatureEnabled = (enabled: boolean): void => {
        if (this.shortcutInput) {
            this.shortcutInput.setPinFeatureEnabled(enabled);
        }
    }

    setPinShortcutEnabled = (enabled: boolean): void => {
        if (this.shortcutInput) {
            this.shortcutInput.setPinShortcutEnabled(enabled);
        }
    }

    setPinInputMode = (mode: InputMode | null): void => {
        if (this.shortcutInput) {
            this.shortcutInput.setPinInputMode(mode);
        }
    }

    setPinHoldTime = (ms: number): void => {
        if (this.shortcutInput) {
            this.shortcutInput.setPinHoldTime(ms);
        }
    }

    setGeminiBaseUrl = (baseUrl: string): void => {
        this.geminiBaseUrl = baseUrl.trim();
    }

    setGeminiApiKey = (apiKey: string): void => {
        this.geminiApiKey = apiKey;
    }

    setGeminiModel = (model: string): void => {
        this.geminiModel = model.trim();
    }

    private validateGeminiConfiguration(): { ok: boolean; message: string; detail: string } {
        if (!this.geminiModel) {
            return {
                ok: false,
                message: "Gemini model is not set",
                detail: "Set the model name in Translation settings before translating.",
            };
        }

        if (!this.geminiApiKey) {
            return {
                ok: false,
                message: "Gemini API key is not set",
                detail: "Add your Gemini API key in Translation settings before translating.",
            };
        }

        if (this.geminiBaseUrl) {
            try {
                const url = new URL(this.geminiBaseUrl);
                if (!["http:", "https:"].includes(url.protocol)) {
                    throw new Error("invalid protocol");
                }
            } catch {
                return {
                    ok: false,
                    message: "Gemini Base URL is invalid",
                    detail: "Use a valid http(s) URL or leave it empty to use the official Gemini endpoint.",
                };
            }
        }

        return { ok: true, message: "", detail: "" };
    }
}
