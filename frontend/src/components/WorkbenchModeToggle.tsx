import React from 'react';
import { UiLanguage } from '../types/store';
import { getUiCopy } from '../i18n/ui';

interface WorkbenchModeToggleProps {
    uiLanguage: UiLanguage;
    onChangeLanguage: (language: UiLanguage) => void;
}

export const WorkbenchModeToggle: React.FC<WorkbenchModeToggleProps> = ({
    uiLanguage,
    onChangeLanguage,
}) => {
    const copy = getUiCopy(uiLanguage);

    return (
        <div className="border-b border-[rgba(255,255,255,0.035)] px-4 py-2.5">
            <div className="flex items-center justify-between gap-3">
                <div className="cursor-section-label">{copy.language.label}</div>
                <div className="workspace-strip-muted flex items-center gap-1 rounded-[999px] border border-[rgba(255,255,255,0.05)] p-1">
                    {(['zh-CN', 'en-US'] as UiLanguage[]).map((language) => {
                        const isActive = language === uiLanguage;
                        return (
                            <button
                                key={language}
                                type="button"
                                onClick={() => onChangeLanguage(language)}
                                className={`rounded-[999px] px-2.5 py-[3px] text-[10px] font-medium transition-colors ${
                                    isActive
                                        ? 'cursor-chip-active'
                                        : 'text-[var(--color-dark-text-faint)] hover:text-[var(--color-dark-text-main)]'
                                }`}
                                aria-label={language === 'zh-CN' ? copy.language.zhFull : copy.language.enFull}
                            >
                                {language === 'zh-CN' ? copy.language.zhShort : copy.language.enShort}
                            </button>
                        );
                    })}
                </div>
            </div>
        </div>
    );
};
