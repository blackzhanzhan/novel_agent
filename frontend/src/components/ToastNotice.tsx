import React, { useEffect } from 'react';
import { UiNotice } from '../types/store';
import { useUiCopy } from '../i18n/ui';

interface ToastNoticeProps {
    notice: UiNotice | null;
    onClose: () => void;
}

function toneClasses(type: UiNotice['type']): string {
    if (type === 'success') {
        return 'border-[var(--tone-success-border)] text-[var(--tone-success-text)] bg-[var(--tone-success-bg)]';
    }
    if (type === 'error') {
        return 'border-[var(--tone-danger-border)] text-[var(--tone-danger-text)] bg-[var(--tone-danger-bg)]';
    }
    return 'border-[var(--tone-info-border)] text-[var(--tone-info-text)] bg-[var(--tone-info-bg)]';
}

export const ToastNotice: React.FC<ToastNoticeProps> = ({ notice, onClose }) => {
    const copy = useUiCopy();
    useEffect(() => {
        if (!notice) return;
        const timer = window.setTimeout(() => onClose(), 3200);
        return () => window.clearTimeout(timer);
    }, [notice, onClose]);

    if (!notice) return null;

    return (
        <div className="pointer-events-none fixed right-4 top-4 z-50">
            <div className={`workspace-strip pointer-events-auto rounded-[10px] border px-4 py-2.5 text-sm shadow-[0_14px_30px_rgba(0,0,0,0.22)] backdrop-blur ${toneClasses(notice.type)}`}>
                <div className="flex items-center gap-3">
                    <span>{notice.message}</span>
                    <button
                        type="button"
                        onClick={onClose}
                        className="text-xs text-[var(--color-dark-text-faint)] hover:text-[var(--color-dark-text-main)]"
                    >
                        {copy.common.close}
                    </button>
                </div>
            </div>
        </div>
    );
};
