import React from 'react';
import { useUiCopy } from '../i18n/ui';

interface ConflictBannerProps {
    isVisible: boolean;
    onRefreshLock: () => void;
}

export const ConflictBanner: React.FC<ConflictBannerProps> = ({ isVisible, onRefreshLock }) => {
    const copy = useUiCopy();
    if (!isVisible) return null;

    return (
        <div className="absolute left-4 right-4 top-4 z-50">
            <div className="workspace-strip flex items-center justify-between gap-4 rounded-[10px] border border-[var(--tone-danger-border)] bg-[var(--tone-danger-bg)] px-4 py-2.5 text-sm shadow-[0_14px_26px_rgba(0,0,0,0.24)]">
                <div className="flex items-center space-x-2 text-[#ffe2e3]">
                    <span>⚠️</span>
                    <span><strong>WRITE CONFLICT (409):</strong> {copy.review.conflictHint}</span>
                </div>
                <button
                    onClick={onRefreshLock}
                    className="rounded-[8px] border border-[rgba(255,255,255,0.14)] bg-[rgba(255,255,255,0.04)] px-3 py-1.5 text-xs font-semibold text-[#fff1f1] transition-colors hover:bg-[rgba(255,255,255,0.08)]"
                >
                    {copy.review.refreshLock}
                </button>
            </div>
        </div>
    );
};
