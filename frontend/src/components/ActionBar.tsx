import React from 'react';

interface ActionBarProps {
    isVisible: boolean;
    isConfirmDisabled: boolean;
    onConfirm: () => void;
    onRollback: () => void;
    mode?: 'legacy' | 'disabled';
    confirmLabel?: string;
}

export const ActionBar: React.FC<ActionBarProps> = ({
    isVisible,
    isConfirmDisabled,
    onConfirm,
    onRollback,
    mode = 'legacy',
    confirmLabel = '批准确权',
}) => {
    if (!isVisible || mode === 'disabled') return null;

    return (
        <div className="flex items-center space-x-4">
            <span className="cursor-section-label">Review Actions</span>
            <button
                onClick={onRollback}
                className="rounded-[12px] border border-[var(--color-accent-red)] bg-transparent px-5 py-2 text-sm font-medium text-[var(--color-accent-red)] transition-colors hover:bg-[var(--color-accent-red)] hover:text-white"
            >
                湮灭回滚
            </button>
            <button
                onClick={onConfirm}
                disabled={isConfirmDisabled}
                className="rounded-[12px] bg-[var(--color-accent-green)] px-5 py-2 text-sm font-medium text-[#08110b] transition-colors hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
            >
                {confirmLabel}
            </button>
        </div>
    );
};
