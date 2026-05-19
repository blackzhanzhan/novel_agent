import React, { useCallback, useState } from 'react';
import { CommandPrompt } from './CommandPrompt';

interface ChatComposerDockProps {
    isRunDisabled: boolean;
    isStreaming: boolean;
    submitLabel?: string;
    onSubmit: (intent: string, clearComposer: () => void) => void;
    onStop: () => void;
}

export const ChatComposerDock: React.FC<ChatComposerDockProps> = ({
    isRunDisabled,
    isStreaming,
    submitLabel,
    onSubmit,
    onStop,
}) => {
    const [value, setValue] = useState('');

    const clearComposer = useCallback(() => {
        setValue('');
    }, []);

    const handleSubmit = useCallback((intent: string) => {
        onSubmit(intent, clearComposer);
    }, [clearComposer, onSubmit]);

    return (
        <CommandPrompt
            isRunDisabled={isRunDisabled}
            isStreaming={isStreaming}
            value={value}
            submitLabel={submitLabel}
            rewriteMode={false}
            onChange={setValue}
            onSubmit={handleSubmit}
            onStop={onStop}
        />
    );
};
