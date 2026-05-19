import { useState } from 'react';
import { AppStore, RepoIntegrity } from '../types/store';
import { updateMainlineFile } from '../api/checkout';
import { ApiError } from '../api/client';
import { getErrorMessage, isLayoutRepairRequired, extractIntegrityFromError } from '../lib/errorUtils';

export function useHumanEditMode(deps: {
    store: AppStore;
    editorContent: string;
    setEditorContent: (v: string) => void;
    repoIntegrity: RepoIntegrity | null;
    setRepoIntegrity: (v: RepoIntegrity | null) => void;
    getErrorMessage: typeof getErrorMessage;
    loadMainline: (file?: string, opts?: { preserveDraftReview?: boolean }) => Promise<void>;
}) {
    const { store, editorContent, setEditorContent, repoIntegrity, setRepoIntegrity } = deps;

    const [isEditing, setIsEditing] = useState(false);
    const [editBaseEtag, setEditBaseEtag] = useState('');
    const [editDraft, setEditDraft] = useState('');
    const [isSaving, setIsSaving] = useState(false);
    const [saveConflict, setSaveConflict] = useState<{ draft: string; draftFile: string } | null>(null);

    const handleEnterEdit = () => {
        if (repoIntegrity?.needsRepair) {
            store.setUiNotice({
                type: "error",
                message: "仓库核心布局不完整，修复后才能进入人工编辑。",
                ts: Date.now(),
            });
            return;
        }
        setEditBaseEtag(store.baseEtag);
        setEditDraft(editorContent);
        setIsEditing(true);
        setSaveConflict(null);
    };

    const handleCancelEdit = () => {
        // Restore original content without saving
        setEditDraft('');
        setIsEditing(false);
        setSaveConflict(null);
        // Reload from store (no network call needed, content unchanged on disk)
        setEditorContent(store.mainlineContent);
    };

    const handleSaveEdit = async (forceContent?: string) => {
        if (!store.bookRef.value || !store.activeFile) return;
        const submitContent = forceContent ?? editDraft;
        setIsSaving(true);
        try {
            const result = await updateMainlineFile(
                { kind: store.bookRef.kind, value: store.bookRef.value },
                store.activeFile,
                submitContent,
                editBaseEtag
            );
            store.setMainlineFact(submitContent, result.etag);
            setEditorContent(submitContent);
            setIsEditing(false);
            setSaveConflict(null);
            setEditDraft('');
            store.setUiNotice({ type: 'success', message: `✏️ 已保存 ${store.activeFile}，commit: ${(result.commitId || '').slice(0, 8)}`, ts: Date.now() });
        } catch (err) {
            if (err instanceof ApiError && err.code === 'WRITE_CONFLICT') {
                // ETag mismatch: AI modified file concurrently
                setSaveConflict({ draft: submitContent, draftFile: '' });
                const draftFile: string = (err as ApiError & { data?: { draft_file?: string } }).data?.draft_file || '';
                const draftShort = draftFile ? draftFile.replace(/^.*?novel_git_server\/storage\//, 'storage/') : 'conflicts/*.ai_conflict_draft.md';
                setSaveConflict({ draft: submitContent, draftFile: draftShort });
                store.setUiNotice({ type: 'error', message: `⚠️ 写入冲突，你的修改已存为草稿：${draftShort}`, ts: Date.now() });
            } else if (isLayoutRepairRequired(err)) {
                const integrity = extractIntegrityFromError(err);
                if (integrity) {
                    setRepoIntegrity(integrity);
                }
                store.setUiNotice({ type: 'error', message: '仓库核心布局不完整，修复后才能继续保存。', ts: Date.now() });
            } else {
                store.setUiNotice({ type: 'error', message: `保存失败：${getErrorMessage(err, '未知异常')}`, ts: Date.now() });
            }
        } finally {
            setIsSaving(false);
        }
    };

    return {
        isEditing,
        setIsEditing,
        editBaseEtag,
        setEditBaseEtag,
        editDraft,
        setEditDraft,
        isSaving,
        saveConflict,
        setSaveConflict,
        handleEnterEdit,
        handleCancelEdit,
        handleSaveEdit,
    };
}
