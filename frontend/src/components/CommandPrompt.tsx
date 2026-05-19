import React from 'react';
import { useUiCopy } from '../i18n/ui';

interface CommandPromptProps {
    isRunDisabled: boolean;
    isStreaming: boolean;
    value: string;
    submitLabel?: string;
    rewriteMode?: boolean;
    onChange: (next: string) => void;
    onSubmit: (intent: string) => void;
    onStop: () => void;
    onCancelRewrite?: () => void;
}

export const CommandPrompt: React.FC<CommandPromptProps> = ({
    isRunDisabled,
    isStreaming,
    value,
    submitLabel,
    rewriteMode = false,
    onChange,
    onSubmit,
    onStop,
    onCancelRewrite,
}) => {
    const copy = useUiCopy();
    const resolvedSubmitLabel = submitLabel ?? copy.composer.send;
    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (value.trim() && !isRunDisabled) {
            onSubmit(value.trim());
        }
    };

    return (
        <form onSubmit={handleSubmit} className="border-t border-[rgba(255,255,255,0.028)] bg-[rgba(255,255,255,0.006)] px-2 pb-2 pt-1.5">
            {rewriteMode && (
                <div className="mb-2 border-l border-[var(--tone-warning-border)] bg-[rgba(255,255,255,0.012)] px-2.5 py-1.5 text-[11px] text-[var(--tone-warning-text)]">
                    {copy.composer.rewriteNotice}
                </div>
            )}
            <div className="command-dock flex items-center gap-2 rounded-[10px] px-2 py-1.5">
                    <input
                        type="text"
                        value={value}
                        onChange={(e) => onChange(e.target.value)}
                        placeholder={isStreaming ? copy.composer.placeholderStreaming : rewriteMode ? copy.composer.placeholderRewrite : copy.composer.placeholderIdle}
                        className="command-dock-input min-w-0 flex-grow bg-transparent text-[13px]"
                    />
                    {isStreaming ? (
                        <button
                            type="button"
                            onClick={onStop}
                            className="rounded-[999px] border border-[var(--tone-danger-border)] px-3 py-1.5 text-[13px] font-medium text-[var(--tone-danger-text)] transition-colors hover:bg-[var(--tone-danger-bg)]"
                        >
                            {copy.composer.stop}
                        </button>
                    ) : (
                        <button
                            type="submit"
                            disabled={isRunDisabled}
                            className="rounded-[999px] border border-[var(--tone-success-border)] bg-[var(--tone-success-bg)] px-3 py-1.5 text-[13px] font-medium text-[var(--tone-success-text)] transition-colors hover:bg-[rgba(255,255,255,0.12)] disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {resolvedSubmitLabel}
                        </button>
                    )}
                </div>
            {onCancelRewrite && !isStreaming && (
                <div className="mt-2 flex justify-end">
                    <button
                        type="button"
                        onClick={onCancelRewrite}
                        className="text-[11px] font-mono text-[#8b949e] underline-offset-2 hover:text-[#d0d7de] hover:underline"
                    >
                        {copy.composer.cancelRewrite}
                    </button>
                </div>
            )}
        </form>
    );
};
